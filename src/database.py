from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class DownloadDB:
    """统一的 SQLite 下载任务管理。"""

    def __init__(self, db_path: str | Path = "downloads.db") -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        
        # 创建表（旧版本）
        self._conn.execute(
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
        self._migrate()
        
        self._conn.commit()
        
    def _migrate(self):
        """执行数据库迁移，添加新字段"""
        cursor = self._conn.execute("PRAGMA table_info(downloads)")
        columns = {row[1] for row in cursor.fetchall()}
        
        # 添加 downloaded_bytes 字段
        if "downloaded_bytes" not in columns:
            self._conn.execute("ALTER TABLE downloads ADD COLUMN downloaded_bytes INTEGER DEFAULT 0")
        
        # 添加 total_bytes 字段
        if "total_bytes" not in columns:
            self._conn.execute("ALTER TABLE downloads ADD COLUMN total_bytes INTEGER")
        
        # 添加 last_progress_at 字段
        if "last_progress_at" not in columns:
            self._conn.execute("ALTER TABLE downloads ADD COLUMN last_progress_at TIMESTAMP")
        
        # 添加 retry_count 字段
        if "retry_count" not in columns:
            self._conn.execute("ALTER TABLE downloads ADD COLUMN retry_count INTEGER DEFAULT 0")
        
        # 创建去重任务表
        self._conn.execute(
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
        
        # 创建去重媒体表
        self._conn.execute(
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(task_id, file_id)
            )
            """
        )
        
        # 创建去重结果表
        self._conn.execute(
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
        existing = self.get_task(channel, message_id)
        if existing is not None:
            if existing["status"] == "completed":
                return -1
            if existing["status"] == "failed":
                self._conn.execute(
                    "UPDATE downloads SET status = 'queued', source = ?, error_message = NULL, "
                    "updated_at = CURRENT_TIMESTAMP, retry_count = 0 WHERE channel = ? AND message_id = ?",
                    (source, channel, message_id),
                )
                self._conn.commit()
                return existing["id"]
            # 其他状态（queued / downloading）返回已有 id
            return existing["id"]

        cur = self._conn.execute(
            "INSERT INTO downloads (channel, message_id, source, filename, file_size, total_bytes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (channel, message_id, source, filename, file_size, total_bytes),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

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
        self._conn.execute(
            f"UPDATE downloads SET {', '.join(fields)} WHERE channel = ? AND message_id = ?",
            params,
        )
        self._conn.commit()
        
    def update_progress(
        self,
        channel: str,
        message_id: int,
        downloaded_bytes: int,
    ) -> None:
        """更新下载进度（便捷方法）"""
        self._conn.execute(
            "UPDATE downloads SET downloaded_bytes = ?, last_progress_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE channel = ? AND message_id = ?",
            (downloaded_bytes, channel, message_id),
        )
        self._conn.commit()
        
    def get_pending_tasks(self, limit: int = 100) -> list[dict]:
        """获取待恢复的任务（downloading 或 failed 状态）"""
        cur = self._conn.execute(
            "SELECT * FROM downloads WHERE status IN ('downloading', 'failed') "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

    def get_task(self, channel: str, message_id: int) -> Optional[dict]:
        """获取单条任务记录。"""
        cur = self._conn.execute(
            "SELECT * FROM downloads WHERE channel = ? AND message_id = ?",
            (channel, message_id),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def is_downloaded(self, channel: str, message_id: int) -> bool:
        """检查是否已下载完成。"""
        cur = self._conn.execute(
            "SELECT 1 FROM downloads WHERE channel = ? AND message_id = ? AND status = 'completed'",
            (channel, message_id),
        )
        return cur.fetchone() is not None

    def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> list[dict]:
        """列出任务，可按状态过滤。"""
        if status is not None:
            cur = self._conn.execute(
                "SELECT * FROM downloads WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM downloads ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cur.fetchall()]

    def record(
        self,
        channel: str,
        message_id: int,
        filename: str,
        file_size: Optional[int] = None,
    ) -> None:
        """兼容旧 API，直接记录为 completed。"""
        existing = self.get_task(channel, message_id)
        if existing is None:
            self._conn.execute(
                "INSERT INTO downloads (channel, message_id, filename, file_size, status) "
                "VALUES (?, ?, ?, ?, 'completed')",
                (channel, message_id, filename, file_size),
            )
        else:
            self._conn.execute(
                "UPDATE downloads SET filename = ?, file_size = ?, status = 'completed', "
                "updated_at = CURRENT_TIMESTAMP WHERE channel = ? AND message_id = ?",
                (filename, file_size, channel, message_id),
            )
        self._conn.commit()

    def create_dedupe_task(
        self,
        chat_id: int,
        chat_title: Optional[str] = None,
        start_message_id: Optional[int] = None,
        total_messages: Optional[int] = None,
    ) -> int:
        """创建去重任务，返回 id。"""
        cur = self._conn.execute(
            "INSERT INTO dedupe_tasks (chat_id, chat_title, start_message_id, total_messages) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, chat_title, start_message_id, total_messages),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_dedupe_task(
        self,
        task_id: int,
        status: Optional[str] = None,
        last_scanned_message_id: Optional[int] = None,
        processed_messages: Optional[int] = None,
    ) -> None:
        """更新去重任务。"""
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
        self._conn.execute(
            f"UPDATE dedupe_tasks SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def get_dedupe_task(self, task_id: int) -> Optional[dict]:
        """获取单条去重任务记录。"""
        cur = self._conn.execute(
            "SELECT * FROM dedupe_tasks WHERE id = ?",
            (task_id,),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def list_dedupe_tasks(self, limit: int = 50) -> list[dict]:
        """列出去重任务。"""
        cur = self._conn.execute(
            "SELECT * FROM dedupe_tasks ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]

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
    ) -> int:
        """添加去重媒体记录，返回 id。如果已存在则更新 occurrence_count。"""
        existing = self.get_dedupe_media(task_id, file_id)
        if existing is not None:
            self._conn.execute(
                "UPDATE dedupe_media SET occurrence_count = occurrence_count + 1 WHERE task_id = ? AND file_id = ?",
                (task_id, file_id),
            )
            self._conn.commit()
            return existing["id"]
        
        cur = self._conn.execute(
            "INSERT INTO dedupe_media (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, file_id, file_size, duration, width, height, first_seen_message_id, first_seen_date),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_dedupe_media(self, task_id: int, file_id: str) -> Optional[dict]:
        """获取单条去重媒体记录。"""
        cur = self._conn.execute(
            "SELECT * FROM dedupe_media WHERE task_id = ? AND file_id = ?",
            (task_id, file_id),
        )
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def get_dedupe_media_list(
        self,
        task_id: int,
        page: int = 1,
        limit: int = 20,
        search: Optional[str] = None,
        filter_type: str = 'all',
    ) -> list[dict]:
        """获取去重媒体列表，支持分页、搜索和筛选。"""
        offset = (page - 1) * limit
        query = "SELECT * FROM dedupe_media WHERE task_id = ?"
        params: list = [task_id]
        
        if search is not None:
            query += " AND file_id LIKE ?"
            params.append(f"%{search}%")
        
        if filter_type == 'duplicates':
            query += " AND occurrence_count > 1"
        elif filter_type == 'singles':
            query += " AND occurrence_count = 1"
        
        query += " ORDER BY occurrence_count DESC, created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cur = self._conn.execute(query, params)
        return [dict(row) for row in cur.fetchall()]

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
        cur = self._conn.execute(
            "INSERT INTO dedupe_results (task_id, message_id, file_id, is_duplicate, is_original, downloaded) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (task_id, message_id, file_id, int(is_duplicate), int(is_original), int(downloaded)),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()


# 兼容旧代码
DownloadHistory = DownloadDB
