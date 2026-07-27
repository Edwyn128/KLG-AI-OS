import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import { useUIStore } from '@/store/uiStore'
import { AppLayout } from '@/components/layout/AppLayout'
import { LoginModal } from '@/components/auth/LoginModal'

export function App() {
  const { hydrate, isAuthenticated, showLogin } = useAuthStore()
  const { hydrateCompact, hydrateTheme } = useUIStore()

  useEffect(() => {
    hydrate()
    hydrateCompact()
    hydrateTheme()
  }, [hydrate, hydrateCompact, hydrateTheme])

  return (
    <>
      {(isAuthenticated || !showLogin) && <AppLayout />}
      <LoginModal />
    </>
  )
}
