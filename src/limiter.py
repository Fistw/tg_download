from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class FloodWaitCoordinator:
    """全局 FloodWait 协调器，管理限流状态"""

    def __init__(self):
        self._wait_until: float = 0.0
        self._lock = asyncio.Lock()
        self._wait_count = 0

    async def wait_if_needed(self) -> None:
        """检查是否需要等待，并执行等待"""
        async with self._lock:
            now = time.time()
            if now < self._wait_until:
                wait_seconds = self._wait_until - now
                logger.info(
                    f"FloodWait active, waiting {wait_seconds:.1f}s "
                    f"(total {self._wait_count} waits so far)"
                )
                await asyncio.sleep(wait_seconds)

    async def set_wait(self, seconds: int) -> None:
        """设置等待时间（当遇到 FloodWaitError 时调用）"""
        async with self._lock:
            now = time.time()
            new_wait_until = now + seconds
            # 只有当新的等待时间比当前更长时才更新
            if new_wait_until > self._wait_until:
                self._wait_until = new_wait_until
                self._wait_count += 1
                logger.warning(
                    f"FloodWaitError: setting global wait for {seconds}s, "
                    f"total {self._wait_count} waits"
                )
            else:
                logger.debug(
                    f"Ignoring FloodWaitError for {seconds}s, "
                    f"existing wait is longer"
                )

    def reset(self) -> None:
        """重置协调器状态（主要用于测试）"""
        self._wait_until = 0.0
        self._wait_count = 0

    @property
    def is_waiting(self) -> bool:
        """检查当前是否处于等待状态"""
        return time.time() < self._wait_until

    @property
    def remaining_wait(self) -> float:
        """获取剩余等待时间（秒）"""
        return max(0.0, self._wait_until - time.time())


class RetryStrategy:
    """智能重试策略：指数退避 + 抖动"""

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        max_retries: int = 10,
        jitter_factor: float = 0.2,
    ):
        """
        初始化重试策略

        Args:
            base_delay: 基础延迟（秒）
            max_delay: 最大延迟（秒）
            max_retries: 最大重试次数
            jitter_factor: 抖动因子（0.0-1.0）
        """
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self.jitter_factor = jitter_factor

    def get_delay(self, attempt: int) -> float:
        """
        计算第 N 次重试的延迟时间

        Args:
            attempt: 尝试次数（从 0 开始）

        Returns:
            延迟秒数
        """
        if attempt < 0:
            return 0.0

        # 指数退避
        delay = self.base_delay * (2 ** attempt)

        # 不超过最大延迟
        delay = min(delay, self.max_delay)

        # 添加抖动（±jitter_factor）
        import random
        jitter = delay * self.jitter_factor
        delay = random.uniform(delay - jitter, delay + jitter)

        # 确保延迟为正
        return max(0.1, delay)

    def should_retry(self, attempt: int) -> bool:
        """
        检查是否应该继续重试

        Args:
            attempt: 尝试次数（从 0 开始）

        Returns:
            是否应该继续重试
        """
        return attempt < self.max_retries


# 全局单例
_global_flood_coordinator: Optional[FloodWaitCoordinator] = None


def get_flood_coordinator() -> FloodWaitCoordinator:
    """获取全局 FloodWait 协调器单例"""
    global _global_flood_coordinator
    if _global_flood_coordinator is None:
        _global_flood_coordinator = FloodWaitCoordinator()
    return _global_flood_coordinator
