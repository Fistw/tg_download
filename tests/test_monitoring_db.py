from src.monitoring_db import MonitoringDB


def test_dashboard_stats_combines_download_metrics_and_forwarded_batches(tmp_path):
    db = MonitoringDB(tmp_path / "monitoring.db")

    completed_id = db.start_download_task(1, "completed.mp4", 100)
    db.complete_download_task(completed_id, 100, 25.0)
    db.start_download_task(2, "active.mp4", 100)
    failed_id = db.start_download_task(3, "failed.mp4", 100)
    db.complete_download_task(failed_id, 0, 0.0, status="failed")

    batch_id = db.start_forwarded_video_batch("album", 123, 456, 4)
    db.update_forwarded_video_batch(batch_id, 2, 1, "downloading")

    stats = db.get_dashboard_stats()["downloads"]

    assert stats == {
        "total": 7,
        "completed": 3,
        "active": 2,
        "failed": 2,
        "avg_speed_kb_s": 25.0,
    }


def test_dashboard_stats_returns_zero_download_counts_without_history(tmp_path):
    db = MonitoringDB(tmp_path / "monitoring.db")

    stats = db.get_dashboard_stats()["downloads"]

    assert stats == {
        "total": 0,
        "completed": 0,
        "active": 0,
        "failed": 0,
        "avg_speed_kb_s": 0,
    }
