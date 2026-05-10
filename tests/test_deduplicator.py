import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.deduplicator import Deduplicator
from src.database import DownloadDB


class TestDeduplicator:
    def test_create_task(self, tmp_path):
        """测试创建去重任务"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            client = None
            deduplicator = Deduplicator(client, db)
            
            task_id = deduplicator.create_task(chat_id=12345, chat_title="Test Chat")
            assert isinstance(task_id, int)
            assert task_id >= 1
            
            task = db.get_dedupe_task(task_id)
            assert task is not None
            assert task["chat_id"] == 12345
            assert task["chat_title"] == "Test Chat"
            assert task["status"] == "pending"
        finally:
            db.close()
    
    def test_pause_resume_scan(self, tmp_path):
        """测试暂停和恢复扫描"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            client = None
            deduplicator = Deduplicator(client, db)
            
            # 初始状态：_pause_event 应该是 set() 的
            assert deduplicator._pause_event.is_set() is True
            
            # 测试暂停
            deduplicator.pause_scan()
            assert deduplicator._pause_event.is_set() is False
            
            # 测试恢复
            deduplicator.resume_scan()
            assert deduplicator._pause_event.is_set() is True
        finally:
            db.close()
    
    def test_get_media_list_empty(self, tmp_path):
        """测试获取空媒体列表"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            client = None
            deduplicator = Deduplicator(client, db)
            
            task_id = deduplicator.create_task(chat_id=12345)
            media_list = deduplicator.get_media_list(task_id)
            assert isinstance(media_list, list)
            assert len(media_list) == 0
        finally:
            db.close()
    
    def test_get_media_list_with_data(self, tmp_path):
        """测试获取有数据的媒体列表"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            client = None
            deduplicator = Deduplicator(client, db)
            
            task_id = deduplicator.create_task(chat_id=12345)
            db.add_dedupe_media(task_id, file_id="file1")
            db.add_dedupe_media(task_id, file_id="file2")
            db.add_dedupe_media(task_id, file_id="file3")
            
            media_list = deduplicator.get_media_list(task_id)
            assert len(media_list) == 3
        finally:
            db.close()
    
    def test_get_media_list_pagination(self, tmp_path):
        """测试媒体列表分页"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            client = None
            deduplicator = Deduplicator(client, db)
            
            task_id = deduplicator.create_task(chat_id=12345)
            for i in range(25):
                db.add_dedupe_media(task_id, file_id=f"file_{i}")
            
            # 第一页，每页10条
            page1 = deduplicator.get_media_list(task_id, page=1, limit=10)
            assert len(page1) == 10
            
            # 第二页，每页10条
            page2 = deduplicator.get_media_list(task_id, page=2, limit=10)
            assert len(page2) == 10
            
            # 第三页，剩余5条
            page3 = deduplicator.get_media_list(task_id, page=3, limit=10)
            assert len(page3) == 5
        finally:
            db.close()
    
    def test_get_media_list_search(self, tmp_path):
        """测试媒体列表搜索"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            client = None
            deduplicator = Deduplicator(client, db)
            
            task_id = deduplicator.create_task(chat_id=12345)
            db.add_dedupe_media(task_id, file_id="abc_123")
            db.add_dedupe_media(task_id, file_id="abc_456")
            db.add_dedupe_media(task_id, file_id="def_789")
            
            results = deduplicator.get_media_list(task_id, search="abc")
            assert len(results) == 2
            assert all("abc" in m["file_id"] for m in results)
        finally:
            db.close()
    
    def test_get_media_list_filter(self, tmp_path):
        """测试媒体列表筛选"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            client = None
            deduplicator = Deduplicator(client, db)
            
            task_id = deduplicator.create_task(chat_id=12345)
            db.add_dedupe_media(task_id, file_id="single")
            db.add_dedupe_media(task_id, file_id="dup")
            db.add_dedupe_media(task_id, file_id="dup")
            
            singles = deduplicator.get_media_list(task_id, filter_type="singles")
            assert len(singles) == 1
            assert singles[0]["file_id"] == "single"
            
            duplicates = deduplicator.get_media_list(task_id, filter_type="duplicates")
            assert len(duplicates) == 1
            assert duplicates[0]["file_id"] == "dup"
        finally:
            db.close()
    
    @pytest.mark.asyncio
    async def test_download_media_single_file(self, tmp_path):
        """测试下载单个文件"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            # 创建模拟 client
            mock_client = AsyncMock()
            
            # 模拟一个视频消息
            mock_message = MagicMock()
            # 模拟 _is_video 会返回 True
            mock_client.get_messages.return_value = mock_message
            
            deduplicator = Deduplicator(mock_client, db)
            task_id = deduplicator.create_task(chat_id=12345)
            db.add_dedupe_media(task_id, file_id="test_file", first_seen_message_id=100)
            
            # 模拟 download_message 函数和 _is_video 函数
            with patch("src.deduplicator.download_message", new_callable=AsyncMock) as mock_download:
                with patch("src.deduplicator._is_video") as mock_is_video:
                    mock_download.return_value = "downloaded_file.mp4"
                    mock_is_video.return_value = True
                    
                    count = await deduplicator.download_media(
                        task_id,
                        output_dir=str(tmp_path / "output"),
                        file_id="test_file"
                    )
                    
                    assert count == 1
                    mock_client.get_messages.assert_called_once_with(12345, ids=100)
                    mock_download.assert_called_once()
        finally:
            db.close()
    
    @pytest.mark.asyncio
    async def test_download_media_nonexistent_task(self, tmp_path):
        """测试下载不存在的任务"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            mock_client = AsyncMock()
            deduplicator = Deduplicator(mock_client, db)
            
            with pytest.raises(ValueError, match="不存在"):
                await deduplicator.download_media(
                    999,
                    output_dir=str(tmp_path / "output"),
                    file_id="test_file"
                )
        finally:
            db.close()
    
    @pytest.mark.asyncio
    async def test_download_media_no_params(self, tmp_path):
        """测试没有提供下载参数"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            mock_client = AsyncMock()
            deduplicator = Deduplicator(mock_client, db)
            task_id = deduplicator.create_task(chat_id=12345)
            
            with pytest.raises(ValueError, match="必须指定"):
                await deduplicator.download_media(
                    task_id,
                    output_dir=str(tmp_path / "output")
                )
        finally:
            db.close()
