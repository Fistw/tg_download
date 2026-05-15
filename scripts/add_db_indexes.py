#!/usr/bin/env python3
"""
为现有数据库添加索引的脚本
用于提升媒体列表查询性能
"""

import sys
import os
import logging
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.database import DownloadDB
import sqlite3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def add_indexes_to_existing_db(db_path: str = "downloads.db"):
    """为现有数据库添加索引"""
    logger.info(f"正在为数据库 {db_path} 添加索引...")
    
    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    try:
        # 为 dedupe_media 表添加索引
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_media_task_id 
            ON dedupe_media(task_id)
        """)
        logger.info("✓ 添加索引 idx_dedupe_media_task_id")
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_media_task_occurrence 
            ON dedupe_media(task_id, occurrence_count DESC)
        """)
        logger.info("✓ 添加索引 idx_dedupe_media_task_occurrence")
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_media_task_duration 
            ON dedupe_media(task_id, duration)
        """)
        logger.info("✓ 添加索引 idx_dedupe_media_task_duration")
        
        # 为 dedupe_results 表添加索引
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_results_task_file 
            ON dedupe_results(task_id, file_id, is_original)
        """)
        logger.info("✓ 添加索引 idx_dedupe_results_task_file")
        
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_results_task_id 
            ON dedupe_results(task_id)
        """)
        logger.info("✓ 添加索引 idx_dedupe_results_task_id")
        
        conn.commit()
        logger.info("🎉 所有索引创建成功！")
        return True
    except Exception as e:
        logger.error(f"创建索引失败: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()


def check_indexes(db_path: str = "downloads.db"):
    """检查数据库中的索引"""
    logger.info(f"检查数据库 {db_path} 的索引...")
    
    if not os.path.exists(db_path):
        logger.error(f"数据库文件不存在: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    try:
        # 查看 dedupe_media 表的索引
        logger.info("\ndedupe_media 表的索引:")
        cur = conn.execute("PRAGMA index_list(dedupe_media)")
        for row in cur.fetchall():
            logger.info(f"  - {row[1]}")
        
        # 查看 dedupe_results 表的索引
        logger.info("\ndedupe_results 表的索引:")
        cur = conn.execute("PRAGMA index_list(dedupe_results)")
        for row in cur.fetchall():
            logger.info(f"  - {row[1]}")
    finally:
        conn.close()


if __name__ == "__main__":
    db_path = "downloads.db"
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    if len(sys.argv) > 2 and sys.argv[2] == "--check":
        check_indexes(db_path)
    else:
        add_indexes_to_existing_db(db_path)
        print("\n检查索引状态...")
        check_indexes(db_path)
