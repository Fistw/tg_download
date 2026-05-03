from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, Optional, Set

from telethon import TelegramClient
from telethon.tl.types import Message, MessageMediaDocument

from .config import DownloadConfig
from .connection_pool import TelegramConnectionPool
from .limiter import RetryStrategy, get_flood_coordinator
from .monitoring import DownloadSpeedMonitor

__all__ = ["ChunkedDownloader", "DownloadChunk"]

logger = logging.getLogger(__name__)


@dataclass
class DownloadChunk:
    """单个下载分片。"""
    index: int  # 分片索引（0-based）
    start: int  # 起始字节
    end: int  # 结束字节（不包含）
    downloaded: int = 0  # 已下载字节
    status: str = "pending"  # pending / downloading / completed / failed
    error: Optional[str] = None
    temp_path: Optional[Path] = None


class ChunkedDownloader:
    """分片下载器。

    将单个文件分为多个分片，使用连接池并发下载，最后合并。
    """

    def __init__(
        self,
        config: DownloadConfig,
        pool: Optional[TelegramConnectionPool] = None,
    ) -> None:
        self._config = config
        self._pool = pool
        self._retry_strategy = RetryStrategy(
            max_retries=config.max_retries,
            base_delay=config.retry_base_delay,
            max_delay=config.retry_max_delay,
        )
        self._flood_coordinator = get_flood_coordinator()
        self._speed_monitor = DownloadSpeedMonitor()

    def calculate_chunks(self, file_size: int, chunk_size_mb: int) -> list[DownloadChunk]:
        """计算文件分片。

        Args:
            file_size: 文件总大小（字节）
            chunk_size_mb: 每个分片大小（MB）

        Returns:
            分片列表
        """
        chunk_size = chunk_size_mb * 1024 * 1024
        chunks: list[DownloadChunk] = []

        current_pos = 0
        index = 0
        while current_pos < file_size:
            end_pos = min(current_pos + chunk_size, file_size)
            chunks.append(
                DownloadChunk(
                    index=index,
                    start=current_pos,
                    end=end_pos,
                )
            )
            current_pos = end_pos
            index += 1

        return chunks

    def get_temp_chunk_path(self, output_dir: Path, filename: str, index: int) -> Path:
        """获取分片临时文件路径。"""
        return output_dir / f"{filename}.part{index}"

    async def download_single_chunk(
        self,
        client: TelegramClient,
        message: Message,
        chunk: DownloadChunk,
        temp_path: Path,
    ) -> DownloadChunk:
        """下载单个分片。

        Args:
            client: Telegram 客户端
            message: 消息对象
            chunk: 分片信息
            temp_path: 临时文件路径

        Returns:
            更新后的分片信息
        """
        chunk.status = "downloading"
        chunk.temp_path = temp_path
        offset = chunk.start + chunk.downloaded
        limit = chunk.end - offset

        try:
            async for chunk_data in client.iter_download(
                message.media,
                offset=offset,
                limit=limit,
            ):
                with open(temp_path, "ab") as f:
                    f.write(chunk_data)

                chunk.downloaded += len(chunk_data)

            chunk.status = "completed"
            logger.debug(f"Chunk {chunk.index} downloaded successfully")

        except Exception as e:
            chunk.status = "failed"
            chunk.error = str(e)
            logger.error(f"Chunk {chunk.index} download failed: {e}")
            raise

        return chunk

    async def download_file(
        self,
        message: Message,
        output_path: Path,
    ) -> Path:
        """分片下载文件。

        Args:
            message: 包含文件的消息
            output_path: 输出文件路径

        Returns:
            下载完成后的文件路径
        """
        if not self._config.enable_chunked_download:
            raise RuntimeError("Chunked download is not enabled in config")

        # 获取文件大小
        file_size = 0
        if isinstance(message.media, MessageMediaDocument):
            file_size = message.media.document.size
        if file_size == 0:
            raise ValueError("Could not get file size")

        output_dir = output_path.parent
        filename = output_path.name

        # 计算分片
        chunks = self.calculate_chunks(file_size, self._config.chunk_size_mb)
        logger.info(f"File split into {len(chunks)} chunks")

        # 准备分片临时文件
        for chunk in chunks:
            temp_path = self.get_temp_chunk_path(output_dir, filename, chunk.index)
            if temp_path.exists():
                chunk.downloaded = temp_path.stat().st_size
                if chunk.downloaded == (chunk.end - chunk.start):
                    chunk.status = "completed"

        # 开始速度监控
        self._speed_monitor.start(file_size)

        # 并发下载分片
        pending_chunks = [c for c in chunks if c.status == "pending"]
        completed_count = len([c for c in chunks if c.status == "completed"])
        logger.info(f"Already completed {completed_count} chunks")

        if pending_chunks:
            await self._download_chunks_concurrent(message, output_dir, filename, pending_chunks)

        # 合并分片
        await self._merge_chunks(chunks, output_path, output_dir, filename)

        # 完成速度监控
        self._speed_monitor.finish()

        return output_path

    async def _download_chunks_concurrent(
        self,
        message: Message,
        output_dir: Path,
        filename: str,
        chunks: list[DownloadChunk],
    ) -> None:
        """并发下载多个分片。"""
        semaphore = asyncio.Semaphore(self._config.max_concurrent_chunks)

        async def download_one(chunk: DownloadChunk):
            async with semaphore:
                temp_path = self.get_temp_chunk_path(output_dir, filename, chunk.index)

                async def attempt_download():
                    if self._pool:
                        async with self._pool.acquire() as client:
                            return await self.download_single_chunk(client, message, chunk, temp_path)
                    else:
                        # 兼容没有连接池的情况，需要外部提供，但这里先抛出错误
                        raise RuntimeError("Connection pool is required for chunked download")

                # 使用重试策略
                retry_num = 0
                while True:
                    try:
                        await self._flood_coordinator.wait_if_needed()
                        return await attempt_download()
                    except Exception as e:
                        wait_time = self._retry_strategy.get_delay(retry_num)
                        logger.warning(
                            f"Chunk {chunk.index} download attempt {retry_num+1} failed: {e}, "
                            f"waiting {wait_time:.2f}s"
                        )
                        await asyncio.sleep(wait_time)
                        retry_num += 1

        # 运行所有下载任务
        tasks = [download_one(chunk) for chunk in chunks]
        await asyncio.gather(*tasks)

    async def _merge_chunks(
        self,
        chunks: list[DownloadChunk],
        output_path: Path,
        output_dir: Path,
        filename: str,
    ) -> None:
        """合并下载的分片。

        Args:
            chunks: 所有分片
            output_path: 最终输出路径
            output_dir: 输出目录
            filename: 文件名
        """
        logger.info(f"Merging {len(chunks)} chunks into {output_path}")

        hasher = hashlib.md5()
        total_bytes = 0

        # 合并分片
        with open(output_path, "wb") as f_out:
            for chunk in chunks:
                temp_path = self.get_temp_chunk_path(output_dir, filename, chunk.index)
                if not temp_path.exists():
                    raise RuntimeError(f"Chunk {chunk.index} file missing: {temp_path}")

                with open(temp_path, "rb") as f_in:
                    while True:
                        data = f_in.read(8192)
                        if not data:
                            break
                        f_out.write(data)
                        hasher.update(data)
                        total_bytes += len(data)

        # 验证文件大小
        expected_size = sum(c.end - c.start for c in chunks)
        if total_bytes != expected_size:
            raise RuntimeError(f"File size mismatch: expected {expected_size}, got {total_bytes}")

        # 清理临时分片文件
        for chunk in chunks:
            temp_path = self.get_temp_chunk_path(output_dir, filename, chunk.index)
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning(f"Could not remove temp chunk: {temp_path}")

        logger.info(f"Successfully merged chunks into {output_path}")
