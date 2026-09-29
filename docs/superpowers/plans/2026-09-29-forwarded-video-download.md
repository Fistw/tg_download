# Forwarded Video Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let allowlisted users send videos to the Telegram bot and save each received video on the server.

**Architecture:** Add video-only incoming-message and album handlers to `setup_bot_handlers`. The Bot client downloads incoming media into `config.download.output_dir`; filenames are sanitized and include the chat and message IDs. Each batch gets one start/progress message, updated after each video; separate messages are independent batches.

**Tech Stack:** Python 3.9+, Telethon, `pathlib`, existing `AppConfig` and allowlist helper.

---

### Task 1: Add safe video detection and destination naming

**Files:**
- Modify: `src/bot_handler.py`

- [x] **Step 1: Add a predicate for Telegram video media**

Add `re` and `uuid` to the imports and add this module-level helper after `_is_allowed`:

```python
def _is_video_message(message: Any) -> bool:
    if getattr(message, "video", None):
        return True
    file_info = getattr(message, "file", None)
    mime_type = getattr(file_info, "mime_type", None)
    return bool(mime_type and mime_type.lower().startswith("video/"))
```

- [x] **Step 2: Add a safe, unique filename builder**

Add this helper after `_is_video_message`:

```python
def _video_download_name(message: Any, chat_id: int) -> str:
    file_info = getattr(message, "file", None)
    original_name = getattr(file_info, "name", None)
    if original_name:
        filename = Path(str(original_name).replace("\\", "/")).name
        filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename)
        filename = filename.strip(" .")
        if len(filename.encode("utf-8")) > 120:
            original_suffix = Path(filename).suffix
            suffix = original_suffix.encode("utf-8")[:24].decode("utf-8", errors="ignore")
            stem = filename[: -len(original_suffix)] if original_suffix else filename
            stem_limit = 120 - len(suffix.encode("utf-8"))
            stem = stem.encode("utf-8")[:stem_limit].decode("utf-8", errors="ignore")
            filename = f"{stem or 'video'}{suffix}"
    else:
        filename = "video.mp4"
    return f"{chat_id}_{message.id}_{filename or 'video.mp4'}"
```

The message ID makes repeated filenames in different incoming messages distinct; sanitizing both slash styles prevents a Telegram filename from choosing a directory outside the configured output folder.

### Task 2: Save incoming videos for allowlisted users

**Files:**
- Modify: `src/bot_handler.py`

- [x] **Step 1: Register incoming video and album handlers**

Inside `setup_bot_handlers`, make video captions take precedence over link and `/download` patterns so one incoming video cannot start two downloads. Add this guard at the top of both `on_download` and `on_link`:

```python
        if _is_video_message(event.message):
            return
```

Add a shared batch helper inside `setup_bot_handlers`, after `_handle_bot_download`:

```python
    async def _download_video_batch(messages, chat_id: int, send_status) -> None:
        videos = [message for message in messages if _is_video_message(message)]
        if not videos:
            return

        total = len(videos)
        status_message = await send_status(f"开始下载，共 {total} 个视频…")
        downloaded_count = 0
        failed_count = 0
        for message in videos:
            try:
                await _download_incoming_video(bot_client, message, output_dir, chat_id)
                downloaded_count += 1
            except Exception:
                failed_count += 1
                logger.exception("转发视频下载失败，消息 ID: %s", message.id)

            processed_count = downloaded_count + failed_count
            state = "下载完成" if processed_count == total else "下载中"
            progress = f"{state}：已下载 {downloaded_count}/{total} 个视频"
            if failed_count:
                progress += f"，失败 {failed_count} 个"
            try:
                await status_message.edit(progress)
            except Exception:
                logger.warning("更新转发视频下载进度失败")
                try:
                    status_message = await send_status(progress)
                except Exception:
                    logger.exception("发送转发视频下载进度失败")
```

After `on_link`, add a `NewMessage(incoming=True)` handler for ungrouped video messages. It must return for messages with `grouped_id` so the album handler owns them. Authorize with `_is_allowed`, then call `_download_video_batch([message], chat_id, event.reply)`.

Also add an `events.Album` handler. Ignore empty or outgoing albums, filter `event.messages` through `_is_video_message`, authorize `event.sender_id`, and call `_download_video_batch(videos, event.chat_id or event.sender_id, event.respond)`. A single video and each separate forwarded message are 1/1; an album reports the number of video items in that album. Telethon's Album event aggregates grouped messages, so it can report the total before downloading starts.

### Task 3: Review and deploy the change

**Files:**
- Review: `src/bot_handler.py`
- Include: `docs/superpowers/specs/2026-09-29-forwarded-video-download-design.md`
- Include: `docs/superpowers/plans/2026-09-29-forwarded-video-download.md`

- [x] **Step 1: Inspect the change**

Run `git diff --check` and inspect `git diff` to confirm that only incoming video messages are saved, allowlist checks run before downloading, filenames stay within `output_dir`, and existing link handlers remain unchanged.

- [ ] **Step 2: Commit and publish**

Commit the code and updated design/plan with message `feat: report forwarded video download progress`, then push the resulting `main` history to `Fistw/tg_download`.

- [ ] **Step 3: Update the server and restart the service**

Fast-forward `/root/workspace/tg_download` to the pushed `main` commit, restart `tg-download.service`, and confirm `systemctl is-active tg-download.service` returns `active`.
