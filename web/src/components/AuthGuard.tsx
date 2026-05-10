import { useState, useEffect } from 'react'
import { Box, Paper, Typography, TextField, Button, CircularProgress, Alert } from '@mui/material'
import { apiClient } from '../api/client'

interface AuthGuardProps {
  children: React.ReactNode
}

export default function AuthGuard({ children }: AuthGuardProps) {
  const [showLogin, setShowLogin] = useState(!apiClient.isAuthenticated())
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  const [loginError, setLoginError] = useState('')
  const [isLoggingIn, setIsLoggingIn] = useState(false)

  useEffect(() => {
    const handleAuthRequired = () => {
      setShowLogin(true)
    }
    window.addEventListener('authRequired', handleAuthRequired)
    return () => window.removeEventListener('authRequired', handleAuthRequired)
  }, [])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoggingIn(true)
    setLoginError('')

    try {
      const result = await apiClient.login(loginUsername, loginPassword)
      if (result.success) {
        setShowLogin(false)
      } else {
        setLoginError(result.message)
      }
    } catch (error) {
      setLoginError('登录失败，请稍后重试')
    } finally {
      setIsLoggingIn(false)
    }
  }

  // 登录界面
  if (showLogin) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '80vh' }}>
        <Paper elevation={3} sx={{ p: 4, width: '100%', maxWidth: 400, borderRadius: 3 }}>
          <Box sx={{ textAlign: 'center', mb: 3 }}>
            <Typography variant="h4" sx={{ fontWeight: 700, mb: 1 }}>
              Telegram 下载
            </Typography>
            <Typography variant="body1" sx={{ color: 'text.secondary' }}>
              请输入配置文件中设置的凭据
            </Typography>
          </Box>

          <form onSubmit={handleLogin}>
            <TextField
              fullWidth
              label="用户名"
              variant="outlined"
              value={loginUsername}
              onChange={(e) => setLoginUsername(e.target.value)}
              sx={{ mb: 2 }}
              autoComplete="username"
            />
            <TextField
              fullWidth
              label="密码"
              type="password"
              variant="outlined"
              value={loginPassword}
              onChange={(e) => setLoginPassword(e.target.value)}
              sx={{ mb: 2 }}
              autoComplete="current-password"
            />
            {loginError && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {loginError}
              </Alert>
            )}
            <Button
              fullWidth
              variant="contained"
              type="submit"
              disabled={isLoggingIn}
              sx={{ py: 1.5, borderRadius: 2 }}
            >
              {isLoggingIn ? <CircularProgress size={24} /> : '登录'}
            </Button>
          </form>
        </Paper>
      </Box>
    )
  }

  // 已认证，渲染子组件
  return <>{children}</>
}
