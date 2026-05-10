from __future__ import annotations

import sqlite3
import threading
import logging
from pathlib import Path
from typing import Optional

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
                    "INSERT INTO downloads (channel, message_id, source, filename, file_size, total_bytes) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
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
                        "INSERT INTO downloads (channel, message_id, filename, file_size, status) "
                        "VALUES (?, ?, ?, ?, 'completed')",
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
                    "INSERT INTO dedupe_media (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date, thumbnail_path, thumbnail_width, thumbnail_height) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date, final_thumbnail_path, thumbnail_width, thumbnail_height),
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
    ) -> list[dict]:
        """获取去重媒体列表，支持分页、搜索和筛选。"""
        with _db_lock:
            conn = self._get_connection()
            try:
                offset = (page - 1) * limit
                query = """
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
                        m.thumbnail_height,
                        COALESCE(r.is_original, 0) as is_original,
                        COALESCE(r.downloaded, 0) as downloaded
                    FROM dedupe_media m
                    LEFT JOIN dedupe_results r ON m.task_id = r.task_id AND m.file_id = r.file_id AND r.is_original = 1
                    WHERE m.task_id = ?
                """
                params: list = [task_id]
                
                if search is not None:
                    query += " AND m.file_id LIKE ?"
                    params.append(f"%{search}%")
                
                if filter_type == 'duplicates':
                    query += " AND m.occurrence_count > 1"
                elif filter_type == 'singles':
                    query += " AND m.occurrence_count = 1"
                
                query += " ORDER BY m.occurrence_count DESC, m.created_at DESC LIMIT ? OFFSET ?"
                params.extend([limit, offset])
                
                cur = conn.execute(query, params)
                media_list = []
                for row in cur.fetchall():
                    item = dict(row)
                    # 确保布尔值是 Python 布尔类型
                    item['is_original'] = bool(item.get('is_original', False))
                    item['downloaded'] = bool(item.get('downloaded', False))
                    # 添加一个字段，表示是否有缩略图（检查 thumbnail_path 是否存在）
                    item['has_thumbnail'] = bool(item.get('thumbnail_path'))
                    media_list.append(item)
                return media_list
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
                            "INSERT INTO dedupe_media (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date, thumbnail_path, thumbnail_width, thumbnail_height) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

    def close(self) -> None:
        """关闭数据库连接。这里不需要操作，因为我们每次都创建新连接。"""
        pass


# 兼容旧代码
DownloadHistory = DownloadDB
