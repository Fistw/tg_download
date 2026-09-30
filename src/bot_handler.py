from __future__ import annotations

import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    from telethon import TelegramClient, events, Button
    BUTTON_AVAILABLE = True
except ImportError:
    from telethon import TelegramClient, events
    BUTTON_AVAILABLE = False

from .config import AppConfig
from .downloader import download_by_link, DownloadResult, VideoMetadata
from .database import DownloadDB
from .utils import parse_telegram_link, format_file_size
from .cache import cleanup_cache

logger = logging.getLogger(__name__)

_pending_send_text_confirmations: Dict[int, Tuple[int, asyncio.Future[bool]]] = {}
_pending_send_callbacks: Dict[str, Tuple[int, asyncio.Future[bool]]] = {}


def _is_allowed(user_id: int, allowed_users: list[int]) -> bool:
    """检查用户是否有权限使用 Bot。空列表表示允许所有人。"""
    if not allowed_users:
        return True
    return user_id in allowed_users


def _is_video_message(message: Any) -> bool:
    if getattr(message, "video", None):
        return True
    file_info = getattr(message, "file", None)
    mime_type = getattr(file_info, "mime_type", None)
    return bool(mime_type and mime_type.lower().startswith("video/"))


def _video_download_name(message: Any, chat_id: int) -> str:
    file_info = getattr(message, "file", None)
    original_name = getattr(file_info, "name", None)
    if original_name:
        filename = Path(str(original_name).replace("\\", "/")).name
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
        filename = filename.strip(" .")
        if len(filename.encode("utf-8")) > 120:
            original_suffix = Path(filename).suffix
            suffix = original_suffix.encode("utf-8")[:24].decode("utf-8", errors="ignore")
            stem = filename[: -len(original_suffix)] if original_suffix else filename
            stem_limit = 120 - len(suffix.encode("utf-8"))
            stem = stem.encode("utf-8")[:stem_limit].decode("utf-8", errors="ignore")
            filename = f"{stem or 'video'}{suffix}"
    else:
        filename = "video.mp4"
    return f"{chat_id}_{message.id}_{filename or 'video.mp4'}"


async def _download_incoming_video(
    bot_client: TelegramClient,
    message: Any,
    output_dir: str,
    chat_id: int,
) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    target = output_path / _video_download_name(message, chat_id)
    if target.exists():
        return target

    temporary = output_path / f".{target.name}.{uuid.uuid4().hex}.part"
    try:
        downloaded = await bot_client.download_media(message, file=str(temporary))
        if not downloaded:
            raise RuntimeError("Telegram 未返回下载文件")
        Path(downloaded).replace(target)
        return target
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


async def _send_video_with_metadata(
    bot_client: TelegramClient,
    chat_id: Any,
    video_result: DownloadResult | Path,
    download_config: Any | None = None,
):
    """使用元数据发送视频，支持预览图和流媒体播放，并优化上传速度。"""
    import time
    from pathlib import Path

    # 获取实际文件路径
    file_path = None
    attributes = None
    thumb = None
    supports_streaming = True

    if isinstance(video_result, DownloadResult):
        file_path = video_result.path
        attributes = video_result.metadata.attributes
        thumb = video_result.metadata.thumb
        supports_streaming = video_result.metadata.supports_streaming
        logger.info(f"📺 Sending video with metadata: {file_path}")
        logger.info(f"   - Supports streaming: {supports_streaming}")
        logger.info(f"   - Has attributes: {bool(attributes)}")
        logger.info(f"   - Has thumbnail: {bool(thumb)}")
    else:
        file_path = Path(video_result)
        logger.info(f"📺 Sending video without metadata: {file_path}")

    # 获取文件大小
    file_size_bytes = 0
    if file_path.exists():
        file_size_bytes = file_path.stat().st_size

    # 确定上传分块大小
    part_size_kb = 128  # 默认值，向后兼容
    if download_config:
        part_size_kb = download_config.upload_part_size_kb
        # 检查是否是大文件，使用优化配置
        threshold_bytes = download_config.upload_large_file_threshold_mb * 1024 * 1024
        if file_size_bytes > threshold_bytes:
            part_size_kb = download_config.upload_large_file_part_size_kb
            logger.info(f"   📏 Detected large file: using part_size={part_size_kb}KB")

    # 限制最大为 512KB（Telethon 限制）
    part_size_kb = min(part_size_kb, 512)

    logger.info(f"   Using part size: {part_size_kb} KB for file size: {file_size_bytes / (1024*1024):.2f} MB")

    # 初始化监控记录
    monitoring_record_id = None
    try:
        from src.monitoring_db import get_monitoring_db
        db = get_monitoring_db()
        filename = file_path.name
        monitoring_record_id = db.start_upload_task(filename, file_size_bytes)
    except Exception:
        pass

    # 关键：先上传文件（设置分块大小），然后发送
    start_time = time.time()
    try:
        # 先上传文件（使用优化的分块大小）
        logger.info(f"   Uploading file to Telegram servers...")
        uploaded_file = await bot_client.upload_file(
            str(file_path),
            part_size_kb=part_size_kb
        )

        # 记录上传完成时间
        upload_time = time.time() - start_time
        speed_kb_s = (file_size_bytes / 1024) / upload_time if upload_time > 0 else 0
        logger.info(f"   Upload completed in {upload_time:.2f}s, average speed: {speed_kb_s:.2f} KB/s")

        # 然后发送
        logger.info(f"   Calling send_file with uploaded file and supports_streaming={supports_streaming}")
        send_kwargs = {
            "supports_streaming": supports_streaming
        }
        if attributes:
            send_kwargs["attributes"] = attributes
        if thumb:
            send_kwargs["thumb"] = thumb

        result = await bot_client.send_file(
            chat_id,
            uploaded_file,
            **send_kwargs
        )

        total_time = time.time() - start_time
        total_speed_kb_s = (file_size_bytes / 1024) / total_time if total_time > 0 else 0
        logger.info(f"   ✅ Video sent successfully! Total time: {total_time:.2f}s, total average speed: {total_speed_kb_s:.2f} KB/s")

        # 更新监控记录
        if monitoring_record_id:
            try:
                from src.monitoring_db import get_monitoring_db
                db = get_monitoring_db()
                db.complete_upload_task(
                    monitoring_record_id,
                    file_size_bytes,
                    total_speed_kb_s,
                    "completed"
                )
            except Exception:
                pass
    except Exception as e:
        logger.error(f"   ❌ Error sending video: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        # 更新监控记录为失败
        if monitoring_record_id:
            try:
                from src.monitoring_db import get_monitoring_db
                db = get_monitoring_db()
                db.complete_upload_task(
                    monitoring_record_id,
                    0,
                    0,
                    "failed"
                )
            except Exception:
                pass


async def _request_send_confirmation(
    bot_client: TelegramClient,
    user_id: int,
    message_id: int,
    timeout_seconds: int,
) -> bool:
    """询问用户是否发送下载好的文件。"""
    if BUTTON_AVAILABLE:
        callback_send = f"botdl_{user_id}_{message_id}_send"
        question_msg = await bot_client.send_message(
            user_id,
            "✅ 下载完成！\n\n是否发送文件给你？",
            buttons=[Button.inline("📤 发送", data=callback_send)]
        )

        should_send_future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        _pending_send_callbacks[callback_send] = (user_id, should_send_future)
        try:
            return await asyncio.wait_for(should_send_future, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            try:
                await bot_client.edit_message(
                    user_id,
                    question_msg.id,
                    "✅ 下载完成！\n\n(⏰ 已超时，默认不发送)",
                    buttons=None,
                )
            except Exception as e:
                logger.warning(f"编辑确认消息失败: {e}")
            return False
        finally:
            _pending_send_callbacks.pop(callback_send, None)

    question_msg = await bot_client.send_message(
        user_id,
        "✅ 下载完成！\n\n是否发送文件？\n"
        "- \"是\" 或 \"y\" 发送\n- \"否\" 或 \"n\" 不发送\n\n"
        f"({timeout_seconds} 秒后默认不发送)"
    )

    should_send_future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    _pending_send_text_confirmations[user_id] = (question_msg.id, should_send_future)
    try:
        return await asyncio.wait_for(should_send_future, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        await bot_client.send_message(user_id, "⏰ 超时，默认不发送文件。")
        return False
    finally:
        _pending_send_text_confirmations.pop(user_id, None)


async def setup_bot_handlers(
    bot_client: TelegramClient,
    user_client: TelegramClient,
    config: AppConfig,
    history: DownloadDB | None = None,
) -> None:
    """注册 Bot 命令处理器。"""
    allowed = config.bot.allowed_users
    output_dir = config.download.output_dir

    def _cleanup_download_cache(reason: str) -> None:
        if not config.download.enable_cache_cleanup:
            return
        try:
            result = cleanup_cache(
                Path(output_dir),
                config.download.cache_retention_days,
                config.download.max_cache_size_gb,
            )
            logger.info(
                "转发视频任务%s后清理缓存完成：删除 %s 个文件，释放 %.2f GB",
                reason,
                len(result.deleted_files),
                result.total_freed_bytes / (1024 ** 3),
            )
        except Exception:
            logger.exception("转发视频任务%s时清理缓存失败", reason)

    async def _handle_bot_download(event, link: str) -> None:
        """Bot 下载公共逻辑：记录数据库 + 下载 + 发送文件。"""
        try:
            parsed = parse_telegram_link(link)
        except ValueError:
            await event.reply(f"无效的链接: {link}")
            return

        try:
            if history:
                task_id = history.create_task(parsed.channel, parsed.message_id, source="bot")
                if task_id == -1:
                    await event.reply("该视频已下载过，跳过")
                    return
                history.update_status(parsed.channel, parsed.message_id, "downloading")

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
                if config.download.ask_before_send:
                    should_send = await _request_send_confirmation(
                        bot_client,
                        event.chat_id,
                        parsed.message_id,
                        config.download.ask_timeout_seconds,
                    )
                    if not should_send:
                        await event.reply("下载完成，未发送文件。")
                        return

                await event.reply("下载完成，正在发送文件...")
                await _send_video_with_metadata(bot_client, event.chat_id, result, config.download)
            else:
                await event.reply(f"下载完成: {file_path}")
        except Exception as e:
            if history:
                history.update_status(parsed.channel, parsed.message_id, "failed", error_message=str(e))
            logger.exception("Bot 下载失败")
            await event.reply(f"下载失败: {e}")

    async def _download_video_batch(
        messages, chat_id: int, send_status, batch_type: str, sender_id: int
    ) -> None:
        videos = [message for message in messages if _is_video_message(message)]
        if not videos:
            return

        total = len(videos)
        status_message = await send_status(f"开始下载，共 {total} 个视频…")
        downloaded_count = 0
        failed_count = 0
        batch_id = None
        monitoring_db = None
        try:
            from src.monitoring_db import get_monitoring_db

            monitoring_db = get_monitoring_db()
        except Exception:
            logger.exception("初始化转发视频任务记录失败，将继续下载")

        if monitoring_db is not None:
            try:
                batch_id = monitoring_db.start_forwarded_video_batch(
                    batch_type, chat_id, sender_id, total
                )
            except Exception:
                logger.exception("创建转发视频任务记录失败，将继续下载")

        # 下载前先应用已有的保留期和容量限制，避免目录已超限时继续占满磁盘。
        _cleanup_download_cache("开始前")

        for message in videos:
            try:
                await _download_incoming_video(bot_client, message, output_dir, chat_id)
                downloaded_count += 1
            except Exception:
                failed_count += 1
                logger.exception("转发视频下载失败，消息 ID: %s", message.id)

            processed_count = downloaded_count + failed_count
            state = "下载完成" if processed_count == total else "下载中"
            if processed_count == total:
                if failed_count == 0:
                    batch_status = "completed"
                elif downloaded_count == 0:
                    batch_status = "failed"
                else:
                    batch_status = "partially_failed"
            else:
                batch_status = "downloading"

            if monitoring_db is not None and batch_id is not None:
                try:
                    monitoring_db.update_forwarded_video_batch(
                        batch_id, downloaded_count, failed_count, batch_status
                    )
                except Exception:
                    logger.exception("更新转发视频任务进度失败")

            progress = f"{state}：已下载 {downloaded_count}/{total} 个视频"
            if failed_count:
                progress += f"，失败 {failed_count} 个"
            try:
                await status_message.edit(progress)
            except Exception:
                logger.warning("更新转发视频下载进度失败")
                try:
                    status_message = await send_status(progress)
                except Exception:
                    logger.exception("发送转发视频下载进度失败")

        # 与现有下载流程一致，任务完成后再次按保留期和容量限制清理。
        _cleanup_download_cache("完成后")

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

    @bot_client.on(events.NewMessage())
    async def on_confirmation_reply(event):
        pending = _pending_send_text_confirmations.get(event.sender_id)
        if pending is None:
            return

        text = (event.raw_text or "").strip().lower()
        if text in {"是", "y", "yes"}:
            _, should_send_future = pending
            if not should_send_future.done():
                should_send_future.set_result(True)
            await event.reply("✅ 已收到，开始发送文件。")
        elif text in {"否", "n", "no"}:
            _, should_send_future = pending
            if not should_send_future.done():
                should_send_future.set_result(False)
            await event.reply("已取消发送。")

    @bot_client.on(events.CallbackQuery())
    async def on_send_confirmation_callback(event):
        callback_data = event.data.decode() if event.data else ""
        if not callback_data.startswith("botdl_"):
            return

        if callback_data not in _pending_send_callbacks:
            await event.answer("❌ 该操作已过期或无效")
            return

        user_id, should_send_future = _pending_send_callbacks[callback_data]
        if event.sender_id != user_id:
            await event.answer("❌ 你没有权限执行此操作")
            return

        try:
            await event.edit("✅ 下载完成！\n\n📤 正在发送文件...", buttons=None)
        except Exception as e:
            logger.warning(f"编辑确认消息失败: {e}")

        await event.answer("✅ 已收到！正在发送...")
        if not should_send_future.done():
            should_send_future.set_result(True)

    @bot_client.on(events.NewMessage(pattern=r"/download\s+(.+)"))
    async def on_download(event):
        if _is_video_message(event.message):
            return
        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        link = event.pattern_match.group(1).strip()
        await event.reply(f"开始下载: {link}")
        await _handle_bot_download(event, link)

    @bot_client.on(events.NewMessage(pattern=r"https?://t\.me/\S+"))
    async def on_link(event):
        if _is_video_message(event.message):
            return
        if (event.text or "").startswith("/"):
            return
        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        link = event.text.strip()
        await event.reply(f"开始下载: {link}")
        await _handle_bot_download(event, link)

    @bot_client.on(events.NewMessage(incoming=True))
    async def on_incoming_video(event):
        message = event.message
        if not _is_video_message(message):
            return
        if getattr(message, "grouped_id", None):
            return

        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        chat_id = event.chat_id or event.sender_id
        await _download_video_batch(
            [message], chat_id, event.reply, "single", event.sender_id
        )

    @bot_client.on(events.Album)
    async def on_incoming_video_album(event):
        messages = list(event.messages)
        if not messages or messages[0].out:
            return

        videos = [message for message in messages if _is_video_message(message)]
        if not videos:
            return

        if not _is_allowed(event.sender_id, allowed):
            await event.respond("你没有权限使用此 Bot")
            return

        chat_id = event.chat_id or event.sender_id
        await _download_video_batch(
            videos, chat_id, event.respond, "album", event.sender_id
        )

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
