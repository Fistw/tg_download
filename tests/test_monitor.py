import sqlite3
import pytest
from unittest.mock import MagicMock

from src.database import DownloadHistory
from src.monitor import _passes_filters
from src.config import MonitorConfig, MonitorFilters


class TestDownloadHistory:
    def test_record_and_check(self, tmp_path):
        db_path = tmp_path / "test.db"
        history = DownloadHistory(db_path)
        try:
            assert history.is_downloaded("chan", 1) is False
            history.record("chan", 1, "file.mp4", 1024)
            assert history.is_downloaded("chan", 1) is True
            assert history.is_downloaded("chan", 2) is False
        finally:
            history.close()

    def test_duplicate_record_ignored(self, tmp_path):
        db_path = tmp_path / "test.db"
        history = DownloadHistory(db_path)
        try:
            history.record("chan", 1, "file.mp4", 1024)
            # 重复插入不应报错
            history.record("chan", 1, "file2.mp4", 2048)
            assert history.is_downloaded("chan", 1) is True
        finally:
            history.close()

    def test_different_channels(self, tmp_path):
        db_path = tmp_path / "test.db"
        history = DownloadHistory(db_path)
        try:
            history.record("chan_a", 1, "a.mp4")
            assert history.is_downloaded("chan_a", 1) is True
            assert history.is_downloaded("chan_b", 1) is False
        finally:
            history.close()


def _make_media_message(mime="video/mp4", size_bytes=10 * 1024 * 1024, text="", is_video=True):
    """创建模拟的媒体消息用于过滤测试。"""
    from telethon.tl.types import MessageMediaDocument

    attrs = []
    if is_video:
        attr_video = MagicMock()
        type(attr_video).__name__ = "DocumentAttributeVideo"
        attrs.append(attr_video)

    doc = MagicMock()
    doc.mime_type = mime
    doc.size = size_bytes
    doc.attributes = attrs

    media = MagicMock(spec=MessageMediaDocument)
    media.document = doc

    msg = MagicMock()
    msg.media = media
    msg.text = text
    return msg


class TestPassesFilters:
    def test_video_passes_default_filters(self):
        msg = _make_media_message()
        config = MonitorConfig()
        assert _passes_filters(msg, config) is True

    def test_non_video_rejected(self):
        msg = _make_media_message(mime="application/pdf", is_video=False)
        config = MonitorConfig()
        assert _passes_filters(msg, config) is False

    def test_too_small_rejected(self):
        msg = _make_media_message(size_bytes=100)  # 100 bytes
        config = MonitorConfig(filters=MonitorFilters(min_size_mb=1))
        assert _passes_filters(msg, config) is False

    def test_too_large_rejected(self):
        msg = _make_media_message(size_bytes=5 * 1024 ** 3)  # 5 GB
        config = MonitorConfig(filters=MonitorFilters(max_size_mb=4096))
        assert _passes_filters(msg, config) is False

    def test_keyword_match(self):
        msg = _make_media_message(text="This is a Tutorial video")
        config = MonitorConfig(filters=MonitorFilters(keywords=["tutorial"]))
        assert _passes_filters(msg, config) is True

    def test_keyword_no_match(self):
        msg = _make_media_message(text="Random content")
        config = MonitorConfig(filters=MonitorFilters(keywords=["tutorial"]))
        assert _passes_filters(msg, config) is False

    def test_no_keywords_passes(self):
        msg = _make_media_message(text="anything")
        config = MonitorConfig(filters=MonitorFilters(keywords=[]))
        assert _passes_filters(msg, config) is True

    def test_text_message_rejected(self):
        msg = MagicMock()
        msg.media = None
        config = MonitorConfig()
        assert _passes_filters(msg, config) is False
