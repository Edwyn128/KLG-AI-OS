import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import { useUIStore } from '@/store/uiStore'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoginModal } from '@/components/auth/LoginModal'

export function App() {
  const { hydrate, isAuthenticated, showLogin } = useAuthStore()
  const { hydrateCompact } = useUIStore()

  useEffect(() => {
    hydrate()
    hydrateCompact()
  }, [hydrate, hydrateCompact])

  return (
    <>
      {(isAuthenticated || !showLogin) && <AppLayout />}
      <LoginModal />
    </>
  )
}
