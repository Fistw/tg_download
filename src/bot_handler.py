from __future__ import annotations

import logging

from telethon import TelegramClient, events

from .config import AppConfig
from .downloader import download_by_link
from .database import DownloadDB
from .utils import parse_telegram_link

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int, allowed_users: list[int]) -> bool:
    """检查用户是否有权限使用 Bot。空列表表示允许所有人。"""
    if not allowed_users:
        return True
    return user_id in allowed_users


async def setup_bot_handlers(
    bot_client: TelegramClient,
    user_client: TelegramClient,
    config: AppConfig,
    history: DownloadDB | None = None,
) -> None:
    """注册 Bot 命令处理器。"""
    allowed = config.bot.allowed_users
    output_dir = config.download.output_dir

    async def _handle_bot_download(event, link: str) -> None:
        """Bot 下载公共逻辑：记录数据库 + 下载 + 发送文件。"""
        try:
            parsed = parse_telegram_link(link)
        except ValueError:
            await event.reply(f"无效的链接: {link}")
            return

        if history:
            task_id = history.create_task(parsed.channel, parsed.message_id, source="bot")
            if task_id == -1:
                await event.reply("该视频已下载过，跳过")
                return
            history.update_status(parsed.channel, parsed.message_id, "downloading")

        try:
            path = await download_by_link(user_client, link, output_dir)
            if path is None:
                await event.reply("该消息不包含视频内容")
                if history:
                    history.update_status(parsed.channel, parsed.message_id, "completed")
                return

            if history:
                file_size = path.stat().st_size if path.exists() else None
                history.update_status(parsed.channel, parsed.message_id, "completed", filename=path.name, file_size=file_size)

            if path.exists() and path.stat().st_size < 2 * 1024 ** 3:
                await event.reply("下载完成，正在发送文件...")
                await bot_client.send_file(event.chat_id, str(path))
            else:
                await event.reply(f"下载完成: {path}")
        except Exception as e:
            if history:
                history.update_status(parsed.channel, parsed.message_id, "failed", error_message=str(e))
            logger.exception("Bot 下载失败")
            await event.reply(f"下载失败: {e}")

    @bot_client.on(events.NewMessage(pattern=r"/start"))
    async def on_start(event):
        if not _is_allowed(event.sender_id, allowed):
            return
        await event.reply(
            "Telegram 视频下载 Bot\n\n"
            "命令:\n"
            "/download <链接> — 下载指定链接的视频\n"
            "/status — 查看状态\n"
        )

    @bot_client.on(events.NewMessage(pattern=r"/download\s+(.+)"))
    async def on_download(event):
        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        link = event.pattern_match.group(1).strip()
        await event.reply(f"开始下载: {link}")
        await _handle_bot_download(event, link)

    @bot_client.on(events.NewMessage(pattern=r"https?://t\.me/\S+"))
    async def on_link(event):
        if (event.text or "").startswith("/"):
            return
        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        link = event.text.strip()
        await event.reply(f"开始下载: {link}")
        await _handle_bot_download(event, link)

    @bot_client.on(events.NewMessage(pattern=r"/status"))
    async def on_status(event):
        if not _is_allowed(event.sender_id, allowed):
            return

        monitor_channels = config.monitor.channels
        status_text = (
            f"监控频道数: {len(monitor_channels)}\n"
            f"频道列表: {', '.join(monitor_channels) if monitor_channels else '无'}\n"
            f"下载目录: {output_dir}"
        )
        await event.reply(status_text)

    logger.info("Bot 命令处理器已注册")
