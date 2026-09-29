# Forwarded Video Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let allowlisted users send videos to the Telegram bot and save each received video on the server.

**Architecture:** Add a video-only incoming-message handler to `setup_bot_handlers`. The Bot client downloads its own incoming media into `config.download.output_dir`; filenames are sanitized and include the chat and message IDs. The handler replies with a result and does not re-send the file.

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

- [x] **Step 1: Register an incoming video handler**

Inside `setup_bot_handlers`, make video captions take precedence over link and `/download` patterns so one incoming video cannot start two downloads. Add this guard at the top of both `on_download` and `on_link`:

```python
        if _is_video_message(event.message):
            return
```

Then, after `on_link`, add:

```python
    @bot_client.on(events.NewMessage(incoming=True))
    async def on_incoming_video(event):
        message = event.message
        if not _is_video_message(message):
            return

        if not _is_allowed(event.sender_id, allowed):
            await event.reply("你没有权限使用此 Bot")
            return

        chat_id = event.chat_id or event.sender_id
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        target = output_path / _video_download_name(message, chat_id)
        if target.exists():
            await event.reply(f"视频已保存在服务器：{target.name}")
            return
        temporary = output_path / f".{target.name}.{uuid.uuid4().hex}.part"

        try:
            downloaded = await bot_client.download_media(message, file=str(temporary))
            if not downloaded:
                raise RuntimeError("Telegram 未返回下载文件")
            Path(downloaded).replace(target)
            await event.reply(f"视频已保存到服务器：{target.name}")
        except Exception as e:
            temporary.unlink(missing_ok=True)
            logger.exception("转发视频下载失败")
            await event.reply(f"视频下载失败：{e}")
```

Telethon emits each item in a Telegram album as an incoming message, so each video is saved separately with its own message ID. The handler only responds to video media and leaves the existing link and command handlers unchanged.

### Task 3: Review and deploy the change

**Files:**
- Review: `src/bot_handler.py`
- Include: `docs/superpowers/specs/2026-09-29-forwarded-video-download-design.md`
- Include: `docs/superpowers/plans/2026-09-29-forwarded-video-download.md`

- [x] **Step 1: Inspect the change**

Run `git diff --check` and inspect `git diff` to confirm that only incoming video messages are saved, allowlist checks run before downloading, filenames stay within `output_dir`, and existing link handlers remain unchanged.

- [ ] **Step 2: Commit and publish**

Commit the code and planning document with message `feat: save videos forwarded to bot`, then push the resulting `main` history to `Fistw/tg_download`.

- [ ] **Step 3: Update the server and restart the service**

Fast-forward `/root/workspace/tg_download` to the pushed `main` commit, restart `tg-download.service`, and confirm `systemctl is-active tg-download.service` returns `active`.
