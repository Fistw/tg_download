import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import src.bot_handler as bot_handler
from src.bot_handler import (
    _is_allowed,
    _request_send_confirmation,
    _pending_send_callbacks,
    _pending_send_text_confirmations,
)


class TestIsAllowed:
    def test_empty_list_allows_all(self):
        assert _is_allowed(12345, []) is True

    def test_user_in_list(self):
        assert _is_allowed(111, [111, 222]) is True

    def test_user_not_in_list(self):
        assert _is_allowed(333, [111, 222]) is False


class TestRequestSendConfirmation:
    @pytest.mark.asyncio
    async def test_button_confirmation_returns_true(self, monkeypatch):
        monkeypatch.setattr(bot_handler, "BUTTON_AVAILABLE", True)
        _pending_send_callbacks.clear()
        bot_client = AsyncMock()
        bot_client.send_message.return_value = SimpleNamespace(id=101)

        task = asyncio.create_task(
            _request_send_confirmation(bot_client, user_id=123, message_id=456, timeout_seconds=5)
        )
        await asyncio.sleep(0)

        assert "botdl_123_456_send" in _pending_send_callbacks
        _, future = _pending_send_callbacks["botdl_123_456_send"]
        future.set_result(True)

        result = await task
        assert result is True
        assert "botdl_123_456_send" not in _pending_send_callbacks

    @pytest.mark.asyncio
    async def test_text_confirmation_can_cancel_immediately(self, monkeypatch):
        monkeypatch.setattr(bot_handler, "BUTTON_AVAILABLE", False)
        _pending_send_text_confirmations.clear()
        bot_client = AsyncMock()
        bot_client.send_message.return_value = SimpleNamespace(id=202)

        task = asyncio.create_task(
            _request_send_confirmation(bot_client, user_id=321, message_id=654, timeout_seconds=5)
        )
        await asyncio.sleep(0)

        assert 321 in _pending_send_text_confirmations
        _, future = _pending_send_text_confirmations[321]
        future.set_result(False)

        result = await task
        assert result is False
        assert 321 not in _pending_send_text_confirmations
