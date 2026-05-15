import pytest
from pathlib import Path

from src.database import DownloadDB
from src.deduplicator import Deduplicator


class TestTwoLevelDedupe:
    """测试两层去重功能"""
    
    def test_add_and_get_dedupe_level1(self, tmp_path):
        """测试添加和获取第一层去重结果"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = 1
            
            # 添加一些测试媒体
            db.add_dedupe_media(task_id, "file1", first_seen_message_id=100)
            db.add_dedupe_media(task_id, "file1", first_seen_message_id=200)
            db.add_dedupe_media(task_id, "file2", first_seen_message_id=150)
            
            # 获取刚添加的媒体ID
            media_list, _ = db.get_dedupe_media_list(task_id)
            media_ids = [m['id'] for m in media_list]
            
            # 添加第一层去重结果
            group_id = "file1"
            primary_media_id = media_ids[0]
            db.add_dedupe_level1(task_id, group_id, primary_media_id, media_ids[:2])
            
            # 获取第一层去重结果
            level1 = db.get_dedupe_level1(task_id)
            
            assert len(level1) == 1
            assert level1[0]['group_id'] == group_id
            assert level1[0]['primary_media_id'] == primary_media_id
            assert len(level1[0]['media_ids']) == 2
            
        finally:
            db.close()
    
    def test_add_and_get_dedupe_level2(self, tmp_path):
        """测试添加和获取第二层去重结果"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = 1
            
            # 添加第二层去重结果
            group_id = "level2_group_0"
            primary_group_id = "group1"
            level1_group_ids = ["group1", "group2", "group3"]
            similarity_score = 0.95
            hamming_distance = 5
            
            db.add_dedupe_level2(
                task_id, group_id, primary_group_id, level1_group_ids,
                similarity_score, hamming_distance
            )
            
            # 获取第二层去重结果
            level2 = db.get_dedupe_level2(task_id)
            
            assert len(level2) == 1
            assert level2[0]['group_id'] == group_id
            assert level2[0]['primary_level1_group_id'] == primary_group_id
            assert level2[0]['level1_group_ids'] == level1_group_ids
            assert level2[0]['similarity_score'] == pytest.approx(0.95)
            assert level2[0]['hamming_distance'] == 5
            
        finally:
            db.close()
    
    def test_clear_dedupe_results(self, tmp_path):
        """测试清除去重结果"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = 1
            
            # 添加一些去重结果
            db.add_dedupe_level1(task_id, "group1", 1, [1, 2])
            db.add_dedupe_level2(task_id, "l2g1", "group1", ["group1", "group2"])
            
            # 清除结果
            db.clear_dedupe_results(task_id)
            
            # 验证已清除
            assert len(db.get_dedupe_level1(task_id)) == 0
            assert len(db.get_dedupe_level2(task_id)) == 0
            
        finally:
            db.close()
    
    def test_deduplicator_level1_dedupe(self, tmp_path):
        """测试 Deduplicator 的第一层去重"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            deduplicator = Deduplicator(None, db)
            task_id = deduplicator.create_task(chat_id=12345)
            
            # 添加测试媒体（包含重复 file_id）
            db.add_dedupe_media(task_id, "file_a", first_seen_message_id=100)
            db.add_dedupe_media(task_id, "file_a", first_seen_message_id=200)
            db.add_dedupe_media(task_id, "file_a", first_seen_message_id=300)
            db.add_dedupe_media(task_id, "file_b", first_seen_message_id=150)
            db.add_dedupe_media(task_id, "file_b", first_seen_message_id=250)
            db.add_dedupe_media(task_id, "file_c", first_seen_message_id=180)
            
            # 运行第一层去重
            group_count = deduplicator.run_level1_dedupe(task_id)
            
            # 应该有3个组：file_a, file_b, file_c
            assert group_count == 3
            
            # 验证结果
            level1 = db.get_dedupe_level1(task_id)
            assert len(level1) == 3
            
        finally:
            db.close()
    
    def test_update_media_phash(self, tmp_path):
        """测试更新媒体 phash"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = 1
            file_id = "test_file"
            
            # 添加测试媒体
            db.add_dedupe_media(task_id, file_id)
            
            # 更新 phash
            test_phash = "abcdef123456"
            db.update_media_phash(task_id, file_id, test_phash)
            
            # 获取并验证
            media = db.get_dedupe_media(task_id, file_id)
            assert media is not None
            assert media['phash'] == test_phash
            
        finally:
            db.close()
    
    def test_get_media_with_phash(self, tmp_path):
        """测试获取有 phash 的媒体"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = 1
            
            # 添加一些媒体，部分有 phash
            db.add_dedupe_media(task_id, "file1", phash="hash1")
            db.add_dedupe_media(task_id, "file2")
            db.add_dedupe_media(task_id, "file3", phash="hash3")
            
            # 获取有 phash 的媒体
            media_with_phash = db.get_media_with_phash(task_id)
            
            assert len(media_with_phash) == 2
            file_ids = {m['file_id'] for m in media_with_phash}
            assert file_ids == {"file1", "file3"}
            
        finally:
            db.close()
