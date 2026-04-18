import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from src.downloader import (
    _is_video,
    _build_filename,
    download_message,
    download_by_link,
    download_range,
)


def _make_video_message(msg_id=1, mime="video/mp4", filename="test.mp4", size=1024):
    """创建一个模拟的视频消息对象。"""
    attr_video = MagicMock(spec=[])  # 空 spec，不会自动生成 file_name 属性
    type(attr_video).__name__ = "DocumentAttributeVideo"

    attr_filename = MagicMock(spec=[])
    attr_filename.file_name = filename

    doc = MagicMock()
    doc.mime_type = mime
    doc.size = size
    doc.attributes = [attr_video, attr_filename]

    media = MagicMock()
    media.__class__.__name__ = "MessageMediaDocument"
    type(media).document = PropertyMock(return_value=doc)

    msg = MagicMock()
    msg.id = msg_id
    msg.media = media
    msg.text = ""

    # 让 isinstance 检查通过
    from telethon.tl.types import MessageMediaDocument
    msg.media.__class__ = MessageMediaDocument

    return msg


def _make_text_message(msg_id=2):
    """创建一个纯文本消息。"""
    msg = MagicMock()
    msg.id = msg_id
    msg.media = None
    return msg


class TestIsVideo:
    def test_video_message(self):
        msg = _make_video_message()
        assert _is_video(msg) is True

    def test_text_message(self):
        msg = _make_text_message()
        assert _is_video(msg) is False

    def test_non_video_document(self):
        doc = MagicMock()
        doc.mime_type = "application/pdf"
        doc.attributes = []

        media = MagicMock()
        type(media).document = PropertyMock(return_value=doc)

        from telethon.tl.types import MessageMediaDocument
        media.__class__ = MessageMediaDocument

        msg = MagicMock()
        msg.media = media
        assert _is_video(msg) is False


class TestBuildFilename:
    def test_with_original_filename(self):
        msg = _make_video_message(msg_id=42, filename="holiday.mp4")
        name = _build_filename("test_channel", 42, msg)
        assert name == "test_channel_42_holiday.mp4"

    def test_with_numeric_channel(self):
        msg = _make_video_message(msg_id=10, filename="vid.mkv")
        name = _build_filename("-1001234567890", 10, msg)
        assert name == "1001234567890_10_vid.mkv"

    def test_without_filename_attribute(self):
        attr_video = MagicMock(spec=[])  # 空 spec，没有 file_name
        type(attr_video).__name__ = "DocumentAttributeVideo"

        doc = MagicMock()
        doc.mime_type = "video/mp4"
        doc.size = 100
        doc.attributes = [attr_video]

        media = MagicMock()
        type(media).document = PropertyMock(return_value=doc)
        from telethon.tl.types import MessageMediaDocument
        media.__class__ = MessageMediaDocument

        msg = MagicMock()
        msg.id = 5
        msg.media = media
        name = _build_filename("chan", 5, msg)
        assert name == "chan_5_video.mp4"


class TestDownloadByLink:
    @pytest.mark.asyncio
    async def test_download_by_link_calls_get_messages(self, tmp_path):
        client = AsyncMock()
        msg = _make_video_message(msg_id=123)
        msg.get_input_chat = AsyncMock(return_value=MagicMock(username="testchan"))
        client.get_messages = AsyncMock(return_value=msg)

        out_file = tmp_path / "testchan_123_test.mp4"
        client.download_media = AsyncMock(return_value=str(out_file))
        # 创建假文件使 exists() 返回 True
        out_file.touch()

        result = await download_by_link(
            client, "https://t.me/testchan/123", str(tmp_path)
        )

        client.get_messages.assert_awaited_once_with("testchan", ids=123)

    @pytest.mark.asyncio
    async def test_download_by_link_none_message_raises(self):
        client = AsyncMock()
        client.get_messages = AsyncMock(return_value=None)

        with pytest.raises(RuntimeError, match="无法获取消息"):
            await download_by_link(client, "https://t.me/chan/999", "/tmp")


class TestDownloadRange:
    @pytest.mark.asyncio
    async def test_download_range_filters_none(self, tmp_path):
        client = AsyncMock()
        msg1 = _make_video_message(msg_id=1)
        msg1.get_input_chat = AsyncMock(return_value=MagicMock(username="ch"))
        client.download_media = AsyncMock(return_value=str(tmp_path / "file.mp4"))
        (tmp_path / "file.mp4").touch()

        # get_messages 返回包含 None 的列表
        client.get_messages = AsyncMock(return_value=[msg1, None])

        results = await download_range(client, "ch", 1, 2, str(tmp_path))
        # 至少处理了非 None 的消息
        assert client.get_messages.await_count == 1
