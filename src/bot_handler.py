from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from telethon import TelegramClient, events

from .config import AppConfig
from .downloader import download_by_link, DownloadResult, VideoMetadata
from .database import DownloadDB
from .utils import parse_telegram_link, format_file_size
from .cache import cleanup_cache

logger = logging.getLogger(__name__)


def _is_allowed(user_id: int, allowed_users: list[int]) -> bool:
    """检查用户是否有权限使用 Bot。空列表表示允许所有人。"""
    if not allowed_users:
        return True
    return user_id in allowed_users


async def _send_video_with_metadata(
    bot_client: TelegramClient,
    chat_id: Any,
    video_result: DownloadResult | Path,
):
    """使用元数据发送视频，支持预览图和流媒体播放。"""
    # 获取实际文件路径
    file_path = None
    if isinstance(video_result, DownloadResult):
        file_path = video_result.path
        logger.info(f"📺 Sending video with metadata: {file_path}")
        logger.info(f"   - Supports streaming: {video_result.metadata.supports_streaming}")
        logger.info(f"   - Has attributes: {bool(video_result.metadata.attributes)}")
        logger.info(f"   - Has thumbnail: {bool(video_result.metadata.thumb)}")
    else:
        file_path = video_result
        logger.info(f"📺 Sending video without metadata: {file_path}")
    
    # 关键：设置 supports_streaming=True 来启用流媒体播放
    try:
        logger.info(f"   Calling send_file with supports_streaming=True")
        result = await bot_client.send_file(
            chat_id, 
            str(file_path), 
            supports_streaming=True
        )
        logger.info(f"   ✅ Video sent successfully!")
    except Exception as e:
        logger.error(f"   ❌ Error sending video: {e}")
        import traceback
        logger.error(traceback.format_exc())


async def setup_bot_handlers(
    bot_client: TelegramClient,
    user_client: TelegramClient,
    config: AppConfig,
    history: DownloadDB | None = None,
) -> None:
    """注册 Bot 命令处理器。"""
    allowed = config.bot.allowed_users
    output_dir = config.download.output_dir

    async def _handle_bot_download(event, link: str) -> None:
        """Bot 下载公共逻辑：记录数据库 + 下载 + 发送文件。"""
        try:
            parsed = parse_telegram_link(link)
        except ValueError:
            await event.reply(f"无效的链接: {link}")
            return

        if history:
            task_id = history.create_task(parsed.channel, parsed.message_id, source="bot")
            if task_id == -1:
                await event.reply("该视频已下载过，跳过")
                return
            history.update_status(parsed.channel, parsed.message_id, "downloading")

        try:
            result = await download_by_link(user_client, link, output_dir)
            if result is None:
                await event.reply("该消息不包含视频内容")
                if history:
                    history.update_status(parsed.channel, parsed.message_id, "completed")
                return

            # 获取实际文件路径
            file_path = None
            if isinstance(result, DownloadResult):
                file_path = result.path
            else:
                file_path = result

            if history:
                file_size = file_path.stat().st_size if file_path.exists() else None
                history.update_status(parsed.channel, parsed.message_id, "completed", filename=file_path.name, file_size=file_size)

            if file_path.exists() and file_path.stat().st_size < 2 * 1024 ** 3:
                await event.reply("下载完成，正在发送文件...")
                await _send_video_with_metadata(bot_client, event.chat_id, result)
            else:
                await event.reply(f"下载完成: {file_path}")
        except Exception as e:
            if history:
                history.update_status(parsed.channel, parsed.message_id, "failed", error_message=str(e))
            logger.exception("Bot 下载失败")
            await event.reply(f"下载失败: {e}")

    @bot_client.on(events.NewMessage(pattern=r"/start"))
    async def on_start(event):
        if not _is_allowed(event.sender_id, allowed):
            return
        await event.reply(
            "Telegram 视频下载 Bot\n\n"
            "命令:\n"
            "/download <链接> — 下载指定链接的视频\n"
            "/status — 查看状态\n"
            "/clean_cache — 清理本地缓存视频\n"
            "/clean_cache --dry-run — 预览清理而不删除\n"
        )

    @bot_client.on(events.NewMessage(pattern=r"/download\s+(.+)"))
    async def on_download(event):
        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        link = event.pattern_match.group(1).strip()
        await event.reply(f"开始下载: {link}")
        await _handle_bot_download(event, link)

    @bot_client.on(events.NewMessage(pattern=r"https?://t\.me/\S+"))
    async def on_link(event):
        if (event.text or "").startswith("/"):
            return
        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        link = event.text.strip()
        await event.reply(f"开始下载: {link}")
        await _handle_bot_download(event, link)

    @bot_client.on(events.NewMessage(pattern=r"/status"))
    async def on_status(event):
        if not _is_allowed(event.sender_id, allowed):
            return

        monitor_channels = config.monitor.channels
        status_text = (
            f"监控频道数: {len(monitor_channels)}\n"
            f"频道列表: {', '.join(monitor_channels) if monitor_channels else '无'}\n"
            f"下载目录: {output_dir}"
        )
        await event.reply(status_text)
    
    @bot_client.on(events.NewMessage(pattern=r"/clean_cache(\s+--dry-run)?$"))
    async def on_clean_cache(event):
        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return
        
        dry_run = bool(event.pattern_match.group(1))
        msg_parts = [
            f"开始清理缓存{'（预览模式）' if dry_run else ''}...",
            f"  保留天数: {config.download.cache_retention_days} 天",
            f"  最大大小: {config.download.max_cache_size_gb:.2f} GB",
        ]
        status_msg = await event.reply("\n".join(msg_parts))
        
        try:
            result = cleanup_cache(
                Path(output_dir),
                config.download.cache_retention_days,
                config.download.max_cache_size_gb,
                dry_run=dry_run
            )
            
            result_text = [
                f"清理完成！",
                f"  删除文件: {len(result.deleted_files)} 个",
                f"  释放空间: {format_file_size(result.total_freed_bytes)}",
                f"  目录大小: {format_file_size(result.dir_size_before)} -> {format_file_size(result.dir_size_after)}"
            ]
            
            if dry_run and len(result.deleted_files) > 0:
                result_text.append("")
                result_text.append("⚠️  预览模式：没有实际删除")
            
            await status_msg.edit("\n".join(msg_parts + [""] + result_text))
        
        except Exception as e:
            logger.exception("清理缓存失败")
            await status_msg.edit(f"清理失败: {e}")

    logger.info("Bot 命令处理器已注册")
