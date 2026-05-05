# tg-download

下载 Telegram 频道中**被禁止下载或转发**的视频文件。

基于 Telethon MTProto 协议直接与 Telegram 服务器通信，绕过客户端层面的 `noforwards` 限制。

## 功能

- **CLI 手动下载** — 通过链接或消息 ID 范围下载视频
- **Bot 交互下载** — 在 Telegram 中发送链接即可触发下载
- **频道自动监控** — 监听指定频道，自动下载新视频
- **点赞自动下载** — 对视频消息点赞即可自动下载（支持主频道和评论）
- **多视频支持** — 一条消息或媒体组中的多个视频全部下载并统一发送
- **并发下载** — Semaphore 控制并发数，避免触发限流
- **高速下载** — 支持自定义下载块大小，集成 cryptg 加密加速
- **SQLite 任务管理** — 下载状态持久化，断点续传不丢失
- **失败自动重试** — 网络异常自动重试，FloodWait 自动等待
- **WebDAV 服务器** — 内置 WebDAV 服务器，让 NAS 可以直接挂载并同步下载目录
- **NAS 自动同步** — 下载完成后自动通过 WebDAV 或 SFTP 同步到 NAS
- **Bot 交互选择** — 下载完成后询问用户是否发送文件（默认不发送）
- **Web 监控看板** — 实时查看下载和上传进度、系统指标
- **健康检查** — 自动监控服务健康，失败时自动重启
- **多线程服务** — 同时处理多个请求，避免单个大文件下载阻塞

## 快速开始

### 前置条件

- Python 3.9+
- 从 [my.telegram.org](https://my.telegram.org) 获取 `api_id` 和 `api_hash`
- 从 [@BotFather](https://t.me/BotFather) 获取 Bot Token（可选，用于 Bot 交互）
- **推荐安装** `pip install cryptg` (大幅提升下载和上传速度)

### 安装

```bash
git clone https://github.com/Fistw/tg_download.git
cd tg_download
pip install -e .
# 可选：安装加密加速库（推荐）
pip install cryptg
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
  max_concurrent: 3  # 同时下载的最大文件数
  chunk_size_kb: 2048  # 下载块大小（KB），推荐 2048（2MB）
  enable_reaction_download: false  # 是否启用点赞下载
  send_download_to_allowed_users: true  # 是否将下载的文件发送给允许的用户
  ask_before_send: true  # 下载完成后是否询问用户再发送文件
  ask_timeout_seconds: 300  # 询问超时时间（秒）

# WebDAV 服务器配置（用于群晖 NAS 访问/同步）
webdav_server:
  enable: false
  host: "0.0.0.0"
  port: 8080
  mount_path: "/"
  username: ""  # 留空则不启用认证
  password: ""
  directory: ""  # 留空则使用 download.output_dir
  # 监控看板认证（单独配置）
  monitoring_username: ""
  monitoring_password: ""
  # 健康检查配置
  health_check_enabled: true  # 是否启用健康检查
  health_check_interval: 30  # 健康检查间隔（秒）
  health_check_failure_threshold: 3  # 连续失败多少次触发重启
  health_check_timeout: 5  # 健康检查超时（秒）
  health_check_max_restarts_per_hour: 5  # 每小时最大重启次数
  server_backlog: 128  # 服务器 socket 队列大小

# NAS 同步配置（下载完成后自动上传到 NAS）
nas_sync:
  enable: false
  sync_type: "webdav"  # "webdav" 或 "sftp"
  # WebDAV 配置（如果 sync_type 是 "webdav"）
  webdav_url: ""
  webdav_username: ""
  webdav_password: ""
  webdav_remote_path: "/"
  # SFTP 配置（如果 sync_type 是 "sftp"）
  sftp_host: ""
  sftp_port: 22
  sftp_username: ""
  sftp_password: ""
  sftp_remote_path: "/"
  sftp_key_path: ""  # 可选，使用密钥认证
  # 通用配置
  max_retries: 3
  retry_delay_seconds: 5
  delete_after_sync: false  # 同步成功后是否删除本地文件

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
    - 123456789  # 允许使用 Bot 的用户 ID
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
  send_download_to_allowed_users: true
```

然后对包含视频的消息点赞，系统将自动下载！支持：
- 主频道消息（如 `https://t.me/channel/123`）
- 评论区消息（如 `https://t.me/channel/123?comment=456`）
- **媒体组消息**（一条消息包含多个视频）

### Web 监控看板

当启用 WebDAV 服务器时，访问 `http://你的服务器:8080/dashboard` 即可查看：

- 实时下载进度和速度图表
- 系统资源使用（CPU、内存）
- 健康检查状态和恢复历史

访问监控看板需要使用 `monitoring_username` 和 `monitoring_password` 进行 HTTP Basic 认证。

### 健康检查与自动恢复

启用健康检查后，系统会定期检查 WebDAV 服务是否正常运行。如果发现服务无响应，会连续检查 `health_check_failure_threshold` 次，若均失败则自动重启服务。

健康检查功能需要配合 systemd 使用，提供了示例文件 `tg-download.service.example`。

### 一键部署

```bash
./scripts/deploy.sh
```

## 项目结构

```
src/
├── cli.py              # CLI 入口
├── client.py           # Telegram 客户端管理
├── config.py           # 配置加载
├── database.py         # SQLite 任务管理
├── downloader.py       # 下载核心逻辑
├── reaction_monitor.py # 点赞事件监控
├── monitor.py          # 频道监控
├── bot_handler.py      # Bot 命令处理
├── monitoring_db.py    # 监控数据存储
├── webdav_server.py    # WebDAV 服务器 + 监控看板
└── utils.py            # 工具函数
```

## 与群晖 NAS 配合使用

有两种方式可以将下载的视频同步到群晖 NAS：

### 方案一：内置 WebDAV 服务器 + 群晖 Cloud Sync（推荐）

1. **安装额外依赖**：
   ```bash
   pip install -e ".[nas]"
   ```

2. **启用并配置 WebDAV 服务器**：
   ```yaml
   webdav_server:
     enable: true
     host: "0.0.0.0"
     port: 8080
     username: "your_username"
     password: "your_password"
   ```

3. **在群晖 DSM 中配置 Cloud Sync**：
   - 打开「Cloud Sync」
   - 点击「+」添加任务
   - 选择「WebDAV」
   - 服务器地址填：`http://你的服务器IP:8080`
   - 填入用户名密码
   - 选择本地路径和远程路径（如 /video）
   - 设置同步方向为「仅下载远程更改」或「双向同步」
   - 完成！

### 方案二：自动 NAS 同步（WebDAV/SFTP）

如果你希望下载完成后立即自动上传到 NAS，可以启用 NAS 同步功能：

1. **安装额外依赖**：
   ```bash
   pip install -e ".[nas]"
   ```

2. **配置 NAS 同步**：
   ```yaml
   nas_sync:
     enable: true
     sync_type: "webdav"  # 或者 "sftp"
     webdav_url: "http://你的NAS:5005"  # 群晖默认 WebDAV 端口
     webdav_username: "你的NAS用户名"
     webdav_password: "你的NAS密码"
     webdav_remote_path: "/video"
   ```

## 速度优化建议

为获得最佳性能，建议：

1. **安装 cryptg 库**：`pip install cryptg`（C 语言实现的加密加速）
2. **设置合适的 chunk size**：`chunk_size_kb: 2048`（2MB）
3. **调整并发数**：`max_concurrent: 3`（根据网络情况调整）
4. **优化 TCP 参数**（可选，适用于 Linux 服务器）：
   ```bash
   sudo ./scripts/optimize-tcp.sh
   ```

## 许可证

MIT
