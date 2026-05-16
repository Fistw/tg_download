#!/bin/bash
set -euo pipefail

# ============================================================
# 数据库自动备份脚本
# 每日凌晨自动备份，最多保留 3 份
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

# 配置
BACKUP_DIR="$PROJECT_DIR/backups"
MAX_BACKUPS=3
DATE=$(date +%Y%m%d_%H%M%S)

# 数据库列表
DATABASES=(
    "downloads.db"
    "data/monitoring.db"
)

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  📦 数据库自动备份${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "备份时间: ${DATE}"
echo -e "备份目录: ${BACKUP_DIR}"
echo ""

# 创建备份目录
mkdir -p "$BACKUP_DIR"

# 备份每个数据库
BACKUP_SUCCESS=true
for DB in "${DATABASES[@]}"; do
    if [ -f "$DB" ]; then
        echo -e "${YELLOW}正在备份: ${DB}${NC}"
        
        DB_NAME=$(basename "$DB" .db)
        BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${DATE}.db.gz"
        
        # 使用 sqlite3 的 backup API 进行安全备份
        if sqlite3 "$DB" ".backup '$BACKUP_DIR/${DB_NAME}_${DATE}.tmp'" 2>/dev/null; then
            # 压缩备份文件
            gzip -f "$BACKUP_DIR/${DB_NAME}_${DATE}.tmp"
            mv "$BACKUP_DIR/${DB_NAME}_${DATE}.tmp.gz" "$BACKUP_FILE"
            
            # 显示备份信息
            SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
            echo -e "${GREEN}  ✓ 完成: ${BACKUP_FILE} (${SIZE})${NC}"
        else
            # 如果 sqlite3 backup 失败，使用简单的 cp + gzip
            echo -e "${YELLOW}  ⚠️  使用备用备份方法${NC}"
            cp "$DB" "$BACKUP_DIR/${DB_NAME}_${DATE}.tmp"
            gzip -f "$BACKUP_DIR/${DB_NAME}_${DATE}.tmp"
            mv "$BACKUP_DIR/${DB_NAME}_${DATE}.tmp.gz" "$BACKUP_FILE"
            
            SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
            echo -e "${GREEN}  ✓ 完成: ${BACKUP_FILE} (${SIZE})${NC}"
        fi
    else
        echo -e "${YELLOW}  ⚠️  跳过: ${DB} (文件不存在)${NC}"
    fi
done

# 清理旧备份（最多保留 MAX_BACKUPS 份）
echo ""
echo -e "${YELLOW}🧹 清理旧备份 (保留最近 ${MAX_BACKUPS} 份)...${NC}"

for DB in "${DATABASES[@]}"; do
    DB_NAME=$(basename "$DB" .db)
    BACKUP_FILES=("$BACKUP_DIR/${DB_NAME}_"*.db.gz)
    
    # 按时间排序，保留最近 MAX_BACKUPS 份
    if [ ${#BACKUP_FILES[@]} -gt $MAX_BACKUPS ]; then
        # 按修改时间排序，删除旧的
        IFS=$'\n' SORTED_FILES=($(ls -rt "${BACKUP_DIR}/${DB_NAME}_"*.db.gz 2>/dev/null))
        unset IFS
        
        NUM_TO_DELETE=$((${#SORTED_FILES[@]} - MAX_BACKUPS))
        if [ $NUM_TO_DELETE -gt 0 ]; then
            for ((i=0; i<NUM_TO_DELETE; i++)); do
                if [ -f "${SORTED_FILES[i]}" ]; then
                    echo -e "  删除: ${SORTED_FILES[i]}"
                    rm -f "${SORTED_FILES[i]}"
                fi
            done
        fi
    fi
    
    # 显示当前备份
    echo ""
    echo -e "${BLUE}📋 ${DB_NAME} 数据库当前备份:${NC}"
    ls -lh "$BACKUP_DIR/${DB_NAME}_"*.db.gz 2>/dev/null || echo "  (无备份文件)"
done

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}  ✅ 备份完成!${NC}"
echo -e "${BLUE}========================================${NC}"
