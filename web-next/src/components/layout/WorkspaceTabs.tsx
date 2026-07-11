import { useUIStore } from '@/store/uiStore'
import type { Workspace } from '@/types'
import styles from './WorkspaceTabs.module.css'

const TABS: { id: Workspace; label: string; icon: string }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: 'dashboard' },
  { id: 'chat',      label: 'Chat',      icon: 'chat'      },
]

export function WorkspaceTabs() {
  const { activeWorkspace, setWorkspace } = useUIStore()

  return (
    <nav className={styles.tabs}>
      {TABS.map(tab => (
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
