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
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
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

  const fetchData = async () => {
    try {
      const [statsData, downloadsData, uploadsData, recoveriesData] = await Promise.all([
        apiClient.getDashboardStats(),
        apiClient.getDownloads(),
        apiClient.getUploads(),
        apiClient.getRecoveries(),
      ])
      setStats(statsData)
      setDownloads(downloadsData)
      setUploads(uploadsData)
      setRecoveries(recoveriesData)
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

  const memPercent = stats ? Math.round(stats.system.memory_percent) : 0
  const cpuPercent = stats ? Math.round(stats.system.cpu_percent) : 0

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
                    {stats?.downloads.total || 0}
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
                    活跃: {stats?.downloads.active || 0}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main' }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    完成: {stats?.downloads.completed || 0}
                  </Typography>
                </Box>
              </Box>
              <Divider sx={{ my: 2 }} />
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  平均速度:{' '}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {formatSpeed(stats?.downloads.avg_speed_kb_s || 0)}
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
                    {stats?.uploads.total || 0}
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
                    活跃: {stats?.uploads.active || 0}
                  </Typography>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: 'success.main' }} />
                  <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                    完成: {stats?.uploads.completed || 0}
                  </Typography>
                </Box>
              </Box>
              <Divider sx={{ my: 2 }} />
              <Box>
                <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                  平均速度:{' '}
                </Typography>
                <Typography variant="body2" sx={{ fontWeight: 600 }}>
                  {formatSpeed(stats?.uploads.avg_speed_kb_s || 0)}
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
                    {memPercent}%
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
                      width: `${memPercent}%`,
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
                    {cpuPercent}%
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
                      width: `${cpuPercent}%`,
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
            {recoveries.length === 0 ? (
              <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                暂无恢复记录
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
            <Box sx={{ height: 200 }}>
              {downloadChartData.length > 0 && (
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
              )}
            </Box>
          </Paper>
        </Box>

        <Box sx={{ flex: '1 1 400px', minWidth: 400 }}>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Typography variant="h6" sx={{ fontWeight: 600, mb: 3 }}>
              上传速度趋势
            </Typography>
            <Box sx={{ height: 200 }}>
              {uploadChartData.length > 0 && (
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
