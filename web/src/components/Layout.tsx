import { Outlet } from 'react-router-dom'
import Navbar from './Navbar'
import { Container } from '@mui/material'

export default function Layout() {
  return (
    <>
      <Navbar />
      <Container maxWidth="lg" sx={{ py: 4 }}>
        <Outlet />
      </Container>
    </>
  )
}
