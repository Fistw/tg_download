from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, Tuple, Optional, Any

try:
    from telethon import TelegramClient, events, Button
    BUTTON_AVAILABLE = True
except ImportError:
    from telethon import TelegramClient, events
    BUTTON_AVAILABLE = False
    logger.warning("Button 模块导入失败，将使用文本回复模式")
from telethon.tl.types import UpdateMessageReactions, ReactionEmoji

from src.config import AppConfig, load_config
from src.downloader import download_all_videos_in_message, DownloadResult, VideoMetadata
from src.nas_sync import NASSyncer

logger = logging.getLogger(__name__)


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

# 存储等待用户回复的任务：user_id -> (message_id, should_send_event, downloaded_paths)
_pending_tasks: Dict[int, Tuple[int, asyncio.Event, list[DownloadResult | Path]]] = {}
# 存储回调任务信息：callback_data -> (user_id, should_send_event, downloaded_paths)
_callback_tasks: Dict[str, Tuple[int, asyncio.Event, list[DownloadResult | Path]]] = {}


def _is_valid_reaction_event(event_or_update):
    """判断 Raw 事件是否是我们关心的点赞事件"""
    update = None
    if hasattr(event_or_update, "original_update"):
        update = event_or_update.original_update
    else:
        update = event_or_update

    if not isinstance(update, UpdateMessageReactions):
        return False, None, None

    msg_id = update.msg_id
    chat_id = None

    if hasattr(update, "peer"):
        peer = update.peer
        if hasattr(peer, "channel_id"):
            chat_id = f"-100{peer.channel_id}"
        elif hasattr(peer, "chat_id"):
            chat_id = f"-{peer.chat_id}" if peer.chat_id > 0 else str(peer.chat_id)
        elif hasattr(peer, "user_id"):
            chat_id = str(peer.user_id)

    return True, msg_id, chat_id


def _check_own_reaction_from_update(update):
    """从 UpdateMessageReactions 事件里检查是否是自己点的赞，通过 chosen_order 字段！"""
    try:
        if not hasattr(update, "reactions"):
            return False, None

        reactions_obj = update.reactions
        if hasattr(reactions_obj, "results"):
            for rc in reactions_obj.results:
                if hasattr(rc, "chosen_order") and rc.chosen_order is not None:
                    emoji = rc.reaction.emoticon if hasattr(rc.reaction, "emoticon") else None
                    logger.debug(f"Found chosen_reaction! chosen_order: {rc.chosen_order}, emoji: {emoji}")
                    return True, emoji
    except Exception as e:
        logger.debug(f"Error checking chosen_reaction from update: {type(e)} - {e}")

    return False, None


# 保持向后兼容的别名
_is_own_reaction = _check_own_reaction_from_update


async def _get_message_from_chat(client, chat_id, msg_id):
    """获取消息（保持向后兼容）"""
    return await client.get_messages(chat_id, ids=msg_id)


async def _send_files_to_user(bot_client, user_id, downloaded_paths):
    """发送文件给用户，保持媒体组功能"""
    try:
        if downloaded_paths:
            await bot_client.send_message(user_id, f"✅ 点赞视频下载完成！共 {len(downloaded_paths)} 个文件")
            # 构建媒体文件列表
            oversized_files = []
            normal_files_with_meta = []
            normal_file_paths = []
            for idx, res in enumerate(downloaded_paths, 1):
                logger.info(f"  Adding file {idx}/{len(downloaded_paths)}: {res}")
                # 获取实际文件路径
                file_path = None
                if isinstance(res, DownloadResult):
                    file_path = res.path
                    normal_files_with_meta.append(res)
                else:
                    file_path = res
                
                if file_path and file_path.exists():
                    file_size = file_path.stat().st_size
                    logger.info(f"    File size: {file_size} bytes")
                    if file_size < 2 * 1024 ** 3:
                        normal_file_paths.append(str(file_path))
                    else:
                        oversized_files.append(str(file_path))
                else:
                    logger.error(f"    ❌ File not found: {res}")

            # 如果只有一个文件，使用完整的元数据发送
            if len(normal_file_paths) == 1 and normal_files_with_meta:
                await _send_video_with_metadata(bot_client, user_id, normal_files_with_meta[0])
            # 如果有多个文件，批量发送（媒体组），同时尝试设置 supports_streaming
            elif normal_file_paths:
                logger.info(f"📦 Sending {len(normal_file_paths)} files as a media group...")
                try:
                    # 批量发送媒体组，同时设置 supports_streaming
                    await bot_client.send_file(
                        user_id, 
                        normal_file_paths,
                        supports_streaming=True
                    )
                    logger.info(f"  ✅ Media group sent successfully!")
                except Exception as e:
                    logger.error(f"  ❌ Failed to send media group, falling back to individual sends: {e}")
                    # 如果批量发送失败，逐个发送
                    for i, res in enumerate(normal_files_with_meta, 1):
                        logger.info(f"  Sending file {i}/{len(normal_files_with_meta)}...")
                        await _send_video_with_metadata(bot_client, user_id, res)
                        logger.info(f"  ✅ File {i} sent successfully")

            # 发送超大文件的通知
            for oversized_file in oversized_files:
                await bot_client.send_message(user_id, f"文件太大（超过 2GB），路径: {oversized_file}")

            logger.info(f"✅ All files sent to user {user_id}")
        else:
            await bot_client.send_message(user_id, "❌ 未找到视频文件")
    except Exception as e:
        logger.error(f"Failed to send message to user {user_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())


async def start_reaction_monitor(client: TelegramClient, config: AppConfig, download_queue=None, history=None, bot_client=None):
    """启动点赞自动下载监控"""
    if not config.download.enable_reaction_download:
        logger.warning("💡 Reaction download is disabled in config")
        return

    nas_syncer = NASSyncer(config.nas_sync)

    logger.info("✅ Reaction download function enabled!")
    logger.info("🚀 Reaction monitor started, waiting for likes!")

    @client.on(events.Raw())
    async def on_raw_update(event_or_update):
        """监听 Raw 事件，查找反应更新"""
        try:
            event_type = type(event_or_update).__name__
            logger.debug(f"📨 Received Raw event/update type: {event_type}")

            update = None
            if hasattr(event_or_update, 'original_update'):
                update = event_or_update.original_update
            else:
                update = event_or_update

            is_valid, msg_id, chat_id = _is_valid_reaction_event(event_or_update)
            if not is_valid or msg_id is None or chat_id is None:
                return

            logger.info(f"🎯 Found Reaction event: {chat_id}/{msg_id}")

            is_own, emoji = _check_own_reaction_from_update(update)
            if not is_own:
                logger.debug("Not my reaction (no chosen_order), skipping")
                return

            if emoji not in ['👍', '❤️', '🎉']:
                logger.debug(f"Emoji {emoji} not in allowed list, skipping")
                return

            logger.info(f"💖 Detected my like! Emoji: {emoji}, downloading message {chat_id}/{msg_id}!")

            try:
                peer = update.peer
                message = await client.get_messages(peer, ids=msg_id)
                if not message:
                    logger.error("Failed to get message")
                    return

                # 构建消息链接
                message_link = ""
                if hasattr(update.peer, 'channel_id'):
                    channel_id = update.peer.channel_id
                    message_link = f"https://t.me/c/{channel_id}/{msg_id}"
                elif hasattr(update.peer, 'chat_id'):
                    chat_id_val = update.peer.chat_id
                    message_link = f"https://t.me/{chat_id_val}/{msg_id}"
                elif hasattr(update.peer, 'user_id'):
                    user_id = update.peer.user_id
                    message_link = f"https://t.me/{user_id}/{msg_id}"

                # 立即发送点赞通知到 Bot
                if (
                    bot_client
                    and config.download.send_download_to_allowed_users
                    and config.bot.allowed_users
                ):
                    for user_id in config.bot.allowed_users:
                        try:
                            await bot_client.send_message(
                                user_id,
                                f"💖 检测到点赞！正在下载...\n{message_link}"
                            )
                        except Exception as e:
                            logger.error(f"Failed to send notification to user {user_id}: {e}")

                logger.info("Downloading all videos in message!")
                config_dir = config.download.output_dir
                chunk_size = config.download.chunk_size_kb
                downloaded_paths = await download_all_videos_in_message(client, message, config_dir, chunk_size_kb=chunk_size)

                logger.info(f"✅ Download completed! Downloaded {len(downloaded_paths)} files")
                logger.info(f"Downloaded paths: {downloaded_paths}")

                # 同步到 NAS
                if config.nas_sync.enable and downloaded_paths:
                    for path in downloaded_paths:
                        try:
                            await nas_syncer.sync_file(path)
                        except Exception as e:
                            logger.warning(f"NAS 同步失败: {e}")

                # 处理发送给用户的逻辑
                if (
                    bot_client
                    and config.download.send_download_to_allowed_users
                    and config.bot.allowed_users
                ):
                    for user_id in config.bot.allowed_users:
                        try:
                            if config.download.ask_before_send:
                                if BUTTON_AVAILABLE:
                                    # 生成唯一的回调数据
                                    callback_prefix = f"dl_{user_id}_{msg_id}"
                                    callback_send = f"{callback_prefix}_send"
                                    
                                    # 询问用户是否发送（使用按钮）
                                    logger.info(f"Sending button message to user {user_id}")
                                    question_msg = await bot_client.send_message(
                                        user_id,
                                        f"✅ 下载完成！共 {len(downloaded_paths)} 个文件。",
                                        buttons=[Button.inline("📤 发送", data=callback_send)]
                                    )

                                    # 创建事件等待用户回复
                                    should_send_event = asyncio.Event()
                                    _pending_tasks[user_id] = (question_msg.id, should_send_event, downloaded_paths)
                                    _callback_tasks[callback_send] = (user_id, should_send_event, downloaded_paths)

                                    # 等待用户回复或超时
                                    try:
                                        await asyncio.wait_for(
                                            should_send_event.wait(),
                                            timeout=config.download.ask_timeout_seconds
                                        )
                                        should_send = should_send_event.is_set()
                                    except asyncio.TimeoutError:
                                        should_send = False
                                        try:
                                            await bot_client.edit_message(
                                                user_id,
                                                question_msg.id,
                                                f"✅ 下载完成！共 {len(downloaded_paths)} 个文件。\n\n"
                                                f"(⏰ 已超时)"
                                            )
                                        except Exception as e:
                                            logger.warning(f"编辑消息失败: {e}")
                                    finally:
                                        if user_id in _pending_tasks:
                                            del _pending_tasks[user_id]
                                        if callback_send in _callback_tasks:
                                            del _callback_tasks[callback_send]

                                    # 根据用户选择发送文件
                                    if should_send:
                                        await _send_files_to_user(bot_client, user_id, downloaded_paths)
                                else:
                                    # 回退到文本模式（按钮不可用）
                                    question_msg = await bot_client.send_message(
                                        user_id,
                                        f"✅ 下载完成！共 {len(downloaded_paths)} 个文件。\n\n"
                                        f"是否发送文件给你？\n"
                                        f"回复：\n"
                                        f"- \"是\" 或 \"y\" 发送\n"
                                        f"- \"否\" 或 \"n\" 不发送\n\n"
                                        f"({config.download.ask_timeout_seconds} 秒后默认不发送)"
                                    )

                                    # 创建事件等待用户回复
                                    should_send_event = asyncio.Event()
                                    _pending_tasks[user_id] = (question_msg.id, should_send_event, downloaded_paths)

                                    # 等待用户回复或超时
                                    try:
                                        await asyncio.wait_for(
                                            should_send_event.wait(),
                                            timeout=config.download.ask_timeout_seconds
                                        )
                                        should_send = should_send_event.is_set()
                                    except asyncio.TimeoutError:
                                        should_send = False
                                        await bot_client.send_message(user_id, "⏰ 超时，默认不发送文件。")
                                    finally:
                                        if user_id in _pending_tasks:
                                            del _pending_tasks[user_id]

                                    # 根据用户选择发送文件
                                    if should_send:
                                        await _send_files_to_user(bot_client, user_id, downloaded_paths)
                            else:
                                # 直接发送（保持原有行为）
                                await _send_files_to_user(bot_client, user_id, downloaded_paths)
                        except Exception as e:
                            logger.error(f"Failed to send message to user {user_id}: {e}")
                            import traceback
                            logger.error(traceback.format_exc())

            except Exception as e:
                logger.error(f"Error downloading message: {type(e)} - {e}")
                import traceback
                logger.error(traceback.format_exc())
                if bot_client and config.download.send_download_to_allowed_users and config.bot.allowed_users:
                    for user_id in config.bot.allowed_users:
                        try:
                            await bot_client.send_message(user_id, f"❌ 下载失败: {e}")
                        except:
                            pass

        except Exception as e:
            logger.error(f"Error handling Raw event: {type(e)} - {e}")
            import traceback
            logger.error(traceback.format_exc())

    # 只有当 bot_client 存在时才添加 Bot 消息处理器
    if bot_client:
        @bot_client.on(events.CallbackQuery())
        async def on_callback_query(event):
            """处理按钮点击回调"""
            try:
                callback_data = event.data.decode() if event.data else ""
                logger.debug(f"Received callback query: {callback_data}")

                if callback_data not in _callback_tasks:
                    await event.answer("❌ 该操作已过期或无效")
                    return

                user_id, should_send_event, downloaded_paths = _callback_tasks[callback_data]

                # 确认是正确的用户
                if event.sender_id != user_id:
                    await event.answer("❌ 你没有权限执行此操作")
                    return

                # 更新消息，移除按钮并显示状态
                try:
                    new_text = (
                        f"✅ 下载完成！共 {len(downloaded_paths)} 个文件。\n\n"
                        f"📤 正在发送文件..."
                    )
                    await event.edit(new_text, buttons=None)
                except Exception as e:
                    logger.warning(f"Failed to edit message: {e}")

                # 发送反馈
                await event.answer("✅ 已收到！正在发送...")

                # 设置事件 - 发送文件
                should_send_event.set()

            except Exception as e:
                logger.error(f"Error handling callback query: {e}")
                import traceback
                logger.error(traceback.format_exc())
                try:
                    await event.answer("❌ 处理失败")
                except:
                    pass

        @bot_client.on(events.NewMessage())
        async def on_bot_message(event):
            """监听 Bot 消息，处理用户回复（保持向后兼容）"""
            try:
                user_id = event.sender_id
                if user_id not in _pending_tasks:
                    return

                msg_id, should_send_event, downloaded_paths = _pending_tasks[user_id]

                # 解析用户回复
                text = event.raw_text.strip().lower()
                if text in ["是", "y", "yes", "发送"]:
                    should_send_event.set()
                elif text in ["否", "n", "no", "不发送"]:
                    should_send_event.clear()
                else:
                    await event.reply("❓ 请回复 \"是\" 或 \"否\"，或点击按钮")
                    return
            except Exception as e:
                logger.error(f"Error handling bot message: {e}")
                import traceback
                logger.error(traceback.format_exc())
