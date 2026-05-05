#!/bin/bash
# tg-download TCP 参数优化脚本
# 适用于 Linux 系统

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# 检查是否为 root 用户
check_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}错误: 此脚本需要 root 权限${NC}"
        echo -e "${YELLOW}请使用 sudo 或切换到 root 用户${NC}"
        exit 1
    fi
}

# 显示当前 TCP 参数
show_current() {
    echo -e "${BLUE}=== 当前 TCP 参数 ===${NC}"
    echo -e "${YELLOW}1. net.core.somaxconn:${NC} $(sysctl -n net.core.somaxconn 2>/dev/null || echo '默认值: 128')"
    echo -e "${YELLOW}2. net.core.netdev_max_backlog:${NC} $(sysctl -n net.core.netdev_max_backlog 2>/dev/null || echo '默认值: 1000')"
    echo -e "${YELLOW}3. net.ipv4.tcp_max_syn_backlog:${NC} $(sysctl -n net.ipv4.tcp_max_syn_backlog 2>/dev/null || echo '默认值: 1024')"
    echo -e "${YELLOW}4. net.ipv4.tcp_syncookies:${NC} $(sysctl -n net.ipv4.tcp_syncookies 2>/dev/null || echo '默认值: 1')"
    echo -e "${YELLOW}5. net.ipv4.tcp_tw_reuse:${NC} $(sysctl -n net.ipv4.tcp_tw_reuse 2>/dev/null || echo '默认值: 1')"
    echo -e "${YELLOW}6. net.core.rmem_max:${NC} $(sysctl -n net.core.rmem_max 2>/dev/null || echo '默认值: 16777216')"
    echo -e "${YELLOW}7. net.core.wmem_max:${NC} $(sysctl -n net.core.wmem_max 2>/dev/null || echo '默认值: 16777216')"
    echo ""
}

# 应用优化参数
apply_optimization() {
    echo -e "${BLUE}=== 正在应用 TCP 参数优化 ===${NC}"
    
    # 备份当前配置
    if [[ -f /etc/sysctl.conf ]]; then
        cp /etc/sysctl.conf /etc/sysctl.conf.backup.$(date +%Y%m%d_%H%M%S)
        echo -e "${GREEN}已备份当前 sysctl 配置${NC}"
    fi
    
    # 应用参数
    cat >> /etc/sysctl.conf << EOF

# tg-download TCP 优化配置
net.core.somaxconn = 4096
net.core.netdev_max_backlog = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.tcp_syncookies = 1
net.ipv4.tcp_tw_reuse = 1
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
EOF
    
    # 使参数生效
    sysctl -p
    
    echo -e "${GREEN}TCP 参数优化已应用!${NC}"
    echo ""
    show_current
}

# 恢复默认配置
restore_default() {
    echo -e "${BLUE}=== 正在恢复默认配置 ===${NC}"
    
    # 检查是否有备份文件
    local backups=(/etc/sysctl.conf.backup.*)
    if [[ -f /etc/sysctl.conf.backup.* ]]; then
        local latest_backup=$(ls -t /etc/sysctl.conf.backup.* | head -1)
        cp "$latest_backup" /etc/sysctl.conf
        sysctl -p
        echo -e "${GREEN}已从备份恢复: $latest_backup${NC}"
    else
        echo -e "${YELLOW}未找到备份文件${NC}"
        echo "尝试移除 tg-download 配置块..."
        if [[ -f /etc/sysctl.conf ]]; then
            grep -v -A 8 "# tg-download TCP 优化配置" /etc/sysctl.conf > /tmp/sysctl.tmp
            mv /tmp/sysctl.tmp /etc/sysctl.conf
            sysctl -p
            echo -e "${GREEN}已移除 tg-download 配置块${NC}"
        fi
    fi
}

# 主菜单
main() {
    check_root
    
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}tg-download TCP 参数优化工具${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
    
    case "${1:-check}" in
        check)
            show_current
            ;;
        apply)
            show_current
            apply_optimization
            ;;
        restore)
            restore_default
            ;;
        *)
            echo "使用方法: $0 {check|apply|restore}"
            echo ""
            echo "命令说明:"
            echo "  check   - 查看当前 TCP 参数 (默认)"
            echo "  apply   - 应用 TCP 优化参数"
            echo "  restore - 恢复默认配置"
            exit 1
            ;;
    esac
}

main "$@"
