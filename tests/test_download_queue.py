import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock
import asyncio

from src.downloader import DownloadQueue


def _make_video_message(msg_id=1, mime="video/mp4", filename="test.mp4", size=1024):
    from telethon.tl.types import MessageMediaDocument
    attr_video = MagicMock(spec=[])
    type(attr_video).__name__ = "DocumentAttributeVideo"
    attr_filename = MagicMock(spec=[])
    attr_filename.file_name = filename
    doc = MagicMock()
    doc.mime_type = mime
    doc.size = size
    doc.attributes = [attr_video, attr_filename]
    media = MagicMock()
    media.__class__ = MessageMediaDocument
    type(media).document = PropertyMock(return_value=doc)
    msg = MagicMock()
    msg.id = msg_id
    msg.media = media
    msg.text = ""
    return msg


def _mock_iter_download(chunk_size=512, file_size=1024):
    """创建一个模拟的 iter_download 异步迭代器。"""
    async def mock_iter(*args, **kwargs):
        offset = kwargs.get('offset', 0)
        remaining = file_size - offset
        while remaining > 0:
            chunk = b'x' * min(chunk_size, remaining)
            yield chunk
            remaining -= len(chunk)
    return mock_iter


class TestDownloadQueue:
    @pytest.mark.asyncio
    async def test_submit_skips_completed(self, tmp_path):
        from src.database import DownloadDB
        db = DownloadDB(tmp_path / "test.db")
        db.record("chan", 1, "file.mp4")  # 标记已完成

        client = AsyncMock()
        queue = DownloadQueue(client, str(tmp_path), db, max_concurrent=2)
        msg = _make_video_message(msg_id=1)
        result = await queue.submit(msg, "chan")
        assert result is None
        db.close()

    @pytest.mark.asyncio
    async def test_submit_downloads_and_updates_status(self, tmp_path):
        from src.database import DownloadDB
        db = DownloadDB(tmp_path / "test.db")

        client = AsyncMock()
        out_file = tmp_path / "chan_1_test.mp4"
        out_file.touch()
        client.iter_download = _mock_iter_download()

        msg = _make_video_message(msg_id=1)
        msg.get_input_chat = AsyncMock(return_value=MagicMock(username="chan"))

        queue = DownloadQueue(client, str(tmp_path), db, max_concurrent=2)
        result = await queue.submit(msg, "chan")

        task = db.get_task("chan", 1)
        assert task is not None
        assert task["status"] == "completed"
        db.close()

    @pytest.mark.asyncio
    async def test_submit_records_failure(self, tmp_path):
        from src.database import DownloadDB
        db = DownloadDB(tmp_path / "test.db")

        async def mock_iter_error(*args, **kwargs):
            raise RuntimeError("network error")

        client = AsyncMock()
        client.iter_download = mock_iter_error

        msg = _make_video_message(msg_id=2)
        msg.get_input_chat = AsyncMock(return_value=MagicMock(username="chan"))

        queue = DownloadQueue(client, str(tmp_path), db, max_concurrent=2)
        with pytest.raises(RuntimeError):
            await queue.submit(msg, "chan")

        task = db.get_task("chan", 2)
        assert task is not None
        assert task["status"] == "failed"
        db.close()

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, tmp_path):
        """验证 Semaphore 确实限制了并发数。"""
        from src.database import DownloadDB
        db = DownloadDB(tmp_path / "test.db")

        concurrent_count = 0
        max_observed = 0

        async def mock_iter(*args, **kwargs):
            nonlocal concurrent_count, max_observed
            concurrent_count += 1
            max_observed = max(max_observed, concurrent_count)
            await asyncio.sleep(0.05)
            yield b'x' * 512
            concurrent_count -= 1

        client = AsyncMock()
        client.iter_download = mock_iter

        queue = DownloadQueue(client, str(tmp_path), db, max_concurrent=2)

        msgs = []
        for i in range(5):
            msg = _make_video_message(msg_id=i + 10)
            msg.get_input_chat = AsyncMock(return_value=MagicMock(username="chan"))
            msgs.append(msg)

        tasks = [queue.submit(msg, "chan") for msg in msgs]
        await asyncio.gather(*tasks)

        assert max_observed <= 2  # 并发不超过 2
        db.close()
