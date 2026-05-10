from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.tl.types import MessageMediaDocument

from .database import DownloadDB
from .limiter import FloodWaitCoordinator, get_flood_coordinator
from .downloader import download_message, _is_video

logger = logging.getLogger(__name__)


class Deduplicator:
    """去重管理器，支持扫描、去重和下载视频。"""

    def __init__(
        self,
        client: TelegramClient,
        db: DownloadDB,
        flood_coordinator: Optional[FloodWaitCoordinator] = None,
    ) -> None:
        self._client = client
        self._db = db
        self._flood_coordinator = flood_coordinator or get_flood_coordinator()
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # 默认不暂停

    def create_task(
        self,
        chat_id: int,
        chat_title: Optional[str] = None,
        start_message_id: Optional[int] = None,
        total_messages: Optional[int] = None,
    ) -> int:
        """创建去重任务，返回任务 ID。"""
        return self._db.create_dedupe_task(chat_id, chat_title, start_message_id, total_messages)

    async def scan_chat(self, task_id: int) -> None:
        """扫描聊天记录，识别视频媒体。"""
        task = self._db.get_dedupe_task(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")

        chat_id = task["chat_id"]
        last_scanned_id = task["last_scanned_message_id"]
        processed = task["processed_messages"] or 0

        logger.info("开始扫描聊天 %d，从消息 ID %s 开始", chat_id, last_scanned_id or "开始")
        self._db.update_dedupe_task(task_id, status="scanning")

        try:
            async for message in self._client.iter_messages(chat_id, offset_id=last_scanned_id, reverse=False):
                await self._pause_event.wait()

                if message is None:
                    continue

                if _is_video(message):
                    doc = message.media.document
                    file_id = str(doc.id)
                    file_size = doc.size
                    duration = None
                    width = None
                    height = None

                    for attr in doc.attributes:
                        if type(attr).__name__ == "DocumentAttributeVideo":
                            duration = getattr(attr, "duration", None)
                            width = getattr(attr, "w", None)
                            height = getattr(attr, "h", None)
                            break

                    self._db.add_dedupe_media(
                        task_id,
                        file_id,
                        file_size,
                        duration,
                        width,
                        height,
                        message.id,
                        message.date.isoformat() if message.date else None,
                    )

                    self._db.add_dedupe_result(
                        task_id,
                        message.id,
                        file_id,
                        is_duplicate=False,
                        is_original=True,
                    )

                processed += 1
                if processed % 1000 == 0:
                    self._db.update_dedupe_task(
                        task_id,
                        last_scanned_message_id=message.id,
                        processed_messages=processed,
                    )
                    logger.info("已扫描 %d 条消息，当前消息 ID %d", processed, message.id)

                await self._flood_coordinator.wait_if_needed()

            self._db.update_dedupe_task(
                task_id,
                status="completed",
                processed_messages=processed,
            )
            logger.info("扫描完成，共处理 %d 条消息", processed)

        except asyncio.CancelledError:
            self._db.update_dedupe_task(task_id, status="paused")
            logger.info("扫描已暂停")
            raise
        except Exception as e:
            self._db.update_dedupe_task(task_id, status="failed")
            logger.error("扫描失败: %s", e)
            raise

    def pause_scan(self) -> None:
        """暂停扫描。"""
        self._pause_event.clear()
        logger.info("扫描已暂停")

    def resume_scan(self) -> None:
        """恢复扫描。"""
        self._pause_event.set()
        logger.info("扫描已恢复")

    def get_media_list(
        self,
        task_id: int,
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None,
        filter_type: str = "all",
    ) -> list[dict]:
        """获取媒体列表。"""
        return self._db.get_dedupe_media_list(task_id, page, limit, search, filter_type)

    async def download_media(
        self,
        task_id: int,
        output_dir: str | Path,
        file_id: Optional[str] = None,
        download_all: bool = False,
    ) -> int:
        """下载去重后的视频。

        Args:
            task_id: 去重任务 ID
            output_dir: 输出目录
            file_id: 指定下载单个文件的 file_id
            download_all: 是否下载所有去重后的文件

        Returns:
            下载的文件数量
        """
        task = self._db.get_dedupe_task(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")

        chat_id = task["chat_id"]
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # 获取要下载的媒体列表
        if download_all:
            media_list = self._db.get_dedupe_media_list(task_id, filter_type="singles")
            # 同时获取重复文件的第一个出现
            duplicates = self._db.get_dedupe_media_list(task_id, filter_type="duplicates")
            media_list.extend(duplicates)
        elif file_id:
            media = self._db.get_dedupe_media(task_id, file_id)
            media_list = [media] if media else []
        else:
            raise ValueError("必须指定 file_id 或设置 download_all=True")

        downloaded_count = 0

        for media in media_list:
            if media is None:
                continue

            message_id = media["first_seen_message_id"]
            try:
                message = await self._client.get_messages(chat_id, ids=message_id)
                if message and _is_video(message):
                    await self._flood_coordinator.wait_if_needed()
                    result = await download_message(
                        self._client,
                        message,
                        output_dir,
                        flood_coordinator=self._flood_coordinator,
                    )
                    if result:
                        downloaded_count += 1
                        logger.info("已下载: %s", result)
            except Exception as e:
                logger.error("下载消息 %d 失败: %s", message_id, e)
                continue

        return downloaded_count
