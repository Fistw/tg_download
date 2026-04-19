import pytest

from src.utils import (
    parse_telegram_link,
    parse_range,
    format_file_size,
    format_progress,
    TelegramLink,
)


class TestParseTelegramLink:
    def test_public_channel_link(self):
        result = parse_telegram_link("https://t.me/testchannel/456")
        assert result == TelegramLink(channel="testchannel", message_id=456)

    def test_public_channel_http(self):
        result = parse_telegram_link("http://t.me/my_channel/1")
        assert result == TelegramLink(channel="my_channel", message_id=1)

    def test_private_channel_link(self):
        result = parse_telegram_link("https://t.me/c/1234567890/789")
        assert result == TelegramLink(channel="-1001234567890", message_id=789)

    def test_invalid_link_raises(self):
        with pytest.raises(ValueError, match="无法解析"):
            parse_telegram_link("https://example.com/not_telegram")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            parse_telegram_link("")

    def test_link_with_extra_path_not_matched(self):
        # /c/ 格式必须匹配 "c" 而非普通用户名
        result = parse_telegram_link("https://t.me/c/9999/100")
        assert result.channel == "-1009999"
        assert result.message_id == 100

    def test_public_channel_link_with_comment(self):
        result = parse_telegram_link("https://t.me/RSOOXX/1165?comment=512")
        assert result == TelegramLink(channel="RSOOXX", message_id=512)

    def test_private_channel_link_with_comment(self):
        result = parse_telegram_link("https://t.me/c/1234567890/789?comment=456")
        assert result == TelegramLink(channel="-1001234567890", message_id=456)

    def test_public_channel_link_with_fragment(self):
        result = parse_telegram_link("https://t.me/testchannel/456#hash")
        assert result == TelegramLink(channel="testchannel", message_id=456)


class TestParseRange:
    def test_valid_range(self):
        assert parse_range("100-200") == (100, 200)

    def test_range_with_spaces(self):
        assert parse_range(" 10 - 20 ") == (10, 20)

    def test_single_value_raises(self):
        with pytest.raises(ValueError, match="无效的范围格式"):
            parse_range("100")

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError, match="起始值"):
            parse_range("200-100")

    def test_same_start_end(self):
        assert parse_range("50-50") == (50, 50)


class TestFormatFileSize:
    def test_bytes(self):
        assert format_file_size(500) == "500 B"

    def test_kilobytes(self):
        assert format_file_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_file_size(10 * 1024 * 1024) == "10.0 MB"

    def test_gigabytes(self):
        assert format_file_size(2.5 * 1024 ** 3) == "2.50 GB"

    def test_zero(self):
        assert format_file_size(0) == "0 B"


class TestFormatProgress:
    def test_normal_progress(self):
        result = format_progress(512 * 1024, 1024 * 1024)
        assert "50.0%" in result

    def test_unknown_total(self):
        result = format_progress(1024, 0)
        assert "未知" in result

    def test_complete(self):
        result = format_progress(1024, 1024)
        assert "100.0%" in result
