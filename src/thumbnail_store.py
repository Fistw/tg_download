from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class ThumbnailStore:
    """缩略图文件存储管理类。"""

    def __init__(self, base_dir: str | Path = "thumbnails") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, task_id: int, file_id: str) -> Path:
        """
        获取缩略图的存储路径。
        使用二级目录结构避免单个目录文件过多：
        base_dir/task_id_short_hash/file_id_short_hash.jpg
        """
        # 为任务ID创建短哈希作为一级目录
        task_hash = hashlib.md5(str(task_id).encode()).hexdigest()[:8]
        # 为文件ID创建短哈希作为文件名
        file_hash = hashlib.md5(file_id.encode()).hexdigest()[:16]
        
        task_dir = self.base_dir / task_hash
        task_dir.mkdir(exist_ok=True)
        
        return task_dir / f"{file_hash}.jpg"

    def save(self, task_id: int, file_id: str, data: bytes) -> str:
        """
        保存缩略图到文件系统。
        
        Args:
            task_id: 去重任务ID
            file_id: Telegram文件ID
            data: 缩略图二进制数据
            
        Returns:
            相对存储路径（用于数据库存储）
        """
        file_path = self._get_path(task_id, file_id)
        
        try:
            with open(file_path, "wb") as f:
                f.write(data)
            
            # 返回相对路径（相对于base_dir）
            relative_path = file_path.relative_to(self.base_dir)
            return str(relative_path)
        except Exception as e:
            logger.error(f"保存缩略图失败 {task_id}/{file_id}: {e}")
            raise

    def load(self, relative_path: str) -> Optional[bytes]:
        """
        从文件系统加载缩略图。
        
        Args:
            relative_path: 相对存储路径
            
        Returns:
            缩略图二进制数据，如果文件不存在返回None
        """
        if not relative_path:
            return None
            
        try:
            file_path = self.base_dir / relative_path
            if not file_path.exists():
                logger.warning(f"缩略图文件不存在: {file_path}")
                return None
                
            with open(file_path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.error(f"加载缩略图失败 {relative_path}: {e}")
            return None

    def delete(self, relative_path: str) -> bool:
        """
        删除缩略图文件。
        
        Args:
            relative_path: 相对存储路径
            
        Returns:
            是否成功删除
        """
        if not relative_path:
            return False
            
        try:
            file_path = self.base_dir / relative_path
            if file_path.exists():
                file_path.unlink()
                logger.debug(f"删除缩略图: {file_path}")
                return True
            return False
        except Exception as e:
            logger.error(f"删除缩略图失败 {relative_path}: {e}")
            return False

    def delete_task_thumbnails(self, task_id: int) -> int:
        """
        删除指定任务的所有缩略图。
        
        Args:
            task_id: 去重任务ID
            
        Returns:
            删除的文件数量
        """
        task_hash = hashlib.md5(str(task_id).encode()).hexdigest()[:8]
        task_dir = self.base_dir / task_hash
        
        if not task_dir.exists():
            return 0
            
        count = 0
        try:
            for file_path in task_dir.glob("*.jpg"):
                file_path.unlink()
                count += 1
            
            # 尝试删除空目录
            try:
                task_dir.rmdir()
            except OSError:
                # 目录不为空，忽略
                pass
                
            logger.info(f"删除任务 {task_id} 的 {count} 个缩略图")
            return count
        except Exception as e:
            logger.error(f"删除任务缩略图失败 {task_id}: {e}")
            return count

    def get_size(self, relative_path: str) -> Optional[int]:
        """
        获取缩略图文件大小。
        
        Args:
            relative_path: 相对存储路径
            
        Returns:
            文件大小（字节），如果不存在返回None
        """
        if not relative_path:
            return None
            
        try:
            file_path = self.base_dir / relative_path
            if file_path.exists():
                return file_path.stat().st_size
            return None
        except Exception as e:
            logger.error(f"获取缩略图大小失败 {relative_path}: {e}")
            return None
