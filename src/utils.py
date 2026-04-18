from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class TelegramLink:
    channel: str
    message_id: int


# 支持 https://t.me/channel/123 和 https://t.me/c/1234567890/123（私有频道）
_PUBLIC_LINK_RE = re.compile(
    r"https?://t\.me/([A-Za-z0-9_]+)/(\d+)"
)
_PRIVATE_LINK_RE = re.compile(
    r"https?://t\.me/c/(\d+)/(\d+)"
)


def parse_telegram_link(url: str) -> TelegramLink:
    """解析 Telegram 消息链接，返回频道标识和消息 ID。

    支持格式:
      - https://t.me/channel_name/123
      - https://t.me/c/1234567890/123 （私有频道）
    """
    # 先尝试匹配私有频道格式，因为 /c/ 会被公有正则错误匹配为用户名 "c"
    m = _PRIVATE_LINK_RE.match(url)
    if m:
        # 私有频道 ID 需要加上 -100 前缀转为 Telethon 的 peer id
        return TelegramLink(channel=f"-100{m.group(1)}", message_id=int(m.group(2)))

    m = _PUBLIC_LINK_RE.match(url)
    if m:
        return TelegramLink(channel=m.group(1), message_id=int(m.group(2)))

    raise ValueError(f"无法解析 Telegram 链接: {url}")


def parse_range(range_str: str) -> tuple[int, int]:
    """解析 '100-200' 格式的范围字符串，返回 (start, end)。"""
    parts = range_str.split("-", 1)
    if len(parts) != 2:
        raise ValueError(f"无效的范围格式: {range_str}，期望格式为 'start-end'")
    start, end = int(parts[0].strip()), int(parts[1].strip())
    if start > end:
        raise ValueError(f"范围起始值 {start} 大于结束值 {end}")
    return start, end


def format_file_size(size_bytes: int | float) -> str:
    """将字节数格式化为人类可读的文件大小。"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / 1024 ** 2:.1f} MB"
    else:
        return f"{size_bytes / 1024 ** 3:.2f} GB"


def format_progress(current: int, total: int) -> str:
    """格式化下载进度。"""
    if total <= 0:
        return f"{format_file_size(current)} / 未知"
    pct = current / total * 100
    return f"{format_file_size(current)} / {format_file_size(total)} ({pct:.1f}%)"
