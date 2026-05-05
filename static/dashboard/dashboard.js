// 图表实例
let downloadChart, uploadChart;

// 格式化文件大小
function formatFileSize(bytes) {
    if (!bytes) return '-';
    const units = ['B', 'KB', 'MB', 'GB'];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
        size /= 1024;
        i++;
    }
    return `${size.toFixed(1)} ${units[i]}`;
}

// 格式化速度
function formatSpeed(kb_s) {
    if (!kb_s) return '0 KB/s';
    if (kb_s >= 1024) {
        return `${(kb_s / 1024).toFixed(1)} MB/s`;
    }
    return `${kb_s.toFixed(0)} KB/s`;
}

// 初始化图表
function initCharts() {
    const dlCtx = document.getElementById('downloadChart').getContext('2d');
    const ulCtx = document.getElementById('uploadChart').getContext('2d');
    
    // 下载图表
    downloadChart = new Chart(dlCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '下载速度 (KB/s)',
                data: [],
                borderColor: 'rgb(34, 197, 94)',
                backgroundColor: 'rgba(34, 197, 94, 0.1)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    ticks: { color: 'rgba(148, 163, 184, 0.8)' },
                    grid: { color: 'rgba(71, 85, 105, 0.3)' }
                },
                y: {
                    ticks: { color: 'rgba(148, 163, 184, 0.8)' },
                    grid: { color: 'rgba(71, 85, 105, 0.3)' }
                }
            }
        }
    });
    
    // 上传图表
    uploadChart = new Chart(ulCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: '上传速度 (KB/s)',
                data: [],
                borderColor: 'rgb(59, 130, 246)',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                fill: true,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    ticks: { color: 'rgba(148, 163, 184, 0.8)' },
                    grid: { color: 'rgba(71, 85, 105, 0.3)' }
                },
                y: {
                    ticks: { color: 'rgba(148, 163, 184, 0.8)' },
                    grid: { color: 'rgba(71, 85, 105, 0.3)' }
                }
            }
        }
    });
}

// 更新健康检查显示
function updateHealthCheck(data) {
    const healthData = data.health_check;
    
    // 更新健康状态图标
    const healthIcon = document.getElementById('health-status-icon');
    if (healthData.failed_checks_24h > 0) {
        healthIcon.textContent = '🟡';
    } else {
        healthIcon.textContent = '🟢';
    }
    
    // 更新检查统计
    document.getElementById('health-total-checks').textContent = healthData.total_checks_24h;
    document.getElementById('health-failed-checks').textContent = healthData.failed_checks_24h;
    
    // 更新最后成功时间
    const lastSuccessEl = document.getElementById('health-last-success');
    if (healthData.last_success) {
        const lastSuccessDate = new Date(healthData.last_success);
        lastSuccessEl.textContent = `最后成功: ${lastSuccessDate.toLocaleString('zh-CN')}`;
    } else {
        lastSuccessEl.textContent = '最后成功: -';
    }
}

// 更新恢复历史
function updateRecoveryHistory(data) {
    const container = document.getElementById('recovery-history');
    if (!data || data.length === 0) {
        container.innerHTML = '<p class="text-slate-500 text-sm">暂无恢复记录</p>';
        return;
    }
    
    container.innerHTML = data.slice(0, 5).map(item => {
        const date = new Date(item.created_at);
        return `
            <div class="bg-slate-800/50 rounded p-3 border border-yellow-900/30">
                <div class="flex justify-between items-start">
                    <span class="text-yellow-400 font-medium">${item.action_taken}</span>
                    <span class="text-slate-500 text-xs">${date.toLocaleString('zh-CN')}</span>
                </div>
                <p class="text-slate-400 text-sm mt-1">${item.reason}</p>
            </div>
        `;
    }).join('');
}

// 更新统计卡片
function updateStats(data) {
    // 下载统计
    document.getElementById('download-total').textContent = data.downloads.total;
    document.getElementById('download-active').textContent = data.downloads.active;
    document.getElementById('download-completed').textContent = data.downloads.completed;
    document.getElementById('download-avg-speed').textContent = formatSpeed(data.downloads.avg_speed_kb_s);
    
    // 上传统计
    document.getElementById('upload-total').textContent = data.uploads.total;
    document.getElementById('upload-active').textContent = data.uploads.active;
    document.getElementById('upload-completed').textContent = data.uploads.completed;
    document.getElementById('upload-avg-speed').textContent = formatSpeed(data.uploads.avg_speed_kb_s);
    
    // 系统指标
    const memPercent = Math.round(data.system.memory_percent);
    const cpuPercent = Math.round(data.system.cpu_percent);
    document.getElementById('memory-percent').textContent = `${memPercent}%`;
    document.getElementById('memory-bar').style.width = `${memPercent}%`;
    document.getElementById('cpu-percent').textContent = `${cpuPercent}%`;
    document.getElementById('cpu-bar').style.width = `${cpuPercent}%`;
    
    // 更新健康检查信息
    if (data.health_check) {
        updateHealthCheck(data);
    }
    
    // 更新时间
    document.getElementById('last-updated').textContent = new Date().toLocaleString('zh-CN');
}

// 更新下载表格
function updateDownloadTable(data) {
    const tbody = document.getElementById('download-table');
    tbody.innerHTML = data.map(item => `
        <tr class="table-row border-b border-slate-700/50">
            <td class="py-2 px-1 text-slate-200 truncate max-w-[200px]" title="${item.filename}">${item.filename}</td>
            <td class="py-2 px-1 text-right text-slate-300">${formatFileSize(item.file_size_bytes)}</td>
            <td class="py-2 px-1 text-right text-green-400">${formatSpeed(item.speed_kb_s)}</td>
            <td class="py-2 px-1 text-right">
                <span class="px-2 py-1 rounded text-xs font-medium ${
                    item.status === 'completed' ? 'bg-green-900/50 text-green-400' :
                    item.status === 'downloading' ? 'bg-yellow-900/50 text-yellow-400' :
                    'bg-red-900/50 text-red-400'
                }">
                    ${item.status}
                </span>
            </td>
        </tr>
    `).join('');
}

// 更新上传表格
function updateUploadTable(data) {
    const tbody = document.getElementById('upload-table');
    tbody.innerHTML = data.map(item => `
        <tr class="table-row border-b border-slate-700/50">
            <td class="py-2 px-1 text-slate-200 truncate max-w-[200px]" title="${item.filename}">${item.filename}</td>
            <td class="py-2 px-1 text-right text-slate-300">${formatFileSize(item.file_size_bytes)}</td>
            <td class="py-2 px-1 text-right text-blue-400">${formatSpeed(item.speed_kb_s)}</td>
            <td class="py-2 px-1 text-right">
                <span class="px-2 py-1 rounded text-xs font-medium ${
                    item.status === 'completed' ? 'bg-green-900/50 text-green-400' :
                    item.status === 'uploading' ? 'bg-yellow-900/50 text-yellow-400' :
                    'bg-red-900/50 text-red-400'
                }">
                    ${item.status}
                </span>
            </td>
        </tr>
    `).join('');
}

// 更新图表
function updateCharts(downloadData, uploadData) {
    // 下载数据
    const dlLabels = downloadData.slice(-10).map(item => {
        const d = new Date(item.created_at);
        return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    });
    const dlSpeeds = downloadData.slice(-10).map(item => Math.round(item.speed_kb_s));
    downloadChart.data.labels = dlLabels;
    downloadChart.data.datasets[0].data = dlSpeeds;
    downloadChart.update('none');
    
    // 上传数据
    const ulLabels = uploadData.slice(-10).map(item => {
        const d = new Date(item.created_at);
        return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`;
    });
    const ulSpeeds = uploadData.slice(-10).map(item => Math.round(item.speed_kb_s));
    uploadChart.data.labels = ulLabels;
    uploadChart.data.datasets[0].data = ulSpeeds;
    uploadChart.update('none');
}

// 刷新数据
async function refreshData() {
    try {
        // 获取统计
        const statsResp = await fetch('/api/dashboard/stats');
        const stats = await statsResp.json();
        updateStats(stats);
        
        // 获取下载历史
        const dlResp = await fetch('/api/downloads');
        const dlData = await dlResp.json();
        updateDownloadTable(dlData);
        
        // 获取上传历史
        const ulResp = await fetch('/api/uploads');
        const ulData = await ulResp.json();
        updateUploadTable(ulData);
        
        // 获取恢复历史
        const recResp = await fetch('/api/health/recoveries');
        const recData = await recResp.json();
        updateRecoveryHistory(recData);
        
        // 更新图表
        updateCharts(dlData, ulData);
    } catch (err) {
        console.error('Error fetching data:', err);
    }
}

// 初始化
window.addEventListener('DOMContentLoaded', () => {
    initCharts();
    refreshData();
    
    // 每10秒自动刷新
    setInterval(refreshData, 10000);
});
