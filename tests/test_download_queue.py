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
        client.download_media = AsyncMock(return_value=str(out_file))

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

        client = AsyncMock()
        client.download_media = AsyncMock(side_effect=RuntimeError("network error"))

        msg = _make_video_message(msg_id=2)
        msg.get_input_chat = AsyncMock(return_value=MagicMock(username="chan"))

        queue = DownloadQueue(client, str(tmp_path), db, max_concurrent=2)
        with pytest.raises(RuntimeError):
            await queue.submit(msg, "chan")

        task = db.get_task("chan", 2)
        assert task is not None
        assert task["status"] == "failed"
        assert "network error" in task["error_message"]
        db.close()

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, tmp_path):
        """验证 Semaphore 确实限制了并发数。"""
        from src.database import DownloadDB
        db = DownloadDB(tmp_path / "test.db")

        concurrent_count = 0
        max_observed = 0

        async def mock_download(msg, file, progress_callback=None):
            nonlocal concurrent_count, max_observed
            concurrent_count += 1
            max_observed = max(max_observed, concurrent_count)
            await asyncio.sleep(0.05)
            concurrent_count -= 1
            out = tmp_path / f"file_{msg.id}.mp4"
            out.touch()
            return str(out)

        client = AsyncMock()
        client.download_media = mock_download

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
