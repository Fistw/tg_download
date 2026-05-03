#!/bin/bash
# 查看远程服务器的 tg-download 日志

set -e

SCRIPT_DIR="$(dirname "$0")"
cd "$SCRIPT_DIR/.."

# 检查是否有 .env 文件
if [ ! -f .env ]; then
    echo "❌ 未找到 .env 文件"
    echo "请从 .env.example 复制一份并填写配置"
    exit 1
fi

# 从 .env 文件读取配置
echo "📄 从 .env 文件读取配置..."
source .env 2>/dev/null || true
REMOTE_HOST=$(grep REMOTE_HOST .env | cut -d'=' -f2)
REMOTE_PATH=$(grep REMOTE_PATH .env | cut -d'=' -f2)

if [ -z "$REMOTE_HOST" ] || [ -z "$REMOTE_PATH" ]; then
    echo "❌ REMOTE_HOST 或 REMOTE_PATH 未在 .env 文件中设置"
    exit 1
fi

# 显示选项菜单
echo "========================================="
echo "  选择日志查看方式"
echo "========================================="
echo "远程主机: $REMOTE_HOST"
echo "远程路径: $REMOTE_PATH"
echo ""
echo "1) 查看系统服务日志 (systemctl)"
echo "2) 查看完整日志 (cat)"
echo "3) 查看最新日志 (tail -100)"
echo "4) 实时跟踪日志 (tail -f)"
echo "5) 搜索速度相关日志 (grep -i 'speed\|upload')"
echo "0) 退出"
echo ""

read -p "请输入选项 [0-5]: " choice

case $choice in
    1)
        echo "📋 查看系统服务日志..."
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && systemctl status tg-download -n 100"
        ;;
    2)
        echo "📄 查看完整日志..."
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && cat logs/tg_download.log"
        ;;
    3)
        echo "📋 查看最新日志 (最后 100 行)..."
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && tail -100 logs/tg_download.log"
        ;;
    4)
        echo "🚀 实时跟踪日志 (按 Ctrl+C 停止)..."
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && tail -f logs/tg_download.log"
        ;;
    5)
        echo "🔍 搜索速度相关日志..."
        ssh "$REMOTE_HOST" "cd $REMOTE_PATH && grep -i 'speed\\|upload' logs/tg_download.log || true"
        ;;
    0)
        echo "👋 退出"
        exit 0
        ;;
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac
