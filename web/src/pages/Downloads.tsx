import { useEffect, useState } from 'react'
import {
  Typography,
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Button,
  CircularProgress,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { apiClient } from '../api/client'
import type { DownloadItem } from '../types'

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
      return 'warning'
    case 'failed':
      return 'error'
    default:
      return 'default'
  }
}

export default function Downloads() {
  const [downloads, setDownloads] = useState<DownloadItem[]>([])
  const [loading, setLoading] = useState(true)

  const fetchData = async () => {
    try {
      const data = await apiClient.getDownloads()
      setDownloads(data)
    } catch (err) {
      console.error('Error fetching downloads:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 10000)
    return () => clearInterval(interval)
  }, [])

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 4 }}>
        <Box>
          <Typography variant="h4" sx={{ fontWeight: 700 }}>
            下载历史
          </Typography>
          <Typography variant="body1" sx={{ color: 'text.secondary', mt: 1 }}>
            查看所有下载任务
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

      <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 8 }}>
            <CircularProgress />
          </Box>
        ) : (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>文件名</TableCell>
                  <TableCell align="right">大小</TableCell>
                  <TableCell align="right">速度</TableCell>
                  <TableCell align="right">状态</TableCell>
                  <TableCell align="right">时间</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {downloads.map((item, index) => (
                  <TableRow key={index} hover>
                    <TableCell>
                      <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 250 }}>
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
                    <TableCell align="right">
                      <Typography variant="body2" sx={{ color: 'text.secondary' }}>
                        {new Date(item.created_at).toLocaleString('zh-CN')}
                      </Typography>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Paper>
    </Box>
  )
}
