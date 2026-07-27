import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import type { Workspace } from '@/types'
import styles from './WorkspaceTabs.module.css'

interface TabDef {
  id: Workspace
  label: string
  icon: string
  staffOnly?: boolean     // hidden from client users
  adminOnly?: boolean     // hidden unless isAdmin
  superAdminOnly?: boolean // hidden unless isSuperAdmin (Stu)
  accountingOnly?: boolean // hidden unless isAccounting
}

const TABS: TabDef[] = [
  { id: 'today',      label: 'Today',      icon: 'wb_sunny' },
  { id: 'matters',    label: 'Matters',    icon: 'folder_open' },
  { id: 'chat',       label: 'Chat',       icon: 'chat' },
  { id: 'deadlines',  label: 'Deadlines',  icon: 'event_upcoming',       staffOnly: true },
  { id: 'bloodhound', label: 'Bloodhound', icon: 'radar',                adminOnly: true },
  { id: 'accounting', label: 'Accounting', icon: 'receipt_long',         accountingOnly: true },
  { id: 'admin',      label: 'Admin',      icon: 'admin_panel_settings', superAdminOnly: true },
]

export function WorkspaceTabs() {
  const { activeWorkspace, setWorkspace } = useUIStore()
  const { isClient, isAdmin, isSuperAdmin, isAccounting } = useAuthStore()

  const visibleTabs = TABS.filter(t => {
    if (isClient)             return !t.staffOnly && !t.adminOnly && !t.superAdminOnly && !t.accountingOnly
    if (t.superAdminOnly)     return isSuperAdmin
    if (t.adminOnly)          return isAdmin || isSuperAdmin
    if (t.accountingOnly)     return isAccounting || isSuperAdmin
    return true
  })

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
