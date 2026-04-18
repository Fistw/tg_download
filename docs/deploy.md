# tg-download 部署文档

## 前置条件

- 一台 Linux/macOS 服务器（推荐 Ubuntu 22.04+）
- Python 3.9+
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

脚本会引导你完成 Python 安装、配置填写、Telegram 登录和服务启动。

---

## 手动部署

### 第一步：安装 Python 并安装依赖

```bash
python3 --version  # 确保 3.9+
pip install -e .
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

## 使用方式

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

---

## 安全注意事项

- `config.yaml`、`user_session.session`、`.env` 已在 `.gitignore` 中，不会被提交到 git
- session 文件等同于登录凭证，请妥善保管
- 建议使用环境变量传递敏感信息，而非明文写在配置文件中
