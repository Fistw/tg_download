# Forwarded Video Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show incoming Bot video download batches in the authenticated React Downloads page and retain their records across service restarts.

**Architecture:** Store one aggregate record per Telegram album or standalone video in the existing `MonitoringDB` SQLite database. The Bot updates that record after each item, the existing WSGI dashboard exposes recent batches behind its current authentication, and the React Downloads page polls and renders them beside the existing file-level history.

**Tech Stack:** Python 3.9+, SQLite, WSGI, React 19, TypeScript, Material UI.

---

### Task 1: Persist forwarded video batch state

**Files:**
- Modify: `src/monitoring_db.py`

- [x] **Step 1: Add the batch table and startup recovery**

Create `forwarded_video_batches` in `_initialize_db` with fields: `id INTEGER PRIMARY KEY AUTOINCREMENT`, `batch_type TEXT NOT NULL`, `chat_id INTEGER`, `sender_id INTEGER`, `total_videos INTEGER NOT NULL`, `downloaded_count INTEGER NOT NULL DEFAULT 0`, `failed_count INTEGER NOT NULL DEFAULT 0`, `status TEXT NOT NULL`, `created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`, and `updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`. Add an index on `created_at`.

At initialization, delete records older than `retention_days`, then change leftover `status='downloading'` records to `status='interrupted'` and refresh `updated_at`. Do not reset progress or automatically retry them. Include the table in `cleanup_old_data` using the same cutoff as other monitoring records.

- [x] **Step 2: Add exact batch APIs**

Add these methods to `MonitoringDB`, using `_db_lock` and `_get_connection()` like existing metric methods:

```python
def start_forwarded_video_batch(
    self, batch_type: str, chat_id: int, sender_id: int, total_videos: int
) -> int:
    """Insert a downloading batch with zero downloaded and failed items."""

def update_forwarded_video_batch(
    self, batch_id: int, downloaded_count: int, failed_count: int, status: str
) -> None:
    """Update aggregate counts, status, and updated_at for one batch."""

def get_forwarded_video_batches(self, days: int = 7, limit: int = 100) -> list[dict]:
    """Return recent batch summaries newest first."""
```

`start_forwarded_video_batch` inserts `status='downloading'`. The list query returns `id`, `batch_type`, `chat_id`, `sender_id`, `total_videos`, `downloaded_count`, `failed_count`, `status`, `created_at`, and `updated_at`; it filters to the requested cutoff and applies the limit without mutating stored data.

### Task 2: Update persistent state while the Bot downloads

**Files:**
- Modify: `src/bot_handler.py`

- [x] **Step 1: Give the shared batch handler its source metadata**

Change `_download_video_batch` to accept `batch_type` and `sender_id`. Pass `batch_type="single"` from `on_incoming_video`; pass `batch_type="album"` from `on_incoming_video_album`. Use the existing `chat_id` and the event's `sender_id`.

- [x] **Step 2: Persist aggregate progress without blocking media downloads**

Before the video loop, attempt `monitoring_db.start_forwarded_video_batch(...)` when a database is available. Catch and log database errors, then continue the existing Telegram status/download behavior. After each video, update the aggregate counts. Use `completed` when all succeed, `partially_failed` when at least one succeeds and one fails, `failed` when every item fails, and `downloading` before the batch is finished. On database update errors, log the exception and keep processing the remaining media.

Inside `_download_video_batch`, resolve the shared instance with `get_monitoring_db()` using the same lazy import pattern already used in this module for monitoring records. Catch database initialization errors and continue with `monitoring_db = None`. Since the CLI creates the singleton before installing Bot handlers, this returns the same database instance used by the dashboard.

### Task 3: Expose recent batches through the authenticated dashboard API

**Files:**
- Modify: `src/webdav_server.py`

- [x] **Step 1: Register a GET route and handler**

Add `/api/forwarded-video-tasks` to `MonitoringApp.routes`. Implement `handle_api_forwarded_video_tasks` to accept only GET and return `405 Method Not Allowed` for other methods. For GET, return `_monitoring_db.get_forwarded_video_batches(days=7, limit=100)`, or an empty JSON array if the database is unavailable. Serialize with `ensure_ascii=False` and set the JSON content type like `handle_api_downloads`.

The existing `MonitoringApp.__call__` authentication check runs before route dispatch, so this endpoint must not bypass it.

### Task 4: Render batch progress in React Downloads

**Files:**
- Modify: `web/src/types/index.ts`
- Modify: `web/src/api/client.ts`
- Modify: `web/src/pages/Downloads.tsx`

- [x] **Step 1: Add the API type and client method**

Add `ForwardedVideoBatch` with the exact response fields from Task 1. Add `getForwardedVideoBatches(): Promise<ForwardedVideoBatch[]>` calling `GET /forwarded-video-tasks` through the configured Axios client.

- [x] **Step 2: Fetch and render batches separately from file-level metrics**

Add a `forwardedBatches` state to `Downloads`. In `fetchData`, fetch both `getDownloads()` and `getForwardedVideoBatches()` with `Promise.all`, and keep the existing 10-second refresh interval. Render a “Bot 转发视频任务” section above the existing downloads table with columns for batch type, created time, downloaded/total, failed count, and status. Map `single`/`album` and each status (`downloading`, `completed`, `partially_failed`, `failed`, `interrupted`) to Chinese labels and MUI chip colors. Show a concise empty state when there are no batches.

- [x] **Step 3: Build the React dashboard**

Run `npm run build` from `web/`; expect the TypeScript build and Vite build to complete and update `web/dist` for deployment.

### Task 5: Publish and deploy

**Files:**
- Review all files above and `docs/superpowers/specs/2026-09-29-forwarded-video-dashboard-design.md`

- [x] **Step 1: Review the final diff**

Run `git diff --check`, review the diff for schema/status/API/type consistency, and confirm generated `web/dist` is handled according to the repository's tracked-file policy.

- [x] **Step 2: Commit and push**

Commit the implementation with message `feat: show forwarded video batches in dashboard`, then push `main` to `Fistw/tg_download`.

- [x] **Step 3: Update the remote service**

Fast-forward `/root/workspace/tg_download` to the pushed `main`, restart `tg-download.service`, and confirm `systemctl is-active tg-download.service` returns `active`.
