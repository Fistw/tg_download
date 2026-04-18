# Telegram Restricted Video Downloader — Design Spec

## Overview

A Python CLI tool and background service that downloads videos from Telegram channels/chats where "restrict saving content" (noforwards) is enabled. Uses Telethon (MTProto) to bypass client-level download restrictions.

## Key Insight

Telegram's "restrict saving content" flag (`noforwards`) is a **client-side UI directive**. The MTProto protocol itself does not enforce this restriction — any authenticated user who has access to a channel can request file data via `upload.getFile`. Telethon, as a raw MTProto client, can download these files directly.

## Technology Stack

- **Language:** Python 3.10+
- **Telegram Library:** Telethon (MTProto user client + Bot API)
- **Config:** YAML (PyYAML)
- **Database:** SQLite (download history, deduplication)
- **CLI:** argparse or click
- **Testing:** pytest

## Architecture

```
tg_download/
├── src/
│   ├── __init__.py
│   ├── config.py          # Configuration management
│   ├── client.py          # Telegram client management (User + Bot)
│   ├── downloader.py      # Core download logic
│   ├── monitor.py         # Channel monitoring logic
│   ├── bot_handler.py     # Bot interaction handling
│   ├── utils.py           # Utilities (link parsing, progress display)
│   └── cli.py             # CLI entry point
├── tests/                 # Unit tests
├── config.example.yaml    # Example configuration
├── pyproject.toml         # Project configuration
└── README.md
```

## Running Modes

### 1. CLI Mode

```bash
python -m tg_download download <target>
```

**Supported input formats:**
- Message URL: `https://t.me/channel_name/123`
- Channel + message ID: `channel_name 123`
- Batch range: `channel_name 100-200`

### 2. Serve Mode

```bash
python -m tg_download serve
```

Starts both the Bot interaction handler and the channel monitor concurrently using asyncio.

## Module Design

### config.py — Configuration Management

Loads configuration from a YAML file. Fields:

```yaml
telegram:
  api_id: 12345
  api_hash: "your_api_hash"
  bot_token: "your_bot_token"
  session_name: "user_session"

download:
  output_dir: "./downloads"
  filename_template: "{channel}_{message_id}_{original_name}"

monitor:
  channels:
    - "channel_name_1"
    - "channel_name_2"
  filters:
    min_size_mb: 0
    max_size_mb: 4096
    keywords: []

bot:
  allowed_users:
    - 123456789
```

Environment variables override YAML values for sensitive fields (API_ID, API_HASH, BOT_TOKEN).

### client.py — Telegram Client Management

Manages two Telethon client instances:

1. **User Client** (`TelegramClient`) — Authenticated with phone number/session. Used for:
   - Accessing restricted channels
   - Downloading media files
   - Monitoring new messages

2. **Bot Client** (`TelegramClient` with bot_token) — Used for:
   - Receiving user commands
   - Sending download status notifications
   - Delivering downloaded files to users

Both clients share the same event loop. Provides context managers for clean startup/shutdown.

### downloader.py — Core Download Logic

**Public interface:**

```python
async def download_message(client, message, output_dir, progress_callback=None) -> Path:
    """Download media from a single message. Returns path to downloaded file."""

async def download_by_link(client, link, output_dir, progress_callback=None) -> Path:
    """Parse a Telegram link and download its media."""

async def download_range(client, channel, start_id, end_id, output_dir, progress_callback=None) -> list[Path]:
    """Download media from a range of message IDs."""
```

**Flow:**

1. Parse input (link/channel+ID/range)
2. Call `client.get_messages()` to retrieve message objects
3. Filter for video media (`MessageMediaDocument` with video/* MIME type)
4. Call `client.download_media(message, file=path, progress_callback=cb)`
5. Return path(s) to downloaded file(s)

**File naming:** `{channel_name}_{message_id}_{original_filename}` — avoids collisions.

**Error handling:**
- `FloodWaitError` — respect the wait time, retry after delay
- `FileReferenceExpiredError` — re-fetch message and retry
- Network errors — retry with exponential backoff (max 3 retries)

### monitor.py — Channel Monitoring

Uses Telethon's event system:

```python
@client.on(events.NewMessage(chats=channel_list))
async def on_new_message(event):
    # Check if message contains video media
    # Apply filters (size, keywords)
    # Download if criteria met
    # Record in SQLite to prevent duplicates
```

**SQLite schema for download history:**

```sql
CREATE TABLE downloads (
    id INTEGER PRIMARY KEY,
    channel TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER,
    downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(channel, message_id)
);
```

On startup, checks history to avoid re-downloading already processed messages.

### bot_handler.py — Bot Interaction

**Commands:**

| Command | Description |
|---------|-------------|
| `/download <link>` | Download video from the specified link |
| `/monitor add <channel>` | Add a channel to the monitor list |
| `/monitor remove <channel>` | Remove a channel from the monitor list |
| `/monitor list` | List monitored channels |
| `/status` | Show current download tasks and monitor status |

**Permission control:** Only user IDs listed in `bot.allowed_users` config can interact with the bot.

**Download flow via Bot:**
1. User sends `/download https://t.me/channel/123` to bot
2. Bot acknowledges, forwards request to downloader (using User Client)
3. Downloader executes, sends progress updates to bot chat
4. On completion, bot sends the file to the user (if < 2GB) or sends the local path

### utils.py — Utilities

- `parse_telegram_link(url) -> (channel, message_id)` — Parse various Telegram URL formats
- `format_progress(current, total) -> str` — Format download progress
- `format_file_size(bytes) -> str` — Human-readable file size

### cli.py — CLI Entry Point

```bash
# Download a single video
python -m tg_download download https://t.me/channel/123

# Download a range
python -m tg_download download channel_name --range 100-200

# Start serve mode (bot + monitor)
python -m tg_download serve

# Start serve mode (monitor only, no bot)
python -m tg_download serve --no-bot
```

## Testing Strategy

- **Unit tests** for each module using pytest
- Mock Telethon client interactions using `unittest.mock`
- Test link parsing, config loading, file naming, filter logic
- Integration tests (optional, requires real credentials) marked with `@pytest.mark.integration`

## Security Considerations

- Credentials stored in config file or environment variables, never committed to git
- `.gitignore` includes `*.session`, `config.yaml`, `.env`
- Bot access restricted to allowed user IDs only
- Session files contain authentication tokens — treat as secrets

## Future Enhancements (Out of Scope)

- Multi-session concurrent chunk download (Plan B)
- Web UI dashboard
- Docker deployment
- Download queue with priority
