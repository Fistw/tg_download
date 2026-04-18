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


class TestDownloadHistoryAlias:
    def test_alias_is_download_db(self):
        assert DownloadHistory is DownloadDB
