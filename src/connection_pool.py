from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from typing import (
    TYPE_CHECKING,
    AsyncGenerator,
    Callable,
    Deque,
    List,
    Optional,
    Set,
)

from telethon import TelegramClient

from .config import AppConfig
from .limiter import get_flood_coordinator

if TYPE_CHECKING:
    from typing import Self

__all__ = [
    "ConnectionStatus",
    "PooledConnection",
    "TelegramConnectionPool",
    "get_connection_pool",
]

logger = logging.getLogger(__name__)


class ConnectionStatus(Enum):
    """连接状态。"""
    AVAILABLE = "available"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class PooledConnection:
    """池化的连接。"""
    client: TelegramClient
    status: ConnectionStatus
    index: int
    last_used: Optional[float] = None
    error_count: int = 0


class TelegramConnectionPool:
    """Telegram 连接池。

    管理多个 TelegramClient 连接，支持连接复用、健康检查和负载均衡。
    """

    _instance: Optional[TelegramConnectionPool] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(
        self,
        config: AppConfig,
        pool_size: int = 1,
        max_error_count: int = 3,
        health_check_interval: float = 60.0,
    ) -> None:
        """
        Args:
            config: 应用配置
            pool_size: 连接池大小
            max_error_count: 最大错误次数，超过则标记连接为错误
            health_check_interval: 健康检查间隔（秒）
        """
        self._config = config
        self._pool_size = pool_size
        self._max_error_count = max_error_count
        self._health_check_interval = health_check_interval

        self._connections: List[PooledConnection] = []
        self._available_queue: Deque[PooledConnection] = Deque()
        self._condition = asyncio.Condition()
        self._started = False
        self._health_check_task: Optional[asyncio.Task] = None
        self._flood_coordinator = get_flood_coordinator()

    @classmethod
    async def get_instance(cls, config: AppConfig) -> TelegramConnectionPool:
        """获取连接池单例。

        Args:
            config: 应用配置

        Returns:
            连接池实例
        """
        async with cls._lock:
            if cls._instance is None:
                pool_size = getattr(config.download, "connection_pool_size", 1)
                cls._instance = cls(config, pool_size=pool_size)
                await cls._instance.start()
            return cls._instance

    async def start(self) -> None:
        """启动连接池。"""
        if self._started:
            logger.warning("连接池已启动")
            return

        logger.info(f"正在启动连接池，大小: {self._pool_size}")
        tg = self._config.telegram

        for i in range(self._pool_size):
            session_name = (
                f"{tg.session_name}_pool_{i}"
                if i > 0
                else tg.session_name
            )
            client = TelegramClient(
                session_name,
                tg.api_id,
                tg.api_hash,
            )
            await client.start()
            conn = PooledConnection(
                client=client,
                status=ConnectionStatus.AVAILABLE,
                index=i,
            )
            self._connections.append(conn)
            self._available_queue.append(conn)
            logger.info(f"连接 {i} 已就绪")

        self._started = True
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("连接池启动完成")

    async def stop(self) -> None:
        """停止连接池。"""
        if not self._started:
            return

        logger.info("正在停止连接池")
        self._started = False

        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        for conn in self._connections:
            if conn.client.is_connected():
                await conn.client.disconnect()

        self._connections.clear()
        self._available_queue.clear()
        logger.info("连接池已停止")

    @asynccontextmanager
    async def acquire(self, timeout: Optional[float] = None) -> AsyncGenerator[TelegramClient, None]:
        """获取一个连接。

        Args:
            timeout: 超时时间（秒）

        Yields:
            TelegramClient 实例
        """
        conn = await self._acquire_connection(timeout)
        try:
            yield conn.client
        except Exception as e:
            conn.error_count += 1
            if conn.error_count >= self._max_error_count:
                conn.status = ConnectionStatus.ERROR
                logger.error(f"连接 {conn.index} 错误次数超过限制，标记为错误")
            raise
        finally:
            await self._release_connection(conn)

    async def _acquire_connection(self, timeout: Optional[float] = None) -> PooledConnection:
        """内部方法：获取连接。"""
        if not self._started:
            raise RuntimeError("连接池未启动")

        async with self._condition:
            # 等待可用连接
            while True:
                # 先尝试获取可用的连接
                for conn in list(self._available_queue):
                    if conn.status == ConnectionStatus.AVAILABLE:
                        self._available_queue.remove(conn)
                        conn.status = ConnectionStatus.BUSY
                        import time
                        conn.last_used = time.time()
                        logger.debug(f"获取到连接 {conn.index}")
                        return conn

                # 没有可用连接，等待
                logger.debug("等待可用连接...")
                try:
                    await asyncio.wait_for(
                        self._condition.wait(),
                        timeout=timeout,
                    )
                except asyncio.TimeoutError:
                    raise RuntimeError("获取连接超时") from None

    async def _release_connection(self, conn: PooledConnection) -> None:
        """内部方法：释放连接。"""
        async with self._condition:
            if conn.status != ConnectionStatus.ERROR:
                conn.status = ConnectionStatus.AVAILABLE
                self._available_queue.append(conn)
                logger.debug(f"释放连接 {conn.index}")
            else:
                logger.debug(f"连接 {conn.index} 处于错误状态，不释放回池")

            self._condition.notify()

    async def _health_check_loop(self) -> None:
        """健康检查循环。"""
        while self._started:
            try:
                await asyncio.sleep(self._health_check_interval)
                await self._perform_health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"健康检查出错: {e}")

    async def _perform_health_check(self) -> None:
        """执行健康检查。"""
        for conn in self._connections:
            if conn.status == ConnectionStatus.ERROR:
                # 尝试恢复错误的连接
                try:
                    if not conn.client.is_connected():
                        await conn.client.start()
                    conn.status = ConnectionStatus.AVAILABLE
                    conn.error_count = 0
                    logger.info(f"连接 {conn.index} 已恢复")
                    self._available_queue.append(conn)
                except Exception as e:
                    logger.exception(f"无法恢复连接 {conn.index}: {e}")


def get_connection_pool(config: AppConfig) -> TelegramConnectionPool:
    """获取连接池实例的同步工厂方法（内部使用协程创建）。"""
    # 这个函数只是一个占位符，实际使用需要使用 await TelegramConnectionPool.get_instance(config)
    raise RuntimeError("请使用 await TelegramConnectionPool.get_instance(config) 来获取连接池")
