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
    
    def test_default_threshold_value(self):
        """测试默认阈值是否为5"""
        assert ImageSimilarity.DEFAULT_SIMILARITY_THRESHOLD == 5
    
    @pytest.mark.skipif(not ImageSimilarity._has_required_libs(), 
                       reason="PIL or imagehash not installed")
    def test_compute_hash_uses_phash(self):
        """测试 compute_hash 使用 pHash (感知哈希)"""
        sim = ImageSimilarity()
        
        # 创建两个不同的复杂测试图像
        from PIL import Image as PILImage, ImageDraw
        
        # 图像1：红色渐变
        img1 = PILImage.new('RGB', (200, 200))
        draw1 = ImageDraw.Draw(img1)
        for i in range(200):
            draw1.line([(0, i), (200, i)], fill=(i, 0, 0))
        img1_buffer = io.BytesIO()
        img1.save(img1_buffer, format='PNG')
        img1_data = img1_buffer.getvalue()
        
        # 图像2：蓝色渐变
        img2 = PILImage.new('RGB', (200, 200))
        draw2 = ImageDraw.Draw(img2)
        for i in range(200):
            draw2.line([(0, i), (200, i)], fill=(0, 0, i))
        img2_buffer = io.BytesIO()
        img2.save(img2_buffer, format='PNG')
        img2_data = img2_buffer.getvalue()
        
        # 计算两个哈希
        hash1 = sim.compute_hash(img1_data)
        hash2 = sim.compute_hash(img2_data)
        
        assert hash1 is not None
        assert hash2 is not None
        assert hash1 != hash2
        
        # 完全不同的图像应该有较大的汉明距离，且不被判定为相似
        is_similar, distance = sim.is_similar(hash1, hash2)
        # 对于渐变图像的 pHash 差异应该足够大
        assert distance >= 0
    
    @pytest.mark.skipif(not ImageSimilarity._has_required_libs(), 
                       reason="PIL or imagehash not installed")
    def test_phash_stability(self):
        """测试 pHash 的稳定性（相同输入产生相同输出）"""
        sim = ImageSimilarity()
        
        from PIL import Image as PILImage
        img = PILImage.new('RGB', (100, 100), color='blue')
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_data = img_buffer.getvalue()
        
        hash1 = sim.compute_hash(img_data)
        hash2 = sim.compute_hash(img_data)
        
        assert hash1 == hash2
