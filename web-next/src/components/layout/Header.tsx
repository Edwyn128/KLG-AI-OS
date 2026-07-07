import { useEffect } from 'react'
import { useAuthStore } from '@/store/authStore'
import { useUIStore } from '@/store/uiStore'
import styles from './Header.module.css'

export function Header() {
  const { user, isAuthenticated, logout } = useAuthStore()
  const { isOnline, clock, setClock, setOnline } = useUIStore()

  useEffect(() => {
    function tick() {
      const now = new Date()
      const t = now.toLocaleTimeString('en-US', {
        hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/Los_Angeles',
      })
      setClock(t + ' PT')
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [setClock])

  useEffect(() => {
    function onOnline()  { setOnline(true)  }
    function onOffline() { setOnline(false) }
    window.addEventListener('online',  onOnline)
    window.addEventListener('offline', onOffline)
    return () => {
      window.removeEventListener('online',  onOnline)
      window.removeEventListener('offline', onOffline)
    }
  }, [setOnline])

  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <span className={styles.brandName}>KLG</span>
        <span className={styles.brandSub}>AI OS</span>
      </div>

      <div className={styles.right}>
        <span className={styles.clock}>{clock}</span>
        <span className={`${styles.statusDot} ${isOnline ? styles.online : styles.offline}`} title={isOnline ? 'Connected' : 'Offline'} />
        {isAuthenticated && (
          <button className={styles.userBtn} onClick={logout} title="Sign out">
            <span className={styles.userInitial}>{user[0] ?? '?'}</span>
            <span className={styles.userName}>{user}</span>
          </button>
        )}
      </div>
    </header>
  )
}
