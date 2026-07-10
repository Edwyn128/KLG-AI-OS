import { useUIStore } from '@/store/uiStore'
import { Header } from './Header'
import { WorkspaceTabs } from './WorkspaceTabs'
import { ChatWorkspace } from '@/components/chat/ChatWorkspace'
import { SkillsWorkspace } from '@/components/skills/SkillsWorkspace'
import { CasesWorkspace } from '@/components/cases/CasesWorkspace'
import { ActivityWorkspace } from '@/components/activity/ActivityWorkspace'
import styles from './AppLayout.module.css'

const PANEL_LABELS: Record<string, string> = {
  skills:   'Skills Navigator',
  cases:    'Case Files',
  activity: 'Activity Log',
}

export function AppLayout() {
  const { activeWorkspace, setWorkspace } = useUIStore()
  const panelOpen = activeWorkspace !== 'chat'

  return (
    <div className={styles.shell}>
      <Header />
      <WorkspaceTabs />
      <main className={styles.workspace}>
        <div className={styles.baseLayer}>
          <ChatWorkspace />
        </div>

        {panelOpen && (
          <div className={styles.panel}>
            <div className={styles.panelHeader}>
              <span className={styles.panelTitle}>
                {PANEL_LABELS[activeWorkspace] ?? activeWorkspace}
              </span>
              <button
                className={styles.panelClose}
                onClick={() => setWorkspace('chat')}
                aria-label="Close panel"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>

            {activeWorkspace === 'skills'   && <SkillsWorkspace />}
            {activeWorkspace === 'cases'    && <CasesWorkspace />}
            {activeWorkspace === 'activity' && <ActivityWorkspace />}
          </div>
        )}
      </main>
    </div>
  )
}
