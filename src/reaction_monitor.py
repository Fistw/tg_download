from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Dict, Tuple

from telethon import TelegramClient, events
from telethon.tl.types import UpdateMessageReactions, ReactionEmoji

from src.config import AppConfig, load_config
from src.downloader import download_all_videos_in_message
from src.nas_sync import NASSyncer

logger = logging.getLogger(__name__)

# 存储等待用户回复的任务：user_id -> (message_id, should_send_event, downloaded_paths)
_pending_tasks: Dict[int, Tuple[int, asyncio.Event, list[Path]]] = {}


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
    """发送文件给用户"""
    try:
        if downloaded_paths:
            await bot_client.send_message(user_id, f"✅ 点赞视频下载完成！共 {len(downloaded_paths)} 个文件")
            # 构建媒体文件列表
            media_files = []
            oversized_files = []
            for idx, path in enumerate(downloaded_paths, 1):
                logger.info(f"  Adding file {idx}/{len(downloaded_paths)}: {path}")
                if path and path.exists():
                    file_size = path.stat().st_size
                    logger.info(f"    File size: {file_size} bytes")
                    if file_size < 2 * 1024 ** 3:
                        media_files.append(str(path))
                    else:
                        oversized_files.append(str(path))
                else:
                    logger.error(f"    ❌ File not found: {path}")

            # 使用 send_media_group 发送多个文件（最多10个一组）
            if media_files:
                for i in range(0, len(media_files), 10):
                    batch = media_files[i:i+10]
                    logger.info(f"    Sending batch {i//10 + 1}, {len(batch)} files...")
                    await bot_client.send_file(user_id, batch)
                    logger.info(f"    ✅ Batch sent successfully")

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

                # 同步到 NAS
                if config.nas_sync.enable and downloaded_paths:
                    for path in downloaded_paths:
                        await nas_syncer.sync_file(path)

                # 处理发送给用户的逻辑
                if (
                    bot_client
                    and config.download.send_download_to_allowed_users
                    and config.bot.allowed_users
                ):
                    for user_id in config.bot.allowed_users:
                        try:
                            if config.download.ask_before_send:
                                # 询问用户是否发送
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
                                    await bot_client.send_message(user_id, "✅ 好的，不发送文件。")
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
        @bot_client.on(events.NewMessage())
        async def on_bot_message(event):
            """监听 Bot 消息，处理用户回复"""
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
                    await event.reply("❓ 请回复 \"是\" 或 \"否\"")
                    return
            except Exception as e:
                logger.error(f"Error handling bot message: {e}")
                import traceback
                logger.error(traceback.format_exc())
