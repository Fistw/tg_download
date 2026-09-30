# 概览页指标修复与磁盘用量实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复概览页的零值统计，将 Bot 转发视频纳入下载统计，并显示真实系统指标和下载目录分区的磁盘用量。

**Architecture:** 后端在现有 dashboard stats API 中汇总文件级下载和转发批次，并在响应中返回 CPU、内存和下载分区用量。前端按区域独立处理 API 结果，在概览增加磁盘卡片、失败计数及明确的空数据和局部错误状态。

**Tech Stack:** Python 3.9+, SQLite, psutil, WSGI, React 19, TypeScript, MUI, Vite.

---

### Task 1: 汇总文件级与转发视频下载统计

**Files:**
- Create: `tests/test_monitoring_db.py`
- Modify: `src/monitoring_db.py`

- [ ] **Step 1: 写合并统计回归测试**

在 `tests/test_monitoring_db.py` 写入：

```python
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
```

- [ ] **Step 2: 运行测试确认当前行为不满足统计契约**

Run: `python -m pytest tests/test_monitoring_db.py -q`

Expected: 失败，当前响应缺少 `failed` 字段，且转发批次没有计入下载统计。

- [ ] **Step 3: 在 `get_dashboard_stats` 聚合转发批次**

在现有下载统计 SQL 中增加文件级失败数，并加入下列最近 24 小时的批次查询：

```sql
SELECT
    COALESCE(SUM(total_videos), 0) AS total,
    COALESCE(SUM(downloaded_count), 0) AS completed,
    COALESCE(SUM(failed_count), 0) AS failed,
    COALESCE(SUM(CASE WHEN status = 'downloading'
        THEN MAX(total_videos - downloaded_count - failed_count, 0)
        ELSE 0 END), 0) AS active
FROM forwarded_video_batches
WHERE created_at >= datetime('now', '-24 hours')
```

将查询结果逐字段加到 `download_metrics` 的同名统计上。平均速度继续只使用文件级已完成记录中的 `AVG(speed_kb_s)`。在 `get_dashboard_stats` 返回的 `downloads` 字典增加 `failed`。

- [ ] **Step 4: 运行监控数据库测试**

Run: `python -m pytest tests/test_monitoring_db.py -q`

Expected: 两个用例通过，混合样例返回 7 个总项、3 个完成、2 个活跃、2 个失败，速度为 25 KB/s。

- [ ] **Step 5: 提交统计改动**

```powershell
git add tests/test_monitoring_db.py src/monitoring_db.py
git commit -m "fix: include forwarded videos in dashboard totals"
```

### Task 2: 恢复系统指标并提供下载分区容量

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/webdav_server.py`
- Create: `tests/test_dashboard_system_metrics.py`

- [ ] **Step 1: 写系统与磁盘指标测试**

在 `tests/test_dashboard_system_metrics.py` 写入：

```python
from pathlib import Path

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
```

- [ ] **Step 2: 运行测试确认新磁盘结构尚不存在**

Run: `python -m pytest tests/test_dashboard_system_metrics.py -q`

Expected: 失败，当前 `get_system_metrics` 不接收下载目录且不返回磁盘字段。

- [ ] **Step 3: 声明并实现指标采集**

在 `pyproject.toml` 的运行依赖中加入 `psutil>=5.9`。将 `src/webdav_server.py` 的采集函数实现为：

```python
def get_system_metrics(download_dir: str | Path) -> dict:
    try:
        import psutil
        memory_percent = psutil.virtual_memory().percent
        cpu_percent = psutil.cpu_percent(interval=0.1)
    except Exception:
        memory_percent = None
        cpu_percent = None

    try:
        disk_usage = shutil.disk_usage(download_dir)
        if disk_usage.total <= 0:
            raise OSError("download filesystem reports zero capacity")
        disk = {
            "available": True,
            "total_bytes": disk_usage.total,
            "used_bytes": disk_usage.used,
            "free_bytes": disk_usage.free,
            "used_percent": round(disk_usage.used * 100 / disk_usage.total, 1),
        }
    except OSError:
        disk = {
            "available": False,
            "total_bytes": None,
            "used_bytes": None,
            "free_bytes": None,
            "used_percent": None,
        }

    return {
        "memory_percent": memory_percent,
        "cpu_percent": cpu_percent,
        "active_connections": 0,
        "disk": disk,
    }
```

增加 `shutil` 导入。给 `MonitoringApp.__init__` 增加 `download_dir: str | Path` 参数并保存为 `Path`；由 `WebDAVServer._run_server` 将 `self.download_dir` 传入构造器。`handle_api_stats` 用 `get_system_metrics(self.download_dir)` 设置实时 `system` 字段。后台 30 秒历史采集只把 `memory_percent`、`cpu_percent` 和 `active_connections` 显式传给 `record_system_metrics`，不传 `disk` 字典。

- [ ] **Step 4: 运行系统指标和服务器测试**

Run: `python -m pytest tests/test_dashboard_system_metrics.py tests/test_webdav_server.py -q`

Expected: 所有用例通过；既有 `/health` 测试仍返回 200。

- [ ] **Step 5: 提交后端系统指标改动**

```powershell
git add pyproject.toml src/webdav_server.py tests/test_dashboard_system_metrics.py
git commit -m "feat: expose dashboard disk usage metrics"
```

### Task 3: 展示完整概览并隔离加载错误

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/pages/Overview.tsx`

- [ ] **Step 1: 更新 API 类型**

`DownloadStats` 增加 `failed: number`。`SystemStats.memory_percent` 和 `cpu_percent` 改成 `number | null`，新增 `disk`，字段为 `available: boolean` 以及四个允许 `null` 的容量数值。

- [ ] **Step 2: 让概览请求互相独立**

增加 `stats`、`downloads`、`uploads`、`recoveries` 四个区域错误状态，并把 `fetchData` 改为下列模式：

```ts
const results = await Promise.allSettled([
  apiClient.getDashboardStats(),
  apiClient.getDownloads(),
  apiClient.getUploads(),
  apiClient.getRecoveries(),
])

if (results[0].status === 'fulfilled') setStats(results[0].value)
if (results[1].status === 'fulfilled') setDownloads(results[1].value)
if (results[2].status === 'fulfilled') setUploads(results[2].value)
if (results[3].status === 'fulfilled') setRecoveries(results[3].value)
setErrors({
  stats: results[0].status === 'rejected',
  downloads: results[1].status === 'rejected',
  uploads: results[2].status === 'rejected',
  recoveries: results[3].status === 'rejected',
})
```

把这些语句放进 `try/finally`，在 `finally` 中执行 `setLoading(false)`。每个成功结果只更新对应 state；失败不清空其他区域已有数据。为手动刷新和 10 秒轮询继续共用 `fetchData`。

- [ ] **Step 3: 展示指标和空状态**

下载卡片的活动行增加 `失败: {stats?.downloads.failed ?? '不可用'}`。CPU/内存为 `null` 时显示“不可用”，否则显示百分比。新增与现有 CPU/内存卡同级的“磁盘用量”卡片：可用时显示 `used_percent`、`formatFileSize(used_bytes)`、`formatFileSize(total_bytes)` 和 `formatFileSize(free_bytes)`，用已用百分比设置进度条宽度；不可用时显示“不可用”，进度条宽度设为 0。下载、上传图表的空分支显示“暂无速度数据”；两张历史表格在对应数组为空时渲染一行 `colSpan={4}` 的“暂无记录”。每个区域的错误状态在标题下显示“该区域数据加载失败，请刷新重试”。

- [ ] **Step 4: 构建前端检查类型和打包**

Run: `npm run build --prefix web`

Expected: TypeScript 检查和 Vite 构建均成功，并生成 `web/dist`。

- [ ] **Step 5: 提交前端改动**

```powershell
git add web/src/types/index.ts web/src/pages/Overview.tsx
git commit -m "feat: show complete dashboard and disk usage"
```

### Task 4: 部署并验证概览

**Files:**
- Deploy the commits from Tasks 1–3 to `/root/workspace/tg_download`

- [ ] **Step 1: 构建生产前端并检查工作区**

Run: `npm ci --prefix web`

Expected: npm exits 0 using `web/package-lock.json`.

Run: `npm run build --prefix web`

Expected: 构建成功，无 TypeScript 错误；`web/dist` 为 git 忽略的生产构建目录。

- [ ] **Step 2: 同步提交到服务器仓库并安装新依赖**

通过既有 Git bundle 工作流把本地 `main` 传到服务器、快进合并并推送 `origin/main`。在服务器项目虚拟环境执行 `pip install -e .`，确保安装 `pyproject.toml` 新增的 `psutil`。在服务器执行 `npm ci --prefix web && npm run build --prefix web`，因为 `web/dist` 被 Git 忽略，必须在部署机重建。

- [ ] **Step 3: 重启并验证 API 返回值**

重启 `tg-download.service`。用监控登录会话读取 `/api/dashboard/stats`，确认下载数大于 0、字段含 `failed`、CPU/内存为数值或 `null`，`system.disk.available` 为真且总量、已用、可用和百分比合理。确认 `/health` 返回 `OK`，`systemctl is-active` 为 `active`。

- [ ] **Step 4: 验证部署的 React 页面**

用认证会话请求 `/dashboard`，确认返回的 `index.html` 引用当前 `web/dist/assets` 哈希文件；浏览器登录后打开概览，确认下载、系统和磁盘卡片显示数据，空上传历史显示空状态。检查 `Overview.tsx` 里的 `Promise.allSettled` 四个分支，并在浏览器网络面板阻止一个 `/api/uploads` 请求，确认其他卡片仍更新且上传区域显示错误提示。确认刷新和 10 秒自动更新不清空其他区域。

- [ ] **Step 5: 同步本地远端跟踪引用并检查最终状态**

```powershell
git fetch origin main
git status --short --branch
git log -4 --oneline
```

Expected: 本地 `main` 与 `origin/main` 同步，服务保持 `active`。
