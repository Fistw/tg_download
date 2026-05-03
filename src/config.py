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
    chunk_size_kb: int = 512
    enable_reaction_download: bool = False
    send_download_to_allowed_users: bool = True
    ask_before_send: bool = True  # 新增：是否在发送前询问用户
    ask_timeout_seconds: int = 300  # 新增：询问超时时间（秒）
    # 重试策略配置
    max_retries: int = 5
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0
    # 自动恢复配置
    auto_resume: bool = True
    # 缓存清理配置
    enable_cache_cleanup: bool = True  # 是否启用自动清理
    cache_retention_days: int = 3  # 缓存保留天数
    max_cache_size_gb: float = 8.0  # 最大缓存大小（GB）
    # 连接池配置
    connection_pool_size: int = 1  # 连接池大小，默认1个连接保持向后兼容
    # 分片下载配置
    enable_chunked_download: bool = False  # 是否启用分片下载
    chunk_size_mb: int = 50  # 每个分片的大小（MB）
    max_concurrent_chunks: int = 3  # 最大并发下载分片数


@dataclass
class WebDAVServerConfig:
    enable: bool = False
    host: str = "0.0.0.0"
    port: int = 8080
    mount_path: str = "/"
    username: str = ""
    password: str = ""
    directory: str = ""  # 留空则使用 download.output_dir


@dataclass
class NASSyncConfig:
    enable: bool = False
    sync_type: str = "webdav"  # "webdav" 或 "sftp"
    # WebDAV 客户端配置
    webdav_url: str = ""
    webdav_username: str = ""
    webdav_password: str = ""
    webdav_remote_path: str = "/"
    # SFTP 客户端配置
    sftp_host: str = ""
    sftp_port: int = 22
    sftp_username: str = ""
    sftp_password: str = ""
    sftp_remote_path: str = "/"
    sftp_key_path: str = ""  # 可选，使用密钥认证
    # 通用配置
    max_retries: int = 3
    retry_delay_seconds: int = 5
    delete_after_sync: bool = False  # 同步后是否删除本地文件


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
class LoggingConfig:
    log_dir: str = "./logs"
    max_file_size_mb: int = 10
    retention_days: int = 7
    filename: str = "tg_download.log"


@dataclass
class AppConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    download: DownloadConfig = field(default_factory=DownloadConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    bot: BotConfig = field(default_factory=BotConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    webdav_server: WebDAVServerConfig = field(default_factory=WebDAVServerConfig)
    nas_sync: NASSyncConfig = field(default_factory=NASSyncConfig)


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
        chunk_size_kb=int(dl_raw.get("chunk_size_kb", 512)),
        enable_reaction_download=bool(dl_raw.get("enable_reaction_download", False)),
        send_download_to_allowed_users=bool(dl_raw.get("send_download_to_allowed_users", True)),
        ask_before_send=bool(dl_raw.get("ask_before_send", True)),
        ask_timeout_seconds=int(dl_raw.get("ask_timeout_seconds", 300)),
        max_retries=int(dl_raw.get("max_retries", 5)),
        retry_base_delay=float(dl_raw.get("retry_base_delay", 1.0)),
        retry_max_delay=float(dl_raw.get("retry_max_delay", 60.0)),
        auto_resume=bool(dl_raw.get("auto_resume", True)),
        enable_cache_cleanup=bool(dl_raw.get("enable_cache_cleanup", True)),
        cache_retention_days=int(dl_raw.get("cache_retention_days", 3)),
        max_cache_size_gb=float(dl_raw.get("max_cache_size_gb", 8.0)),
        connection_pool_size=int(dl_raw.get("connection_pool_size", 1)),
        enable_chunked_download=bool(dl_raw.get("enable_chunked_download", False)),
        chunk_size_mb=int(dl_raw.get("chunk_size_mb", 50)),
        max_concurrent_chunks=int(dl_raw.get("max_concurrent_chunks", 3)),
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

    log_raw = raw.get("logging", {})
    logging = LoggingConfig(
        log_dir=log_raw.get("log_dir", "./logs"),
        max_file_size_mb=int(log_raw.get("max_file_size_mb", 10)),
        retention_days=int(log_raw.get("retention_days", 7)),
        filename=log_raw.get("filename", "tg_download.log"),
    )

    webdav_raw = raw.get("webdav_server", {})
    webdav_server = WebDAVServerConfig(
        enable=bool(webdav_raw.get("enable", False)),
        host=webdav_raw.get("host", "0.0.0.0"),
        port=int(webdav_raw.get("port", 8080)),
        mount_path=webdav_raw.get("mount_path", "/"),
        username=os.environ.get("WEBDAV_USERNAME", webdav_raw.get("username", "")),
        password=os.environ.get("WEBDAV_PASSWORD", webdav_raw.get("password", "")),
        directory=webdav_raw.get("directory", ""),
    )

    nas_raw = raw.get("nas_sync", {})
    nas_sync = NASSyncConfig(
        enable=bool(nas_raw.get("enable", False)),
        sync_type=nas_raw.get("sync_type", "webdav"),
        webdav_url=os.environ.get("NAS_WEBDAV_URL", nas_raw.get("webdav_url", "")),
        webdav_username=os.environ.get("NAS_WEBDAV_USERNAME", nas_raw.get("webdav_username", "")),
        webdav_password=os.environ.get("NAS_WEBDAV_PASSWORD", nas_raw.get("webdav_password", "")),
        webdav_remote_path=nas_raw.get("webdav_remote_path", "/"),
        sftp_host=os.environ.get("NAS_SFTP_HOST", nas_raw.get("sftp_host", "")),
        sftp_port=int(os.environ.get("NAS_SFTP_PORT", nas_raw.get("sftp_port", 22))),
        sftp_username=os.environ.get("NAS_SFTP_USERNAME", nas_raw.get("sftp_username", "")),
        sftp_password=os.environ.get("NAS_SFTP_PASSWORD", nas_raw.get("sftp_password", "")),
        sftp_remote_path=nas_raw.get("sftp_remote_path", "/"),
        sftp_key_path=nas_raw.get("sftp_key_path", ""),
        max_retries=int(nas_raw.get("max_retries", 3)),
        retry_delay_seconds=int(nas_raw.get("retry_delay_seconds", 5)),
        delete_after_sync=bool(nas_raw.get("delete_after_sync", False)),
    )

    return AppConfig(
        telegram=telegram,
        download=download,
        monitor=monitor,
        bot=bot,
        logging=logging,
        webdav_server=webdav_server,
        nas_sync=nas_sync,
    )
