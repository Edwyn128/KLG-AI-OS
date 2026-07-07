import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoginModal } from '@/components/auth/LoginModal'

export function App() {
  const { hydrate, isAuthenticated, showLogin } = useAuthStore()

  useEffect(() => {
    hydrate()
  }, [hydrate])

  return (
    <>
      {(isAuthenticated || !showLogin) && <AppLayout />}
      <LoginModal />
    </>
  )
}
