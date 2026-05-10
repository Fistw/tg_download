import { useEffect, useState, useCallback } from 'react'
import {
  Typography,
  Box,
  Paper,
  Button,
  Select,
  MenuItem,
  InputLabel,
  FormControl,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  CircularProgress,
  Alert,
  Snackbar,
  LinearProgress,
  IconButton,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PauseIcon from '@mui/icons-material/Pause'
import DownloadIcon from '@mui/icons-material/Download'
import RefreshIcon from '@mui/icons-material/Refresh'
import DeleteIcon from '@mui/icons-material/Delete'
import { apiClient } from '../api/client'
import type { ChatInfo, DedupeTask, DedupeMedia } from '../types'

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

function formatDuration(seconds: number | null): string {
  if (!seconds) return '-'
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

function getTaskStatusColor(
  status: string
): 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning' {
  switch (status) {
    case 'pending':
      return 'default'
    case 'scanning':
      return 'primary'
    case 'paused':
      return 'warning'
    case 'completed':
      return 'success'
    case 'failed':
      return 'error'
    default:
      return 'default'
  }
}

function getTaskStatusLabel(status: string): string {
  switch (status) {
    case 'pending':
      return '等待中'
    case 'scanning':
      return '扫描中'
    case 'paused':
      return '已暂停'
    case 'completed':
      return '已完成'
    case 'failed':
      return '失败'
    default:
      return status
  }
}

export default function Dedupe() {
  const [chats, setChats] = useState<ChatInfo[]>([])
  const [tasks, setTasks] = useState<DedupeTask[]>([])
  const [selectedChatId, setSelectedChatId] = useState<number | null>(null)
  const [currentTask, setCurrentTask] = useState<DedupeTask | null>(null)
  const [mediaList, setMediaList] = useState<DedupeMedia[]>([])
  const [pagination, setPagination] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMedia, setLoadingMedia] = useState(false)
  const [page, setPage] = useState(1)
  const [filterType, setFilterType] = useState('all')
  const [notification, setNotification] = useState<{
    message: string
    type: 'success' | 'error'
  } | null>(null)

  const showNotification = (message: string, type: 'success' | 'error') => {
    setNotification({ message, type })
  }

  const fetchChats = useCallback(async () => {
    try {
      const data = await apiClient.getChats()
      setChats(data)
    } catch (err) {
      console.error('Error fetching chats:', err)
    }
  }, [])

  const fetchTasks = useCallback(async () => {
    try {
      const data = await apiClient.getDedupeTasks()
      setTasks(data)
      if (data.length > 0 && !currentTask) {
        setCurrentTask(data[0])
      }
    } catch (err) {
      console.error('Error fetching tasks:', err)
    }
  }, [currentTask])

  const fetchMedia = useCallback(
    async (taskId: number, pageNum: number = 1) => {
      if (!taskId) return
      setLoadingMedia(true)
      try {
        const data = await apiClient.getDedupeMedia(taskId, {
          page: pageNum,
          limit: 20,
          filter_type: filterType,
        })
        setMediaList(data.items)
        setPagination(data.pagination)
        setPage(pageNum)
      } catch (err) {
        console.error('Error fetching media:', err)
      } finally {
        setLoadingMedia(false)
      }
    },
    [filterType]
  )

  useEffect(() => {
    const init = async () => {
      await Promise.all([fetchChats(), fetchTasks()])
      setLoading(false)
    }
    init()
  }, [fetchChats, fetchTasks])

  useEffect(() => {
    if (currentTask) {
      fetchMedia(currentTask.id, 1)
    }
  }, [currentTask, fetchMedia])

  useEffect(() => {
    const interval = setInterval(() => {
      if (currentTask && (currentTask.status === 'scanning' || currentTask.status === 'pending')) {
        fetchTasks()
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [currentTask, fetchTasks])

  const handleCreateTask = async () => {
    if (!selectedChatId) return
    try {
      const chat = chats.find((c) => c.id === selectedChatId)
      if (!chat) return
      const task = await apiClient.createDedupeTask({
        chat_id: selectedChatId,
        chat_title: chat.title,
      })
      setCurrentTask(task)
      await fetchTasks()
      showNotification('任务创建成功', 'success')
    } catch (err) {
      showNotification('创建任务失败', 'error')
    }
  }

  const handleStartTask = async () => {
    if (!currentTask) return
    try {
      await apiClient.startDedupeTask(currentTask.id)
      await fetchTasks()
      showNotification('开始扫描', 'success')
    } catch (err) {
      showNotification('启动失败', 'error')
    }
  }

  const handlePauseTask = async () => {
    if (!currentTask) return
    try {
      await apiClient.pauseDedupeTask(currentTask.id)
      await fetchTasks()
      showNotification('已暂停', 'success')
    } catch (err) {
      showNotification('暂停失败', 'error')
    }
  }

  const handleResumeTask = async () => {
    if (!currentTask) return
    try {
      await apiClient.resumeDedupeTask(currentTask.id)
      await fetchTasks()
      showNotification('继续扫描', 'success')
    } catch (err) {
      showNotification('恢复失败', 'error')
    }
  }

  const handleDownloadMedia = async (fileId?: string) => {
    if (!currentTask) return
    try {
      const result = await apiClient.downloadMedia(currentTask.id, {
        file_id: fileId,
        download_all: !fileId,
      })
      showNotification(`已下载 ${result.downloaded_count} 个文件`, 'success')
    } catch (err) {
      showNotification('下载失败', 'error')
    }
  }

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [taskToDelete, setTaskToDelete] = useState<number | null>(null)

  const handleDeleteTask = async (taskId: number) => {
    setTaskToDelete(taskId)
    setDeleteDialogOpen(true)
  }

  const confirmDeleteTask = async () => {
    if (!taskToDelete) return
    try {
      await apiClient.deleteDedupeTask(taskToDelete)
      showNotification('任务已删除', 'success')
      
      // 如果删除的是当前任务，取消选中状态
      if (currentTask && currentTask.id === taskToDelete) {
        setCurrentTask(null)
        setMediaList([])
        setPagination(null)
      }
      
      // 刷新任务列表
      await fetchTasks()
    } catch (err) {
      showNotification('删除任务失败', 'error')
    } finally {
      setDeleteDialogOpen(false)
      setTaskToDelete(null)
    }
  }

  const handleRestartTask = async (taskId: number) => {
    try {
      await apiClient.restartDedupeTask(taskId)
      showNotification('任务已重置并重新开始', 'success')
      
      // 如果是当前任务，刷新任务列表和媒体列表
      if (currentTask && currentTask.id === taskId) {
        await Promise.all([fetchTasks(), fetchMedia(taskId, 1)])
      } else {
        await fetchTasks()
      }
    } catch (err) {
      showNotification('重置任务失败', 'error')
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h4" sx={{ fontWeight: 700, mb: 1 }}>
        去重管理
      </Typography>
      <Typography variant="body1" sx={{ color: 'text.secondary', mb: 4 }}>
        扫描群组，识别和下载重复媒体文件
      </Typography>

      <Paper elevation={1} sx={{ borderRadius: 3, p: 3, mb: 3 }}>
        <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
          选择群组
        </Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, alignItems: 'flex-end' }}>
          <Box sx={{ flex: '1 1 250px', minWidth: 250 }}>
            <FormControl fullWidth>
              <InputLabel>群组</InputLabel>
              <Select
                value={selectedChatId || ''}
                label="群组"
                onChange={(e) => setSelectedChatId(Number(e.target.value))}
              >
                {chats.map((chat) => (
                  <MenuItem key={chat.id} value={chat.id}>
                    {chat.title}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
          <Box sx={{ flex: '0 0 auto' }}>
            <Button
              variant="contained"
              onClick={handleCreateTask}
              disabled={!selectedChatId}
              sx={{ borderRadius: 2, minWidth: 150 }}
            >
              创建任务
            </Button>
          </Box>
        </Box>
      </Paper>

      {currentTask && (
        <>
          <Paper elevation={1} sx={{ borderRadius: 3, p: 3, mb: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <Typography variant="h6" sx={{ fontWeight: 600 }}>
                  扫描进度
                </Typography>
                <Chip
                  label={getTaskStatusLabel(currentTask.status)}
                  color={getTaskStatusColor(currentTask.status)}
                  size="small"
                />
              </Box>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                {currentTask.status === 'pending' && (
                  <Button
                    variant="contained"
                    startIcon={<PlayArrowIcon />}
                    onClick={handleStartTask}
                    sx={{ borderRadius: 2 }}
                  >
                    开始扫描
                  </Button>
                )}
                {currentTask.status === 'scanning' && (
                  <Button
                    variant="outlined"
                    startIcon={<PauseIcon />}
                    onClick={handlePauseTask}
                    sx={{ borderRadius: 2 }}
                  >
                    暂停
                  </Button>
                )}
                {currentTask.status === 'paused' && (
                  <Button
                    variant="contained"
                    startIcon={<PlayArrowIcon />}
                    onClick={handleResumeTask}
                    sx={{ borderRadius: 2 }}
                  >
                    继续
                  </Button>
                )}
                {/* 失败任务可以重置 */}
                {currentTask.status === 'failed' && (
                  <Button
                    variant="contained"
                    startIcon={<RefreshIcon />}
                    onClick={() => handleRestartTask(currentTask.id)}
                    sx={{ borderRadius: 2 }}
                    color="warning"
                  >
                    重新开始
                  </Button>
                )}
                {/* 任何状态都可以重置（非扫描中） */}
                {(currentTask.status === 'completed' || currentTask.status === 'failed' || currentTask.status === 'pending') && (
                  <Tooltip title="重置任务">
                    <IconButton
                      onClick={() => handleRestartTask(currentTask.id)}
                      color="primary"
                    >
                      <RefreshIcon />
                    </IconButton>
                  </Tooltip>
                )}
                {/* 任何状态都可以删除 */}
                <Tooltip title="删除任务">
                  <IconButton
                    onClick={() => handleDeleteTask(currentTask.id)}
                    color="error"
                  >
                    <DeleteIcon />
                  </IconButton>
                </Tooltip>
              </Box>
            </Box>

            <Typography variant="subtitle1" sx={{ mb: 1 }}>
              {currentTask.chat_title}
            </Typography>
            <Box sx={{ mb: 2 }}>
              <LinearProgress
                variant="determinate"
                value={currentTask.progress}
                sx={{ borderRadius: 4, height: 8 }}
              />
            </Box>
            <Typography variant="body2" sx={{ color: 'text.secondary', mb: 2 }}>
              进度: {currentTask.progress}%
            </Typography>

            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mt: 1 }}>
              <Box sx={{ flex: '1 1 180px', minWidth: 180 }}>
                <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                    已处理
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    {currentTask.processed_messages}
                  </Typography>
                </Paper>
              </Box>
              <Box sx={{ flex: '1 1 180px', minWidth: 180 }}>
                <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                    独特媒体
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 700, color: 'success.main' }}>
                    {currentTask.unique_media}
                  </Typography>
                </Paper>
              </Box>
              <Box sx={{ flex: '1 1 180px', minWidth: 180 }}>
                <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                    重复媒体
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 700, color: 'warning.main' }}>
                    {currentTask.duplicate_count}
                  </Typography>
                </Paper>
              </Box>
              <Box sx={{ flex: '1 1 180px', minWidth: 180 }}>
                <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                  <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block' }}>
                    总消息
                  </Typography>
                  <Typography variant="h6" sx={{ fontWeight: 700 }}>
                    {currentTask.total_messages || '-'}
                  </Typography>
                </Paper>
              </Box>
            </Box>
          </Paper>

          <Paper elevation={1} sx={{ borderRadius: 3, p: 3 }}>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600 }}>
                媒体列表
              </Typography>
              <Box sx={{ display: 'flex', gap: 2 }}>
                <FormControl sx={{ minWidth: 120 }}>
                  <Select
                    value={filterType}
                    size="small"
                    onChange={(e) => setFilterType(e.target.value)}
                  >
                    <MenuItem value="all">全部</MenuItem>
                    <MenuItem value="singles">独特</MenuItem>
                    <MenuItem value="duplicates">重复</MenuItem>
                  </Select>
                </FormControl>
                <Button
                  variant="contained"
                  startIcon={<DownloadIcon />}
                  onClick={() => handleDownloadMedia()}
                  disabled={mediaList.length === 0}
                  sx={{ borderRadius: 2 }}
                >
                  下载全部
                </Button>
              </Box>
            </Box>

            {loadingMedia ? (
              <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
                <CircularProgress />
              </Box>
            ) : mediaList.length === 0 ? (
              <Box sx={{ textAlign: 'center', py: 6 }}>
                <Typography sx={{ color: 'text.secondary' }}>
                  暂无媒体文件
                </Typography>
              </Box>
            ) : (
              <TableContainer>
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell>预览</TableCell>
                      <TableCell>File ID</TableCell>
                      <TableCell align="right">大小</TableCell>
                      <TableCell align="right">时长</TableCell>
                      <TableCell align="right">出现次数</TableCell>
                      <TableCell align="right">操作</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {mediaList.map((media, index) => (
                      <TableRow key={index} hover>
                        <TableCell>
                          <Box
                            sx={{
                              width: 48,
                              height: 32,
                              bgcolor: 'grey.100',
                              borderRadius: 1.5,
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            <span style={{ color: 'grey.500', fontSize: 20 }}>🎬</span>
                          </Box>
                        </TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 150 }}>
                            {media.file_id.slice(0, 30)}...
                          </Typography>
                        </TableCell>
                        <TableCell align="right">{formatFileSize(media.file_size)}</TableCell>
                        <TableCell align="right">{formatDuration(media.duration)}</TableCell>
                        <TableCell align="right">
                          <Chip
                            label={media.occurrence_count}
                            color={media.occurrence_count > 1 ? 'warning' : 'success'}
                            size="small"
                          />
                        </TableCell>
                        <TableCell align="right">
                          <Button
                            variant="outlined"
                            size="small"
                            onClick={() => handleDownloadMedia(media.file_id)}
                            disabled={media.downloaded}
                            sx={{ borderRadius: 1.5 }}
                          >
                            {media.downloaded ? '已下载' : '下载'}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            )}

            {pagination && pagination.total_pages > 1 && (
              <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 2, mt: 3 }}>
                <Button
                  variant="outlined"
                  disabled={page <= 1}
                  onClick={() => fetchMedia(currentTask.id, page - 1)}
                  sx={{ borderRadius: 2 }}
                >
                  上一页
                </Button>
                <Typography>
                  第 {page} 页 / 共 {pagination.total_pages} 页
                </Typography>
                <Button
                  variant="outlined"
                  disabled={page >= pagination.total_pages}
                  onClick={() => fetchMedia(currentTask.id, page + 1)}
                  sx={{ borderRadius: 2 }}
                >
                  下一页
                </Button>
              </Box>
            )}
          </Paper>

          {tasks.length > 0 && (
            <Paper elevation={1} sx={{ borderRadius: 3, p: 3, mt: 3 }}>
              <Typography variant="h6" sx={{ fontWeight: 600, mb: 2 }}>
                历史任务
              </Typography>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                {tasks.map((task) => (
                  <Box
                    key={task.id}
                    sx={{
                      p: 2,
                      borderRadius: 2,
                      border: 1,
                      borderColor: task.id === currentTask?.id ? 'primary.main' : 'divider',
                      bgcolor: task.id === currentTask?.id ? 'primary.50' : 'grey.50',
                    }}
                  >
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <Box 
                        sx={{ 
                          flex: 1, cursor: 'pointer' }}
                        onClick={() => setCurrentTask(task)}
                      >
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {task.chat_title}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
                          进度: {task.progress}% | 独特: {task.unique_media} | 重复: {task.duplicate_count}
                        </Typography>
                      </Box>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 1 }}>
                        <Chip
                          label={getTaskStatusLabel(task.status)}
                          color={getTaskStatusColor(task.status)}
                          size="small"
                        />
                        {/* 重置按钮 - 非扫描中时显示 */}
                        {task.status !== 'scanning' && (
                          <Tooltip title="重置任务">
                            <IconButton
                              size="small"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleRestartTask(task.id);
                              }}
                              color="primary"
                            >
                              <RefreshIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                        {/* 删除按钮 */}
                        <Tooltip title="删除任务">
                          <IconButton
                            size="small"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleDeleteTask(task.id);
                            }}
                            color="error"
                          >
                            <DeleteIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </Box>
                    </Box>
                  </Box>
                ))}
              </Box>
            </Paper>
          )}
        </>
      )}

      <Snackbar
        open={!!notification}
        autoHideDuration={3000}
        onClose={() => setNotification(null)}
      >
        <Alert
          onClose={() => setNotification(null)}
          severity={notification?.type}
          sx={{ width: '100%' }}
        >
          {notification?.message}
        </Alert>
      </Snackbar>

      {/* 删除任务确认对话框 */}
      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
        aria-labelledby="delete-dialog-title"
        aria-describedby="delete-dialog-description"
      >
        <DialogTitle id="delete-dialog-title">确认删除任务</DialogTitle>
        <DialogContent>
          <DialogContentText id="delete-dialog-description">
            您确定要删除此任务吗？此操作将同时删除所有相关的媒体和结果记录，且不可恢复。
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)} disabled={false}>
            取消
          </Button>
          <Button onClick={confirmDeleteTask} color="error" variant="contained" autoFocus>
            确认删除
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
