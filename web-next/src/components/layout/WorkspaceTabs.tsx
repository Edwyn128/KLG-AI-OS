import { useUIStore } from '@/store/uiStore'
import type { Workspace } from '@/types'
import styles from './WorkspaceTabs.module.css'

const TABS: { id: Workspace; label: string; icon: string }[] = [
  { id: 'chat',     label: 'Matters',         icon: 'chat'            },
  { id: 'skills',  label: 'Skills Navigator', icon: 'bolt'            },
  { id: 'cases',   label: 'Case Files',       icon: 'folder_open'     },
  { id: 'activity',label: 'Activity Log',     icon: 'history'         },
]

export function WorkspaceTabs() {
  const { activeWorkspace, setWorkspace } = useUIStore()

  const handleTabClick = (id: Workspace) => {
    if (id !== 'chat' && id === activeWorkspace) {
      setWorkspace('chat')
    } else {
      setWorkspace(id)
    }
  }

  return (
    <nav className={styles.tabs}>
      {TABS.map(tab => (
        <button
          key={tab.id}
          className={`${styles.tab} ${activeWorkspace === tab.id ? styles.active : ''}`}
          onClick={() => handleTabClick(tab.id)}
        >
          <span className={`material-symbols-outlined ${styles.icon}`}>{tab.icon}</span>
          <span className={styles.label}>{tab.label}</span>
        </button>
      ))}
    </nav>
  )
}
