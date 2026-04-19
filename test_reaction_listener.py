#!/usr/bin/env python3
"""Reaction 事件测试监听器"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events

from src.config import load_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("test_reaction")


async def main():
    # 加载配置
    config = load_config()
    session_path = Path(config.telegram.session_name)

    # 创建客户端
    client = TelegramClient(
        str(session_path),
        config.telegram.api_id,
        config.telegram.api_hash
    )

    @client.on(events.Raw())
    async def on_raw_update(event):
        """监听所有 Raw 事件"""
        try:
            if hasattr(event, "original_update"):
                update = event.original_update
                update_type = type(update).__name__
                logger.info(f"📨 收到 Raw 事件: {update_type}")
                
                # 如果是 UpdateMessageReactions，打印详细信息
                from telethon.tl.types import UpdateMessageReactions
                if isinstance(update, UpdateMessageReactions):
                    logger.info(f"💥 直接命中 UpdateMessageReactions!")
                    logger.info(f"📋 内容: {repr(update)}")
                    
                    # 获取自己的 ID
                    me = await client.get_me()
                    my_id = me.id if me else -1
                    logger.info(f"👤 自己的 ID: {my_id}")
                    
                    # 检查最近的 Reactions
                    if hasattr(update, "reactions"):
                        reactions = update.reactions
                        if hasattr(reactions, "recent_reactions"):
                            recent_reactions = reactions.recent_reactions
                            logger.info(f"Recent Reactions 数量: {len(recent_reactions)}")
                            
                            for idx, r in enumerate(recent_reactions):
                                logger.info(f"  Reaction [{idx}]: {repr(r)}")
                                
                                # 检查反应类型是否是 👍
                                if hasattr(r, "reaction"):
                                    reaction = r.reaction
                                    if hasattr(reaction, "emoticon"):
                                        emoji = reaction.emoticon
                                        logger.info(f"    Emoji: {emoji}")
                        
                        # 打印完整的 Reactions 信息
                        logger.info(f"Reactions 对象: {repr(reactions)}")
        
        except Exception as e:
            logger.exception(f"处理 Raw 事件异常: {e}")

    # 启动客户端
    logger.info("启动测试客户端...")
    await client.start()
    logger.info("客户端启动成功！")
    logger.info("开始监听 Raw 事件，请在 Telegram 中进行一些操作或点赞...")

    # 保持运行
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())

