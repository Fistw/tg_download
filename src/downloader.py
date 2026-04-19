from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, FileReferenceExpiredError
from telethon.tl.types import MessageMediaDocument

from .database import DownloadDB
from .utils import parse_telegram_link, format_progress

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int], None]]

MAX_RETRIES = 3


def _is_video(message) -> bool:
    """检查消息是否包含视频媒体。"""
    if not isinstance(message.media, MessageMediaDocument):
        return False
    doc = message.media.document
    if doc is None:
        return False
    for attr in doc.attributes:
        # DocumentAttributeVideo 表示这是一个视频文件
        if type(attr).__name__ == "DocumentAttributeVideo":
            return True
    return any(
        doc.mime_type.startswith("video/") for _ in [1]
    ) if doc.mime_type else False


def _build_filename(channel: str, message_id: int, message) -> str:
    """根据频道名、消息 ID 和原始文件名构建下载文件名。"""
    original = None
    if isinstance(message.media, MessageMediaDocument) and message.media.document:
        for attr in message.media.document.attributes:
            if hasattr(attr, "file_name") and attr.file_name:
                original = attr.file_name
                break
    if original is None:
        mime = message.media.document.mime_type or "video/mp4"
        ext = mime.split("/")[-1]
        original = f"video.{ext}"
    # 清理频道名中的特殊字符
    safe_channel = str(channel).lstrip("-").replace("/", "_")
    return f"{safe_channel}_{message_id}_{original}"


async def _download_with_retry(
    client: TelegramClient,
    message,
    file_path: Path,
    progress_callback: ProgressCallback = None,
    chunk_size_kb: int = 512,
) -> Path:
    """带重试逻辑的下载，支持自定义块大小。"""
    request_size = chunk_size_kb * 1024  # KB -> bytes
    
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 使用 iter_download 并支持自定义 request_size 以提高速度
            file_size = message.media.document.size if (message.media and message.media.document) else 0
            downloaded = 0
            with open(str(file_path), 'wb') as f:
                async for chunk in client.iter_download(
                    message,
                    request_size=request_size,
                ):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and file_size > 0:
                        progress_callback(downloaded, file_size)
            return file_path
        except FloodWaitError as e:
            logger.warning("触发 FloodWait，等待 %d 秒后重试 (第%d次)", e.seconds, attempt)
            await asyncio.sleep(e.seconds)
        except FileReferenceExpiredError:
            logger.warning("FileReference 已过期，重新获取消息 (第%d次)", attempt)
            # 重新获取消息以刷新 file_reference
            chat = await message.get_input_chat()
            refreshed = await client.get_messages(chat, ids=message.id)
            if refreshed is None:
                raise RuntimeError(f"无法重新获取消息 {message.id}")
            message = refreshed
        except Exception:
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            logger.warning("下载失败，%d 秒后重试 (第%d次)", wait, attempt)
            await asyncio.sleep(wait)
    raise RuntimeError(f"下载在 {MAX_RETRIES} 次重试后仍然失败")


async def download_message(
    client: TelegramClient,
    message,
    output_dir: str | Path,
    progress_callback: ProgressCallback = None,
    chunk_size_kb: int = 512,
) -> Path | None:
    """下载单条消息中的视频媒体。如果消息不含视频则返回 None。"""
    if not _is_video(message):
        logger.debug("消息 %d 不包含视频，跳过", message.id)
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chat = await message.get_input_chat()
    channel_name = getattr(chat, "username", None) or str(getattr(chat, "channel_id", "unknown"))
    filename = _build_filename(channel_name, message.id, message)
    file_path = output_dir / filename

    if file_path.exists():
        logger.info("文件已存在，跳过: %s", file_path)
        return file_path

    total_size = message.media.document.size if message.media.document else 0
    logger.info("开始下载: %s (大小: %s)", filename, format_progress(0, total_size))

    result = await _download_with_retry(client, message, file_path, progress_callback, chunk_size_kb)
    logger.info("下载完成: %s", result)
    return result


async def download_all_videos_in_message(
    client: TelegramClient,
    message,
    output_dir: str | Path,
    progress_callback: ProgressCallback = None,
    chunk_size_kb: int = 512,
) -> list[Path]:
    """下载一条消息里的所有视频（包括 grouped 的消息组）。"""
    downloaded: list[Path] = []

    # 先尝试下载本条消息的视频
    if _is_video(message):
        path = await download_message(client, message, output_dir, progress_callback, chunk_size_kb)
        if path:
            downloaded.append(path)

    # 检查是否有 grouped_id，下载同组里的其他消息
    if hasattr(message, "grouped_id") and message.grouped_id:
        try:
            chat = await message.get_input_chat()
            # 获取同组的所有消息
            # 首先获取大概范围（message.id 附近）
            nearby_ids = list(range(message.id - 20, message.id + 20))
            nearby_messages = await client.get_messages(chat, ids=nearby_ids)
            for nearby_msg in nearby_messages:
                if nearby_msg and nearby_msg.grouped_id == message.grouped_id and nearby_msg.id != message.id and _is_video(nearby_msg):
                    path = await download_message(client, nearby_msg, output_dir, progress_callback, chunk_size_kb)
                    if path:
                        downloaded.append(path)
        except Exception as e:
            logger.warning(f"获取 grouped 消息失败: {e}")

    # 去重（避免重复下载）
    unique_downloaded = []
    seen_paths = set()
    for p in downloaded:
        if p and str(p) not in seen_paths:
            unique_downloaded.append(p)
            seen_paths.add(str(p))
    return unique_downloaded


async def download_by_link(
    client: TelegramClient,
    link: str,
    output_dir: str | Path,
    progress_callback: ProgressCallback = None,
) -> Path | None:
    """通过 Telegram 消息链接下载视频。"""
    parsed = parse_telegram_link(link)
    channel = parsed.channel

    # 处理私有频道 ID
    entity = int(channel) if channel.lstrip("-").isdigit() else channel

    # 如果是评论消息，需要从讨论组频道中获取
    if parsed.is_comment:
        # 获取主频道的完整信息
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.types import InputChannel
        # 先获取主频道实体
        main_channel = await client.get_entity(entity)
        # 获取完整频道信息，其中包含讨论组
        full_channel = await client(GetFullChannelRequest(main_channel))
        # 检查是否有讨论组
        if (
            hasattr(full_channel, 'full_chat')
            and hasattr(full_channel.full_chat, 'linked_chat_id')
            and full_channel.full_chat.linked_chat_id
        ):
            # 使用正确的讨论组 ID
            discussion_chat_id = full_channel.full_chat.linked_chat_id
            entity = int(f"-100{discussion_chat_id}")
            # 显式获取讨论组实体，确保它被缓存
            await client.get_entity(entity)

    message = await client.get_messages(entity, ids=parsed.message_id)

    if message is None:
        raise RuntimeError(f"无法获取消息: {link}")

    return await download_message(client, message, output_dir, progress_callback)


async def download_range(
    client: TelegramClient,
    channel: str,
    start_id: int,
    end_id: int,
    output_dir: str | Path,
    progress_callback: ProgressCallback = None,
    max_concurrent: int = 3,
) -> list[Path]:
    """下载指定消息 ID 范围内的所有视频（并发）。"""
    entity = int(channel) if channel.lstrip("-").isdigit() else channel
    ids = list(range(start_id, end_id + 1))
    messages = await client.get_messages(entity, ids=ids)

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _download_one(msg):
        async with semaphore:
            return await download_message(client, msg, output_dir, progress_callback)

    tasks = []
    for msg in messages:
        if msg is not None:
            tasks.append(_download_one(msg))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    paths: list[Path] = []
    for r in results:
        if isinstance(r, Path):
            paths.append(r)
        elif isinstance(r, Exception):
            logger.error("下载失败: %s", r)
    return paths


class DownloadQueue:
    """基于 Semaphore 的并发下载队列，集成数据库状态管理。"""

    def __init__(self, client: TelegramClient, output_dir: str | Path, db: DownloadDB, max_concurrent: int = 3) -> None:
        self._client = client
        self._output_dir = Path(output_dir)
        self._db = db
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def submit(self, message, channel: str, source: str = "cli", progress_callback: ProgressCallback = None) -> Path | None:
        """提交单个下载任务到队列。自动管理数据库状态。"""
        task_id = self._db.create_task(channel, message.id, source=source)
        if task_id == -1:
            logger.info("消息 %s/%d 已下载完成，跳过", channel, message.id)
            return None

        async with self._semaphore:
            self._db.update_status(channel, message.id, "downloading")
            try:
                path = await download_message(self._client, message, self._output_dir, progress_callback)
                if path is not None:
                    self._db.update_status(channel, message.id, "completed", filename=path.name, file_size=path.stat().st_size if path.exists() else None)
                else:
                    self._db.update_status(channel, message.id, "completed")
                return path
            except Exception as e:
                self._db.update_status(channel, message.id, "failed", error_message=str(e))
                raise
