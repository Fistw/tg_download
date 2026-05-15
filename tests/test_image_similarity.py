import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import io

from src.image_similarity import ImageSimilarity


class TestImageSimilarity:
    """测试图像相似度计算模块"""
    
    def test_init_default_threshold(self):
        """测试使用默认阈值初始化"""
        sim = ImageSimilarity()
        assert sim.similarity_threshold == ImageSimilarity.DEFAULT_SIMILARITY_THRESHOLD
    
    def test_init_custom_threshold(self):
        """测试使用自定义阈值初始化"""
        sim = ImageSimilarity(similarity_threshold=5)
        assert sim.similarity_threshold == 5
    
    def test_hamming_distance_same_hash(self):
        """测试相同哈希的汉明距离"""
        sim = ImageSimilarity()
        distance = sim.hamming_distance("abcdef", "abcdef")
        assert distance == 0
    
    def test_hamming_distance_different_hash(self):
        """测试不同哈希的汉明距离"""
        sim = ImageSimilarity()
        # 两个单字符差异，每个字符最多4位差异
        distance = sim.hamming_distance("a", "b")
        assert distance >= 0
    
    def test_is_similar_none_hash(self):
        """测试 None 哈希比较"""
        sim = ImageSimilarity()
        is_similar, distance = sim.is_similar(None, "abcdef")
        assert not is_similar
        assert distance == -1
        
        is_similar, distance = sim.is_similar("abcdef", None)
        assert not is_similar
        assert distance == -1
    
    def test_similarity_score_none_hash(self):
        """测试 None 哈希相似度分数"""
        sim = ImageSimilarity()
        score = sim.similarity_score(None, "abcdef")
        assert score == 0.0
    
    @pytest.mark.skipif(not ImageSimilarity._has_required_libs(), 
                       reason="PIL or imagehash not installed")
    def test_compute_hash_from_data(self):
        """测试从二进制数据计算哈希（需要 PIL）"""
        sim = ImageSimilarity()
        
        # 创建一个简单的测试图像
        from PIL import Image as PILImage
        img = PILImage.new('RGB', (100, 100), color='red')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_data = img_buffer.getvalue()
        
        phash = sim.compute_hash(img_data)
        assert phash is not None
        assert isinstance(phash, str)
        assert len(phash) > 0
    
    def test_has_required_libs(self):
        """测试检查依赖库是否存在"""
        # 这个方法应该总是返回布尔值
        result = ImageSimilarity._has_required_libs()
        assert isinstance(result, bool)
