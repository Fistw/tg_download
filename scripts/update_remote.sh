#!/bin/bash

# ========================================
# 从 .env 文件读取配置（或使用环境变量）
# ========================================
# 项目根目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 从 .env 文件加载配置（如果存在）
if [ -f "$PROJECT_DIR/.env" ]; then
    echo "📄 从 .env 文件读取配置..."
    set -a  # 自动 export 变量
    source "$PROJECT_DIR/.env"
    set +a
fi

# 检查 REMOTE_HOST 是否配置
if [ -z "$REMOTE_HOST" ]; then
    echo "❌ 请先配置远程服务器！"
    echo "方式 1：复制 .env.example 为 .env 并填入真实配置"
    echo "        cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env"
    echo "        然后编辑 $PROJECT_DIR/.env"
    echo "方式 2：设置环境变量"
    echo "        export REMOTE_HOST=\"root@your.remote.host\""
    echo "        export REMOTE_PATH=\"/root/workspace/tg_download\""
    exit 1
fi

# 默认 REMOTE_PATH
if [ -z "$REMOTE_PATH" ]; then
    REMOTE_PATH="/root/workspace/tg_download"
fi

echo "========================================"
echo "  开始同步代码到远程服务器"
echo "========================================"
echo "远程主机: $REMOTE_HOST"
echo "远程路径: $REMOTE_PATH"
echo ""

# 检查 rsync 是否可用
if ! command -v rsync &> /dev/null; then
    echo "⚠️  远程服务器没有 rsync，尝试使用 git pull 方式..."
    
    # 如果没有 rsync，尝试用 git 方式
    git status &> /dev/null
    if [ $? -eq 0 ]; then
        # 检查是否有未提交的改动
        if ! git diff --quiet; then
            echo "⚠️  本地有未提交的改动，先 commit..."
            git add -A
            git commit -m "chore: 更新代码（自动）"
        fi
        
        # 推送到 GitHub
        echo "📤 推送代码到 GitHub..."
        git push || { echo "❌ 推送失败！"; exit 1; }
        echo "✓ 推送成功"
        
        # 让用户自己在远程 git pull
        echo ""
        echo "========================================"
        echo "  ✅ 已推送到 GitHub！"
        echo "  现在请在远程服务器上执行："
        echo "  cd $REMOTE_PATH"
        echo "  git pull"
        echo "  systemctl restart tg-download.service"
        echo "========================================"
        exit 0
    fi
fi

# 1. 使用 rsync 直接同步文件
echo "📤 同步文件到远程服务器..."
rsync -avz --delete \
  --exclude=".git" \
  --exclude=".venv" \
  --exclude="__pycache__" \
  --exclude="*.pyc" \
  --exclude="user_session.session" \
  --exclude="user_session_bot.session" \
  --exclude="config.yaml" \
  --exclude="downloads/" \
  --exclude="*.db" \
  ./ "$REMOTE_HOST:$REMOTE_PATH/"

if [ $? -ne 0 ]; then
    echo "❌ 同步失败！"
    exit 1
fi
echo "✓ 同步成功"
echo ""

# 2. 连接远程服务器，重启服务
echo "🔄 连接远程服务器..."
ssh "$REMOTE_HOST" << 'REMOTE_EOF'
cd /root/workspace/tg_download || exit 1

echo "🔄 重启 tg-download 服务..."
if command -v systemctl &> /dev/null; then
    systemctl restart tg-download.service 2>/dev/null || systemctl restart tg-download 2>/dev/null
else
    echo "⚠️  没有找到 systemctl，请手动重启"
fi

echo "✅ 完成！"
echo "📋 查看最新日志（如果可用）..."
if command -v journalctl &> /dev/null; then
    journalctl -u tg-download.service -n 30 --no-pager 2>/dev/null || true
fi
REMOTE_EOF

echo ""
echo "========================================"
echo "  ✅ 远程更新完成！"
echo "========================================"

