from __future__ import annotations

import io
import logging
from typing import Optional, Tuple
from pathlib import Path

try:
    from PIL import Image
    import imagehash
    HAS_IMAGE_LIBS = True
except ImportError:
    HAS_IMAGE_LIBS = False

logger = logging.getLogger(__name__)


class ImageSimilarity:
    """图像相似度计算类，基于感知哈希（dHash）"""
    
    # 默认阈值：汉明距离小于等于10认为是相似图片
    DEFAULT_SIMILARITY_THRESHOLD = 10
    
    @staticmethod
    def _has_required_libs() -> bool:
        """检查是否安装了必要的图像处理库"""
        return HAS_IMAGE_LIBS

    def __init__(self, similarity_threshold: int = DEFAULT_SIMILARITY_THRESHOLD):
        """
        初始化图像相似度计算器

        Args:
            similarity_threshold: 汉明距离阈值，小于等于该值认为相似
        """
        self.similarity_threshold = similarity_threshold
        if not HAS_IMAGE_LIBS:
            logger.warning(
                "PIL or imagehash not installed. "
                "Install with: pip install pillow imagehash"
            )

    def compute_hash(self, image_data: bytes) -> Optional[str]:
        """
        计算图像的dHash（差异哈希）

        Args:
            image_data: 图像二进制数据

        Returns:
            哈希字符串，如果失败返回None
        """
        if not HAS_IMAGE_LIBS:
            return None

        try:
            image = Image.open(io.BytesIO(image_data))
            # 转换为灰度图
            image = image.convert("L")
            # 计算dHash
            phash = imagehash.dhash(image)
            return str(phash)
        except Exception as e:
            logger.debug(f"Failed to compute image hash: {e}")
            return None

    def compute_hash_from_path(self, image_path: str | Path) -> Optional[str]:
        """
        从文件路径计算图像哈希

        Args:
            image_path: 图像文件路径

        Returns:
            哈希字符串，如果失败返回None
        """
        if not HAS_IMAGE_LIBS:
            return None

        try:
            with open(image_path, "rb") as f:
                return self.compute_hash(f.read())
        except Exception as e:
            logger.debug(f"Failed to read image file {image_path}: {e}")
            return None

    def hamming_distance(self, hash1: str, hash2: str) -> int:
        """
        计算两个哈希字符串的汉明距离

        Args:
            hash1: 第一个哈希字符串
            hash2: 第二个哈希字符串

        Returns:
            汉明距离
        """
        if len(hash1) != len(hash2):
            # 如果长度不同，返回最大可能距离
            return max(len(hash1), len(hash2)) * 4

        distance = 0
        for c1, c2 in zip(hash1, hash2):
            # 将16进制字符转换为整数
            try:
                n1 = int(c1, 16)
                n2 = int(c2, 16)
                # 计算异或后1的个数
                distance += bin(n1 ^ n2).count("1")
            except ValueError:
                distance += 4  # 无效字符，算作最大差异

        return distance

    def is_similar(
        self, hash1: Optional[str], hash2: Optional[str]
    ) -> Tuple[bool, int]:
        """
        判断两个哈希是否相似

        Args:
            hash1: 第一个哈希
            hash2: 第二个哈希

        Returns:
            (是否相似, 汉明距离)
        """
        if hash1 is None or hash2 is None:
            return False, -1

        distance = self.hamming_distance(hash1, hash2)
        return distance <= self.similarity_threshold, distance

    def similarity_score(
        self, hash1: Optional[str], hash2: Optional[str]
    ) -> float:
        """
        计算相似度分数 (0.0 - 1.0)

        Args:
            hash1: 第一个哈希
            hash2: 第二个哈希

        Returns:
            相似度分数，1.0表示完全相同
        """
        if hash1 is None or hash2 is None:
            return 0.0

        distance = self.hamming_distance(hash1, hash2)
        # dHash通常是64位（16个16进制字符），最大可能距离是64
        max_distance = 64.0
        return max(0.0, 1.0 - (distance / max_distance))
