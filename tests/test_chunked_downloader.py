import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest
from src.chunked_downloader import ChunkedDownloader, DownloadChunk
from src.config import DownloadConfig


class TestDownloadChunk:
    """测试 DownloadChunk 数据类。"""

    def test_default_values(self):
        """测试默认值。"""
        chunk = DownloadChunk(
            index=0,
            start=0,
            end=1024,
        )
        assert chunk.index == 0
        assert chunk.start == 0
        assert chunk.end == 1024
        assert chunk.downloaded == 0
        assert chunk.status == "pending"
        assert chunk.error is None
        assert chunk.temp_path is None


class TestChunkedDownloader:
    """测试 ChunkedDownloader 类。"""

    @pytest.fixture
    def config(self):
        """测试配置 fixture。"""
        return DownloadConfig(
            enable_chunked_download=True,
            chunk_size_mb=1,
            max_concurrent_chunks=2,
            max_retries=3,
            retry_base_delay=0.1,
        )

    @pytest.fixture
    def temp_dir(self):
        """临时目录 fixture。"""
        with tempfile.TemporaryDirectory() as temp:
            yield Path(temp)

    def test_calculate_chunks(self, config):
        """测试分片计算。"""
        downloader = ChunkedDownloader(config)
        chunks = downloader.calculate_chunks(2500000, chunk_size_mb=1)  # 2.5MB
        assert len(chunks) == 3
        assert chunks[0].start == 0
        assert chunks[0].end == 1048576
        assert chunks[1].start == 1048576
        assert chunks[1].end == 2097152
        assert chunks[2].start == 2097152
        assert chunks[2].end == 2500000

    def test_get_temp_chunk_path(self, config, temp_dir):
        """测试获取分片临时路径。"""
        downloader = ChunkedDownloader(config)
        path = downloader.get_temp_chunk_path(temp_dir, "test.mp4", 0)
        assert path == temp_dir / "test.mp4.part0"

    def test_get_temp_chunk_path_index_1(self, config, temp_dir):
        """测试获取分片临时路径 index 1。"""
        downloader = ChunkedDownloader(config)
        path = downloader.get_temp_chunk_path(temp_dir, "test.mp4", 1)
        assert path == temp_dir / "test.mp4.part1"

    @pytest.mark.asyncio
    async def test_merge_chunks(self, config, temp_dir):
        """测试合并分片。"""
        downloader = ChunkedDownloader(config)

        # 创建测试分片文件
        chunk0 = temp_dir / "test.mp4.part0"
        chunk1 = temp_dir / "test.mp4.part1"
        with open(chunk0, "wb") as f:
            f.write(b"Hello")
        with open(chunk1, "wb") as f:
            f.write(b"World")

        chunks = [
            DownloadChunk(index=0, start=0, end=5, status="completed", temp_path=chunk0),
            DownloadChunk(index=1, start=5, end=10, status="completed", temp_path=chunk1),
        ]

        output_path = temp_dir / "test.mp4"
        await downloader._merge_chunks(chunks, output_path, temp_dir, "test.mp4")

        # 验证输出
        assert output_path.exists()
        with open(output_path, "rb") as f:
            content = f.read()
        assert content == b"HelloWorld"
        assert not chunk0.exists()  # 临时文件被清理
        assert not chunk1.exists()

    @pytest.mark.asyncio
    async def test_download_single_chunk_mocked(self, config):
        """测试下载单个分片（mock）。"""
        downloader = ChunkedDownloader(config)

        mock_client = AsyncMock()
        mock_message = MagicMock()

        async def mock_iter_download(*args, **kwargs):
            yield b"Test "
            yield b"data"

        mock_client.iter_download = mock_iter_download

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir) / "test.part0"
            chunk = DownloadChunk(
                index=0,
                start=0,
                end=9,
            )
            await downloader.download_single_chunk(
                mock_client, mock_message, chunk, temp_path
            )

            assert chunk.status == "completed"
            assert temp_path.exists()
            with open(temp_path, "rb") as f:
                assert f.read() == b"Test data"
