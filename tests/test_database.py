import pytest

from src.database import DownloadDB, DownloadHistory


class TestCreateAndGetTask:
    def test_create_task_returns_id(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_task("chan", 1, source="cli")
            assert isinstance(task_id, int)
            assert task_id >= 1
        finally:
            db.close()

    def test_get_task_returns_dict(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            task = db.get_task("chan", 1)
            assert task is not None
            assert task["channel"] == "chan"
            assert task["message_id"] == 1
            assert task["status"] == "queued"
            assert task["source"] == "cli"
        finally:
            db.close()

    def test_get_task_not_found(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            assert db.get_task("chan", 999) is None
        finally:
            db.close()

    def test_create_task_with_optional_fields(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1, source="bot", filename="v.mp4", file_size=1024)
            task = db.get_task("chan", 1)
            assert task["filename"] == "v.mp4"
            assert task["file_size"] == 1024
            assert task["source"] == "bot"
        finally:
            db.close()


class TestUpdateStatus:
    def test_update_status(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.update_status("chan", 1, "downloading")
            task = db.get_task("chan", 1)
            assert task["status"] == "downloading"
        finally:
            db.close()

    def test_update_status_with_error(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.update_status("chan", 1, "failed", error_message="timeout")
            task = db.get_task("chan", 1)
            assert task["status"] == "failed"
            assert task["error_message"] == "timeout"
        finally:
            db.close()

    def test_update_status_with_filename_and_size(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.update_status("chan", 1, "completed", filename="out.mp4", file_size=2048)
            task = db.get_task("chan", 1)
            assert task["status"] == "completed"
            assert task["filename"] == "out.mp4"
            assert task["file_size"] == 2048
        finally:
            db.close()


class TestDeduplication:
    def test_completed_task_returns_minus_one(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.update_status("chan", 1, "completed")
            result = db.create_task("chan", 1)
            assert result == -1
        finally:
            db.close()

    def test_failed_task_resets_to_queued(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_task("chan", 1)
            db.update_status("chan", 1, "failed", error_message="err")
            retry_id = db.create_task("chan", 1)
            assert retry_id == task_id
            task = db.get_task("chan", 1)
            assert task["status"] == "queued"
            assert task["error_message"] is None
        finally:
            db.close()

    def test_queued_task_returns_existing_id(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            id1 = db.create_task("chan", 1)
            id2 = db.create_task("chan", 1)
            assert id1 == id2
        finally:
            db.close()


class TestIsDownloaded:
    def test_not_downloaded(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            assert db.is_downloaded("chan", 1) is False
        finally:
            db.close()

    def test_queued_not_counted(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            assert db.is_downloaded("chan", 1) is False
        finally:
            db.close()

    def test_completed_is_downloaded(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.update_status("chan", 1, "completed")
            assert db.is_downloaded("chan", 1) is True
        finally:
            db.close()


class TestListTasks:
    def test_list_all(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.create_task("chan", 2)
            tasks = db.list_tasks()
            assert len(tasks) == 2
        finally:
            db.close()

    def test_filter_by_status(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.create_task("chan", 2)
            db.update_status("chan", 2, "completed")
            queued = db.list_tasks(status="queued")
            completed = db.list_tasks(status="completed")
            assert len(queued) == 1
            assert queued[0]["message_id"] == 1
            assert len(completed) == 1
            assert completed[0]["message_id"] == 2
        finally:
            db.close()

    def test_limit(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            for i in range(5):
                db.create_task("chan", i)
            tasks = db.list_tasks(limit=3)
            assert len(tasks) == 3
        finally:
            db.close()


class TestRecord:
    def test_record_creates_completed(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.record("chan", 1, "file.mp4", 1024)
            assert db.is_downloaded("chan", 1) is True
            task = db.get_task("chan", 1)
            assert task["filename"] == "file.mp4"
            assert task["file_size"] == 1024
            assert task["status"] == "completed"
        finally:
            db.close()

    def test_record_updates_existing(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.record("chan", 1, "file.mp4", 2048)
            task = db.get_task("chan", 1)
            assert task["status"] == "completed"
            assert task["filename"] == "file.mp4"
        finally:
            db.close()

    def test_record_duplicate_no_error(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.record("chan", 1, "file.mp4", 1024)
            db.record("chan", 1, "file2.mp4", 2048)
            task = db.get_task("chan", 1)
            assert task["filename"] == "file2.mp4"
        finally:
            db.close()


class TestClose:
    def test_close_prevents_further_ops(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        db.close()
        with pytest.raises(Exception):
            db.get_task("chan", 1)


class TestDownloadProgress:
    def test_update_progress(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1, total_bytes=1024)
            db.update_progress("chan", 1, 512)
            task = db.get_task("chan", 1)
            assert task["downloaded_bytes"] == 512
            assert task["total_bytes"] == 1024
            assert task["last_progress_at"] is not None
        finally:
            db.close()
    
    def test_update_status_with_progress(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.update_status("chan", 1, "downloading", downloaded_bytes=256, total_bytes=1024, increment_retry=True)
            task = db.get_task("chan", 1)
            assert task["downloaded_bytes"] == 256
            assert task["total_bytes"] == 1024
            assert task["retry_count"] == 1
        finally:
            db.close()


class TestPendingTasks:
    def test_get_pending_tasks(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_task("chan", 1)
            db.update_status("chan", 1, "downloading")
            
            db.create_task("chan", 2)
            db.update_status("chan", 2, "failed", error_message="test")
            
            db.create_task("chan", 3)
            db.update_status("chan", 3, "completed")
            
            pending = db.get_pending_tasks()
            assert len(pending) == 2
            
            message_ids = {t["message_id"] for t in pending}
            assert 1 in message_ids
            assert 2 in message_ids
        finally:
            db.close()


class TestDownloadHistoryAlias:
    def test_alias_is_download_db(self):
        assert DownloadHistory is DownloadDB


class TestDedupeTask:
    def test_create_dedupe_task(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345, chat_title="Test Chat", start_message_id=100, total_messages=500)
            assert isinstance(task_id, int)
            assert task_id >= 1
            
            task = db.get_dedupe_task(task_id)
            assert task is not None
            assert task["chat_id"] == 12345
            assert task["chat_title"] == "Test Chat"
            assert task["start_message_id"] == 100
            assert task["total_messages"] == 500
            assert task["status"] == "pending"
        finally:
            db.close()
    
    def test_update_dedupe_task(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            db.update_dedupe_task(task_id, status="scanning", last_scanned_message_id=50, processed_messages=100)
            
            task = db.get_dedupe_task(task_id)
            assert task["status"] == "scanning"
            assert task["last_scanned_message_id"] == 50
            assert task["processed_messages"] == 100
        finally:
            db.close()
    
    def test_get_dedupe_task_not_found(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            assert db.get_dedupe_task(999) is None
        finally:
            db.close()
    
    def test_list_dedupe_tasks(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            db.create_dedupe_task(chat_id=12345, chat_title="Chat 1")
            db.create_dedupe_task(chat_id=67890, chat_title="Chat 2")
            
            tasks = db.list_dedupe_tasks()
            assert len(tasks) == 2
            assert {t["chat_title"] for t in tasks} == {"Chat 1", "Chat 2"}
        finally:
            db.close()
    
    def test_list_dedupe_tasks_limit(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            for i in range(5):
                db.create_dedupe_task(chat_id=1000 + i, chat_title=f"Chat {i}")
            
            tasks = db.list_dedupe_tasks(limit=3)
            assert len(tasks) == 3
        finally:
            db.close()


class TestDedupeMedia:
    def test_add_dedupe_media(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            media_id = db.add_dedupe_media(
                task_id,
                file_id="file_123",
                file_size=1024000,
                duration=120,
                width=1920,
                height=1080,
                first_seen_message_id=50,
                first_seen_date="2024-01-01T00:00:00"
            )
            assert isinstance(media_id, int)
            assert media_id >= 1
            
            media = db.get_dedupe_media(task_id, "file_123")
            assert media is not None
            assert media["file_id"] == "file_123"
            assert media["file_size"] == 1024000
            assert media["occurrence_count"] == 1
        finally:
            db.close()
    
    def test_add_dedupe_media_existing_increments_count(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            media_id1 = db.add_dedupe_media(task_id, file_id="file_123")
            media_id2 = db.add_dedupe_media(task_id, file_id="file_123")
            
            assert media_id1 == media_id2
            
            media = db.get_dedupe_media(task_id, "file_123")
            assert media["occurrence_count"] == 2
        finally:
            db.close()
    
    def test_get_dedupe_media_not_found(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            assert db.get_dedupe_media(task_id, "nonexistent") is None
        finally:
            db.close()
    
    def test_get_dedupe_media_list_pagination(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            for i in range(30):
                db.add_dedupe_media(task_id, file_id=f"file_{i}")
            
            # 第一页
            page1, total1 = db.get_dedupe_media_list(task_id, page=1, limit=10)
            assert len(page1) == 10
            assert total1 == 30
            
            # 第二页
            page2, total2 = db.get_dedupe_media_list(task_id, page=2, limit=10)
            assert len(page2) == 10
            assert total2 == 30
        finally:
            db.close()
    
    def test_get_dedupe_media_list_search(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            db.add_dedupe_media(task_id, file_id="test_file_123")
            db.add_dedupe_media(task_id, file_id="test_file_456")
            db.add_dedupe_media(task_id, file_id="other_file_789")
            
            results, total = db.get_dedupe_media_list(task_id, search="test")
            assert len(results) == 2
            assert total == 2
            assert all("test" in m["file_id"] for m in results)
        finally:
            db.close()
    
    def test_get_dedupe_media_list_filter_duplicates(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            db.add_dedupe_media(task_id, file_id="file_single")
            db.add_dedupe_media(task_id, file_id="file_dup")
            db.add_dedupe_media(task_id, file_id="file_dup")
            
            # 筛选重复项
            duplicates, total_dup = db.get_dedupe_media_list(task_id, filter_type="duplicates")
            assert len(duplicates) == 1
            assert total_dup == 1
            assert duplicates[0]["file_id"] == "file_dup"
            
            # 筛选单项
            singles, total_single = db.get_dedupe_media_list(task_id, filter_type="singles")
            assert len(singles) == 1
            assert total_single == 1
            assert singles[0]["file_id"] == "file_single"
            
            # 筛选全部
            all_media, total_all = db.get_dedupe_media_list(task_id, filter_type="all")
            assert len(all_media) == 2
            assert total_all == 2
        finally:
            db.close()


class TestDedupeResult:
    def test_add_dedupe_result(self, tmp_path):
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            result_id = db.add_dedupe_result(
                task_id,
                message_id=100,
                file_id="file_123",
                is_duplicate=False,
                is_original=True,
                downloaded=False
            )
            assert isinstance(result_id, int)
            assert result_id >= 1
        finally:
            db.close()


class TestMediaPhash:
    """测试媒体感知哈希相关功能"""
    
    def test_update_media_phash(self, tmp_path):
        """测试更新媒体的 phash"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            db.add_dedupe_media(task_id, file_id="test_file")
            
            # 更新 phash
            db.update_media_phash(task_id, "test_file", "abcdef123456")
            
            # 验证
            media = db.get_dedupe_media(task_id, "test_file")
            assert media["phash"] == "abcdef123456"
        finally:
            db.close()
    
    def test_clear_media_phash(self, tmp_path):
        """测试清除媒体的 phash"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            
            # 添加多个带 phash 的媒体
            db.add_dedupe_media(task_id, file_id="file1", phash="hash1")
            db.add_dedupe_media(task_id, file_id="file2", phash="hash2")
            db.add_dedupe_media(task_id, file_id="file3", phash="hash3")
            
            # 先验证 phash 存在
            media1 = db.get_dedupe_media(task_id, "file1")
            media2 = db.get_dedupe_media(task_id, "file2")
            assert media1["phash"] == "hash1"
            assert media2["phash"] == "hash2"
            
            # 清除 phash
            db.clear_media_phash(task_id)
            
            # 验证 phash 已清除
            media1 = db.get_dedupe_media(task_id, "file1")
            media2 = db.get_dedupe_media(task_id, "file2")
            media3 = db.get_dedupe_media(task_id, "file3")
            assert media1["phash"] is None
            assert media2["phash"] is None
            assert media3["phash"] is None
        finally:
            db.close()
    
    def test_clear_media_phash_no_media(self, tmp_path):
        """测试在没有媒体的情况下清除 phash (不应该报错)"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            
            # 即使没有媒体也应该能正常执行
            db.clear_media_phash(task_id)
        finally:
            db.close()
    
    def test_get_media_with_phash(self, tmp_path):
        """测试获取有 phash 的媒体"""
        db = DownloadDB(tmp_path / "test.db")
        try:
            task_id = db.create_dedupe_task(chat_id=12345)
            
            # 部分有 phash，部分没有
            db.add_dedupe_media(task_id, file_id="file1", phash="hash1")
            db.add_dedupe_media(task_id, file_id="file2", phash="hash2")
            db.add_dedupe_media(task_id, file_id="file3")
            
            media_with_phash = db.get_media_with_phash(task_id)
            assert len(media_with_phash) == 2
            file_ids = {m["file_id"] for m in media_with_phash}
            assert "file1" in file_ids
            assert "file2" in file_ids
            assert "file3" not in file_ids
        finally:
            db.close()
