#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# 检查配置文件
if [ ! -f config.yaml ]; then
    echo "未找到 config.yaml，正在从 config.example.yaml 复制..."
    cp config.example.yaml config.yaml
    echo "请编辑 config.yaml 填入你的 Telegram API 凭据后重新运行"
    exit 1
fi

# 启动
echo "正在启动 tg-download..."
python3 -m src serve
