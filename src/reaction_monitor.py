from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from telethon import TelegramClient, events
from telethon.tl.types import UpdateMessageReactions, ReactionEmoji

from .config import AppConfig
from .database import DownloadDB
from .downloader import DownloadQueue, download_message

logger = logging.getLogger(__name__)


def _is_valid_reaction_event(event_or_update) -> tuple[bool, Optional[int], Optional[str]]:
    """
    判断 Raw 事件是否是我们关心的点赞事件。
    返回 (is_valid, msg_id, chat_id)
    """
    # 兼容两种格式：
    # 1. 有的是 event 对象，里面有 event.original_update
    # 2. 有的直接就是 update 对象！
    update = None
    if hasattr(event_or_update, "original_update"):
        update = event_or_update.original_update
    else:
        update = event_or_update

    # 检查是否是 UpdateMessageReactions
    if not isinstance(update, UpdateMessageReactions):
        return False, None, None

    # 获取消息 ID
    msg_id = update.msg_id
    if not msg_id:
        return False, None, None

    # 检查 Peer 类型，获取 Chat ID
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


async def _is_own_reaction(client: TelegramClient, update, msg_id) -> tuple[bool, str | None]:
    """
    判断是否是自己添加的反应（点赞）
    返回 (是否是自己点赞, 可能的讨论组ID)
    """
    if not hasattr(update, "reactions"):
        return False, None
    
    reactions = update.reactions
    logger.info(f"📋 reactions.results: {getattr(reactions, 'results', [])}")
    
    if not hasattr(reactions, "results"):
        return False, None
    
    for rc in reactions.results:
        logger.debug(f"ReactionCount: {repr(rc)}")
        if hasattr(rc, "chosen_order") and rc.chosen_order is not None:
            # chosen_order 不是 None，说明是我们自己的反应！
            logger.info(f"🎯 找到 chosen_order={rc.chosen_order}，是我们自己的反应！")
            if hasattr(rc, "reaction"):
                if isinstance(rc.reaction, ReactionEmoji):
                    emoji = rc.reaction.emoticon
                    logger.info(f"😄 Emoji: {emoji}")
                    if emoji == "👍":
                        logger.info("✅ 找到了我们自己的👍点赞！")
                        return True, None
                else:
                    logger.debug(f"不是 ReactionEmoji: {type(rc.reaction)}")
    
    return False, None


async def _get_message_from_chat(
    client: TelegramClient, chat: str | int, msg_id: int
):
    """从指定聊天中获取消息"""
    try:
        # 先尝试直接获取
        msg = await client.get_messages(chat, ids=msg_id)
        if msg:
            return msg, chat

        # 失败的话，可能是讨论组，尝试获取主频道完整信息并找到 linked_chat
        from telethon.tl.functions.channels import GetFullChannelRequest
        main_chat = await client.get_entity(chat)
        full_channel = await client(GetFullChannelRequest(main_chat))

        if (
            hasattr(full_channel, "full_chat")
            and hasattr(full_channel.full_chat, "linked_chat_id")
            and full_channel.full_chat.linked_chat_id
        ):
            linked_chat = int(f"-100{full_channel.full_chat.linked_chat_id}")
            msg = await client.get_messages(linked_chat, ids=msg_id)
            return msg, linked_chat
        else:
            return None, chat
    except Exception as e:
        logger.warning(f"获取消息失败: {chat}/{msg_id}, 错误: {e}")
        return None, chat


async def start_reaction_monitor(
    client: TelegramClient,
    config: AppConfig,
    download_queue: DownloadQueue,
    history: DownloadDB | None = None,
) -> None:
    """启动 Reaction 监控"""
    if not config.download.enable_reaction_download:
        logger.warning("⚠️ Reaction 下载功能未启用（config.yaml 里 download.enable_reaction_download 不是 True）")
        return

    logger.info("✅ Reaction 下载功能已启用！")

    if history is None:
        history = DownloadDB()

    @client.on(events.Raw())
    async def on_raw_update(event_or_update):
        """监听 Raw 事件，查找反应更新"""
        try:
            # 💥 超详细调试：打印所有 Raw 事件完整信息！
            obj_type = type(event_or_update).__name__
            logger.info(f"📨 收到 Raw 事件/Update: {obj_type}")
            logger.debug(f"📋 内容: {event_or_update}")
            
            # 提取 update 对象
            update = None
            if hasattr(event_or_update, "original_update"):
                update = event_or_update.original_update
            else:
                update = event_or_update

            is_valid, msg_id, chat_id = _is_valid_reaction_event(event_or_update)
            if not is_valid or msg_id is None or chat_id is None:
                return

            logger.info(f"🎯 识别到 Reaction 事件: {chat_id}/{msg_id}")

            # 检查是否是自己的点赞
            is_own, _ = await _is_own_reaction(client, update, msg_id)
            if not is_own:
                logger.debug("❌ 不是自己的点赞或不是 👍，跳过")
                return

            logger.info(f"💖 检测到自己的点赞事件: {chat_id}/{msg_id}")

            # 获取消息
            msg, final_chat_id = await _get_message_from_chat(client, chat_id, msg_id)
            if msg is None:
                logger.warning(f"⚠️ 未找到消息: {final_chat_id}/{msg_id}")
                return

            # 检查是否是视频
            from .downloader import _is_video
            if not _is_video(msg):
                logger.debug(f"⚠️ 被点赞消息不含视频: {final_chat_id}/{msg_id}")
                return

            logger.info(f"🎥 识别到视频消息: {final_chat_id}/{msg_id}")

            # 检查是否已下载过
            channel_str = str(final_chat_id)
            if history.is_downloaded(channel_str, msg.id):
                logger.info(f"✅ 视频已下载过，跳过: {channel_str}/{msg.id}")
                return

            # 提交下载任务
            logger.info(f"⬇️ 开始下载点赞的视频: {channel_str}/{msg.id}")
            task_id = history.create_task(channel_str, msg.id, source="reaction")
            if task_id == -1:
                logger.info("⏭️ 任务已存在，跳过")
                return

            try:
                history.update_status(channel_str, msg.id, "downloading")
                path = await download_message(client, msg, config.download.output_dir)
                if path is not None:
                    file_size = path.stat().st_size if path.exists() else None
                    history.update_status(
                        channel_str,
                        msg.id,
                        "completed",
                        filename=path.name,
                        file_size=file_size
                    )
                    logger.info(f"🎉 下载完成: {path}")
                else:
                    history.update_status(channel_str, msg.id, "completed")
            except Exception as e:
                logger.exception(f"❌ 下载失败: {channel_str}/{msg.id}")
                history.update_status(
                    channel_str, msg.id, "failed", error_message=str(e)
                )
        except Exception as e:
            logger.exception(f"💥 处理 Reaction 事件异常: {e}")

    # 关键！先调用 get_dialogs 刷新会话缓存，确保能接收事件！
    logger.info("📞 调用 get_dialogs() 刷新会话...")
    dialogs = await client.get_dialogs(limit=10)
    logger.info(f"✅ 已获取 {len(dialogs)} 个会话！")
    
    logger.info("🚀 Reaction 监控已启动，等待点赞中...")
