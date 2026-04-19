from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class TelegramConfig:
    api_id: int = 0
    api_hash: str = ""
    bot_token: str = ""
    session_name: str = "user_session"


@dataclass
class DownloadConfig:
    output_dir: str = "./downloads"
    max_concurrent: int = 3
    enable_reaction_download: bool = False
    send_download_to_allowed_users: bool = True


@dataclass
class MonitorFilters:
    min_size_mb: float = 0
    max_size_mb: float = 4096
    keywords: list[str] = field(default_factory=list)


@dataclass
class MonitorConfig:
    channels: list[str] = field(default_factory=list)
    filters: MonitorFilters = field(default_factory=MonitorFilters)


@dataclass
class BotConfig:
    allowed_users: list[int] = field(default_factory=list)


@dataclass
class AppConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    bot: BotConfig = field(default_factory=BotConfig)


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """从 YAML 文件加载配置，环境变量可覆盖敏感字段。"""
    path = Path(path)
    raw: dict = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    tg_raw = raw.get("telegram", {})
    telegram = TelegramConfig(
        api_id=int(os.environ.get("TG_API_ID", tg_raw.get("api_id", 0))),
        api_hash=os.environ.get("TG_API_HASH", tg_raw.get("api_hash", "")),
        bot_token=os.environ.get("TG_BOT_TOKEN", tg_raw.get("bot_token", "")),
        session_name=tg_raw.get("session_name", "user_session"),
    )

    dl_raw = raw.get("download", {})
    download = DownloadConfig(
        output_dir=dl_raw.get("output_dir", "./downloads"),
        max_concurrent=int(dl_raw.get("max_concurrent", 3)),
        enable_reaction_download=bool(dl_raw.get("enable_reaction_download", False)),
        send_download_to_allowed_users=bool(dl_raw.get("send_download_to_allowed_users", True)),
    )

    mon_raw = raw.get("monitor", {})
    filt_raw = mon_raw.get("filters", {})
    monitor = MonitorConfig(
        channels=mon_raw.get("channels", []),
        filters=MonitorFilters(
            min_size_mb=filt_raw.get("min_size_mb", 0),
            max_size_mb=filt_raw.get("max_size_mb", 4096),
            keywords=filt_raw.get("keywords", []),
        ),
    )

    bot_raw = raw.get("bot", {})
    bot = BotConfig(
        allowed_users=bot_raw.get("allowed_users", []),
    )

    return AppConfig(telegram=telegram, download=download, monitor=monitor, bot=bot)
