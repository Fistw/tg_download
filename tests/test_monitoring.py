import time
import pytest
from src.monitoring import DownloadSpeedMonitor, DownloadMetrics


class TestDownloadMetrics:
    """测试 DownloadMetrics 数据类。"""

    def test_default_values(self):
        """测试默认值。"""
        metrics = DownloadMetrics()
        assert metrics.total_bytes == 0
        assert metrics.downloaded_bytes == 0
        assert metrics.start_time is None
        assert metrics.end_time is None
        assert metrics.current_speed == 0.0
        assert metrics.average_speed == 0.0
        assert metrics.peak_speed == 0.0
        assert metrics.sliding_avg_speed == 0.0


class TestDownloadSpeedMonitor:
    """测试 DownloadSpeedMonitor 类。"""

    def test_start(self):
        """测试 start 方法。"""
        monitor = DownloadSpeedMonitor()
        monitor.start(1024 * 1024)  # 1 MB
        assert monitor.metrics.total_bytes == 1024 * 1024
        assert monitor.metrics.downloaded_bytes == 0
        assert monitor.metrics.start_time is not None

    def test_update_single_progress(self):
        """测试更新单个下载进度。"""
        monitor = DownloadSpeedMonitor(window_seconds=10)
        monitor.start(1024 * 1024)
        time.sleep(0.05)  # 小延迟
        monitor.update(512 * 1024)
        assert monitor.metrics.downloaded_bytes == 512 * 1024
        assert monitor.metrics.current_speed > 0
        assert monitor.metrics.average_speed > 0

    def test_peak_speed(self):
        """测试峰值速度记录。"""
        monitor = DownloadSpeedMonitor(window_seconds=10)
        monitor.start(1024 * 1024)
        monitor.update(100000)  # 第一次更新
        first_peak = monitor.metrics.peak_speed
        time.sleep(0.01)
        monitor.update(500000)  # 更快的更新
        assert monitor.metrics.peak_speed >= first_peak

    def test_finish(self):
        """测试 finish 方法。"""
        monitor = DownloadSpeedMonitor()
        monitor.start(1024 * 1024)
        monitor.update(512 * 1024)
        monitor.finish()
        assert monitor.metrics.end_time is not None
        assert monitor.metrics.end_time > monitor.metrics.start_time

    def test_reset(self):
        """测试 reset 方法。"""
        monitor = DownloadSpeedMonitor()
        monitor.start(1024 * 1024)
        monitor.update(512 * 1024)
        monitor.reset()
        assert monitor.metrics.total_bytes == 0
        assert monitor.metrics.downloaded_bytes == 0
        assert monitor.metrics.start_time is None

    def test_format_speed(self):
        """测试速度格式化。"""
        assert DownloadSpeedMonitor.format_speed(0) == "0 B/s"
        assert DownloadSpeedMonitor.format_speed(500) == "500.00 B/s"
        assert DownloadSpeedMonitor.format_speed(2048) == "2.00 KB/s"
        assert DownloadSpeedMonitor.format_speed(2048 * 1024) == "2.00 MB/s"

    def test_sliding_window_avg(self):
        """测试滑动窗口平均速度。"""
        monitor = DownloadSpeedMonitor(window_seconds=5, sample_count=5)
        monitor.start(1024 * 1024)
        monitor.update(10000)
        time.sleep(0.02)
        monitor.update(20000)
        time.sleep(0.02)
        monitor.update(30000)
        assert monitor.metrics.sliding_avg_speed >= 0

    def test_multiple_updates(self):
        """测试多次更新。"""
        monitor = DownloadSpeedMonitor(window_seconds=10)
        monitor.start(1024 * 1024)

        bytes_list = [10000, 50000, 100000, 200000, 500000]
        for b in bytes_list:
            time.sleep(0.01)
            monitor.update(b)

        assert monitor.metrics.downloaded_bytes == 500000
        assert monitor.metrics.peak_speed > 0
        assert monitor.metrics.average_speed > 0
