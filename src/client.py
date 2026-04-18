from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Self

from telethon import TelegramClient

from .config import AppConfig

logger = logging.getLogger(__name__)


class ClientManager:
    """管理 Telegram User Client 和 Bot Client 的生命周期。"""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._user_client: TelegramClient | None = None
        self._bot_client: TelegramClient | None = None

    @property
    def user(self) -> TelegramClient:
        if self._user_client is None:
            raise RuntimeError("User client 未初始化，请先调用 start()")
        return self._user_client

    @property
    def bot(self) -> TelegramClient:
        if self._bot_client is None:
            raise RuntimeError("Bot client 未初始化，请先调用 start()")
        return self._bot_client

    async def start(self, start_bot: bool = True) -> None:
        """启动客户端连接。"""
        tg = self._config.telegram

        self._user_client = TelegramClient(
            tg.session_name,
            tg.api_id,
            tg.api_hash,
        )
        await self._user_client.start()
        logger.info("User client 已连接")

        if start_bot and tg.bot_token:
            self._bot_client = TelegramClient(
                f"{tg.session_name}_bot",
                tg.api_id,
                tg.api_hash,
            )
            await self._bot_client.start(bot_token=tg.bot_token)
            logger.info("Bot client 已连接")

    async def stop(self) -> None:
        """断开所有客户端连接。"""
        if self._bot_client is not None:
            await self._bot_client.disconnect()
            logger.info("Bot client 已断开")
        if self._user_client is not None:
            await self._user_client.disconnect()
            logger.info("User client 已断开")

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()
