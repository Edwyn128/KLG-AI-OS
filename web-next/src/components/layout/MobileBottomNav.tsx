import { useState } from 'react'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import type { Workspace } from '@/types'
import styles from './MobileBottomNav.module.css'

interface TabDef {
  id: Workspace
  label: string
  icon: string
  staffOnly?: boolean
  adminOnly?: boolean
  superAdminOnly?: boolean
  accountingOnly?: boolean
}

const PRIMARY_MOBILE_TABS: TabDef[] = [
  { id: 'today',     label: 'Today',     icon: 'wb_sunny' },
  { id: 'matters',   label: 'Matters',   icon: 'folder_open' },
  { id: 'chat',      label: 'Chat',      icon: 'chat' },
  { id: 'deadlines', label: 'Deadlines', icon: 'event_upcoming', staffOnly: true },
]

const SECONDARY_MOBILE_TABS: TabDef[] = [
  { id: 'skills',     label: 'Skills',     icon: 'bolt',                 staffOnly: true },
  { id: 'bloodhound', label: 'Bloodhound', icon: 'radar',                adminOnly: true },
  { id: 'accounting', label: 'Accounting', icon: 'receipt_long',         accountingOnly: true },
  { id: 'admin',      label: 'Admin',      icon: 'admin_panel_settings', superAdminOnly: true },
]

export function MobileBottomNav() {
  const { activeWorkspace, setWorkspace } = useUIStore()
  const { isClient, isAdmin, isSuperAdmin, isAccounting } = useAuthStore()
  const [drawerOpen, setDrawerOpen] = useState(false)

  const filterTab = (t: TabDef) => {
    if (isClient)         return !t.staffOnly && !t.adminOnly && !t.superAdminOnly && !t.accountingOnly
    if (t.superAdminOnly) return isSuperAdmin
    if (t.adminOnly)      return isAdmin || isSuperAdmin
    if (t.accountingOnly) return isAccounting || isSuperAdmin
    return true
  }

  const primaryTabs = PRIMARY_MOBILE_TABS.filter(filterTab)
  const secondaryTabs = SECONDARY_MOBILE_TABS.filter(filterTab)

  const handleSelectTab = (tabId: Workspace) => {
    setWorkspace(tabId)
    setDrawerOpen(false)
  }

  const isSecondaryActive = secondaryTabs.some(t => t.id === activeWorkspace)

  return (
    <>
      <nav className={styles.bottomNav}>
        {primaryTabs.map(tab => (
          <button
            key={tab.id}
            className={`${styles.navItem} ${activeWorkspace === tab.id ? styles.active : ''}`}
            onClick={() => handleSelectTab(tab.id)}
          >
            <span className={`material-symbols-outlined ${styles.icon}`}>{tab.icon}</span>
            <span>{tab.label}</span>
          </button>
        ))}

        {secondaryTabs.length > 0 && (
          <button
            className={`${styles.navItem} ${isSecondaryActive ? styles.active : ''}`}
            onClick={() => setDrawerOpen(true)}
          >
            <span className={`material-symbols-outlined ${styles.icon}`}>grid_view</span>
            <span>More</span>
          </button>
        )}
      </nav>

      {drawerOpen && (
        <>
          <div className={styles.drawerOverlay} onClick={() => setDrawerOpen(false)} />
          <div className={styles.drawerContent}>
            <div className={styles.drawerHeader}>
              <span className={styles.drawerTitle}>Workspaces</span>
              <button className={styles.closeBtn} onClick={() => setDrawerOpen(false)}>
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
            <div className={styles.drawerGrid}>
              {secondaryTabs.map(tab => (
                <button
                  key={tab.id}
                  className={`${styles.drawerItem} ${activeWorkspace === tab.id ? styles.active : ''}`}
                  onClick={() => handleSelectTab(tab.id)}
                >
                  <span className={`material-symbols-outlined ${styles.drawerIcon}`}>{tab.icon}</span>
                  <span>{tab.label}</span>
                </button>
              ))}
            </div>
          </div>
        </>
      )}
    </>
  )
}
