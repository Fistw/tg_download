# tg-download 部署文档

## 前置条件

- 一台 Linux/macOS 服务器（推荐 Ubuntu 22.04+）
- Python 3.9+
- **Node.js 18+** （用于 React 前端构建）
- 一个 Telegram 账号
- 从 [my.telegram.org](https://my.telegram.org) 获取的 `api_id` 和 `api_hash`
- 从 [@BotFather](https://t.me/BotFather) 创建的 Bot Token（如需 Bot 交互功能）

---

## 一键部署

```bash
git clone <your-repo-url> tg_download
cd tg_download
./scripts/deploy.sh
```

脚本会引导你完成 Python 安装、配置填写、Telegram 登录、前端构建和服务启动。

---

## 本地开发部署

### 第一步：安装 Python、Node.js 并安装依赖

```bash
python3 --version  # 确保 3.9+
pip install -e .

# 安装 Node.js（如果尚未安装）
# Ubuntu/Debian:
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
# macOS:
brew install node

# 构建 React 前端
cd web
npm install
npm run build
cd ..
```

### 第二步：创建配置文件

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，填入你的凭据：

```yaml
telegram:
  api_id: 12345678              # 从 my.telegram.org 获取
  api_hash: "your_api_hash"     # 从 my.telegram.org 获取
  bot_token: "123456:ABC-xxx"   # 从 @BotFather 获取
  session_name: "user_session"  # 保持默认即可

download:
  output_dir: "./downloads"     # 下载保存目录
  max_concurrent: 3             # 最大并发下载数

monitor:
  channels:                     # 需要自动监控的频道
    - "channel_username"        # 公开频道填用户名
    - "-1001234567890"          # 私有频道填数字 ID
  filters:
    min_size_mb: 0
    max_size_mb: 4096
    keywords: []                # 留空表示不过滤

bot:
  allowed_users:
    - 123456789                 # 允许使用 Bot 的 Telegram 用户 ID
```

> **获取你的用户 ID：** 在 Telegram 中给 [@userinfobot](https://t.me/userinfobot) 发消息即可查看。
>
> **获取私有频道 ID：** 在 Telegram Web 版打开频道，URL 中的数字加上 `-100` 前缀即为频道 ID。

### 第三步：首次登录生成 session 文件

```bash
python -m src download "https://t.me/some_channel/1"
```

按提示输入：
1. **手机号**（带国际区号，如 `+8613800138000`）
2. Telegram 发来的**验证码**
3. **两步验证密码**（如果开启了的话）

登录成功后，项目目录下会生成 `user_session.session` 文件。

> **重要：** 这个 session 文件相当于你的登录凭证，妥善保管，不要泄露。

### 第四步：启动服务

```bash
# 前台运行
python3 -m src serve

# 后台运行（使用 nohup）
nohup python3 -m src serve > tg_download.log 2>&1 &

# 或使用启动脚本
./scripts/start.sh
```

### 可选：systemd 服务配置

创建 `/etc/systemd/system/tg-download.service`：

```ini
[Unit]
Description=Telegram Video Downloader
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/path/to/tg_download
ExecStart=/usr/bin/python3 -m src serve
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-download
sudo systemctl start tg-download

# 查看状态
sudo systemctl status tg-download
journalctl -u tg-download -f
```

---

## 数据库自动备份

### 手动备份（随时可用）

```bash
# 在项目目录下执行
./scripts/backup_db.sh
```

备份会保存到 `backups/` 目录，文件名包含日期时间：
- `downloads_20260516_020000.db.gz`
- `monitoring_20260516_020000.db.gz`

### 自动备份（每日凌晨，推荐）

使用 systemd timer 配置每日自动备份：

```bash
# 1. 复制备份服务配置
sudo cp tg-download-backup.service.example /etc/systemd/system/tg-download-backup.service
sudo cp tg-download-backup.timer.example /etc/systemd/system/tg-download-backup.timer

# 2. 根据需要编辑服务文件中的路径和用户
sudo nano /etc/systemd/system/tg-download-backup.service

# 3. 重新加载 systemd 配置
sudo systemctl daemon-reload

# 4. 启用并启动 timer
sudo systemctl enable tg-download-backup.timer
sudo systemctl start tg-download-backup.timer

# 5. 查看 timer 状态
sudo systemctl list-timers | grep tg-download-backup

# 6. 手动触发一次备份（测试用）
sudo systemctl start tg-download-backup.service

# 7. 查看备份日志
journalctl -u tg-download-backup.service -f
```

默认配置是**每日凌晨 02:00** 执行备份，每个数据库最多保留 **3 份**最近的备份。

### 从备份恢复

```bash
# 1. 进入备份目录
cd backups

# 2. 解压备份文件
gunzip downloads_20260516_020000.db.gz

# 3. 复制回项目根目录（先关闭服务！）
sudo systemctl stop tg-download
cp downloads_20260516_020000.db ../downloads.db

# 4. 重启服务
sudo systemctl start tg-download
```

---

## 安全远程更新

配置好远程服务器后，可以使用安全更新脚本进行部署：

### 1. 配置远程服务器信息

复制 `.env.example` 为 `.env` 并编辑：

```bash
cp .env.example .env
# 编辑 .env，填入你的远程服务器信息
```

`.env` 文件内容：

```env
# 远程服务器配置
REMOTE_HOST=root@your.remote.host
REMOTE_PATH=/root/workspace/tg_download
```

### 2. 执行安全更新

```bash
./scripts/update_remote.sh
```

这个脚本的安全特性：
- ✅ **不会覆盖** 数据库文件 (*.db)
- ✅ **不会覆盖** 配置文件 (config.yaml, .env)
- ✅ **不会覆盖** 下载和缩略图数据
- ✅ 自动构建和同步前端
- ✅ 安全重启服务

### 3. 检查配置差异（可选）

如果 `config.example.yaml` 有更新，可以使用配置检查工具查看差异：

```bash
# 检查本地配置
python3 scripts/check_config_update.py --local

# 检查远程配置
python3 scripts/check_config_update.py --remote
```

### 4. 手动安全同步（不推荐）

如果必须手动同步，**请务必使用**以下命令：

```bash
rsync -avz \
  --exclude="*.db" \
  --exclude="*.db-shm" \
  --exclude="*.db-wal" \
  --exclude="data/" \
  --exclude="downloads/" \
  --exclude="thumbnails/" \
  --exclude="logs/" \
  --exclude="venv/" \
  --exclude=".venv/" \
  --exclude="web/node_modules/" \
  --exclude="__pycache__/" \
  --exclude="*.pyc" \
  --exclude=".pytest_cache/" \
  --exclude="*.session" \
  --exclude="*.session-journal" \
  --exclude=".git/" \
  --exclude=".trae/" \
  --exclude="config.yaml" \
  --exclude=".env" \
  ./ root@your.remote.host:/root/workspace/tg_download/
```

---

## 使用方式

### Dashboard 监控面板

访问 `http://your-server:8080/dashboard` 查看：
- 下载/上传统计
- 系统指标
- 去重功能（扫描群组、查看重复视频、下载唯一视频）

旧版页面仍然可以通过 `/dashboard-legacy` 访问。

### CLI 手动下载

```bash
# 下载单个视频
python -m src download "https://t.me/channel/123"

# 批量下载消息范围
python -m src download channel_name --range 100-200

# 指定输出目录
python -m src download "https://t.me/channel/123" -o /path/to/output
```

### Bot 交互下载

启动 serve 模式后，在 Telegram 中向你的 Bot 发送：

- 直接发送链接：`https://t.me/channel/123`（自动识别并下载）
- `/download https://t.me/channel/123` — 下载视频
- `/status` — 查看运行状态

下载完成后，Bot 会将文件直接发送给你（文件 < 2GB 时）。

---

## 迁移到新机器

将以下文件从旧机器复制到新机器的项目目录下即可：

```bash
scp config.yaml user_session.session user@new_server:/path/to/tg_download/
```

- `config.yaml` — 你的配置
- `user_session.session` — 登录会话（有了它不需要重新登录）
- `web/dist/` — 构建好的前端文件（可选，可在新机器重新构建）
- `downloads/` — 已下载的文件（可选）
- `downloads.db` — 下载历史记录（可选）

---

## 故障排查

| 问题 | 解决方案 |
|------|---------|
| `FloodWaitError` | Telegram 限流，程序会自动等待后重试 |
| `SessionPasswordNeededError` | 需要输入两步验证密码 |
| `AuthKeyUnregisteredError` | session 文件失效，删除 `*.session` 后重新登录 |
| Bot 不响应 | 检查 `bot_token` 是否正确，`allowed_users` 是否包含你的 ID |
| 无法下载私有频道 | 确保你的 Telegram 账号已加入该频道 |
| Dashboard 404 | 确保已构建 React 前端：`cd web && npm install && npm run build` |

---

## 安全注意事项

- `config.yaml`、`user_session.session`、`.env` 已在 `.gitignore` 中，不会被提交到 git
- session 文件等同于登录凭证，请妥善保管
- 建议使用环境变量传递敏感信息，而非明文写在配置文件中
- **永远不要** 直接 rsync 所有文件，务必使用 `scripts/update_remote.sh`
- **永远不要** 覆盖数据库文件或配置文件
