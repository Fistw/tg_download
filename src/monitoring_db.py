from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generator, Optional

# 全局锁，防止多线程并发问题
_db_lock = threading.Lock()


class MonitoringDB:
    def __init__(self, db_path: str | Path = "./data/monitoring.db", retention_days: int = 7):
        self.db_path = Path(db_path)
        self.retention_days = retention_days
        # 确保目录存在
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS download_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id INTEGER,
                        filename TEXT NOT NULL,
                        file_size_bytes INTEGER,
                        downloaded_bytes INTEGER DEFAULT 0,
                        speed_kb_s REAL DEFAULT 0,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS upload_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT NOT NULL,
                        file_size_bytes INTEGER,
                        uploaded_bytes INTEGER DEFAULT 0,
                        speed_kb_s REAL DEFAULT 0,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS system_metrics (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        memory_percent REAL,
                        cpu_percent REAL,
                        active_connections INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_dl_created ON download_metrics(created_at)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_ul_created ON upload_metrics(created_at)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_sys_created ON system_metrics(created_at)
                """)
                conn.commit()
            finally:
                conn.close()

    def cleanup_old_data(self) -> None:
        """清理保留天数之前的数据"""
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)
        cutoff_str = cutoff_date.isoformat()
        
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM download_metrics WHERE created_at < ?", (cutoff_str,))
                conn.execute("DELETE FROM upload_metrics WHERE created_at < ?", (cutoff_str,))
                conn.execute("DELETE FROM system_metrics WHERE created_at < ?", (cutoff_str,))
                conn.commit()
            finally:
                conn.close()

    # ==================== 下载指标 ====================

    def start_download_task(
        self,
        task_id: Optional[int],
        filename: str,
        file_size_bytes: Optional[int] = None
    ) -> int:
        """开始记录下载任务"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("""
                    INSERT INTO download_metrics 
                    (task_id, filename, file_size_bytes, status) 
                    VALUES (?, ?, ?, 'downloading')
                """, (task_id, filename, file_size_bytes))
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def update_download_progress(
        self,
        record_id: int,
        downloaded_bytes: int,
        speed_kb_s: float
    ) -> None:
        """更新下载进度"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    UPDATE download_metrics 
                    SET downloaded_bytes=?, speed_kb_s=?, updated_at=CURRENT_TIMESTAMP 
                    WHERE id=?
                """, (downloaded_bytes, speed_kb_s, record_id))
                conn.commit()
            finally:
                conn.close()

    def complete_download_task(
        self,
        record_id: int,
        file_size_bytes: int,
        speed_kb_s: float,
        status: str = "completed"
    ) -> None:
        """完成下载任务"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    UPDATE download_metrics 
                    SET downloaded_bytes=?, speed_kb_s=?, status=?, updated_at=CURRENT_TIMESTAMP 
                    WHERE id=?
                """, (file_size_bytes, speed_kb_s, status, record_id))
                conn.commit()
            finally:
                conn.close()

    def get_download_metrics(
        self,
        hours: int = 24,
        limit: int = 100
    ) -> list[dict]:
        """获取下载指标"""
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("""
                    SELECT id, task_id, filename, file_size_bytes, downloaded_bytes, 
                           speed_kb_s, status, created_at, updated_at 
                    FROM download_metrics 
                    WHERE created_at >= ? 
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (cutoff_str, limit))
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

    # ==================== 上传指标 ====================

    def start_upload_task(
        self,
        filename: str,
        file_size_bytes: Optional[int] = None
    ) -> int:
        """开始记录上传任务"""
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("""
                    INSERT INTO upload_metrics 
                    (filename, file_size_bytes, status) 
                    VALUES (?, ?, 'uploading')
                """, (filename, file_size_bytes))
                conn.commit()
                return cursor.lastrowid
            finally:
                conn.close()

    def update_upload_progress(
        self,
        record_id: int,
        uploaded_bytes: int,
        speed_kb_s: float
    ) -> None:
        """更新上传进度"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    UPDATE upload_metrics 
                    SET uploaded_bytes=?, speed_kb_s=?, updated_at=CURRENT_TIMESTAMP 
                    WHERE id=?
                """, (uploaded_bytes, speed_kb_s, record_id))
                conn.commit()
            finally:
                conn.close()

    def complete_upload_task(
        self,
        record_id: int,
        file_size_bytes: int,
        speed_kb_s: float,
        status: str = "completed"
    ) -> None:
        """完成上传任务"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    UPDATE upload_metrics 
                    SET uploaded_bytes=?, speed_kb_s=?, status=?, updated_at=CURRENT_TIMESTAMP 
                    WHERE id=?
                """, (file_size_bytes, speed_kb_s, status, record_id))
                conn.commit()
            finally:
                conn.close()

    def get_upload_metrics(
        self,
        hours: int = 24,
        limit: int = 100
    ) -> list[dict]:
        """获取上传指标"""
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("""
                    SELECT id, filename, file_size_bytes, uploaded_bytes, 
                           speed_kb_s, status, created_at, updated_at 
                    FROM upload_metrics 
                    WHERE created_at >= ? 
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (cutoff_str, limit))
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

    # ==================== 系统指标 ====================

    def record_system_metrics(
        self,
        memory_percent: Optional[float] = None,
        cpu_percent: Optional[float] = None,
        active_connections: Optional[int] = None
    ) -> None:
        """记录系统指标"""
        with _db_lock:
            conn = self._get_connection()
            try:
                conn.execute("""
                    INSERT INTO system_metrics 
                    (memory_percent, cpu_percent, active_connections) 
                    VALUES (?, ?, ?)
                """, (memory_percent, cpu_percent, active_connections))
                conn.commit()
            finally:
                conn.close()

    def get_system_metrics(
        self,
        hours: int = 24,
        limit: int = 100
    ) -> list[dict]:
        """获取系统指标"""
        cutoff = datetime.now() - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()
        with _db_lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute("""
                    SELECT id, memory_percent, cpu_percent, active_connections, created_at 
                    FROM system_metrics 
                    WHERE created_at >= ? 
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (cutoff_str, limit))
                return [dict(row) for row in cursor.fetchall()]
            finally:
                conn.close()

    # ==================== 综合统计 ====================

    def get_dashboard_stats(self) -> dict:
        """获取看板统计数据"""
        with _db_lock:
            conn = self._get_connection()
            try:
                # 下载统计
                dl_stats = conn.execute("""
                    SELECT 
                        COUNT(*) as total_downloads,
                        COUNT(CASE WHEN status='completed' THEN 1 END) as completed_downloads,
                        COUNT(CASE WHEN status='downloading' THEN 1 END) as active_downloads,
                        AVG(CASE WHEN status='completed' THEN speed_kb_s END) as avg_dl_speed
                    FROM download_metrics 
                    WHERE created_at >= datetime('now', '-24 hours')
                """).fetchone()
                
                # 上传统计
                ul_stats = conn.execute("""
                    SELECT 
                        COUNT(*) as total_uploads,
                        COUNT(CASE WHEN status='completed' THEN 1 END) as completed_uploads,
                        COUNT(CASE WHEN status='uploading' THEN 1 END) as active_uploads,
                        AVG(CASE WHEN status='completed' THEN speed_kb_s END) as avg_ul_speed
                    FROM upload_metrics 
                    WHERE created_at >= datetime('now', '-24 hours')
                """).fetchone()
                
                # 最新系统指标
                latest_sys = conn.execute("""
                    SELECT memory_percent, cpu_percent, active_connections, created_at 
                    FROM system_metrics 
                    ORDER BY created_at DESC LIMIT 1
                """).fetchone()

                return {
                    "downloads": {
                        "total": dl_stats["total_downloads"],
                        "completed": dl_stats["completed_downloads"],
                        "active": dl_stats["active_downloads"],
                        "avg_speed_kb_s": dl_stats["avg_dl_speed"] or 0
                    },
                    "uploads": {
                        "total": ul_stats["total_uploads"],
                        "completed": ul_stats["completed_uploads"],
                        "active": ul_stats["active_uploads"],
                        "avg_speed_kb_s": ul_stats["avg_ul_speed"] or 0
                    },
                    "system": {
                        "memory_percent": latest_sys["memory_percent"] if latest_sys else 0,
                        "cpu_percent": latest_sys["cpu_percent"] if latest_sys else 0,
                        "active_connections": latest_sys["active_connections"] if latest_sys else 0,
                        "last_updated": latest_sys["created_at"] if latest_sys else None
                    }
                }
            finally:
                conn.close()


# 全局单例
_monitoring_db: Optional[MonitoringDB] = None


def get_monitoring_db(retention_days: int = 7) -> MonitoringDB:
    global _monitoring_db
    if _monitoring_db is None:
        _monitoring_db = MonitoringDB(retention_days=retention_days)
    return _monitoring_db
