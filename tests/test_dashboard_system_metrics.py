from src.webdav_server import get_system_metrics


def test_system_metrics_reports_disk_usage_for_download_directory(tmp_path):
    metrics = get_system_metrics(tmp_path)

    disk = metrics["disk"]
    assert disk["available"] is True
    assert disk["total_bytes"] > 0
    assert disk["used_bytes"] + disk["free_bytes"] == disk["total_bytes"]
    assert 0 <= disk["used_percent"] <= 100
    assert metrics["memory_percent"] is None or 0 <= metrics["memory_percent"] <= 100
    assert metrics["cpu_percent"] is None or 0 <= metrics["cpu_percent"] <= 100


def test_system_metrics_marks_missing_download_directory_unavailable(tmp_path):
    metrics = get_system_metrics(tmp_path / "missing")

    assert metrics["disk"] == {
        "available": False,
        "total_bytes": None,
        "used_bytes": None,
        "free_bytes": None,
        "used_percent": None,
    }
