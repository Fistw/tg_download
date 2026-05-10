import { AppBar, Toolbar, Typography, Button, Box } from '@mui/material'
import { Link, useLocation } from 'react-router-dom'
import DownloadIcon from '@mui/icons-material/Download'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import DashboardIcon from '@mui/icons-material/Dashboard'
import FilterAltIcon from '@mui/icons-material/FilterAlt'
import LogoutIcon from '@mui/icons-material/Logout'
import { apiClient } from '../api/client'

export default function Navbar() {
  const location = useLocation()
  const isInDashboard = location.pathname.startsWith('/dashboard')

  const isActive = (path: string): boolean => {
    const targetPath = isInDashboard ? `/dashboard${path}` : path
    return location.pathname === targetPath || (path === '/' && location.pathname === '/')
  }

  const getLinkPath = (path: string): string => {
    return isInDashboard ? `/dashboard${path}` : path
  }

  const handleLogout = async () => {
    try {
      await apiClient.logout()
      window.location.reload()
    } catch (error) {
      console.error('Logout error:', error)
      window.location.reload()
    }
  }

  return (
    <AppBar position="sticky" elevation={0} sx={{ bgcolor: 'background.paper', borderBottom: '1px solid', borderColor: 'divider' }}>
      <Toolbar sx={{ justifyContent: 'space-between', maxWidth: 'lg', mx: 'auto', width: '100%', px: 3 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <Box sx={{ bgcolor: 'primary.main', borderRadius: 2, p: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <DownloadIcon sx={{ color: 'white', fontSize: 24 }} />
          </Box>
          <Box>
            <Typography variant="h6" sx={{ fontWeight: 700, color: 'text.primary', lineHeight: 1.2 }}>
              tg-download
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              监控面板
            </Typography>
          </Box>
        </Box>

        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            component={Link}
            to={getLinkPath('/')}
            variant={isActive('/') ? 'contained' : 'text'}
            color="primary"
            startIcon={<DashboardIcon />}
            sx={{ borderRadius: 2, textTransform: 'none', fontWeight: 500 }}
          >
            概览
          </Button>
          <Button
            component={Link}
            to={getLinkPath('/downloads')}
            variant={isActive('/downloads') ? 'contained' : 'text'}
            color="primary"
            startIcon={<DownloadIcon />}
            sx={{ borderRadius: 2, textTransform: 'none', fontWeight: 500 }}
          >
            下载
          </Button>
          <Button
            component={Link}
            to={getLinkPath('/uploads')}
            variant={isActive('/uploads') ? 'contained' : 'text'}
            color="primary"
            startIcon={<CloudUploadIcon />}
            sx={{ borderRadius: 2, textTransform: 'none', fontWeight: 500 }}
          >
            上传
          </Button>
          <Button
            component={Link}
            to={getLinkPath('/dedupe')}
            variant={isActive('/dedupe') ? 'contained' : 'text'}
            color="primary"
            startIcon={<FilterAltIcon />}
            sx={{ borderRadius: 2, textTransform: 'none', fontWeight: 500 }}
          >
            去重
          </Button>
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box
              sx={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                bgcolor: 'success.main',
                animation: 'pulse 2s infinite',
                '@keyframes pulse': {
                  '0%, 100%': { opacity: 1 },
                  '50%': { opacity: 0.5 },
                },
              }}
            />
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              运行中
            </Typography>
          </Box>
          <Button
            variant="outlined"
            size="small"
            startIcon={<LogoutIcon />}
            onClick={handleLogout}
            sx={{ borderRadius: 2 }}
          >
            登出
          </Button>
        </Box>
      </Toolbar>
    </AppBar>
  )
}
