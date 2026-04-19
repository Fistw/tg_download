#!/usr/bin/env python3
"""超级详细的 Reaction 调试脚本！"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events

from src.config import load_config

# 设置超级详细的日志
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("debug_reaction")
telethon_logger = logging.getLogger("telethon")
telethon_logger.setLevel(logging.INFO)  # 减少 telethon 的噪音


async def main():
    config = load_config()
    session_path = Path(config.telegram.session_name)

    client = TelegramClient(
        str(session_path),
        config.telegram.api_id,
        config.telegram.api_hash
    )

    logger.info("=" * 60)
    logger.info("超级调试模式启动！")
    logger.info("=" * 60)

    @client.on(events.Raw())
    async def on_all_events(update):
        """监听所有事件！"""
        # 打印原始类型
        logger.debug("-" * 60)
        logger.debug(f"👀 收到原始事件类型: {type(update)}")
        logger.debug(f"📋 事件的 __dict__: {dir(update)}")

        # 尝试不同的访问方式
        try:
            if hasattr(update, "__dict__"):
                logger.debug(f"📦 完整事件内容: {update}")
        except Exception as e:
            logger.debug(f"打印完整事件失败: {e}")

        # 检查是不是和 Reaction 相关
        update_type_name = type(update).__name__.lower()
        if "reaction" in update_type_name:
            logger.warning("🎉 可能收到 Reaction 相关事件!")

    # 启动
    await client.start()
    logger.info("✅ 客户端启动成功！")

    # 关键！先调用一次 get_dialogs() 来刷新会话缓存！
    logger.info("📞 正在调用 get_dialogs() 刷新会话...")
    dialogs = await client.get_dialogs(limit=10)
    logger.info(f"✅ 已获取 {len(dialogs)} 个会话！")

    # 获取自己的 ID
    me = await client.get_me()
    logger.info(f"👤 我是: {me.first_name} (ID: {me.id})")
    logger.info("=" * 60)
    logger.info("🎉 现在你可以在 Telegram 客户端点赞视频！")
    logger.info("📌 或者随便发消息看看能不能接收到事件！")
    logger.info("=" * 60)

    # 保持运行
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
