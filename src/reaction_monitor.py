
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import UpdateMessageReactions, ReactionEmoji

from src.config import load_config
from src.downloader import download_all_videos_in_message
from src.downloader import _is_video as is_video_message

logger = logging.getLogger(__name__)


def _is_valid_reaction_event(event_or_update):
    """判断 Raw 事件是否是我们关心的点赞事件"""
    update = None
    if hasattr(event_or_update, 'original_update'):
        update = event_or_update.original_update
    else:
        update = event_or_update

    if not isinstance(update, UpdateMessageReactions):
        return False, None, None

    msg_id = update.msg_id
    chat_id = None

    if hasattr(update, 'peer'):
        peer = update.peer
        if hasattr(peer, 'channel_id'):
            chat_id = f"-100{peer.channel_id}"
        elif hasattr(peer, 'chat_id'):
            chat_id = f"-{peer.chat_id}" if peer.chat_id > 0 else str(peer.chat_id)
        elif hasattr(peer, 'user_id'):
            chat_id = str(peer.user_id)

    return True, msg_id, chat_id


def _check_own_reaction_from_update(update):
    """从 UpdateMessageReactions 事件里检查是否是自己点的赞，通过 chosen_order 字段！"""
    try:
        if not hasattr(update, 'reactions'):
            return False, None

        reactions_obj = update.reactions
        if hasattr(reactions_obj, 'results'):
            for rc in reactions_obj.results:
                if hasattr(rc, 'chosen_order') and rc.chosen_order is not None:
                    emoji = rc.reaction.emoticon if hasattr(rc.reaction, 'emoticon') else None
                    logger.debug(f"Found chosen_reaction! chosen_order: {rc.chosen_order}, emoji: {emoji}")
                    return True, emoji
    except Exception as e:
        logger.debug(f"Error checking chosen_reaction from update: {type(e)} - {e}")

    return False, None


async def start_reaction_monitor(client: TelegramClient, config: load_config, download_queue=None, history=None, bot_client=None):
    """启动点赞自动下载监控"""
    if not config.download.enable_reaction_download:
        logger.warning("💡 Reaction download is disabled in config")
        return

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
                    chat_id = update.peer.chat_id
                    message_link = f"https://t.me/{chat_id}/{msg_id}"
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
                downloaded_paths = await download_all_videos_in_message(client, message, config_dir)

                logger.info(f"✅ Download completed! Downloaded {len(downloaded_paths)} files")

                # 如果需要发送给 bot 的允许用户
                if (
                    bot_client
                    and config.download.send_download_to_allowed_users
                    and config.bot.allowed_users
                ):
                    for user_id in config.bot.allowed_users:
                        try:
                            if downloaded_paths:
                                await bot_client.send_message(user_id, f"✅ 点赞视频下载完成！共 {len(downloaded_paths)} 个文件")
                                logger.info(f"Sending {len(downloaded_paths)} files to user {user_id}...")
                                # 逐个发送文件
                                for idx, path in enumerate(downloaded_paths, 1):
                                    logger.info(f"  Sending file {idx}/{len(downloaded_paths)}: {path}")
                                    if path and path.exists():
                                        file_size = path.stat().st_size
                                        logger.info(f"    File size: {file_size} bytes")
                                        if file_size < 2 * 1024 ** 3:
                                            logger.info(f"    Starting upload...")
                                            await bot_client.send_file(user_id, str(path))
                                            logger.info(f"    ✅ File {idx}/{len(downloaded_paths)} sent successfully")
                                        else:
                                            await bot_client.send_message(user_id, f"文件太大（超过 2GB），路径: {path}")
                                    else:
                                        logger.error(f"    ❌ File not found: {path}")
                                logger.info(f"✅ All files sent to user {user_id}")
                            else:
                                await bot_client.send_message(user_id, "❌ 未找到视频文件")
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
