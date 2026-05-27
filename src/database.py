from __future__ import annotations

import sqlite3
import threading
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from .thumbnail_store import ThumbnailStore

# 全局锁，防止多线程并发问题
_db_lock = threading.RLock()  # 使用可重入锁，避免死锁

logger = logging.getLogger(__name__)


class DownloadDB:
    """统一的 SQLite 下载任务管理。"""

    def __init__(self, db_path: str | Path = "downloads.db", thumbnail_dir: str | Path = "thumbnails") -> None:
        self.db_path = Path(db_path)
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 初始化缩略图存储
        self.thumbnail_store = ThumbnailStore(thumbnail_dir)
        self._initialize_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _initialize_db(self) -> None:
        """初始化数据库表"""
        with _db_lock:
            conn = self._get_connection()
            try:
                # 创建表（旧版本）
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS downloads (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        channel TEXT NOT NULL,
                        message_id INTEGER NOT NULL,
                        filename TEXT,
                        file_size INTEGER,
                        status TEXT NOT NULL DEFAULT 'queued',
                        source TEXT NOT NULL DEFAULT 'cli',
                        error_message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(channel, message_id)
                    )
                    """
                )
                
                # 数据库迁移：添加新字段（向后兼容）
                self._migrate(conn)
                
                conn.commit()
            finally:
                conn.close()
    
    def _migrate_blob_thumbnails(self, conn):
        """将数据库中的 BLOB 缩略图迁移到文件系统。"""
        try:
            # 查询有 thumbnail_data 但没有 thumbnail_path 的记录
            cur = conn.execute("""
                SELECT id, task_id, file_id, thumbnail_data 
                FROM dedupe_media 
                WHERE thumbnail_data IS NOT NULL AND thumbnail_path IS NULL
            """)
            
            migrated_count = 0
            for row in cur.fetchall():
                media_id = row['id']
                task_id = row['task_id']
                file_id = row['file_id']
                thumbnail_data = row['thumbnail_data']
                
                try:
                    # 保存到文件系统
                    relative_path = self.thumbnail_store.save(task_id, file_id, thumbnail_data)
                    
                    # 更新数据库记录，设置 path 并清空 data 以节省空间
                    conn.execute("""
                        UPDATE dedupe_media 
                        SET thumbnail_path = ?, thumbnail_data = NULL 
                        WHERE id = ?
                    """, (relative_path, media_id))
                    
                    migrated_count += 1
                except Exception as e:
                    logger.warning(f"迁移缩略图失败 (media_id={media_id}): {e}")
            
            if migrated_count > 0:
                logger.info(f"成功迁移 {migrated_count} 个缩略图到文件系统")
                conn.commit()
                
        except Exception as e:
            logger.error(f"迁移缩略图时出错: {e}")
            # 不回滚，允许部分迁移
        
    def _migrate(self, conn):
        """执行数据库迁移，添加新字段"""
        # 旧的下载表迁移
        cursor = conn.execute("PRAGMA table_info(downloads)")
        columns = {row[1] for row in cursor.fetchall()}

        if "status" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")
        if "source" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy'")
        if "error_message" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN error_message TEXT")
        if "created_at" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN created_at TIMESTAMP")
        if "updated_at" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN updated_at TIMESTAMP")
        
        # 添加 downloaded_bytes 字段
        if "downloaded_bytes" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN downloaded_bytes INTEGER DEFAULT 0")
        
        # 添加 total_bytes 字段
        if "total_bytes" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN total_bytes INTEGER")
        
        # 添加 last_progress_at 字段
        if "last_progress_at" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN last_progress_at TIMESTAMP")
        
        # 添加 retry_count 字段
        if "retry_count" not in columns:
            conn.execute("ALTER TABLE downloads ADD COLUMN retry_count INTEGER DEFAULT 0")

        # 为历史数据回填缺失字段，避免旧库升级后新逻辑读到 NULL。
        conn.execute("""
            UPDATE downloads
            SET status = COALESCE(status, 'completed'),
                source = COALESCE(source, 'legacy'),
                created_at = COALESCE(created_at, downloaded_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, downloaded_at, created_at, CURRENT_TIMESTAMP),
                downloaded_bytes = COALESCE(downloaded_bytes, 0),
                retry_count = COALESCE(retry_count, 0)
        """)
        
        # 创建去重任务表
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                chat_title TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                start_message_id INTEGER,
                last_scanned_message_id INTEGER,
                total_messages INTEGER,
                processed_messages INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # 为去重任务表添加新字段（如果不存在）
        cursor = conn.execute("PRAGMA table_info(dedupe_tasks)")
        dedupe_columns = {row[1] for row in cursor.fetchall()}
        
        # 注意：我们不需要在数据库里存 progress、unique_media 和 duplicate_count，
        # 这些可以在获取时计算
        
        # 创建去重媒体表
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                file_size INTEGER,
                duration INTEGER,
                width INTEGER,
                height INTEGER,
                first_seen_message_id INTEGER,
                first_seen_date TIMESTAMP,
                occurrence_count INTEGER DEFAULT 1,
                thumbnail_data BLOB,
                thumbnail_path TEXT,
                thumbnail_width INTEGER,
                thumbnail_height INTEGER,
                phash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, file_id)
            )
            """
        )
        
        # 为去重媒体表添加新字段（如果不存在）
        cursor = conn.execute("PRAGMA table_info(dedupe_media)")
        dedupe_media_columns = {row[1] for row in cursor.fetchall()}
        
        if "thumbnail_data" not in dedupe_media_columns:
            conn.execute("ALTER TABLE dedupe_media ADD COLUMN thumbnail_data BLOB")
        if "thumbnail_path" not in dedupe_media_columns:
            conn.execute("ALTER TABLE dedupe_media ADD COLUMN thumbnail_path TEXT")
        if "thumbnail_width" not in dedupe_media_columns:
            conn.execute("ALTER TABLE dedupe_media ADD COLUMN thumbnail_width INTEGER")
        if "thumbnail_height" not in dedupe_media_columns:
            conn.execute("ALTER TABLE dedupe_media ADD COLUMN thumbnail_height INTEGER")
        if "phash" not in dedupe_media_columns:
            conn.execute("ALTER TABLE dedupe_media ADD COLUMN phash TEXT")
        
        # 迁移旧的 BLOB 数据到文件系统（如果存在）
        self._migrate_blob_thumbnails(conn)
        
        # 创建去重结果表
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                is_duplicate INTEGER DEFAULT 0,
                is_original INTEGER DEFAULT 0,
                downloaded INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        
        # 创建第一层去重结果表（基于file_id）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_level1 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                group_id TEXT NOT NULL,
                primary_media_id INTEGER NOT NULL,
                media_ids TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, group_id)
            )
            """
        )
        
        # 创建第二层去重结果表（基于图片相似度）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_level2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                group_id TEXT NOT NULL,
                primary_level1_group_id TEXT NOT NULL,
                level1_group_ids TEXT NOT NULL,
                similarity_score REAL,
                hamming_distance INTEGER,
                uninterested INTEGER DEFAULT 0,
                download_target_file_id TEXT,
                download_target_media_id INTEGER,
                download_target_file_size INTEGER,
                download_target_duration REAL,
                download_target_has_thumbnail INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, group_id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dedupe_download_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                file_id TEXT NOT NULL,
                output_dir TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                attempt_count INTEGER DEFAULT 0,
                max_attempts INTEGER DEFAULT 3,
                last_error TEXT,
                next_retry_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, file_id)
            )
            """
        )

        cursor = conn.execute("PRAGMA table_info(dedupe_level2)")
        dedupe_level2_columns = {row[1] for row in cursor.fetchall()}
        if "uninterested" not in dedupe_level2_columns:
            conn.execute("ALTER TABLE dedupe_level2 ADD COLUMN uninterested INTEGER DEFAULT 0")
        if "download_target_file_id" not in dedupe_level2_columns:
            conn.execute("ALTER TABLE dedupe_level2 ADD COLUMN download_target_file_id TEXT")
        if "download_target_media_id" not in dedupe_level2_columns:
            conn.execute("ALTER TABLE dedupe_level2 ADD COLUMN download_target_media_id INTEGER")
        if "download_target_file_size" not in dedupe_level2_columns:
            conn.execute("ALTER TABLE dedupe_level2 ADD COLUMN download_target_file_size INTEGER")
        if "download_target_duration" not in dedupe_level2_columns:
            conn.execute("ALTER TABLE dedupe_level2 ADD COLUMN download_target_duration REAL")
        if "download_target_has_thumbnail" not in dedupe_level2_columns:
            conn.execute("ALTER TABLE dedupe_level2 ADD COLUMN download_target_has_thumbnail INTEGER DEFAULT 0")
        
        # 创建索引以提升查询性能
        self._create_indexes(conn)
    
    def _create_indexes(self, conn):
        """创建必要的数据库索引以提升查询性能"""
        # dedupe_media 表的索引
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_media_task_id 
            ON dedupe_media(task_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_media_task_occurrence 
            ON dedupe_media(task_id, occurrence_count DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_media_task_duration 
            ON dedupe_media(task_id, duration)
        """)
        
        # dedupe_results 表的索引
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_results_task_file 
            ON dedupe_results(task_id, file_id, is_original)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_results_task_id 
            ON dedupe_results(task_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_results_task_downloaded_file
            ON dedupe_results(task_id, downloaded, file_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_level2_task_interest_id
            ON dedupe_level2(task_id, uninterested, id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_level2_task_interest_size_id
            ON dedupe_level2(task_id, uninterested, download_target_file_size, id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_download_jobs_task_status_retry
            ON dedupe_download_jobs(task_id, status, next_retry_at, updated_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_dedupe_download_jobs_status_retry
            ON dedupe_download_jobs(status, next_retry_at, updated_at)
        """)
        
        logger.info("数据库索引创建完成")

    def create_task(
        self,
        channel: str,
        message_id: int,
        source: str = "cli",
        filename: Optional[str] = None,
        file_size: Optional[int] = None,
        total_bytes: Optional[int] = None,
    ) -> int:
        """创建任务，返回 id。已完成返回 -1，失败则重置为 queued。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                existing = self.get_task(channel, message_id)
                if existing is not None:
                    if existing["status"] == "completed":
                        return -1
                    if existing["status"] == "failed":
                        conn.execute(
                            "UPDATE downloads SET status = 'queued', source = ?, error_message = NULL, "
                            "updated_at = CURRENT_TIMESTAMP, retry_count = 0 WHERE channel = ? AND message_id = ?",
                            (source, channel, message_id),
                        )
                        conn.commit()
                        return existing["id"]
                    # 其他状态（queued / downloading）返回已有 id
                    return existing["id"]

                cur = conn.execute(
                    "INSERT INTO downloads "
                    "(channel, message_id, source, filename, file_size, total_bytes, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'queued', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (channel, message_id, source, filename, file_size, total_bytes),
                )
                conn.commit()
                return cur.lastrowid  # type: ignore[return-value]
            finally:
                conn.close()

    def update_status(
        self,
        channel: str,
        message_id: int,
        status: str,
        error_message: Optional[str] = None,
        filename: Optional[str] = None,
        file_size: Optional[int] = None,
        downloaded_bytes: Optional[int] = None,
        total_bytes: Optional[int] = None,
        increment_retry: bool = False,
    ) -> None:
        """更新任务状态及可选字段。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                fields = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
                params: list = [status]
                
                if error_message is not None:
                    fields.append("error_message = ?")
                    params.append(error_message)
                
                if filename is not None:
                    fields.append("filename = ?")
                    params.append(filename)
                
                if file_size is not None:
                    fields.append("file_size = ?")
                    params.append(file_size)
                
                if downloaded_bytes is not None:
                    fields.append("downloaded_bytes = ?")
                    fields.append("last_progress_at = CURRENT_TIMESTAMP")
                    params.append(downloaded_bytes)
                
                if total_bytes is not None:
                    fields.append("total_bytes = ?")
                    params.append(total_bytes)
                
                if increment_retry:
                    fields.append("retry_count = retry_count + 1")
                
                params.extend([channel, message_id])
                conn.execute(
                    f"UPDATE downloads SET {', '.join(fields)} WHERE channel = ? AND message_id = ?",
                    params,
                )
                conn.commit()
            finally:
                conn.close()
        
    def update_progress(
        self,
        channel: str,
        message_id: int,
        downloaded_bytes: int,
    ) -> None:
        """更新下载进度（便捷方法）"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE downloads SET downloaded_bytes = ?, last_progress_at = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP WHERE channel = ? AND message_id = ?",
                    (downloaded_bytes, channel, message_id),
                )
                conn.commit()
            finally:
                conn.close()
        
    def get_pending_tasks(self, limit: int = 100) -> list[dict]:
        """获取待恢复的任务（downloading 或 failed 状态）"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT * FROM downloads WHERE status IN ('downloading', 'failed') "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()

    def get_task(self, channel: str, message_id: int) -> Optional[dict]:
        """获取单条任务记录。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT * FROM downloads WHERE channel = ? AND message_id = ?",
                    (channel, message_id),
                )
                row = cur.fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

    def is_downloaded(self, channel: str, message_id: int) -> bool:
        """检查是否已下载完成。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT 1 FROM downloads WHERE channel = ? AND message_id = ? AND status = 'completed'",
                    (channel, message_id),
                )
                return cur.fetchone() is not None
            finally:
                conn.close()

    def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        """列出任务，可按状态过滤。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                if status is not None:
                    cur = conn.execute(
                        "SELECT * FROM downloads WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                        (status, limit),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?",
                        (limit,),
                    )
                return [dict(row) for row in cur.fetchall()]
            finally:
                conn.close()

    def record(
        self,
        channel: str,
        message_id: int,
        filename: str,
        file_size: Optional[int] = None,
    ) -> None:
        """兼容旧 API，直接记录为 completed。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                existing = self.get_task(channel, message_id)
                if existing is None:
                    conn.execute(
                        "INSERT INTO downloads "
                        "(channel, message_id, filename, file_size, status, source, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, 'completed', 'legacy', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                        (channel, message_id, filename, file_size),
                    )
                else:
                    conn.execute(
                        "UPDATE downloads SET filename = ?, file_size = ?, status = 'completed', "
                        "updated_at = CURRENT_TIMESTAMP WHERE channel = ? AND message_id = ?",
                        (filename, file_size, channel, message_id),
                    )
                conn.commit()
            finally:
                conn.close()

    def create_dedupe_task(
        self,
        chat_id: int,
        chat_title: Optional[str] = None,
        start_message_id: Optional[int] = None,
        total_messages: Optional[int] = None,
    ) -> int:
        """创建去重任务，返回 id。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "INSERT INTO dedupe_tasks (chat_id, chat_title, start_message_id, total_messages) "
                    "VALUES (?, ?, ?, ?)",
                    (chat_id, chat_title, start_message_id, total_messages),
                )
                conn.commit()
                return cur.lastrowid  # type: ignore[return-value]
            finally:
                conn.close()

    def update_dedupe_task(
        self,
        task_id: int,
        status: Optional[str] = None,
        last_scanned_message_id: Optional[int] = None,
        processed_messages: Optional[int] = None,
    ) -> None:
        """更新去重任务。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                fields = ["updated_at = CURRENT_TIMESTAMP"]
                params: list = []
                
                if status is not None:
                    fields.append("status = ?")
                    params.append(status)
                
                if last_scanned_message_id is not None:
                    fields.append("last_scanned_message_id = ?")
                    params.append(last_scanned_message_id)
                
                if processed_messages is not None:
                    fields.append("processed_messages = ?")
                    params.append(processed_messages)
                
                params.append(task_id)
                conn.execute(
                    f"UPDATE dedupe_tasks SET {', '.join(fields)} WHERE id = ?",
                    params,
                )
                conn.commit()
            finally:
                conn.close()

    def get_dedupe_task(self, task_id: int) -> Optional[dict]:
        """获取单条去重任务记录。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT * FROM dedupe_tasks WHERE id = ?",
                    (task_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                
                # 转换为字典，并添加计算字段
                task = dict(row)
                return self._enrich_task_with_calculated_fields(conn, task)
            finally:
                conn.close()

    def list_dedupe_tasks(self, limit: int = 50) -> list[dict]:
        """列出去重任务。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT * FROM dedupe_tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                tasks = []
                for row in cur.fetchall():
                    task = dict(row)
                    tasks.append(self._enrich_task_with_calculated_fields(conn, task))
                return tasks
            finally:
                conn.close()

    def _enrich_task_with_calculated_fields(self, conn, task: dict) -> dict:
        """为任务添加计算字段。"""
        # 获取统计信息
        task_id = task["id"]
        
        # 获取唯一和重复媒体数量
        cur = conn.execute("""
            SELECT 
                COUNT(CASE WHEN occurrence_count = 1 THEN 1 END) AS unique_count,
                COUNT(CASE WHEN occurrence_count > 1 THEN 1 END) AS duplicate_count
            FROM dedupe_media 
            WHERE task_id = ?
        """, (task_id,))
        stats_row = cur.fetchone()
        task["unique_media"] = stats_row["unique_count"] if stats_row["unique_count"] is not None else 0
        task["duplicate_count"] = stats_row["duplicate_count"] if stats_row["duplicate_count"] is not None else 0
        
        # 计算进度百分比
        total = task.get("total_messages")
        processed = task.get("processed_messages", 0) or 0
        if total and total > 0:
            task["progress"] = min(int(100 * processed / total), 100)
        elif processed > 0:
            # 如果没有总数但有处理过的消息，给一个虚拟进度
            task["progress"] = 0
        else:
            task["progress"] = 0
            
        return task

    def add_dedupe_media(
        self,
        task_id: int,
        file_id: str,
        file_size: Optional[int] = None,
        duration: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        first_seen_message_id: Optional[int] = None,
        first_seen_date: Optional[str] = None,
        thumbnail_data: Optional[bytes] = None,
        thumbnail_path: Optional[str] = None,
        thumbnail_width: Optional[int] = None,
        thumbnail_height: Optional[int] = None,
        phash: Optional[str] = None,
    ) -> int:
        """添加去重媒体记录，返回 id。如果已存在则更新 occurrence_count。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                existing = self.get_dedupe_media(task_id, file_id)
                if existing is not None:
                    conn.execute(
                        "UPDATE dedupe_media SET occurrence_count = occurrence_count + 1 WHERE task_id = ? AND file_id = ?",
                        (task_id, file_id),
                    )
                    conn.commit()
                    return existing["id"]
                
                # 处理缩略图：如果有 data 则保存到文件系统
                final_thumbnail_path = thumbnail_path
                if thumbnail_data:
                    try:
                        final_thumbnail_path = self.thumbnail_store.save(task_id, file_id, thumbnail_data)
                    except Exception as e:
                        logger.warning(f"保存缩略图到文件系统失败: {e}")
                
                cur = conn.execute(
                    "INSERT INTO dedupe_media (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date, thumbnail_path, thumbnail_width, thumbnail_height, phash) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date, final_thumbnail_path, thumbnail_width, thumbnail_height, phash),
                )
                conn.commit()
                return cur.lastrowid  # type: ignore[return-value]
            finally:
                conn.close()

    def get_dedupe_media(self, task_id: int, file_id: str) -> Optional[dict]:
        """获取单条去重媒体记录。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT * FROM dedupe_media WHERE task_id = ? AND file_id = ?",
                    (task_id, file_id),
                )
                row = cur.fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()

    def get_dedupe_media_thumbnail(self, task_id: int, media_id: Optional[int] = None, file_id: Optional[str] = None) -> Optional[dict]:
        """获取去重媒体的缩略图数据，从文件系统读取。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                query = "SELECT thumbnail_path, thumbnail_width, thumbnail_height FROM dedupe_media WHERE task_id = ?"
                params: list = [task_id]
                
                if media_id is not None:
                    query += " AND id = ?"
                    params.append(media_id)
                elif file_id is not None:
                    query += " AND file_id = ?"
                    params.append(file_id)
                else:
                    return None
                
                cur = conn.execute(query, params)
                row = cur.fetchone()
                if not row:
                    return None
                
                result = dict(row)
                
                # 从文件系统读取缩略图数据
                thumbnail_path = result.get('thumbnail_path')
                if thumbnail_path:
                    try:
                        thumbnail_data = self.thumbnail_store.load(thumbnail_path)
                        result['thumbnail_data'] = thumbnail_data
                    except Exception as e:
                        logger.warning(f"读取缩略图文件失败: {e}")
                        result['thumbnail_data'] = None
                else:
                    result['thumbnail_data'] = None
                
                return result
            finally:
                conn.close()

    def get_dedupe_media_list(
        self,
        task_id: int,
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None,
        filter_type: str = 'all',
        min_duration: Optional[int] = None,
        max_duration: Optional[int] = None,
    ) -> tuple[list[dict], int]:
        """获取去重媒体列表，支持分页、搜索和筛选。返回 (媒体列表, 总数)"""
        with _db_lock:
            conn = self._get_connection()
            try:
                offset = (page - 1) * limit
                base_query = """
                    FROM dedupe_media m
                    WHERE m.task_id = ?
                """
                params: list = [task_id]
                
                if search is not None:
                    base_query += " AND m.file_id LIKE ?"
                    params.append(f"%{search}%")
                
                if filter_type == 'duplicates':
                    base_query += " AND m.occurrence_count > 1"
                elif filter_type == 'singles':
                    base_query += " AND m.occurrence_count = 1"
                
                if min_duration is not None:
                    base_query += " AND m.duration >= ?"
                    params.append(min_duration)
                
                if max_duration is not None:
                    base_query += " AND m.duration <= ?"
                    params.append(max_duration)
                
                # 获取总数
                count_query = "SELECT COUNT(*) as total " + base_query
                cur = conn.execute(count_query, params)
                total_row = cur.fetchone()
                total = total_row['total'] if total_row else 0
                
                # 获取数据（先获取媒体信息，然后批量查询 dedupe_results）
                # 注意：不查询 phash 和 thumbnail_data 字段以避免大数据传输
                data_query = """
                    SELECT 
                        m.id,
                        m.task_id,
                        m.file_id,
                        m.file_size,
                        m.duration,
                        m.width,
                        m.height,
                        m.first_seen_message_id,
                        m.first_seen_date,
                        m.occurrence_count,
                        m.thumbnail_path,
                        m.thumbnail_width,
                        m.thumbnail_height
                """ + base_query + " ORDER BY m.occurrence_count DESC, m.created_at DESC LIMIT ? OFFSET ?"
                data_params = params + [limit, offset]
                
                cur = conn.execute(data_query, data_params)
                media_list = []
                file_ids = []
                for row in cur.fetchall():
                    item = dict(row)
                    media_list.append(item)
                    file_ids.append(item['file_id'])
                
                # 批量查询 dedupe_results 获取 is_original 和 downloaded 信息
                # 优化：使用 DISTINCT 避免重复的 file_id 记录
                is_original_map = {}
                downloaded_map = {}
                if file_ids:
                    placeholders = ','.join(['?'] * len(file_ids))
                    results_query = """
                        SELECT DISTINCT file_id, is_original, downloaded
                        FROM dedupe_results
                        WHERE task_id = ? AND file_id IN ({}) AND is_original = 1
                    """.format(placeholders)
                    cur = conn.execute(results_query, [task_id] + file_ids)
                    for row in cur.fetchall():
                        fid = row['file_id']
                        is_original_map[fid] = bool(row['is_original'])
                        downloaded_map[fid] = bool(row['downloaded'])
                
                # 完善媒体信息
                for item in media_list:
                    item['is_original'] = is_original_map.get(item['file_id'], False)
                    item['downloaded'] = downloaded_map.get(item['file_id'], False)
                    # 添加一个字段，表示是否有缩略图（检查 thumbnail_path 是否存在）
                    item['has_thumbnail'] = bool(item.get('thumbnail_path'))
                
                return media_list, total
            finally:
                conn.close()

    def add_dedupe_result(
        self,
        task_id: int,
        message_id: int,
        file_id: str,
        is_duplicate: bool = False,
        is_original: bool = False,
        downloaded: bool = False,
    ) -> int:
        """添加去重结果，返回 id。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "INSERT INTO dedupe_results (task_id, message_id, file_id, is_duplicate, is_original, downloaded) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (task_id, message_id, file_id, int(is_duplicate), int(is_original), int(downloaded)),
                )
                conn.commit()
                return cur.lastrowid  # type: ignore[return-value]
            finally:
                conn.close()

    def mark_dedupe_result_downloaded(self, task_id: int, file_id: str, downloaded: bool = True) -> None:
        """更新去重结果的下载状态。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE dedupe_results
                    SET downloaded = ?
                    WHERE task_id = ? AND file_id = ?
                    """,
                    (int(downloaded), task_id, file_id),
                )
                conn.commit()
            finally:
                conn.close()

    def is_dedupe_result_downloaded(self, task_id: int, file_id: str) -> bool:
        """检查指定去重媒体是否已下载完成。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    """
                    SELECT MAX(downloaded)
                    FROM dedupe_results
                    WHERE task_id = ? AND file_id = ?
                    """,
                    (task_id, file_id),
                ).fetchone()
                return bool(row[0]) if row and row[0] is not None else False
            finally:
                conn.close()

    def enqueue_dedupe_download_jobs(
        self,
        task_id: int,
        file_ids: List[str],
        output_dir: str,
        max_attempts: int = 3,
    ) -> List[str]:
        """将二层去重下载任务加入持久化队列。"""
        if not file_ids:
            return []

        queued_file_ids: List[str] = []
        with _db_lock:
            conn = self._get_connection()
            try:
                for file_id in file_ids:
                    if not file_id:
                        continue

                    downloaded_row = conn.execute(
                        """
                        SELECT MAX(downloaded)
                        FROM dedupe_results
                        WHERE task_id = ? AND file_id = ?
                        """,
                        (task_id, file_id),
                    ).fetchone()
                    if downloaded_row and downloaded_row[0]:
                        continue

                    existing = conn.execute(
                        """
                        SELECT id, status
                        FROM dedupe_download_jobs
                        WHERE task_id = ? AND file_id = ?
                        """,
                        (task_id, file_id),
                    ).fetchone()

                    if existing is None:
                        conn.execute(
                            """
                            INSERT INTO dedupe_download_jobs
                            (task_id, file_id, output_dir, status, max_attempts, created_at, updated_at)
                            VALUES (?, ?, ?, 'queued', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            """,
                            (task_id, file_id, output_dir, max_attempts),
                        )
                        queued_file_ids.append(file_id)
                        continue

                    if existing["status"] in {"queued", "retrying", "downloading"}:
                        continue

                    conn.execute(
                        """
                        UPDATE dedupe_download_jobs
                        SET output_dir = ?, status = 'queued', attempt_count = 0,
                            max_attempts = ?, last_error = NULL, next_retry_at = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (output_dir, max_attempts, existing["id"]),
                    )
                    queued_file_ids.append(file_id)

                conn.commit()
                return queued_file_ids
            finally:
                conn.close()

    def reset_incomplete_dedupe_download_jobs(self) -> int:
        """服务重启后，将运行中的下载任务重新置回队列。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    UPDATE dedupe_download_jobs
                    SET status = 'queued', next_retry_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE status = 'downloading'
                    """
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def list_runnable_dedupe_download_jobs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取可立即执行的二层去重下载任务。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM dedupe_download_jobs
                    WHERE status IN ('queued', 'retrying')
                      AND (next_retry_at IS NULL OR datetime(next_retry_at) <= datetime('now'))
                    ORDER BY created_at ASC, id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                conn.close()

    def mark_dedupe_download_job_running(self, job_id: int) -> None:
        """标记二层去重下载任务为运行中。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE dedupe_download_jobs
                    SET status = 'downloading', last_error = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (job_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def complete_dedupe_download_job(self, job_id: int) -> None:
        """标记二层去重下载任务已完成。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE dedupe_download_jobs
                    SET status = 'completed', next_retry_at = NULL, last_error = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (job_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def requeue_dedupe_download_job(self, job_id: int) -> None:
        """取消中的任务重新回到队列。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE dedupe_download_jobs
                    SET status = 'queued', next_retry_at = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (job_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def fail_dedupe_download_job(
        self,
        job_id: int,
        error_message: str,
        retry_delay_seconds: int,
    ) -> str:
        """根据重试次数决定是重试还是最终失败。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    """
                    SELECT attempt_count, max_attempts
                    FROM dedupe_download_jobs
                    WHERE id = ?
                    """,
                    (job_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"下载任务 {job_id} 不存在")

                next_attempt = int(row["attempt_count"] or 0) + 1
                max_attempts = int(row["max_attempts"] or 3)

                if next_attempt >= max_attempts:
                    status = "failed"
                    conn.execute(
                        """
                        UPDATE dedupe_download_jobs
                        SET status = 'failed', attempt_count = ?, last_error = ?,
                            next_retry_at = NULL, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (next_attempt, error_message, job_id),
                    )
                else:
                    status = "retrying"
                    conn.execute(
                        """
                        UPDATE dedupe_download_jobs
                        SET status = 'retrying', attempt_count = ?, last_error = ?,
                            next_retry_at = datetime('now', ?), updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (next_attempt, error_message, f"+{int(retry_delay_seconds)} seconds", job_id),
                    )

                conn.commit()
                return status
            finally:
                conn.close()

    def get_dedupe_download_job_status_map(self, task_id: int) -> Dict[str, str]:
        """获取任务中所有下载队列状态，用于前端展示。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    """
                    SELECT file_id, status
                    FROM dedupe_download_jobs
                    WHERE task_id = ?
                      AND status IN ('queued', 'retrying', 'downloading', 'failed')
                    """,
                    (task_id,),
                ).fetchall()
                status_map: Dict[str, str] = {}
                for row in rows:
                    status = row["status"]
                    if status == "retrying":
                        status = "queued"
                    status_map[row["file_id"]] = status
                return status_map
            finally:
                conn.close()

    def batch_add_dedupe_media(self, media_list: list) -> None:
        """批量添加去重媒体记录，提升性能。"""
        if not media_list:
            return
            
        logger.debug(f"批量添加 {len(media_list)} 条去重媒体记录")
        
        with _db_lock:
            conn = self._get_connection()
            try:
                # 使用事务批量执行
                for media in media_list:
                    # 检查是否存在
                    existing = self._get_dedupe_media_with_conn(conn, media['task_id'], media['file_id'])
                    if existing is not None:
                        conn.execute(
                            "UPDATE dedupe_media SET occurrence_count = occurrence_count + 1 WHERE task_id = ? AND file_id = ?",
                            (media['task_id'], media['file_id']),
                        )
                    else:
                        # 处理缩略图：如果有 data 则保存到文件系统
                        thumbnail_path = None
                        if media.get('thumbnail_data'):
                            try:
                                thumbnail_path = self.thumbnail_store.save(media['task_id'], media['file_id'], media['thumbnail_data'])
                            except Exception as e:
                                logger.warning(f"批量保存缩略图到文件系统失败: {e}")
                        
                        conn.execute(
                            "INSERT INTO dedupe_media (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date, thumbnail_path, thumbnail_width, thumbnail_height, phash) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                media['task_id'],
                                media['file_id'],
                                media.get('file_size'),
                                media.get('duration'),
                                media.get('width'),
                                media.get('height'),
                                media.get('first_seen_message_id'),
                                media.get('first_seen_date'),
                                thumbnail_path,
                                media.get('thumbnail_width'),
                                media.get('thumbnail_height'),
                                media.get('phash'),
                            ),
                        )
                conn.commit()
            finally:
                conn.close()

    def batch_add_dedupe_results(self, result_list: list) -> None:
        """批量添加去重结果，提升性能。"""
        if not result_list:
            return
            
        logger.debug(f"批量添加 {len(result_list)} 条去重结果")
        
        with _db_lock:
            conn = self._get_connection()
            try:
                for result in result_list:
                    conn.execute(
                        "INSERT INTO dedupe_results (task_id, message_id, file_id, is_duplicate, is_original, downloaded) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            result['task_id'],
                            result['message_id'],
                            result['file_id'],
                            int(result.get('is_duplicate', False)),
                            int(result.get('is_original', False)),
                            int(result.get('downloaded', False)),
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

    def _get_dedupe_media_with_conn(self, conn, task_id: int, file_id: str) -> Optional[dict]:
        """使用已有的连接获取媒体记录，用于批量操作。"""
        cur = conn.execute(
            "SELECT * FROM dedupe_media WHERE task_id = ? AND file_id = ?",
            (task_id, file_id),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def delete_dedupe_task(self, task_id: int) -> None:
        """删除去重任务及其关联的所有媒体和结果，包括缩略图文件。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                # 删除缩略图文件
                try:
                    self.thumbnail_store.delete_task_thumbnails(task_id)
                except Exception as e:
                    logger.warning(f"删除任务 {task_id} 的缩略图文件失败: {e}")
                
                # 删除关联的媒体记录
                conn.execute("DELETE FROM dedupe_media WHERE task_id = ?", (task_id,))
                # 删除关联的结果记录
                conn.execute("DELETE FROM dedupe_results WHERE task_id = ?", (task_id,))
                # 删除任务本身
                conn.execute("DELETE FROM dedupe_tasks WHERE id = ?", (task_id,))
                conn.commit()
            finally:
                conn.close()

    def reset_dedupe_task(self, task_id: int) -> None:
        """重置去重任务，用于重跑失败任务，包括删除缩略图文件。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                # 删除缩略图文件
                try:
                    self.thumbnail_store.delete_task_thumbnails(task_id)
                except Exception as e:
                    logger.warning(f"重置任务 {task_id} 时删除缩略图文件失败: {e}")
                
                # 删除关联的媒体和结果记录
                conn.execute("DELETE FROM dedupe_media WHERE task_id = ?", (task_id,))
                conn.execute("DELETE FROM dedupe_results WHERE task_id = ?", (task_id,))
                # 重置任务状态
                conn.execute(
                    "UPDATE dedupe_tasks SET status = 'pending', last_scanned_message_id = NULL, processed_messages = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (task_id,),
                )
                conn.commit()
            finally:
                conn.close()

    def update_media_phash(
        self, task_id: int, file_id: str, phash: Optional[str]
    ) -> None:
        """更新媒体的感知哈希"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "UPDATE dedupe_media SET phash = ? WHERE task_id = ? AND file_id = ?",
                    (phash, task_id, file_id)
                )
                conn.commit()
            finally:
                conn.close()

    def get_media_with_phash(self, task_id: int) -> List[Dict[str, Any]]:
        """获取所有有感知哈希的媒体"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT id, task_id, file_id, phash, file_size, duration,
                           thumbnail_path, first_seen_message_id
                    FROM dedupe_media
                    WHERE task_id = ? AND phash IS NOT NULL
                    """,
                    (task_id,)
                )
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

    def add_dedupe_level1(
        self,
        task_id: int,
        group_id: str,
        primary_media_id: int,
        media_ids: List[int]
    ) -> int:
        """添加第一层去重结果"""
        with _db_lock:
            conn = self._get_connection()
            try:
                media_ids_str = ",".join(str(id) for id in media_ids)
                cursor = conn.execute(
                    """
                    INSERT OR REPLACE INTO dedupe_level1
                    (task_id, group_id, primary_media_id, media_ids)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, group_id, primary_media_id, media_ids_str)
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def get_dedupe_level1(self, task_id: int) -> List[Dict[str, Any]]:
        """获取第一层去重结果"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT dl1.*, dm.file_id as primary_file_id
                    FROM dedupe_level1 dl1
                    JOIN dedupe_media dm ON dl1.primary_media_id = dm.id
                    WHERE dl1.task_id = ?
                    ORDER BY dl1.id
                    """,
                    (task_id,)
                )
                results = []
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    row_dict["media_ids"] = [
                        int(id) for id in row_dict["media_ids"].split(",") if id
                    ]
                    results.append(row_dict)
                return results
            finally:
                conn.close()

    def add_dedupe_level2(
        self,
        task_id: int,
        group_id: str,
        primary_level1_group_id: str,
        level1_group_ids: List[str],
        similarity_score: Optional[float] = None,
        hamming_distance: Optional[int] = None
    ) -> int:
        """添加第二层去重结果"""
        with _db_lock:
            conn = self._get_connection()
            try:
                level1_group_ids_str = ",".join(level1_group_ids)
                target = self._compute_level2_download_target(conn, task_id, level1_group_ids)
                cursor = conn.execute(
                    """
                    INSERT OR REPLACE INTO dedupe_level2
                    (task_id, group_id, primary_level1_group_id, level1_group_ids,
                     similarity_score, hamming_distance, uninterested,
                     download_target_file_id, download_target_media_id, download_target_file_size,
                     download_target_duration, download_target_has_thumbnail)
                    VALUES (?, ?, ?, ?, ?, ?, COALESCE(
                        (SELECT uninterested FROM dedupe_level2 WHERE task_id = ? AND group_id = ?),
                        0
                    ), ?, ?, ?, ?, ?)
                    """,
                    (task_id, group_id, primary_level1_group_id, level1_group_ids_str,
                     similarity_score, hamming_distance, task_id, group_id,
                     target["download_target_file_id"], target["download_target_media_id"],
                     target["download_target_file_size"], target["download_target_duration"],
                     target["download_target_has_thumbnail"])
                )
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def set_dedupe_level2_uninterested(self, task_id: int, group_id: str, uninterested: bool = True) -> None:
        """设置第二层分组是否不感兴趣。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    UPDATE dedupe_level2
                    SET uninterested = ?
                    WHERE task_id = ? AND group_id = ?
                    """,
                    (int(uninterested), task_id, group_id),
                )
                conn.commit()
            finally:
                conn.close()

    def get_dedupe_level2(self, task_id: int) -> List[Dict[str, Any]]:
        """获取第二层去重结果"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT * FROM dedupe_level2
                    WHERE task_id = ?
                    ORDER BY id
                    """,
                    (task_id,)
                )
                results = []
                for row in cursor.fetchall():
                    row_dict = dict(row)
                    row_dict["level1_group_ids"] = row_dict["level1_group_ids"].split(",")
                    results.append(row_dict)
                return results
            finally:
                conn.close()

    def _compute_level2_download_target(
        self,
        conn: sqlite3.Connection,
        task_id: int,
        level1_group_ids: List[str],
    ) -> Dict[str, Any]:
        """计算二层分组默认下载目标：组内最大文件。"""
        if not level1_group_ids:
            return {
                "download_target_file_id": None,
                "download_target_media_id": None,
                "download_target_file_size": None,
                "download_target_duration": None,
                "download_target_has_thumbnail": 0,
            }

        placeholders = ",".join("?" for _ in level1_group_ids)
        rows = conn.execute(
            f"""
            SELECT id, file_id, file_size, duration, thumbnail_path
            FROM dedupe_media
            WHERE task_id = ? AND file_id IN ({placeholders})
            ORDER BY COALESCE(file_size, 0) DESC, id ASC
            """,
            (task_id, *level1_group_ids),
        ).fetchall()
        if not rows:
            return {
                "download_target_file_id": None,
                "download_target_media_id": None,
                "download_target_file_size": None,
                "download_target_duration": None,
                "download_target_has_thumbnail": 0,
            }

        top = rows[0]
        return {
            "download_target_file_id": top["file_id"],
            "download_target_media_id": top["id"],
            "download_target_file_size": top["file_size"],
            "download_target_duration": top["duration"],
            "download_target_has_thumbnail": int(bool(top["thumbnail_path"])),
        }

    def _backfill_level2_download_targets(self, conn: sqlite3.Connection, task_id: int) -> int:
        """为缺失默认下载目标的二层分组补全缓存字段。"""
        rows = conn.execute(
            """
            SELECT id, level1_group_ids
            FROM dedupe_level2
            WHERE task_id = ?
              AND (
                download_target_file_id IS NULL
                OR download_target_media_id IS NULL
                OR download_target_file_size IS NULL
              )
            """,
            (task_id,),
        ).fetchall()
        if not rows:
            return 0

        updates = []
        for row in rows:
            level1_group_ids = [group_id for group_id in (row["level1_group_ids"] or "").split(",") if group_id]
            target = self._compute_level2_download_target(conn, task_id, level1_group_ids)
            updates.append(
                (
                    target["download_target_file_id"],
                    target["download_target_media_id"],
                    target["download_target_file_size"],
                    target["download_target_duration"],
                    target["download_target_has_thumbnail"],
                    row["id"],
                )
            )

        conn.executemany(
            """
            UPDATE dedupe_level2
            SET download_target_file_id = ?,
                download_target_media_id = ?,
                download_target_file_size = ?,
                download_target_duration = ?,
                download_target_has_thumbnail = ?
            WHERE id = ?
            """,
            updates,
        )
        conn.commit()
        return len(updates)

    def get_two_level_dedupe_summary_page(
        self,
        task_id: int,
        level2_page: int = 1,
        level2_limit: int = 50,
        level1_preview_limit: int = 10,
        download_status_filter: Optional[str] = None,
        runtime_status_map: Optional[Dict[str, str]] = None,
        show_uninterested: bool = False,
        include_level1_groups: bool = False,
        min_download_size_bytes: Optional[int] = None,
        max_download_size_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取分页后的两层去重汇总，避免一次性返回超大结果。"""
        level2_page = max(1, int(level2_page or 1))
        level2_limit = max(1, min(int(level2_limit or 50), 200))
        level1_preview_limit = max(0, min(int(level1_preview_limit or 10), 50))
        normalized_status_filter = (download_status_filter or "all").strip().lower()
        runtime_status_map = runtime_status_map or {}
        normalized_min_size = None if min_download_size_bytes in (None, "") else max(0, int(min_download_size_bytes))
        normalized_max_size = None if max_download_size_bytes in (None, "") else max(0, int(max_download_size_bytes))

        def build_level1_groups(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
            groups: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                file_id = row["file_id"]
                if file_id not in groups:
                    groups[file_id] = {
                        "group_id": file_id,
                        "primary_file_id": file_id,
                        "primary_media_id": row["id"],
                        "media_list": [],
                    }
                media = row.copy()
                media["has_thumbnail"] = bool(media.get("thumbnail_path"))
                groups[file_id]["media_list"].append(media)
            return groups

        def fetch_media_meta(
            conn,
            file_ids: Optional[List[str]] = None,
            *,
            order_by_occurrence: bool = False,
            limit: Optional[int] = None,
        ) -> Dict[str, Dict[str, Any]]:
            params: List[Any] = [task_id]
            where_clause = "WHERE dm.task_id = ?"
            if file_ids is not None:
                if not file_ids:
                    return {}
                placeholders = ",".join("?" for _ in file_ids)
                where_clause += f" AND dm.file_id IN ({placeholders})"
                params.extend(file_ids)

            order_clause = "ORDER BY dm.id"
            if order_by_occurrence:
                order_clause = "ORDER BY dm.occurrence_count DESC, dm.id"

            limit_clause = ""
            if limit is not None:
                limit_clause = " LIMIT ?"
                params.append(limit)

            rows = conn.execute(
                f"""
                SELECT dm.id, dm.file_id, dm.file_size, dm.duration,
                       dm.width, dm.height, dm.occurrence_count,
                       dm.thumbnail_path, dm.thumbnail_width,
                       dm.thumbnail_height, dm.phash,
                       dm.first_seen_message_id, dm.first_seen_date
                FROM dedupe_media dm
                {where_clause}
                {order_clause}
                {limit_clause}
                """,
                params,
            ).fetchall()

            media_meta: Dict[str, Dict[str, Any]] = {}
            for row in rows:
                row_dict = dict(row)
                row_dict["has_thumbnail"] = bool(row_dict.get("thumbnail_path"))
                row_dict["downloaded"] = 0
                media_meta[row_dict["file_id"]] = row_dict

            if media_meta:
                downloaded_file_ids = list(media_meta.keys())
                placeholders = ",".join("?" for _ in downloaded_file_ids)
                downloaded_rows = conn.execute(
                    f"""
                    SELECT file_id, MAX(downloaded) AS downloaded
                    FROM dedupe_results
                    WHERE task_id = ? AND file_id IN ({placeholders})
                    GROUP BY file_id
                    """,
                    (task_id, *downloaded_file_ids),
                ).fetchall()
                for downloaded_row in downloaded_rows:
                    file_id = downloaded_row["file_id"]
                    if file_id in media_meta:
                        media_meta[file_id]["downloaded"] = downloaded_row["downloaded"]
            return media_meta

        def build_level2_detail(
            conn,
            level2_rows: List[sqlite3.Row],
            *,
            apply_status_filter: bool,
        ) -> List[Dict[str, Any]]:
            if not level2_rows:
                return []

            level2_groups: List[Dict[str, Any]] = []
            paged_file_ids: List[str] = []
            seen_file_ids: set[str] = set()
            for row in level2_rows:
                row_dict = dict(row)
                row_dict["level1_group_ids"] = [
                    group_id
                    for group_id in row_dict["level1_group_ids"].split(",")
                    if group_id
                ]
                row_dict["uninterested"] = bool(row_dict.get("uninterested"))
                level2_groups.append(row_dict)
                for file_id in row_dict["level1_group_ids"]:
                    if file_id not in seen_file_ids:
                        seen_file_ids.add(file_id)
                        paged_file_ids.append(file_id)

            media_meta = fetch_media_meta(conn, paged_file_ids)
            file_id_to_group = (
                build_level1_groups(list(media_meta.values()))
                if include_level1_groups
                else {}
            )

            level2_detail: List[Dict[str, Any]] = []
            for group in level2_groups:
                candidate_media = None
                for file_id in group["level1_group_ids"]:
                    media = media_meta.get(file_id)
                    if not media:
                        continue
                    size = media.get("file_size") or 0
                    candidate_size = (candidate_media.get("file_size") or 0) if candidate_media else -1
                    if candidate_media is None or size > candidate_size:
                        candidate_media = media

                if candidate_media:
                    candidate_file_id = candidate_media["file_id"]
                    runtime_status = runtime_status_map.get(candidate_file_id)
                    if runtime_status in {"queued", "downloading", "failed", "downloaded"}:
                        download_status = runtime_status
                    elif candidate_media.get("downloaded"):
                        download_status = "downloaded"
                    else:
                        download_status = "not_downloaded"
                else:
                    candidate_file_id = None
                    download_status = "not_downloaded"

                if apply_status_filter and normalized_status_filter not in {"", "all"} and download_status != normalized_status_filter:
                    continue

                level1_groups_in_level2 = []
                if include_level1_groups:
                    level1_groups_in_level2 = [
                        file_id_to_group[level1_group_id]
                        for level1_group_id in group["level1_group_ids"]
                        if level1_group_id in file_id_to_group
                    ]
                level2_detail.append({
                    "group_id": group["group_id"],
                    "primary_level1_group_id": group["primary_level1_group_id"],
                    "level1_group_ids": group["level1_group_ids"],
                    "level1_groups": level1_groups_in_level2,
                    "similarity_score": group["similarity_score"],
                    "hamming_distance": group["hamming_distance"],
                    "download_status": download_status,
                    "download_target_file_id": candidate_file_id,
                    "download_target_media_id": candidate_media["id"] if candidate_media else None,
                    "download_target_file_size": candidate_media.get("file_size") if candidate_media else None,
                    "download_target_duration": candidate_media.get("duration") if candidate_media else None,
                    "download_target_has_thumbnail": candidate_media.get("has_thumbnail") if candidate_media else False,
                    "uninterested": group["uninterested"],
                })
            return level2_detail

        with _db_lock:
            conn = self._get_connection()
            try:
                level1_count = conn.execute(
                    "SELECT COUNT(*) FROM dedupe_media WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]

                level2_count = conn.execute(
                    "SELECT COUNT(*) FROM dedupe_level2 WHERE task_id = ?",
                    (task_id,),
                ).fetchone()[0]

                if level2_count > 0:
                    self._backfill_level2_download_targets(conn, task_id)

                offset = (level2_page - 1) * level2_limit
                filter_clauses: List[str] = []
                filter_params: List[Any] = [task_id]

                if not show_uninterested:
                    filter_clauses.append("uninterested = 0")
                if normalized_min_size is not None:
                    filter_clauses.append("COALESCE(download_target_file_size, 0) >= ?")
                    filter_params.append(normalized_min_size)
                if normalized_max_size is not None:
                    filter_clauses.append("COALESCE(download_target_file_size, 0) <= ?")
                    filter_params.append(normalized_max_size)

                where_sql = "WHERE task_id = ?"
                if filter_clauses:
                    where_sql += " AND " + " AND ".join(filter_clauses)

                if normalized_status_filter in {"", "all"}:
                    filtered_total = conn.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM dedupe_level2
                        {where_sql}
                        """,
                        filter_params,
                    ).fetchone()[0]
                    paged_level2_rows = conn.execute(
                        f"""
                        SELECT *
                        FROM dedupe_level2
                        {where_sql}
                        ORDER BY id
                        LIMIT ? OFFSET ?
                        """,
                        [*filter_params, level2_limit, offset],
                    ).fetchall()
                    level2_detail = build_level2_detail(
                        conn,
                        list(paged_level2_rows),
                        apply_status_filter=False,
                    )
                else:
                    all_level2_rows = conn.execute(
                        f"""
                        SELECT *
                        FROM dedupe_level2
                        {where_sql}
                        ORDER BY id
                        """,
                        filter_params,
                    ).fetchall()
                    filtered_level2 = build_level2_detail(
                        conn,
                        list(all_level2_rows),
                        apply_status_filter=True,
                    )
                    filtered_total = len(filtered_level2)
                    level2_detail = filtered_level2[offset: offset + level2_limit]

                level1_preview = []
                if filtered_total == 0 and level1_count > 0 and level1_preview_limit > 0:
                    preview_meta = fetch_media_meta(
                        conn,
                        None,
                        order_by_occurrence=True,
                        limit=level1_preview_limit,
                    )
                    level1_preview = list(build_level1_groups(list(preview_meta.values())).values())

                return {
                    "task_id": task_id,
                    "level1_groups": level1_preview,
                    "level1_count": level1_count,
                    "level2_groups": level2_detail,
                    "level2_count": level2_count,
                    "level2_pagination": {
                        "page": level2_page,
                        "limit": level2_limit,
                        "total": filtered_total,
                        "total_pages": (filtered_total + level2_limit - 1) // level2_limit if level2_limit else 0,
                    },
                    "download_status_filter": normalized_status_filter,
                    "show_uninterested": show_uninterested,
                    "min_download_size_bytes": normalized_min_size,
                    "max_download_size_bytes": normalized_max_size,
                }
            finally:
                conn.close()

    def get_two_level_dedupe_group_detail(
        self,
        task_id: int,
        group_id: str,
        runtime_status_map: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取单个二层去重分组的完整详情。"""
        runtime_status_map = runtime_status_map or {}

        with _db_lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    """
                    SELECT *
                    FROM dedupe_level2
                    WHERE task_id = ? AND group_id = ?
                    """,
                    (task_id, group_id),
                ).fetchone()
                if not row:
                    return None

                group = dict(row)
                level1_group_ids = [
                    value
                    for value in (group.get("level1_group_ids") or "").split(",")
                    if value
                ]
                group["uninterested"] = bool(group.get("uninterested"))

                media_meta: Dict[str, Dict[str, Any]] = {}
                if level1_group_ids:
                    placeholders = ",".join("?" for _ in level1_group_ids)
                    media_rows = conn.execute(
                        f"""
                        SELECT dm.id, dm.file_id, dm.file_size, dm.duration,
                               dm.width, dm.height, dm.occurrence_count,
                               dm.thumbnail_path, dm.thumbnail_width,
                               dm.thumbnail_height, dm.phash,
                               dm.first_seen_message_id, dm.first_seen_date
                        FROM dedupe_media dm
                        WHERE dm.task_id = ? AND dm.file_id IN ({placeholders})
                        ORDER BY dm.id
                        """,
                        (task_id, *level1_group_ids),
                    ).fetchall()
                    for media_row in media_rows:
                        media = dict(media_row)
                        media["has_thumbnail"] = bool(media.get("thumbnail_path"))
                        media["downloaded"] = 0
                        media_meta[media["file_id"]] = media

                    downloaded_rows = conn.execute(
                        f"""
                        SELECT file_id, MAX(downloaded) AS downloaded
                        FROM dedupe_results
                        WHERE task_id = ? AND file_id IN ({placeholders})
                        GROUP BY file_id
                        """,
                        (task_id, *level1_group_ids),
                    ).fetchall()
                    for downloaded_row in downloaded_rows:
                        file_id = downloaded_row["file_id"]
                        if file_id in media_meta:
                            media_meta[file_id]["downloaded"] = downloaded_row["downloaded"]

                candidate_media = None
                for file_id in level1_group_ids:
                    media = media_meta.get(file_id)
                    if not media:
                        continue
                    size = media.get("file_size") or 0
                    candidate_size = (candidate_media.get("file_size") or 0) if candidate_media else -1
                    if candidate_media is None or size > candidate_size:
                        candidate_media = media

                if candidate_media:
                    candidate_file_id = candidate_media["file_id"]
                    runtime_status = runtime_status_map.get(candidate_file_id)
                    if runtime_status in {"queued", "downloading", "failed", "downloaded"}:
                        download_status = runtime_status
                    elif candidate_media.get("downloaded"):
                        download_status = "downloaded"
                    else:
                        download_status = "not_downloaded"
                else:
                    candidate_file_id = None
                    download_status = "not_downloaded"

                level1_groups: Dict[str, Dict[str, Any]] = {}
                for file_id in level1_group_ids:
                    media = media_meta.get(file_id)
                    if not media:
                        continue
                    level1_groups[file_id] = {
                        "group_id": file_id,
                        "primary_file_id": file_id,
                        "primary_media_id": media["id"],
                        "media_list": [media],
                    }

                return {
                    "group_id": group["group_id"],
                    "primary_level1_group_id": group["primary_level1_group_id"],
                    "level1_group_ids": level1_group_ids,
                    "level1_groups": [
                        level1_groups[file_id]
                        for file_id in level1_group_ids
                        if file_id in level1_groups
                    ],
                    "similarity_score": group["similarity_score"],
                    "hamming_distance": group["hamming_distance"],
                    "download_status": download_status,
                    "download_target_file_id": candidate_file_id,
                    "download_target_media_id": candidate_media["id"] if candidate_media else None,
                    "download_target_file_size": candidate_media.get("file_size") if candidate_media else None,
                    "download_target_duration": candidate_media.get("duration") if candidate_media else None,
                    "download_target_has_thumbnail": candidate_media.get("has_thumbnail") if candidate_media else False,
                    "uninterested": group["uninterested"],
                }
            finally:
                conn.close()

    def get_two_level_dedupe_summary(self, task_id: int) -> Dict[str, Any]:
        """获取两层去重的汇总结果"""
        with _db_lock:
            conn = self._get_connection()
            try:
                # 先获取该任务所有的去重结果
                cursor = conn.execute(
                    """
                    SELECT dr.*, dm.file_id, dm.file_size, dm.duration, dm.thumbnail_path, 
                           dm.thumbnail_width, dm.thumbnail_height, dm.phash,
                           dm.first_seen_message_id, dm.first_seen_date
                    FROM dedupe_results dr
                    JOIN dedupe_media dm ON dr.task_id = dm.task_id AND dr.file_id = dm.file_id
                    WHERE dr.task_id = ?
                    ORDER BY dr.message_id
                    """,
                    (task_id,)
                )
                all_results = [dict(row) for row in cursor.fetchall()]
                
                # 第一层去重：按 file_id 分组
                level1_groups = []
                file_id_to_group: Dict[str, dict] = {}
                
                for result in all_results:
                    file_id = result['file_id']
                    if file_id not in file_id_to_group:
                        # 创建新组
                        group = {
                            "group_id": file_id,
                            "primary_file_id": file_id,
                            "media_list": [],
                            "primary_media_id": result['id'] if result.get('is_original') else None
                        }
                        level1_groups.append(group)
                        file_id_to_group[file_id] = group
                    
                    # 添加 has_thumbnail 字段
                    media = result.copy()
                    media['has_thumbnail'] = bool(media.get('thumbnail_path'))
                    file_id_to_group[file_id]['media_list'].append(media)
                
                # 获取第二层去重信息
                level2 = self.get_dedupe_level2(task_id)
                
                # 构建第二层结果详情
                level2_detail = []
                for g in level2:
                    level1_groups_in_level2 = []
                    for level1_group_id in g["level1_group_ids"]:
                        if level1_group_id in file_id_to_group:
                            level1_groups_in_level2.append(file_id_to_group[level1_group_id])
                    level2_detail.append({
                        "group_id": g["group_id"],
                        "primary_level1_group_id": g["primary_level1_group_id"],
                        "level1_groups": level1_groups_in_level2,
                        "similarity_score": g["similarity_score"],
                        "hamming_distance": g["hamming_distance"]
                    })
                
                return {
                    "task_id": task_id,
                    "level1_groups": level1_groups,
                    "level1_count": len(level1_groups),
                    "level2_groups": level2_detail,
                    "level2_count": len(level2_detail)
                }
            finally:
                conn.close()

    def clear_dedupe_results(self, task_id: int) -> None:
        """清除任务的去重结果"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM dedupe_level1 WHERE task_id = ?", (task_id,))
                conn.execute("DELETE FROM dedupe_level2 WHERE task_id = ?", (task_id,))
                conn.commit()
            finally:
                conn.close()
    
    def clear_media_phash(self, task_id: int) -> None:
        """清除任务所有媒体的感知哈希"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("UPDATE dedupe_media SET phash = NULL WHERE task_id = ?", (task_id,))
                conn.commit()
            finally:
                conn.close()

    def close(self) -> None:
        """关闭数据库连接。这里不需要操作，因为我们每次都创建新连接。"""
        pass


# 兼容旧代码
DownloadHistory = DownloadDB
