import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from src.reaction_monitor import (
    _is_valid_reaction_event,
    _is_own_reaction,
    _get_message_from_chat,
    start_reaction_monitor,
)
from src.config import AppConfig, DownloadConfig, TelegramConfig
from src.database import DownloadDB


def test_enable_reaction_download_default():
    config = DownloadConfig()
    assert config.enable_reaction_download is False


def test_enable_reaction_download_custom():
    config = DownloadConfig(enable_reaction_download=True)
    assert config.enable_reaction_download is True


class TestIsValidReactionEvent:
    def test_returns_false_when_no_original_update(self):
        event = MagicMock(spec=[])
        is_valid, msg_id, chat_id = _is_valid_reaction_event(event)
        assert is_valid is False
        assert msg_id is None
        assert chat_id is None

    def test_returns_false_when_not_update_message_reactions(self):
        event = MagicMock()
        event.original_update = "not the right type"
        is_valid, msg_id, chat_id = _is_valid_reaction_event(event)
        assert is_valid is False
        assert msg_id is None
        assert chat_id is None


@pytest.mark.asyncio
class TestStartReactionMonitor:
    async def test_does_nothing_when_disabled(self):
        client = MagicMock()  # 使用普通 MagicMock，避免 async 装饰问题
        config = AppConfig()
        config.download.enable_reaction_download = False
        download_queue = AsyncMock()
        history = MagicMock()

        await start_reaction_monitor(client, config, download_queue, history)
        # on 应该没有被调用
        assert len(client.on.mock_calls) == 0
