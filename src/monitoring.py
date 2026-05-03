from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

__all__ = ["DownloadSpeedMonitor", "DownloadMetrics"]


@dataclass
class DownloadMetrics:
    """下载指标数据类。"""
    total_bytes: int = 0
    downloaded_bytes: int = 0
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    current_speed: float = 0.0
    average_speed: float = 0.0
    peak_speed: float = 0.0
    sliding_avg_speed: float = 0.0


class DownloadSpeedMonitor:
    """下载速度监控器。

    实时监控下载速度，计算瞬时速度、平均速度、峰值速度和滑动窗口平均速度。
    """

    def __init__(
        self,
        window_seconds: float = 5.0,
        sample_count: int = 10,
    ) -> None:
        """
        Args:
            window_seconds: 滑动窗口的大小（秒）
            sample_count: 滑动窗口中保留的样本数量
        """
        self._window_seconds = window_seconds
        self._sample_count = sample_count

        self._metrics = DownloadMetrics()
        self._speed_samples: Deque[tuple[float, float]] = deque(maxlen=sample_count)
        self._last_update_time: Optional[float] = None
        self._last_downloaded_bytes: int = 0

    @property
    def metrics(self) -> DownloadMetrics:
        """获取当前下载指标。"""
        return self._metrics

    def start(self, total_bytes: int) -> None:
        """开始监控。

        Args:
            total_bytes: 文件总大小
        """
        self._metrics = DownloadMetrics()
        self._metrics.total_bytes = total_bytes
        self._metrics.start_time = time.time()
        self._speed_samples.clear()
        self._last_update_time = self._metrics.start_time
        self._last_downloaded_bytes = 0

    def update(self, downloaded_bytes: int) -> None:
        """更新下载进度。

        Args:
            downloaded_bytes: 当前已下载的字节数
        """
        now = time.time()

        self._metrics.downloaded_bytes = downloaded_bytes

        # 计算瞬时速度
        if self._last_update_time is not None and self._last_downloaded_bytes < downloaded_bytes:
            time_delta = now - self._last_update_time
            bytes_delta = downloaded_bytes - self._last_downloaded_bytes
            if time_delta > 0:
                self._metrics.current_speed = bytes_delta / time_delta
                self._speed_samples.append((now, self._metrics.current_speed))

                # 更新峰值速度
                if self._metrics.current_speed > self._metrics.peak_speed:
                    self._metrics.peak_speed = self._metrics.current_speed

        # 更新平均速度
        if self._metrics.start_time is not None:
            elapsed = now - self._metrics.start_time
            if elapsed > 0:
                self._metrics.average_speed = downloaded_bytes / elapsed

        # 计算滑动窗口平均速度
        self._update_sliding_avg(now)

        # 更新状态
        self._last_update_time = now
        self._last_downloaded_bytes = downloaded_bytes

    def finish(self) -> None:
        """结束监控。"""
        self._metrics.end_time = time.time()
        if self._metrics.start_time is not None:
            elapsed = self._metrics.end_time - self._metrics.start_time
            if elapsed > 0 and self._metrics.downloaded_bytes > 0:
                self._metrics.average_speed = self._metrics.downloaded_bytes / elapsed
                self._metrics.sliding_avg_speed = self._metrics.average_speed

    def _update_sliding_avg(self, current_time: float) -> None:
        """更新滑动窗口平均速度。

        Args:
            current_time: 当前时间
        """
        cutoff_time = current_time - self._window_seconds

        # 清理旧的样本
        while self._speed_samples and self._speed_samples[0][0] < cutoff_time:
            self._speed_samples.popleft()

        if not self._speed_samples:
            self._metrics.sliding_avg_speed = 0.0
            return

        # 计算加权平均
        total_weight = 0.0
        weighted_sum = 0.0

        for sample_time, speed in self._speed_samples:
            weight = sample_time - cutoff_time
            total_weight += weight
            weighted_sum += speed * weight

        if total_weight > 0:
            self._metrics.sliding_avg_speed = weighted_sum / total_weight
        else:
            self._metrics.sliding_avg_speed = 0.0

    def reset(self) -> None:
        """重置监控器。"""
        self._metrics = DownloadMetrics()
        self._speed_samples.clear()
        self._last_update_time = None
        self._last_downloaded_bytes = 0

    @staticmethod
    def format_speed(speed: float) -> str:
        """格式化速度为可读字符串。

        Args:
            speed: 速度（字节/秒）

        Returns:
            格式化的速度字符串
        """
        if speed <= 0:
            return "0 B/s"

        units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
        unit_index = 0
        scaled_speed = speed

        while scaled_speed >= 1024 and unit_index < len(units) - 1:
            scaled_speed /= 1024
            unit_index += 1

        return f"{scaled_speed:.2f} {units[unit_index]}"
