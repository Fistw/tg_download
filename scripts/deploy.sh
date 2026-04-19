#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# tg-download 一键部署脚本
# 支持全新机器从零开始部署，包括安装 Python、配置、首次登录
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "========================================"
echo "  tg-download 一键部署"
echo "========================================"
echo ""

# ----------------------------------------------------------
# 1. 检查并安装 Python
# ----------------------------------------------------------
check_python() {
    echo "[1/5] 检查 Python..."

    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PYTHON_CMD="python"
    fi

    if [[ -n "$PYTHON_CMD" ]]; then
        echo "  ✓ Python 已安装: $($PYTHON_CMD --version)"
    else
        echo "  Python 未安装，正在安装..."
        if command -v apt-get &> /dev/null; then
            sudo apt-get update
            sudo apt-get install -y python3 python3-pip python3-venv
        elif command -v yum &> /dev/null; then
            sudo yum install -y python3 python3-pip
        elif [[ "$(uname)" == "Darwin" ]]; then
            echo "  请通过 Homebrew 安装: brew install python3"
            read -p "  安装完成后按回车继续..." _
        fi
        PYTHON_CMD="python3"
    fi

    # 安装项目依赖
    echo "  安装项目依赖..."
    $PYTHON_CMD -m pip install -e "$PROJECT_DIR" --quiet
    echo "  安装加密加速库 cryptg..."
    $PYTHON_CMD -m pip install cryptg --quiet
    echo "  ✓ 项目依赖已安装"
    echo ""
}

# ----------------------------------------------------------
# 2. 配置文件
# ----------------------------------------------------------
setup_config() {
    echo "[2/5] 配置文件..."

    if [ -f config.yaml ]; then
        echo "  config.yaml 已存在"
        read -p "  是否重新配置？(y/N) " answer
        if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
            echo "  跳过配置"
            echo ""
            return
        fi
    fi

    cp config.example.yaml config.yaml

    echo ""
    echo "  请输入以下信息（从 https://my.telegram.org 获取）:"
    echo ""

    read -p "  API ID: " api_id
    read -p "  API Hash: " api_hash
    read -p "  Bot Token (从 @BotFather 获取，留空跳过): " bot_token
    read -p "  你的 Telegram 用户 ID (从 @userinfobot 获取，留空跳过): " user_id

    # 写入配置
    if [[ "$(uname)" == "Darwin" ]]; then
        SED_INPLACE="sed -i ''"
    else
        SED_INPLACE="sed -i"
    fi

    $SED_INPLACE "s/api_id: 12345/api_id: $api_id/" config.yaml
    $SED_INPLACE "s/api_hash: \"your_api_hash\"/api_hash: \"$api_hash\"/" config.yaml

    if [[ -n "$bot_token" ]]; then
        $SED_INPLACE "s/bot_token: \"your_bot_token\"/bot_token: \"$bot_token\"/" config.yaml
    fi

    if [[ -n "$user_id" ]]; then
        $SED_INPLACE "s/allowed_users: \[\]/allowed_users:\n    - $user_id/" config.yaml
    fi

    echo "  ✓ config.yaml 已生成"
    echo ""
}

# ----------------------------------------------------------
# 3. 首次登录生成 session
# ----------------------------------------------------------
setup_session() {
    echo "[3/5] Telegram 登录..."

    if [ -f user_session.session ]; then
        echo "  session 文件已存在"
        read -p "  是否重新登录？(y/N) " answer
        if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
            echo "  跳过登录"
            echo ""
            return
        fi
    fi

    echo ""
    echo "  需要登录你的 Telegram 账号来生成 session 文件。"
    echo "  这是交互式过程，请按提示输入手机号和验证码。"
    echo ""

    $PYTHON_CMD -c "
import asyncio
from telethon import TelegramClient
import yaml

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

tg = cfg['telegram']

async def login():
    client = TelegramClient(tg['session_name'], tg['api_id'], tg['api_hash'])
    await client.start()
    me = await client.get_me()
    print(f'  ✓ 登录成功: {me.first_name} ({me.phone})')
    await client.disconnect()

asyncio.run(login())
"

    echo ""
}

# ----------------------------------------------------------
# 4. 创建必要目录
# ----------------------------------------------------------
setup_dirs() {
    echo "[4/5] 创建目录..."

    mkdir -p downloads
    echo "  ✓ downloads/ 目录已创建"
    echo ""
}

# ----------------------------------------------------------
# 5. 启动服务
# ----------------------------------------------------------
start_service() {
    echo "[5/5] 启动服务..."
    echo ""

    $PYTHON_CMD -m src serve

    echo ""
    echo "========================================"
    echo "  部署完成！"
    echo "========================================"
    echo ""
    echo "  后续可通过以下方式启动:"
    echo "    前台运行:     python3 -m src serve"
    echo "    后台运行:     nohup python3 -m src serve > tg_download.log 2>&1 &"
    echo "    启动脚本:     ./scripts/start.sh"
    echo ""

    if grep -q "bot_token.*your_bot_token" config.yaml 2>/dev/null; then
        echo "  提示: Bot Token 未配置，Bot 交互功能不可用"
    else
        echo "  现在可以在 Telegram 中给你的 Bot 发送链接来下载视频了！"
    fi
    echo ""
}

# ----------------------------------------------------------
# 主流程
# ----------------------------------------------------------
check_python
setup_config
setup_session
setup_dirs
start_service
