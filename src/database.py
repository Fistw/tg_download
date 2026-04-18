from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class DownloadDB:
    """统一的 SQLite 下载任务管理。"""

    def __init__(self, db_path: str | Path = "downloads.db") -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
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
        self._conn.commit()

    def create_task(
        self,
        channel: str,
        message_id: int,
        source: str = "cli",
        filename: Optional[str] = None,
        file_size: Optional[int] = None,
    ) -> int:
        """创建任务，返回 id。已完成返回 -1，失败则重置为 queued。"""
        existing = self.get_task(channel, message_id)
        if existing is not None:
            if existing["status"] == "completed":
                return -1
            if existing["status"] == "failed":
                self._conn.execute(
                    "UPDATE downloads SET status = 'queued', source = ?, error_message = NULL, "
                    "updated_at = CURRENT_TIMESTAMP WHERE channel = ? AND message_id = ?",
                    (source, channel, message_id),
                )
                self._conn.commit()
                return existing["id"]
            # 其他状态（queued / downloading）返回已有 id
            return existing["id"]

        cur = self._conn.execute(
            "INSERT INTO downloads (channel, message_id, source, filename, file_size) "
            "VALUES (?, ?, ?, ?, ?)",
            (channel, message_id, source, filename, file_size),
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
        params.extend([channel, message_id])
        self._conn.execute(
            f"UPDATE downloads SET {', '.join(fields)} WHERE channel = ? AND message_id = ?",
            params,
        )
        self._conn.commit()

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

    def close(self) -> None:
        """关闭数据库连接。"""
        self._conn.close()


# 兼容旧代码
DownloadHistory = DownloadDB
