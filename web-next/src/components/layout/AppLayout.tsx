import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { Header } from './Header'
import { WorkspaceTabs } from './WorkspaceTabs'
import { DashboardWorkspace } from '@/components/dashboard/DashboardWorkspace'
import { ChatWorkspace } from '@/components/chat/ChatWorkspace'
import { SkillsLauncher } from '@/components/skills/SkillsLauncher'
import styles from './AppLayout.module.css'

export function AppLayout() {
  const { activeWorkspace } = useUIStore()
  const { isClient } = useAuthStore()

  return (
    <div className={styles.shell}>
      <Header />
      <WorkspaceTabs />
      <main className={styles.workspace}>
        {activeWorkspace === 'dashboard' && <DashboardWorkspace />}
        {activeWorkspace === 'chat'      && <ChatWorkspace />}
      </main>
      {/* Skills execute firm-internal workflows (Notion writes, Slack posts) —
          not available to client sessions. */}
      {!isClient && <SkillsLauncher />}
    </div>
  )
}
