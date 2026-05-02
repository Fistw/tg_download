from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
import pytest

from src.cache import cleanup_cache, get_dir_size, scan_cache_dir, CleanupResult


class TestCacheCleanup:
    """缓存清理功能测试"""

    def test_empty_directory(self):
        """测试空目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = cleanup_cache(Path(tmpdir), retention_days=7, max_size_gb=10.0)
            assert len(result.deleted_files) == 0
            assert result.total_freed_bytes == 0
            assert result.dir_size_before == 0
            assert result.dir_size_after == 0

    def test_single_file_under_retention(self):
        """测试单个文件，在保留天数内"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # 创建一个测试文件
            test_file = tmp_path / "test.mp4"
            with test_file.open("wb") as f:
                f.write(b"x" * 1024 * 1024)  # 1MB
            
            # 清理（文件还在保留期内）
            result = cleanup_cache(tmp_path, retention_days=7, max_size_gb=10.0)
            assert len(result.deleted_files) == 0
            assert test_file.exists()

    def test_single_file_over_retention(self):
        """测试单个文件，超过保留天数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            test_file = tmp_path / "test.mp4"
            with test_file.open("wb") as f:
                f.write(b"x" * 1024 * 1024)
            
            # 修改文件时间到 8 天前
            eight_days_ago = time.time() - 8 * 24 * 60 * 60
            os.utime(test_file, (eight_days_ago, eight_days_ago))
            
            # 清理
            result = cleanup_cache(tmp_path, retention_days=7, max_size_gb=10.0)
            assert len(result.deleted_files) == 1
            assert not test_file.exists()

    def test_multiple_files_over_retention(self):
        """测试多个超过保留天数的文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            
            # 创建 3 个文件
            for i in range(3):
                test_file = tmp_path / f"test{i}.mp4"
                with test_file.open("wb") as f:
                    f.write(b"x" * 1024 * 1024)  # 1MB
                
                # 修改时间到 8 天前
                eight_days_ago = time.time() - 8 * 24 * 60 * 60
                os.utime(test_file, (eight_days_ago, eight_days_ago))
            
            # 清理
            result = cleanup_cache(tmp_path, retention_days=7, max_size_gb=10.0)
            assert len(result.deleted_files) == 3
            for i in range(3):
                assert not (tmp_path / f"test{i}.mp4").exists()

    def test_max_size_limit(self):
        """测试最大大小限制"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # 创建 10 个 1MB 的文件（总共 10MB）
            files = []
            for i in range(10):
                test_file = tmp_path / f"test{i}.mp4"
                with test_file.open("wb") as f:
                    f.write(b"x" * 1024 * 1024)  # 1MB
                files.append(test_file)
                
                # 修改时间，让文件有不同的年龄（最早的文件有更早的时间）
                days_ago = 10 - i
                file_time = time.time() - days_ago * 24 * 60 * 60
                os.utime(test_file, (file_time, file_time))
            
            # 设置最大大小为 5MB（需要删除 5 个文件）
            result = cleanup_cache(tmp_path, retention_days=100, max_size_gb=0.005)  # ~5MB
            
            assert len(result.deleted_files) == 5
            # 应该删除最早的 5 个文件（test0 - test4）
            for i in range(5):
                assert not (tmp_path / f"test{i}.mp4").exists()
            # 应该保留最新的 5 个文件
            for i in range(5, 10):
                assert (tmp_path / f"test{i}.mp4").exists()

    def test_dry_run(self):
        """测试 dry-run 模式"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            test_file = tmp_path / "test.mp4"
            with test_file.open("wb") as f:
                f.write(b"x" * 1024 * 1024)
            
            eight_days_ago = time.time() - 8 * 24 * 60 * 60
            os.utime(test_file, (eight_days_ago, eight_days_ago))
            
            # 预览模式
            result = cleanup_cache(tmp_path, retention_days=7, max_size_gb=10.0, dry_run=True)
            assert len(result.deleted_files) == 1  # 标记删除但不实际删除
            assert test_file.exists()  # 文件还在

    def test_get_dir_size(self):
        """测试计算目录大小"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            total_size = 0
            for i in range(3):
                test_file = tmp_path / f"test{i}.mp4"
                file_size = 1024 * 1024  # 1MB
                with test_file.open("wb") as f:
                    f.write(b"x" * file_size)
                total_size += file_size
            
            assert get_dir_size(tmp_path) == total_size

    def test_scan_cache_dir(self):
        """测试扫描缓存目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            # 创建文件
            for i in range(3):
                test_file = tmp_path / f"test{i}.mp4"
                with test_file.open("wb") as f:
                    f.write(b"x" * 1024)
            
            files = scan_cache_dir(tmp_path)
            assert len(files) == 3


class TestCacheConfig:
    """缓存配置测试"""

    def test_cache_config_defaults(self):
        """测试缓存配置的默认值"""
        from src.config import DownloadConfig
        
        config = DownloadConfig()
        assert config.enable_cache_cleanup is True
        assert config.cache_retention_days == 3
        assert config.max_cache_size_gb == 8.0
