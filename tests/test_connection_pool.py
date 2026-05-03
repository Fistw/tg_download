import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.connection_pool import (
    ConnectionStatus,
    PooledConnection,
    TelegramConnectionPool,
)
from src.config import AppConfig, DownloadConfig, TelegramConfig


class TestConnectionStatus:
    """测试 ConnectionStatus 枚举。"""

    def test_enum_values(self):
        """测试枚举值。"""
        assert ConnectionStatus.AVAILABLE.value == "available"
        assert ConnectionStatus.BUSY.value == "busy"
        assert ConnectionStatus.ERROR.value == "error"


class TestPooledConnection:
    """测试 PooledConnection 数据类。"""

    def test_default_values(self):
        """测试默认值。"""
        mock_client = MagicMock()
        conn = PooledConnection(
            client=mock_client,
            status=ConnectionStatus.AVAILABLE,
            index=0,
        )
        assert conn.client == mock_client
        assert conn.status == ConnectionStatus.AVAILABLE
        assert conn.index == 0
        assert conn.last_used is None
        assert conn.error_count == 0


class TestTelegramConnectionPool:
    """测试 TelegramConnectionPool 类。"""

    @pytest.fixture
    def config(self):
        """测试配置 fixture。"""
        return AppConfig(
            telegram=TelegramConfig(
                api_id=12345,
                api_hash="test_hash",
                session_name="test_session",
            ),
            download=DownloadConfig(
                connection_pool_size=2,
            ),
        )

    @pytest.fixture
    def mock_telegram_client(self):
        """Mock TelegramClient fixture。"""
        with patch("src.connection_pool.TelegramClient") as mock:
            instance = mock.return_value
            instance.start = AsyncMock()
            instance.disconnect = AsyncMock()
            instance.is_connected = MagicMock(return_value=True)
            yield mock

    @pytest.mark.asyncio
    async def test_pool_initialization(self, config, mock_telegram_client):
        """测试连接池初始化。"""
        pool = TelegramConnectionPool(config, pool_size=2)
        await pool.start()
        try:
            assert len(pool._connections) == 2
            assert pool._started is True
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_acquire_release_connection(self, config, mock_telegram_client):
        """测试获取和释放连接。"""
        pool = TelegramConnectionPool(config, pool_size=2)
        await pool.start()
        try:
            async with pool.acquire() as client:
                assert client is not None

            # 检查连接是否被释放回池
            assert len(pool._available_queue) == 2
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_multiple_concurrent_acquires(self, config, mock_telegram_client):
        """测试多个并发获取连接。"""
        pool = TelegramConnectionPool(config, pool_size=2)
        await pool.start()
        try:
            acquired_clients = []

            async def acquire_one():
                async with pool.acquire() as client:
                    acquired_clients.append(client)
                    await asyncio.sleep(0.01)

            # 同时获取两个连接
            await asyncio.gather(acquire_one(), acquire_one())
            assert len(acquired_clients) == 2
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_error_handling(self, config, mock_telegram_client):
        """测试错误处理。"""
        pool = TelegramConnectionPool(config, pool_size=1, max_error_count=2)
        await pool.start()
        try:
            with pytest.raises(Exception):
                async with pool.acquire():
                    raise Exception("Test error")

            # 检查错误计数
            assert pool._connections[0].error_count == 1
        finally:
            await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_stop(self, config, mock_telegram_client):
        """测试连接池停止。"""
        pool = TelegramConnectionPool(config, pool_size=2)
        await pool.start()
        await pool.stop()
        assert pool._started is False
        assert len(pool._connections) == 0
