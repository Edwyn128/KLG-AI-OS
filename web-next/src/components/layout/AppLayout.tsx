import { useUIStore } from '@/store/uiStore'
import { Header } from './Header'
import { WorkspaceTabs } from './WorkspaceTabs'
import { ChatWorkspace } from '@/components/chat/ChatWorkspace'
import { SkillsWorkspace } from '@/components/skills/SkillsWorkspace'
import { CasesWorkspace } from '@/components/cases/CasesWorkspace'
import { ActivityWorkspace } from '@/components/activity/ActivityWorkspace'
import styles from './AppLayout.module.css'

export function AppLayout() {
  const { activeWorkspace } = useUIStore()

  return (
    <div className={styles.shell}>
      <Header />
      <WorkspaceTabs />
      <main className={styles.workspace}>
        {activeWorkspace === 'chat'     && <ChatWorkspace />}
        {activeWorkspace === 'skills'   && <SkillsWorkspace />}
        {activeWorkspace === 'cases'    && <CasesWorkspace />}
        {activeWorkspace === 'activity' && <ActivityWorkspace />}
      </main>
    </div>
  )
}
