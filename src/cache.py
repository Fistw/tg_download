from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CleanupResult:
    """清理结果"""
    deleted_files: List[Path]
    total_freed_bytes: int
    dir_size_before: int
    dir_size_after: int
    reason: str = ""


def get_dir_size(dir_path: Path) -> int:
    """计算目录总大小（字节）"""
    total_size = 0
    if not dir_path.exists() or not dir_path.is_dir():
        return total_size
    
    for file in dir_path.rglob("*"):
        if file.is_file():
            try:
                total_size += file.stat().st_size
            except Exception as e:
                logger.warning(f"无法获取文件大小 {file}: {e}")
    return total_size


def scan_cache_dir(dir_path: Path) -> List[Path]:
    """扫描缓存目录，返回所有文件列表"""
    if not dir_path.exists() or not dir_path.is_dir():
        return []
    
    files = []
    for file in dir_path.rglob("*"):
        if file.is_file():
            files.append(file)
    return files


def cleanup_cache(
    dir_path: Path,
    retention_days: int = 3,
    max_size_gb: float = 8.0,
    dry_run: bool = False,
) -> CleanupResult:
    """
    清理缓存目录
    
    Args:
        dir_path: 缓存目录路径
        retention_days: 保留天数
        max_size_gb: 最大缓存大小（GB）
        dry_run: 是否预览模式
    
    Returns:
        CleanupResult 对象
    """
    # 确保目录存在
    if not dir_path.exists() or not dir_path.is_dir():
        logger.info(f"缓存目录不存在或不是目录: {dir_path}")
        return CleanupResult(
            deleted_files=[],
            total_freed_bytes=0,
            dir_size_before=0,
            dir_size_after=0,
            reason="目录不存在",
        )
    
    # 获取初始大小
    size_before = get_dir_size(dir_path)
    max_size_bytes = int(max_size_gb * (1024 ** 3))
    
    logger.info(f"开始清理缓存: {dir_path}")
    logger.info(f"  保留天数: {retention_days} 天")
    logger.info(f"  最大大小: {max_size_gb:.2f} GB ({max_size_bytes:,} bytes)")
    logger.info(f"  当前大小: {size_before / (1024 ** 3):.2f} GB ({size_before:,} bytes)")
    
    # 1. 扫描并按修改时间排序
    files = scan_cache_dir(dir_path)
    files_with_time = []
    for file in files:
        try:
            mtime = file.stat().st_mtime
            files_with_time.append((mtime, file))
        except Exception as e:
            logger.warning(f"无法获取文件时间 {file}: {e}")
    
    # 按修改时间排序，最早的在前
    files_with_time.sort(key=lambda x: x[0])
    
    # 计算当前时间，确定删除阈值
    now = time.time()
    retention_seconds = retention_days * 24 * 60 * 60
    cutoff_time = now - retention_seconds
    
    # 2. 第一步：删除超过保留天数的文件
    to_delete = []
    remaining = []
    total_to_free = 0
    
    logger.info(f"第一步：删除超过 {retention_days} 天的文件")
    for mtime, file in files_with_time:
        if mtime < cutoff_time:
            try:
                file_size = file.stat().st_size
                logger.info(f"  标记删除: {file.name} ({file_size / (1024 ** 2):.2f} MB) - 超过 {retention_days} 天")
                to_delete.append(file)
                total_to_free += file_size
            except Exception as e:
                logger.warning(f"无法读取文件 {file}: {e}")
                remaining.append((mtime, file))
        else:
            remaining.append((mtime, file))
    
    # 3. 第二步：如果仍然超过大小限制，继续删除最早的文件
    if total_to_free > 0:
        # 估算删除后的大小
        estimated_size_after = size_before - total_to_free
    else:
        estimated_size_after = size_before
    
    if estimated_size_after > max_size_bytes:
        logger.info(f"第二步：仍超过大小限制，继续删除最早的文件")
        need_to_free = estimated_size_after - max_size_bytes
        freed_so_far = 0
        
        for mtime, file in remaining:
            if freed_so_far >= need_to_free:
                break
            try:
                file_size = file.stat().st_size
                logger.info(f"  标记删除: {file.name} ({file_size / (1024 ** 2):.2f} MB) - 空间不足")
                to_delete.append(file)
                total_to_free += file_size
                freed_so_far += file_size
            except Exception as e:
                logger.warning(f"无法读取文件 {file}: {e}")
    
    # 4. 执行删除
    deleted = []
    freed = 0
    if not dry_run:
        for file in to_delete:
            try:
                file_size = file.stat().st_size
                logger.info(f"  删除文件: {file}")
                file.unlink()
                deleted.append(file)
                freed += file_size
            except Exception as e:
                logger.error(f"删除文件失败 {file}: {e}")
    else:
        logger.info(f"  预览模式：不实际删除文件")
        deleted = to_delete.copy()
        freed = total_to_free
    
    # 获取最终大小
    size_after = get_dir_size(dir_path) if not dry_run else max(0, size_before - freed)
    
    logger.info(f"清理完成!")
    logger.info(f"  删除文件数: {len(deleted)}")
    logger.info(f"  释放空间: {freed / (1024 ** 3):.2f} GB ({freed:,} bytes)")
    logger.info(f"  最终大小: {size_after / (1024 ** 3):.2f} GB ({size_after:,} bytes)")
    
    reason = f"清理了 {len(deleted)} 个文件，释放 {freed / (1024 ** 3):.2f} GB"
    
    return CleanupResult(
        deleted_files=deleted,
        total_freed_bytes=freed,
        dir_size_before=size_before,
        dir_size_after=size_after,
        reason=reason,
    )
