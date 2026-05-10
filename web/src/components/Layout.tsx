import { Outlet } from 'react-router-dom'
import Navbar from './Navbar'
import AuthGuard from './AuthGuard'
import { Container } from '@mui/material'

export default function Layout() {
  return (
    <AuthGuard>
      <Navbar />
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Outlet />
      </Container>
    </AuthGuard>
  )
}
