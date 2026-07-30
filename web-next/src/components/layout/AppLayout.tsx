import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { Header } from './Header'
import { WorkspaceTabs } from './WorkspaceTabs'
import { TodayWorkspace }      from '@/components/today/TodayWorkspace'
import { DashboardWorkspace }  from '@/components/dashboard/DashboardWorkspace'
import { ChatWorkspace }       from '@/components/chat/ChatWorkspace'
import { DeadlinesWorkspace }  from '@/components/deadlines/DeadlinesWorkspace'
import { BloodhoundWorkspace } from '@/components/bloodhound/BloodhoundWorkspace'
import { AccountingWorkspace } from '@/components/accounting/AccountingWorkspace'
import { AdminWorkspace }      from '@/components/admin/AdminWorkspace'
import { SkillsLauncher }      from '@/components/skills/SkillsLauncher'
import { SkillsWorkspace }     from '@/components/skills/SkillsWorkspace'
import styles from './AppLayout.module.css'

export function AppLayout() {
  const { activeWorkspace } = useUIStore()
  const { isClient } = useAuthStore()

  return (
    <div className={styles.shell}>
      <Header />
      <WorkspaceTabs />
      <main className={styles.workspace}>
        {activeWorkspace === 'today'      && <TodayWorkspace />}
        {activeWorkspace === 'matters'    && <DashboardWorkspace />}
        {activeWorkspace === 'chat'       && <ChatWorkspace />}
        {activeWorkspace === 'deadlines'  && <DeadlinesWorkspace />}
        {activeWorkspace === 'bloodhound' && <BloodhoundWorkspace />}
        {activeWorkspace === 'accounting' && <AccountingWorkspace />}
        {activeWorkspace === 'admin'      && <AdminWorkspace />}
        {activeWorkspace === 'skills'     && <SkillsWorkspace />}
      </main>
      {/* Skills execute firm-internal workflows — not available to client sessions. */}
      {!isClient && <SkillsLauncher />}
    </div>
  )
}
