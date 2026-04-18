from __future__ import annotations

import logging
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaDocument

from .config import MonitorConfig
from .database import DownloadDB
from .downloader import download_message

logger = logging.getLogger(__name__)


def _passes_filters(message, config: MonitorConfig) -> bool:
    """检查消息是否满足监控过滤条件。"""
    if not isinstance(message.media, MessageMediaDocument):
        return False
    doc = message.media.document
    if doc is None:
        return False

    # 检查是否为视频
    is_video = False
    for attr in doc.attributes:
        if type(attr).__name__ == "DocumentAttributeVideo":
            is_video = True
            break
    if not is_video and doc.mime_type and not doc.mime_type.startswith("video/"):
        return False

    # 文件大小过滤
    size_mb = doc.size / (1024 * 1024)
    filters = config.filters
    if size_mb < filters.min_size_mb or size_mb > filters.max_size_mb:
        return False

    # 关键词过滤（消息文本中包含任一关键词即通过）
    if filters.keywords:
        text = (message.text or "").lower()
        if not any(kw.lower() in text for kw in filters.keywords):
            return False

    return True


async def start_monitor(
    client: TelegramClient,
    config: MonitorConfig,
    output_dir: str | Path,
    history: DownloadDB | None = None,
) -> None:
    """注册频道监控事件处理器并运行。"""
    if not config.channels:
        logger.warning("未配置监控频道，监控模式未启动")
        return

    if history is None:
        history = DownloadDB()

    channels = []
    for ch in config.channels:
        channels.append(int(ch) if ch.lstrip("-").isdigit() else ch)

    @client.on(events.NewMessage(chats=channels))
    async def on_new_message(event):
        message = event.message
        chat = await event.get_chat()
        channel_name = getattr(chat, "username", None) or str(getattr(chat, "id", "unknown"))

        if history.is_downloaded(channel_name, message.id):
            return

        if not _passes_filters(message, config):
            return

        logger.info("监控到新视频: 频道=%s, 消息ID=%d", channel_name, message.id)
        task_id = history.create_task(channel_name, message.id, source="monitor")
        if task_id == -1:
            return
        try:
            history.update_status(channel_name, message.id, "downloading")
            path = await download_message(client, message, output_dir)
            if path is not None:
                file_size = path.stat().st_size if path.exists() else None
                history.update_status(channel_name, message.id, "completed", filename=path.name, file_size=file_size)
                logger.info("自动下载完成: %s", path)
            else:
                history.update_status(channel_name, message.id, "completed")
        except Exception:
            history.update_status(channel_name, message.id, "failed", error_message="自动下载异常")
            logger.exception("自动下载失败: 频道=%s, 消息ID=%d", channel_name, message.id)

    logger.info("频道监控已启动，监控 %d 个频道", len(channels))
