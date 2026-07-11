import { useUIStore } from '@/store/uiStore'
import { Header } from './Header'
import { WorkspaceTabs } from './WorkspaceTabs'
import { DashboardWorkspace } from '@/components/dashboard/DashboardWorkspace'
import { ChatWorkspace } from '@/components/chat/ChatWorkspace'
import { SkillsLauncher } from '@/components/skills/SkillsLauncher'
import styles from './AppLayout.module.css'

export function AppLayout() {
  const { activeWorkspace } = useUIStore()

  return (
    <div className={styles.shell}>
      <Header />
      <WorkspaceTabs />
      <main className={styles.workspace}>
        {activeWorkspace === 'dashboard' && <DashboardWorkspace />}
        {activeWorkspace === 'chat'      && <ChatWorkspace />}
      </main>
      <SkillsLauncher />
    </div>
  )
}
