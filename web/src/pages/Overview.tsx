import { useEffect, useState } from 'react'
import {
  Typography,
  Box,
  Paper,
  Card,
  CardContent,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  CircularProgress,
  Divider,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { LineChart } from '@mui/x-charts/LineChart'
import { apiClient } from '../api/client'
import type { DashboardStats, DownloadItem, UploadItem, RecoveryItem } from '../types'

function formatFileSize(bytes: number): string {
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

function formatSpeed(kb_s: number): string {
  if (!kb_s) return '0 KB/s'
  if (kb_s >= 1024) {
    return `${(kb_s / 1024).toFixed(1)} MB/s`
  }
  return `${kb_s.toFixed(0)} KB/s`
}

function getStatusColor(status: string): 'success' | 'warning' | 'error' | 'default' {
  switch (status) {
    case 'completed':
      return 'success'
    case 'downloading':
    case 'uploading':
      return 'warning'
    case 'failed':
      return 'error'
    default:
      return 'default'
  }
}

export default function Overview() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [downloads, setDownloads] = useState<DownloadItem[]>([])
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [recoveries, setRecoveries] = useState<RecoveryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState({ stats: false, downloads: false, uploads: false, recoveries: false })

  const fetchData = async () => {
    try {
      const results = await Promise.allSettled([
        apiClient.getDashboardStats(),
        apiClient.getDownloads(),
        apiClient.getUploads(),
        apiClient.getRecoveries(),
      ])
      if (results[0].status === 'fulfilled') setStats(results[0].value)
      if (results[1].status === 'fulfilled') setDownloads(results[1].value)
      if (results[2].status === 'fulfilled') setUploads(results[2].value)
      if (results[3].status === 'fulfilled') setRecoveries(results[3].value)
      setErrors({
        stats: results[0].status === 'rejected',
        downloads: results[1].status === 'rejected',
        uploads: results[2].status === 'rejected',
        recoveries: results[3].status === 'rejected',
      })
    } catch (err) {
      console.error('Error fetching data:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [])

  const downloadChartData = downloads.slice(-8).map((item) => ({
    time: new Date(item.created_at).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    }),
    speed: Math.round(item.speed_kb_s),
  }))

  const uploadChartData = uploads.slice(-8).map((item) => ({
    time: new Date(item.created_at).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
    }),
    speed: Math.round(item.speed_kb_s),
  }))

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  const memPercent = stats?.system.memory_percent == null ? null : Math.round(stats.system.memory_percent)
  const cpuPercent = stats?.system.cpu_percent == null ? null : Math.round(stats.system.cpu_percent)
  const disk = stats?.system.disk
  const diskPercent = disk?.used_percent ?? 0

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 4 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700 }}>
            概览
          </Typography>
          <Typography variant="body1" sx={{ color: 'text.secondary', mt: 1 }}>
            监控您的下载和上传状态
          </Typography>
          {errors.stats && <Typography variant="body2" color="error" sx={{ mt: 1 }}>统计数据加载失败，请刷新重试</Typography>}
        </Box>
        <Button
          variant="contained"
          startIcon={<RefreshIcon />}
          onClick={fetchData}
          sx={{ borderRadius: 2 }}
        >
          刷新
        </Button>
      </Box>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mb: 4 }}>
        <Box sx={{ flex: '1 1 250px', minWidth: 250 }}>
          <Card elevation={1} sx={{ borderRadius: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    下载统计
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary', mt: 1 }}>
                    {stats ? stats.downloads.total : '不可用'}
                  </Typography>
                </Box>
                <Box sx={{ bgcolor: 'success.light', borderRadius: 2, p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ color: 'success.main', fontSize: 28 }}>📥</span>
                </Box>
              </Box>
              <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'warning.main' }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    活跃: {stats ? stats.downloads.active : '不可用'}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main' }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    完成: {stats ? stats.downloads.completed : '不可用'}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'error.main' }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    失败: {stats?.downloads.failed ?? '不可用'}
                  </Typography>
                </Box>
              </Box>
              <Divider sx={{ my: 2 }} />
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  平均速度:{' '}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {stats ? formatSpeed(stats.downloads.avg_speed_kb_s) : '不可用'}
                </Typography>
              </Box>
            </CardContent>
          </Card>
        </Box>

        <Box sx={{ flex: '1 1 250px', minWidth: 250 }}>
          <Card elevation={1} sx={{ borderRadius: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    上传统计
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary', mt: 1 }}>
                    {stats ? stats.uploads.total : '不可用'}
                  </Typography>
                </Box>
                <Box sx={{ bgcolor: 'primary.light', borderRadius: 2, p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ color: 'primary.main', fontSize: 28 }}>📤</span>
                </Box>
              </Box>
              <Box sx={{ display: 'flex', gap: 2, mt: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'warning.main' }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    活跃: {stats ? stats.uploads.active : '不可用'}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main' }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    完成: {stats ? stats.uploads.completed : '不可用'}
                  </Typography>
                </Box>
              </Box>
              <Divider sx={{ my: 2 }} />
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  平均速度:{' '}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {stats ? formatSpeed(stats.uploads.avg_speed_kb_s) : '不可用'}
                </Typography>
              </Box>
            </CardContent>
          </Card>
        </Box>

        <Box sx={{ flex: '1 1 250px', minWidth: 250 }}>
          <Card elevation={1} sx={{ borderRadius: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    内存使用
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary', mt: 1 }}>
                    {memPercent == null ? '不可用' : `${memPercent}%`}
                  </Typography>
                </Box>
                <Box sx={{ bgcolor: 'secondary.light', borderRadius: 2, p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ color: 'secondary.main', fontSize: 28 }}>🧠</span>
                </Box>
              </Box>
              <Box sx={{ mt: 2 }}>
                <Box sx={{ height: 8, bgcolor: 'grey.200', borderRadius: 4, overflow: 'hidden' }}>
                  <Box
                    sx={{
                      height: '100%',
                      width: `${memPercent ?? 0}%`,
                      bgcolor: 'secondary.main',
                      borderRadius: 4,
                      transition: 'width 0.5s ease',
                    }}
                  />
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Box>

        <Box sx={{ flex: '1 1 250px', minWidth: 250 }}>
          <Card elevation={1} sx={{ borderRadius: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    CPU使用
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary', mt: 1 }}>
                    {cpuPercent == null ? '不可用' : `${cpuPercent}%`}
                  </Typography>
                </Box>
                <Box sx={{ bgcolor: 'warning.light', borderRadius: 2, p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ color: 'warning.main', fontSize: 28 }}>⚡</span>
                </Box>
              </Box>
              <Box sx={{ mt: 2 }}>
                <Box sx={{ height: 8, bgcolor: 'grey.200', borderRadius: 4, overflow: 'hidden' }}>
                  <Box
                    sx={{
                      height: '100%',
                      width: `${cpuPercent ?? 0}%`,
                      bgcolor: 'warning.main',
                      borderRadius: 4,
                      transition: 'width 0.5s ease',
                    }}
                  />
                </Box>
              </Box>
            </CardContent>
          </Card>
        </Box>

        <Box sx={{ flex: '1 1 250px', minWidth: 250 }}>
          <Card elevation={1} sx={{ borderRadius: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
                <Box>
                  <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 0.5 }}>
                    磁盘用量
                  </Typography>
                  <Typography variant="h4" sx={{ fontWeight: 700, color: 'text.primary', mt: 1 }}>
                    {disk?.available ? `${diskPercent}%` : '不可用'}
                  </Typography>
                </Box>
                <Box sx={{ bgcolor: 'info.light', borderRadius: 2, p: 1.5, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <span style={{ color: 'info.main', fontSize: 28 }}>💾</span>
                </Box>
              </Box>
              <Box sx={{ mt: 2 }}>
                <Box sx={{ height: 8, bgcolor: 'grey.200', borderRadius: 4, overflow: 'hidden' }}>
                  <Box
                    sx={{
                      height: '100%',
                      width: `${disk?.available ? diskPercent : 0}%`,
                      bgcolor: 'info.main',
                      borderRadius: 4,
                      transition: 'width 0.5s ease',
                    }}
                  />
                </Box>
                <Typography variant="body2" sx={{ color: 'text.secondary', mt: 1 }}>
                  {disk?.available
                    ? `已用 ${formatFileSize(disk.used_bytes ?? 0)} / 总量 ${formatFileSize(disk.total_bytes ?? 0)}，可用 ${formatFileSize(disk.free_bytes ?? 0)}`
                    : '磁盘容量不可用'}
                </Typography>
              </Box>
            </CardContent>
          </Card>
        </Box>
      </Box>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mb: 4 }}>
        <Box sx={{ flex: '1 1 400px', minWidth: 400 }}>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 3 }}>
              <span style={{ color: stats?.health_check.failed_checks_24h ? 'error.main' : 'success.main', fontSize: 24 }}>
                {stats?.health_check.failed_checks_24h ? '⚠️' : '✅'}
              </span>
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                服务健康状态
              </Typography>
            </Box>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
              <Box sx={{ flex: '1 1 150px', minWidth: 150 }}>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.5 }}>
                  24小时检查次数
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 700 }}>
                  {stats?.health_check.total_checks_24h || 0}
                </Typography>
              </Box>
              <Box sx={{ flex: '1 1 150px', minWidth: 150 }}>
                <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.5 }}>
                  24小时失败次数
                </Typography>
                <Typography variant="h5" sx={{ fontWeight: 700, color: stats?.health_check.failed_checks_24h ? 'error.main' : 'success.main' }}>
                  {stats?.health_check.failed_checks_24h || 0}
                </Typography>
              </Box>
            </Box>
            <Box sx={{ mt: 3, pt: 3, borderTop: 1, borderColor: 'divider' }}>
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                最后成功:{' '}
                {stats?.health_check.last_success
                  ? new Date(stats.health_check.last_success).toLocaleString('zh-CN')
                  : '-'}
              </Typography>
            </Box>
          </Paper>
        </Box>

        <Box sx={{ flex: '1 1 400px', minWidth: 400 }}>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 3 }}>
              <span style={{ color: 'action.active', fontSize: 24 }}>📋</span>
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                恢复历史
              </Typography>
            </Box>
            {errors.recoveries && <Typography variant="body2" color="error" sx={{ mb: 2 }}>恢复历史加载失败，请刷新重试</Typography>}
            {recoveries.length === 0 ? (
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                {errors.recoveries ? '数据加载失败' : '暂无恢复记录'}
              </Typography>
            ) : (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {recoveries.slice(0, 4).map((item, index) => (
                  <Box
                    key={index}
                    sx={{
                      p: 2,
                      bgcolor: 'background.default',
                      borderRadius: 2,
                      border: '1px solid',
                      borderColor: 'divider',
                    }}
                  >
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {item.action_taken}
                      </Typography>
                      <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                        {new Date(item.created_at).toLocaleString('zh-CN')}
                      </Typography>
                    </Box>
                    <Typography variant="body2" sx={{ color: 'text.secondary', mt: 1 }}>
                      {item.reason}
                    </Typography>
                  </Box>
                ))}
              </Box>
            )}
          </Paper>
        </Box>
      </Box>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mb: 4 }}>
        <Box sx={{ flex: '1 1 400px', minWidth: 400 }}>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 3 }}>
              下载速度趋势
            </Typography>
            {errors.downloads && <Typography variant="body2" color="error" sx={{ mb: 2 }}>下载数据加载失败，请刷新重试</Typography>}
            <Box sx={{ height: 200 }}>
              {downloadChartData.length > 0 ? (
                <LineChart
                  dataset={downloadChartData}
                  xAxis={[{ dataKey: 'time', scaleType: 'point' }]}
                  series={[
                    {
                      dataKey: 'speed',
                      label: 'KB/s',
                      color: '#4caf50',
                      showMark: false,
                    },
                  ]}
                  grid={{ vertical: true, horizontal: true }}
                />
              ) : (
                <Typography variant="body2" sx={{ color: 'text.secondary', pt: 8, textAlign: 'center' }}>
                  暂无速度数据
                </Typography>
              )}
            </Box>
          </Paper>
        </Box>

        <Box sx={{ flex: '1 1 400px', minWidth: 400 }}>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 3 }}>
              上传速度趋势
            </Typography>
            {errors.uploads && <Typography variant="body2" color="error" sx={{ mb: 2 }}>上传数据加载失败，请刷新重试</Typography>}
            <Box sx={{ height: 200 }}>
              {uploadChartData.length > 0 ? (
                <LineChart
                  dataset={uploadChartData}
                  xAxis={[{ dataKey: 'time', scaleType: 'point' }]}
                  series={[
                    {
                      dataKey: 'speed',
                      label: 'KB/s',
                      color: '#1976d2',
                      showMark: false,
                    },
                  ]}
                  grid={{ vertical: true, horizontal: true }}
                />
              ) : (
                <Typography variant="body2" sx={{ color: 'text.secondary', pt: 8, textAlign: 'center' }}>
                  暂无速度数据
                </Typography>
              )}
            </Box>
          </Paper>
        </Box>
      </Box>

      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
        <Box sx={{ flex: '1 1 400px', minWidth: 400 }}>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 3 }}>
              下载历史
            </Typography>
            {errors.downloads && <Typography variant="body2" color="error" sx={{ mb: 2 }}>下载历史加载失败，请刷新重试</Typography>}
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>文件名</TableCell>
                    <TableCell align="right">大小</TableCell>
                    <TableCell align="right">速度</TableCell>
                    <TableCell align="right">状态</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {downloads.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={4} align="center" sx={{ color: 'text.secondary' }}>
                        {errors.downloads ? '数据加载失败' : '暂无记录'}
                      </TableCell>
                    </TableRow>
                  )}
                  {downloads.slice(0, 6).map((item, index) => (
                    <TableRow key={index} hover>
                      <TableCell>
                        <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 150 }}>
                          {item.filename}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">{formatFileSize(item.file_size_bytes)}</TableCell>
                      <TableCell align="right">{formatSpeed(item.speed_kb_s)}</TableCell>
                      <TableCell align="right">
                        <Chip
                          label={
                            item.status === 'completed'
                              ? '已完成'
                              : item.status === 'downloading'
                              ? '下载中'
                              : item.status
                          }
                          color={getStatusColor(item.status)}
                          size="small"
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Box>

        <Box sx={{ flex: '1 1 400px', minWidth: 400 }}>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 3 }}>
              上传历史
            </Typography>
            {errors.uploads && <Typography variant="body2" color="error" sx={{ mb: 2 }}>上传历史加载失败，请刷新重试</Typography>}
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>文件名</TableCell>
                    <TableCell align="right">大小</TableCell>
                    <TableCell align="right">速度</TableCell>
                    <TableCell align="right">状态</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {uploads.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={4} align="center" sx={{ color: 'text.secondary' }}>
                        {errors.uploads ? '数据加载失败' : '暂无记录'}
                      </TableCell>
                    </TableRow>
                  )}
                  {uploads.slice(0, 6).map((item, index) => (
                    <TableRow key={index} hover>
                      <TableCell>
                        <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 150 }}>
                          {item.filename}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">{formatFileSize(item.file_size_bytes)}</TableCell>
                      <TableCell align="right">{formatSpeed(item.speed_kb_s)}</TableCell>
                      <TableCell align="right">
                        <Chip
                          label={
                            item.status === 'completed'
                              ? '已完成'
                              : item.status === 'uploading'
                              ? '上传中'
                              : item.status
                          }
                          color={getStatusColor(item.status)}
                          size="small"
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </Box>
      </Box>

      <Box sx={{ textAlign: 'center', mt: 4 }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          最后更新: {new Date().toLocaleString('zh-CN')}
        </Typography>
      </Box>
    </Box>
  )
}
