# tg-download

下载 Telegram 频道中**被禁止下载或转发**的视频文件。

基于 Telethon MTProto 协议直接与 Telegram 服务器通信，绕过客户端层面的 `noforwards` 限制。

## 功能

- **CLI 手动下载** — 通过链接或消息 ID 范围下载视频
- **Bot 交互下载** — 在 Telegram 中发送链接即可触发下载
- **频道自动监控** — 监听指定频道，自动下载新视频
- **点赞自动下载** — 对视频消息点赞即可自动下载（支持主频道和评论）
- **并发下载** — Semaphore 控制并发数，避免触发限流
- **SQLite 任务管理** — 下载状态持久化，断点续传不丢失
- **失败自动重试** — 网络异常自动重试，FloodWait 自动等待

## 快速开始

### 前置条件

- Python 3.9+
- 从 [my.telegram.org](https://my.telegram.org) 获取 `api_id` 和 `api_hash`
- 从 [@BotFather](https://t.me/BotFather) 获取 Bot Token（可选，用于 Bot 交互）

### 安装

```bash
git clone https://github.com/Fistw/tg_download.git
cd tg_download
pip install -e .
```

### 配置

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`：

```yaml
telegram:
  api_id: 12345678
  api_hash: "your_api_hash"
  bot_token: "123456:ABC-xxx"
  session_name: "user_session"

download:
  output_dir: "./downloads"
  max_concurrent: 3
  enable_reaction_download: false  # 是否启用点赞下载

monitor:
  channels:
    - "channel_username"
    - "-1001234567890"
  filters:
    min_size_mb: 0
    max_size_mb: 4096
    keywords: []

bot:
  allowed_users:
    - 123456789
```

### 首次登录

```bash
python -m src download "https://t.me/some_channel/1"
```

按提示输入手机号和验证码，生成 `user_session.session` 文件。

### 使用

```bash
# 下载单个视频
python -m src download "https://t.me/channel/123"

# 批量下载
python -m src download channel_name --range 100-200

# 启动 Bot + 频道监控 + 点赞监控服务
python -m src serve
```

### 点赞下载功能

将 `config.yaml` 中的 `enable_reaction_download` 设为 `true`：

```yaml
download:
  enable_reaction_download: true
```

然后对包含视频的消息点赞，系统将自动下载！支持：
- 主频道消息（如 `https://t.me/channel/123`）
- 评论区消息（如 `https://t.me/channel/123?comment=456`）

### 一键部署

```bash
./scripts/deploy.sh
```

## 项目结构

```
src/
├── cli.py             # CLI 入口
├── client.py          # Telegram 客户端管理
├── config.py          # 配置加载
├── database.py        # SQLite 任务管理
├── downloader.py      # 下载核心逻辑
├── reaction_monitor.py # 点赞事件监控
├── monitor.py         # 频道监控
├── bot_handler.py     # Bot 命令处理
└── utils.py           # 工具函数
```

## 许可证

MIT
