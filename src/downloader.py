from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError, FileReferenceExpiredError
from telethon.tl.types import MessageMediaDocument

from .database import DownloadDB
from .limiter import FloodWaitCoordinator, RetryStrategy, get_flood_coordinator
from .utils import parse_telegram_link, format_progress

logger = logging.getLogger(__name__)

ProgressCallback = Optional[Callable[[int, int], None]]

# 默认配置
DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_BASE_DELAY = 1.0
DEFAULT_RETRY_MAX_DELAY = 60.0


@dataclass
class VideoMetadata:
    """视频元数据，包含发送视频所需的信息"""
    attributes: Optional[Any] = None  # DocumentAttribute 列表
    thumb: Optional[Any] = None  # 缩略图数据
    supports_streaming: bool = True


@dataclass
class DownloadResult:
    """下载结果，包含文件路径和元数据。"""
    path: Path
    metadata: VideoMetadata
    
    def __post_init__(self):
        # 支持向后兼容性：可以像 Path 一样使用
        pass
    
    def __fspath__(self):
        # 支持 os.fspath()
        return str(self.path)
    
    def __str__(self):
        return str(self.path)
    
    @property
    def name(self):
        return self.path.name
    
    def stat(self):
        return self.path.stat()
    
    def exists(self):
        return self.path.exists()


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


def _extract_video_metadata(message) -> VideoMetadata:
    """从消息中提取视频元数据。"""
    metadata = VideoMetadata()
    if not isinstance(message.media, MessageMediaDocument) or not message.media.document:
        return metadata
    
    doc = message.media.document
    metadata.attributes = list(doc.attributes) if doc.attributes else None
    
    # 获取缩略图（如果有）
    if doc.thumbs and len(doc.thumbs) > 0:
        # 选择最大的缩略图
        metadata.thumb = doc.thumbs[-1]
    
    # 检查是否支持流媒体
    metadata.supports_streaming = True
    
    return metadata


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
    chunk_size_kb: int = 2048,
    channel: Optional[str] = None,
    message_id: Optional[int] = None,
    db: Optional[DownloadDB] = None,
    retry_strategy: Optional[RetryStrategy] = None,
    flood_coordinator: Optional[FloodWaitCoordinator] = None,
) -> Path:
    """带重试逻辑的下载，支持断点续传、自定义块大小。"""
    request_size = chunk_size_kb * 1024  # KB -> bytes
    
    # 使用默认策略
    if retry_strategy is None:
        retry_strategy = RetryStrategy(
            max_retries=DEFAULT_MAX_RETRIES,
            base_delay=DEFAULT_RETRY_BASE_DELAY,
            max_delay=DEFAULT_RETRY_MAX_DELAY,
        )
    
    if flood_coordinator is None:
        flood_coordinator = get_flood_coordinator()
    
    # 获取文件大小
    file_size = message.media.document.size if (message.media and message.media.document) else 0
    
    # 检查是否有已下载的部分
    initial_offset = 0
    if file_path.exists():
        initial_offset = file_path.stat().st_size
        if initial_offset > 0:
            if initial_offset >= file_size:
                logger.info("文件已下载完成：%s", file_path)
                return file_path
            logger.info("检测到部分下载文件，从 %d 字节继续：%s", initial_offset, file_path)
    
    # 更新数据库状态为下载中
    if db and channel and message_id:
        db.update_status(
            channel, message_id, "downloading",
            total_bytes=file_size,
            downloaded_bytes=initial_offset,
        )
    
    attempt = 0
    downloaded = initial_offset
    while retry_strategy.should_retry(attempt):
        try:
            await flood_coordinator.wait_if_needed()
            
            current_offset = downloaded
            mode = 'ab' if current_offset > 0 else 'wb'
            
            with open(str(file_path), mode) as f:
                async for chunk in client.iter_download(
                    message,
                    offset=current_offset,
                    request_size=request_size,
                ):
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    # 更新进度到数据库
                    if db and channel and message_id:
                        db.update_progress(channel, message_id, downloaded)
                    
                    if progress_callback and file_size > 0:
                        progress_callback(downloaded, file_size)
            
            logger.info("下载完成：%s (%.2f MB)", file_path, downloaded / (1024 * 1024))
            return file_path
            
        except FloodWaitError as e:
            logger.warning("触发 FloodWait，设置全局等待 %d 秒 (尝试 %d)", e.seconds, attempt + 1)
            await flood_coordinator.set_wait(e.seconds)
            attempt += 1
            
        except FileReferenceExpiredError:
            logger.warning("FileReference 已过期，重新获取消息 (尝试 %d)", attempt + 1)
            # 重新获取消息以刷新 file_reference
            chat = await message.get_input_chat()
            refreshed = await client.get_messages(chat, ids=message.id)
            if refreshed is None:
                raise RuntimeError(f"无法重新获取消息 {message.id}")
            message = refreshed
            attempt += 1
            
        except Exception as e:
            if not retry_strategy.should_retry(attempt):
                # 更新数据库状态为失败
                if db and channel and message_id:
                    db.update_status(
                        channel, message_id, "failed",
                        error_message=str(e),
                        downloaded_bytes=downloaded,
                        increment_retry=True,
                    )
                raise
            
            delay = retry_strategy.get_delay(attempt)
            logger.warning(
                "下载失败，%d 秒后重试 (尝试 %d/%d, 已下载 %d 字节): %s",
                delay, attempt + 1, retry_strategy.max_retries, downloaded, e
            )
            
            # 更新数据库状态
            if db and channel and message_id:
                db.update_status(
                    channel, message_id, "downloading",
                    downloaded_bytes=downloaded,
                    increment_retry=True,
                )
            
            await asyncio.sleep(delay)
            attempt += 1
    
    raise RuntimeError(f"下载在 {retry_strategy.max_retries} 次重试后仍然失败")


async def download_message(
    client: TelegramClient,
    message,
    output_dir: str | Path,
    progress_callback: ProgressCallback = None,
    chunk_size_kb: int = 2048,
    channel: Optional[str] = None,
    db: Optional[DownloadDB] = None,
    retry_strategy: Optional[RetryStrategy] = None,
    flood_coordinator: Optional[FloodWaitCoordinator] = None,
) -> DownloadResult | Path | None:
    """下载单条消息中的视频媒体。如果消息不含视频则返回 None。
    
    返回:
      - DownloadResult 对象（包含 path 和 metadata）
      - 或向后兼容的 Path 对象
    """
    if not _is_video(message):
        logger.debug("消息 %d 不包含视频，跳过", message.id)
        return None

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    chat = await message.get_input_chat()
    channel_name = channel or (getattr(chat, "username", None) or str(getattr(chat, "channel_id", "unknown")))
    filename = _build_filename(channel_name, message.id, message)
    file_path = output_dir / filename

    if file_path.exists():
        # 检查是否已完整下载
        if message.media and message.media.document:
            expected_size = message.media.document.size
            actual_size = file_path.stat().st_size
            if actual_size >= expected_size:
                logger.info("文件已存在且完整，跳过：%s", file_path)
                metadata = _extract_video_metadata(message)
                return DownloadResult(path=file_path, metadata=metadata)

    total_size = message.media.document.size if message.media.document else 0
    logger.info("开始下载：%s (大小: %s)", filename, format_progress(0, total_size))

    result_path = await _download_with_retry(
        client, message, file_path, progress_callback, chunk_size_kb,
        channel=channel_name, message_id=message.id, db=db,
        retry_strategy=retry_strategy, flood_coordinator=flood_coordinator,
    )
    logger.info("下载完成：%s", result_path)
    
    # 提取视频元数据
    metadata = _extract_video_metadata(message)
    
    return DownloadResult(path=result_path, metadata=metadata)


async def download_all_videos_in_message(
    client: TelegramClient,
    message,
    output_dir: str | Path,
    progress_callback: ProgressCallback = None,
    chunk_size_kb: int = 2048,
) -> list[DownloadResult | Path]:
    """下载一条消息里的所有视频（包括 grouped 的消息组）。"""
    downloaded: list[DownloadResult | Path] = []

    # 先尝试下载本条消息的视频
    if _is_video(message):
        result = await download_message(client, message, output_dir, progress_callback, chunk_size_kb)
        if result:
            downloaded.append(result)

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
                    result = await download_message(client, nearby_msg, output_dir, progress_callback, chunk_size_kb)
                    if result:
                        downloaded.append(result)
        except Exception as e:
            logger.warning(f"获取 grouped 消息失败: {e}")

    # 去重（避免重复下载）
    unique_downloaded = []
    seen_paths = set()
    for res in downloaded:
        path_str = None
        if isinstance(res, DownloadResult):
            path_str = str(res.path)
        elif isinstance(res, Path):
            path_str = str(res)
        
        if path_str and path_str not in seen_paths:
            unique_downloaded.append(res)
            seen_paths.add(path_str)
    return unique_downloaded


async def download_by_link(
    client: TelegramClient,
    link: str,
    output_dir: str | Path,
    progress_callback: ProgressCallback = None,
) -> DownloadResult | Path | None:
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
        if isinstance(r, DownloadResult):
            paths.append(r.path)
        elif isinstance(r, Path):
            paths.append(r)
        elif isinstance(r, Exception):
            logger.error("下载失败: %s", r)
    return paths


class DownloadQueue:
    """基于 Semaphore 的并发下载队列，集成数据库状态管理。"""

    def __init__(
        self,
        client: TelegramClient,
        output_dir: str | Path,
        db: DownloadDB,
        max_concurrent: int = 3,
        retry_strategy: Optional[RetryStrategy] = None,
        flood_coordinator: Optional[FloodWaitCoordinator] = None,
    ) -> None:
        self._client = client
        self._output_dir = Path(output_dir)
        self._db = db
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._retry_strategy = retry_strategy
        self._flood_coordinator = flood_coordinator or get_flood_coordinator()

    async def submit(self, message, channel: str, source: str = "cli", progress_callback: ProgressCallback = None) -> Path | None:
        """提交单个下载任务到队列。自动管理数据库状态。"""
        task_id = self._db.create_task(channel, message.id, source=source)
        if task_id == -1:
            logger.info("消息 %s/%d 已下载完成，跳过", channel, message.id)
            return None

        async with self._semaphore:
            self._db.update_status(channel, message.id, "downloading")
            try:
                result = await download_message(
                    self._client, message, self._output_dir, progress_callback,
                    channel=channel, db=self._db,
                    retry_strategy=self._retry_strategy,
                    flood_coordinator=self._flood_coordinator,
                )
                if result is not None:
                    path = result.path if isinstance(result, DownloadResult) else result
                    self._db.update_status(
                        channel, message.id, "completed",
                        filename=path.name,
                        file_size=path.stat().st_size if path.exists() else None,
                    )
                else:
                    self._db.update_status(channel, message.id, "completed")
                return result
            except Exception as e:
                self._db.update_status(channel, message.id, "failed", error_message=str(e))
                raise

    async def resume_pending_tasks(self) -> int:
        """恢复待处理的任务（downloading 或 failed 状态）"""
        pending_tasks = self._db.get_pending_tasks()
        resumed_count = 0
        logger.info("发现 %d 个待恢复的任务", len(pending_tasks))
        
        for task in pending_tasks:
            try:
                # 这里需要重新获取消息并提交下载，暂时跳过完整实现
                # 实际项目中需要保存更多上下文信息以便恢复
                logger.debug(
                    "待恢复任务: channel=%s, message_id=%s, status=%s, "
                    "downloaded=%s/%s bytes",
                    task["channel"], task["message_id"], task["status"],
                    task["downloaded_bytes"], task["total_bytes"],
                )
                # TODO: 完整实现需要额外保存消息上下文
            except Exception as e:
                logger.error("恢复任务失败: %s", e)
                
        return resumed_count
