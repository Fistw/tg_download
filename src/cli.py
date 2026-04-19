from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .config import AppConfig, load_config
from .client import ClientManager
from .downloader import download_by_link, download_range, DownloadQueue
from .database import DownloadDB
from .monitor import start_monitor
from .bot_handler import setup_bot_handlers
from .reaction_monitor import start_reaction_monitor
from .webdav_server import WebDAVServer
from .utils import parse_range, format_file_size


def _setup_logging(verbose: bool = False, config: AppConfig | None = None) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    logger = logging.getLogger()
    logger.setLevel(level)
    
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    logger.addHandler(console_handler)
    
    if config is not None:
        log_dir = Path(config.logging.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / config.logging.filename
        max_bytes = config.logging.max_file_size_mb * 1024 * 1024
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=30,
            encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
        logger.addHandler(file_handler)
        
        _cleanup_old_logs(log_dir, config.logging.retention_days)


def _cleanup_old_logs(log_dir: Path, retention_days: int) -> None:
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    
    for log_file in log_dir.glob("*.log*"):
        if log_file.is_file():
            file_mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if file_mtime < cutoff_date:
                try:
                    log_file.unlink()
                except Exception as e:
                    logging.warning(f"无法删除旧日志文件 {log_file}: {e}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-download",
        description="下载 Telegram 频道中受限制的视频文件",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("-v", "--verbose", action="store_true", help="启用详细日志")
    sub = parser.add_subparsers(dest="command", required=True)

    # download 子命令
    dl = sub.add_parser("download", help="下载指定链接或范围的视频")
    dl.add_argument("target", help="Telegram 消息链接或频道名")
    dl.add_argument("--range", dest="msg_range", help="消息 ID 范围，格式: start-end")
    dl.add_argument("-o", "--output", help="下载输出目录")

    # serve 子命令
    sv = sub.add_parser("serve", help="启动 Bot + 频道监控服务")
    sv.add_argument("--no-bot", action="store_true", help="不启动 Bot")
    sv.add_argument("--no-monitor", action="store_true", help="不启动监控")

    return parser


def _print_progress(current: int, total: int) -> None:
    """CLI 进度回调，打印到 stderr。"""
    from .utils import format_progress
    sys.stderr.write(f"\r{format_progress(current, total)}")
    sys.stderr.flush()
    if total > 0 and current >= total:
        sys.stderr.write("\n")


async def _cmd_download(args, config) -> None:
    output_dir = args.output or config.download.output_dir
    manager = ClientManager(config)
    await manager.start(start_bot=False)
    try:
        if args.msg_range:
            start_id, end_id = parse_range(args.msg_range)
            paths = await download_range(
                manager.user, args.target, start_id, end_id, output_dir,
                _print_progress, max_concurrent=config.download.max_concurrent
            )
            print(f"\n下载完成，共 {len(paths)} 个文件:")
            for p in paths:
                size = format_file_size(p.stat().st_size) if p.exists() else "?"
                print(f"  {p} ({size})")
        else:
            path = await download_by_link(manager.user, args.target, output_dir, _print_progress)
            if path is None:
                print("该消息不包含视频内容")
            else:
                size = format_file_size(path.stat().st_size) if path.exists() else "?"
                print(f"\n下载完成: {path} ({size})")
    finally:
        await manager.stop()


async def _cmd_serve(args, config) -> None:
    start_bot = not args.no_bot and bool(config.telegram.bot_token)
    manager = ClientManager(config)
    await manager.start(start_bot=start_bot)

    history = DownloadDB()
    download_queue = DownloadQueue(
        manager.user, config.download.output_dir, history, config.download.max_concurrent
    )

    # 启动 WebDAV 服务器
    webdav_server = None
    try:
        if config.webdav_server.enable:
            try:
                webdav_server = WebDAVServer(config.webdav_server, config.download.output_dir)
                webdav_server.start()
            except Exception as e:
                print(f"警告: 无法启动 WebDAV 服务器: {e}")
                import traceback
                traceback.print_exc()

        if not args.no_monitor:
            await start_monitor(
                manager.user, config.monitor, config.download.output_dir, history
            )

        await start_reaction_monitor(
            manager.user, config, download_queue, history, manager.bot if start_bot else None
        )

        if start_bot:
            await setup_bot_handlers(manager.bot, manager.user, config, history)

        print("服务已启动，按 Ctrl+C 停止")
        # 保持运行
        await manager.user.run_until_disconnected()
    except KeyboardInterrupt:
        print("\n正在停止...")
    finally:
        if webdav_server:
            webdav_server.stop()
        history.close()
        await manager.stop()


def main() -> None:
    parser = _build_parser()
    args, unknown = parser.parse_known_args()
    
    verbose_flag = args.verbose
    
    config = load_config(args.config)
    _setup_logging(verbose_flag, config)

    if args.command == "download":
        asyncio.run(_cmd_download(args, config))
    elif args.command == "serve":
        asyncio.run(_cmd_serve(args, config))


if __name__ == "__main__":
    main()
