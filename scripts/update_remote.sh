#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 安全远程更新脚本
# 永远不会覆盖数据库和配置文件
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ========================================
# 从 .env 文件读取配置（或使用环境变量）
# ========================================
if [ -f "$PROJECT_DIR/.env" ]; then
    echo -e "${BLUE}📄 从 .env 文件读取配置...${NC}"
    set -a  # 自动 export 变量
    source "$PROJECT_DIR/.env"
    set +a
fi

# 检查 REMOTE_HOST 是否配置
if [ -z "${REMOTE_HOST:-}" ]; then
    echo -e "${RED}❌ 请先配置远程服务器！${NC}"
    echo ""
    echo "方式 1：复制 .env.example 为 .env 并填入真实配置"
    echo "        cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env"
    echo "        然后编辑 $PROJECT_DIR/.env"
    echo ""
    echo "方式 2：设置环境变量"
    echo "        export REMOTE_HOST=\"root@your.remote.host\""
    echo "        export REMOTE_PATH=\"/root/workspace/tg_download\""
    exit 1
fi

# 默认 REMOTE_PATH
if [ -z "${REMOTE_PATH:-}" ]; then
    REMOTE_PATH="/root/workspace/tg_download"
fi

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  🚀 安全远程更新${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "远程主机: ${BLUE}$REMOTE_HOST${NC}"
echo -e "远程路径: ${BLUE}$REMOTE_PATH${NC}"
echo ""

# ========================================
# 重要安全警告
# ========================================
echo -e "${YELLOW}⚠️  安全注意事项：${NC}"
echo -e "  - 不会覆盖数据库文件 (*.db)"
echo -e "  - 不会覆盖 config.yaml 和 .env"
echo -e "  - 不会覆盖下载和缩略图数据"
echo ""

# ========================================
# 1. 使用 rsync 安全同步文件
# ========================================
echo -e "${YELLOW}📤 同步应用文件...${NC}"
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
  ./ "$REMOTE_HOST:$REMOTE_PATH/"

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 同步失败！${NC}"
    exit 1
fi
echo -e "${GREEN}✓ 文件同步成功${NC}"
echo ""

# ========================================
# 2. 检查并处理远程配置文件
# ========================================
echo -e "${YELLOW}⚙️  检查远程配置...${NC}"
ssh "$REMOTE_HOST" << REMOTE_CONFIG
cd "$REMOTE_PATH" || exit 1
if [ ! -f "config.yaml" ]; then
    echo "  远程 config.yaml 未找到，从 example 创建..."
    cp config.example.yaml config.yaml
else
    echo "  远程 config.yaml 已存在，保持原样"
fi
REMOTE_CONFIG

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ 配置检查失败！${NC}"
    exit 1
fi

# ========================================
# 3. 构建并同步前端
# ========================================
echo ""
echo -e "${YELLOW}🔨 构建 React 前端...${NC}"
if [ -d web ]; then
    cd web
    
    if [ ! -d node_modules ]; then
        echo "  安装 npm 依赖..."
        npm install --quiet
    fi
    
    npm run build --quiet
    
    cd ..
    echo -e "${GREEN}✓ 前端构建完成${NC}"
    
    echo ""
    echo -e "${YELLOW}📦 同步前端文件...${NC}"
    rsync -avz --delete web/dist/ "$REMOTE_HOST:$REMOTE_PATH/web/dist/"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}❌ 前端同步失败！${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ 前端同步成功${NC}"
else
    echo -e "${YELLOW}⚠️  web 目录不存在，跳过前端构建${NC}"
fi

# ========================================
# 4. 连接远程服务器重启服务
# ========================================
echo ""
echo -e "${YELLOW}🔄 重启远程服务...${NC}"
ssh "$REMOTE_HOST" << REMOTE_EOF
cd "$REMOTE_PATH" || exit 1

echo "🔧 为数据库添加索引（如果需要）..."
if [ -f "downloads.db" ]; then
    python3 scripts/add_db_indexes.py downloads.db 2>/dev/null || echo "  ⚠️ 索引脚本执行失败，跳过"
else
    echo "  ⚠️ 未找到 downloads.db"
fi

echo "🔄 重启服务..."
if command -v systemctl &> /dev/null; then
    systemctl restart tg-download.service 2>/dev/null || systemctl restart tg-download 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "⚠️ systemctl 命令失败，请检查服务状态"
    fi
else
    echo "⚠️ 没有找到 systemctl，请手动重启服务"
fi

echo ""
echo "✅ 更新完成！"
echo "📋 服务状态（最近 30 条日志）..."
if command -v journalctl &> /dev/null; then
    journalctl -u tg-download.service -n 30 --no-pager 2>/dev/null || true
fi
REMOTE_EOF

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  ✅ 安全更新完成！${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}📍 未被覆盖的关键文件：${NC}"
echo -e "  - 所有数据库文件 (*.db)"
echo -e "  - config.yaml"
echo -e "  - .env"
echo -e "  - downloads/ 和 thumbnails/ 目录"
