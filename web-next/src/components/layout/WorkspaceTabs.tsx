import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import type { Workspace } from '@/types'
import styles from './WorkspaceTabs.module.css'

const TABS: { id: Workspace; label: string; icon: string; clientOnly?: false }[] = [
  { id: 'dashboard',  label: 'Dashboard',  icon: 'dashboard'  },
  { id: 'chat',       label: 'Chat',       icon: 'chat'       },
  { id: 'bloodhound', label: 'Bloodhound', icon: 'search'     },
]

export function WorkspaceTabs() {
  const { activeWorkspace, setWorkspace } = useUIStore()
  const { isClient } = useAuthStore()

  const visibleTabs = isClient ? TABS.filter(t => t.id !== 'bloodhound') : TABS

  return (
    <nav className={styles.tabs}>
      {visibleTabs.map(tab => (
        <button
          key={tab.id}
          className={`${styles.tab} ${activeWorkspace === tab.id ? styles.active : ''}`}
          onClick={() => setWorkspace(tab.id)}
        >
          <span className={`material-symbols-outlined ${styles.icon}`}>{tab.icon}</span>
          <span className={styles.label}>{tab.label}</span>
        </button>
      ))}
    </nav>
  )
}
