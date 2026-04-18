import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.client import ClientManager
from src.config import AppConfig, TelegramConfig


class TestClientManagerProperties:
    def test_user_raises_before_start(self):
        config = AppConfig(telegram=TelegramConfig(api_id=1, api_hash="h"))
        manager = ClientManager(config)
        with pytest.raises(RuntimeError, match="未初始化"):
            _ = manager.user

    def test_bot_raises_before_start(self):
        config = AppConfig(telegram=TelegramConfig(api_id=1, api_hash="h"))
        manager = ClientManager(config)
        with pytest.raises(RuntimeError, match="未初始化"):
            _ = manager.bot


class TestClientManagerStart:
    @pytest.mark.asyncio
    async def test_start_creates_user_client(self):
        config = AppConfig(
            telegram=TelegramConfig(api_id=123, api_hash="hash123", session_name="test")
        )
        manager = ClientManager(config)

        mock_client = AsyncMock()
        with patch("src.client.TelegramClient", return_value=mock_client):
            await manager.start(start_bot=False)

        assert manager.user is mock_client
        mock_client.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_with_bot(self):
        config = AppConfig(
            telegram=TelegramConfig(
                api_id=123, api_hash="hash123", session_name="test", bot_token="bot_tok"
            )
        )
        manager = ClientManager(config)

        mock_user = AsyncMock()
        mock_bot = AsyncMock()
        clients = [mock_user, mock_bot]

        with patch("src.client.TelegramClient", side_effect=clients):
            await manager.start(start_bot=True)

        assert manager.user is mock_user
        assert manager.bot is mock_bot
        mock_bot.start.assert_awaited_once_with(bot_token="bot_tok")

    @pytest.mark.asyncio
    async def test_stop_disconnects(self):
        config = AppConfig(
            telegram=TelegramConfig(api_id=123, api_hash="hash123", session_name="test")
        )
        manager = ClientManager(config)

        mock_client = AsyncMock()
        with patch("src.client.TelegramClient", return_value=mock_client):
            await manager.start(start_bot=False)
            await manager.stop()

        mock_client.disconnect.assert_awaited_once()
