import { useEffect, useState } from 'react'
import { fetchDeadlines, fetchTodayTasks, fetchTodayBriefing } from '@/api/client'
import { useUIStore } from '@/store/uiStore'
import { useChatStore } from '@/store/chatStore'
import { useAuthStore } from '@/store/authStore'
import type { DeadlineItem, Task } from '@/types'
import styles from './TodayWorkspace.module.css'

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function daysUntil(dateStr?: string | null): number | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return null
  return Math.ceil((d.getTime() - Date.now()) / 86400000)
}

function urgencyClass(days: number | null): string {
  if (days == null) return styles.dotGreen
  if (days <= 7) return styles.dotRed
  if (days <= 30) return styles.dotAmber
  return styles.dotGreen
}

function greeting(user: string): string {
  const h = new Date().getHours()
  const name = user && user !== 'Team' ? user : 'there'
  if (h < 12) return `Good morning, ${name}`
  if (h < 17) return `Good afternoon, ${name}`
  return `Good evening, ${name}`
}

function formatToday(): string {
  return new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
}

export function TodayWorkspace() {
  const { user } = useAuthStore()
  const { setWorkspace } = useUIStore()
  const { setDraftInput } = useChatStore()

  const [deadlines, setDeadlines] = useState<DeadlineItem[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [displayUser, setDisplayUser] = useState(user ?? '')
  const [dataLoading, setDataLoading] = useState(true)

  const [briefing, setBriefing] = useState<string | null>(null)
  const [briefingLoading, setBriefingLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setDataLoading(true)

    Promise.all([
      fetchDeadlines(),
      fetchTodayTasks(),
    ])
      .then(([dl, todayRes]) => {
        if (cancelled) return
        setDeadlines(dl.slice(0, 7))
        setTasks(todayRes.tasks)
        setDisplayUser(todayRes.user || user || '')
      })
      .catch(() => {/* non-fatal */})
      .finally(() => { if (!cancelled) setDataLoading(false) })

    return () => { cancelled = true }
  }, [user])

  useEffect(() => {
    let cancelled = false
    setBriefingLoading(true)

    fetchTodayBriefing()
      .then(res => {
        if (cancelled) return
        setBriefing(res.focus)
        if (res.user && !displayUser) setDisplayUser(res.user)
      })
      .catch(() => { if (!cancelled) setBriefing(null) })
      .finally(() => { if (!cancelled) setBriefingLoading(false) })

    return () => { cancelled = true }
  }, [])

  function handleAskAlfred() {
    setDraftInput(`Alfred, let's talk about my priorities for today — ${formatToday()}.`)
    setWorkspace('chat')
  }

  function handleTaskAI(task: Task) {
    setDraftInput(`Alfred, help me with this task: "${task.name}"${task.matter_name ? ` on the ${task.matter_name} matter` : ''}.`)
    setWorkspace('chat')
  }

  const openTasks = tasks.filter(t => t.status !== 'Done')
  const doneTasks = tasks.filter(t => t.status === 'Done')

  return (
    <div className={styles.container}>
      {/* Top greeting bar */}
      <div className={styles.greetingBar}>
        <div className={styles.greetingText}>
          <span className="material-symbols-outlined" style={{ fontSize: 20, color: 'var(--accent)' }}>wb_sunny</span>
          <span className={styles.greeting}>{greeting(displayUser)}</span>
        </div>
        <span className={styles.todayDate}>{formatToday()}</span>
      </div>

      {/* Two-column body */}
      <div className={styles.body}>
        {/* Left: AI briefing card */}
        <div className={styles.briefingCol}>
          <div className={styles.card}>
            <div className={styles.cardLabel}>
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>auto_awesome</span>
              Focus for today
            </div>

            {briefingLoading ? (
              <div className={styles.briefingSkeleton}>
                <div className={styles.skeletonLine} style={{ width: '90%' }} />
                <div className={styles.skeletonLine} style={{ width: '75%' }} />
                <div className={styles.skeletonLine} style={{ width: '82%' }} />
                <div className={styles.skeletonLine} style={{ width: '60%' }} />
              </div>
            ) : briefing ? (
              <div className={styles.briefingText}>
                {briefing.split('\n').filter(Boolean).map((line, i) => (
                  <p key={i} className={styles.briefingLine}>{line}</p>
                ))}
              </div>
            ) : (
              <div className={styles.briefingEmpty}>
                <span className="material-symbols-outlined">psychology</span>
                <p>Briefing unavailable — Alfred couldn't generate a summary right now.</p>
              </div>
            )}

            <button className={styles.askBtn} onClick={handleAskAlfred}>
              <span className="material-symbols-outlined" style={{ fontSize: 15 }}>chat</span>
              Ask Alfred about this
            </button>
          </div>
        </div>

        {/* Right: Deadlines + tasks */}
        <div className={styles.dataCol}>
          {/* Deadlines strip */}
          <div className={styles.card}>
            <div className={styles.cardLabel}>
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>event_upcoming</span>
              Deadlines — next 30 days
            </div>
            {dataLoading ? (
              <div className={styles.listSkeleton}>
                {[0, 1, 2].map(i => <div key={i} className={styles.skeletonRow} />)}
              </div>
            ) : deadlines.length === 0 ? (
              <p className={styles.emptyNote}>No upcoming deadlines in the next 30 days.</p>
            ) : (
              <div className={styles.deadlineList}>
                {deadlines.map(d => {
                  const days = daysUntil(d.next_court_deadline ?? d.target_date)
                  return (
                    <div key={d.id} className={styles.deadlineRow}>
                      <span className={`${styles.dot} ${urgencyClass(days)}`} />
                      <span className={styles.deadlineName}>{d.name}</span>
                      <span className={styles.deadlineDate}>
                        {formatDate(d.next_court_deadline ?? d.target_date)}
                        {days != null && (
                          <span className={styles.daysAway}>
                            {days <= 0 ? ' overdue' : ` · ${days}d`}
                          </span>
                        )}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Your tasks */}
          <div className={styles.card}>
            <div className={styles.cardLabel}>
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>task_alt</span>
              Your tasks
              {!dataLoading && (
                <span className={styles.taskCount}>{openTasks.length} open · {doneTasks.length} done</span>
              )}
            </div>
            {dataLoading ? (
              <div className={styles.listSkeleton}>
                {[0, 1, 2, 3].map(i => <div key={i} className={styles.skeletonRow} />)}
              </div>
            ) : tasks.length === 0 ? (
              <p className={styles.emptyNote}>No tasks assigned to you right now.</p>
            ) : (
              <div className={styles.taskList}>
                {openTasks.map(t => (
                  <div key={t.id} className={styles.taskRow}>
                    <span className={`material-symbols-outlined ${styles.taskIcon}`}>
                      {t.status === 'In Progress' ? 'pending' : 'radio_button_unchecked'}
                    </span>
                    <div className={styles.taskInfo}>
                      <span className={styles.taskName}>{t.name}</span>
                      {t.matter_name && (
                        <span className={styles.taskMatter}>{t.matter_name}</span>
                      )}
                    </div>
                    {t.deadline && (
                      <span className={`${styles.taskDue} ${daysUntil(t.deadline) != null && daysUntil(t.deadline)! <= 7 ? styles.taskDueUrgent : ''}`}>
                        {formatDate(t.deadline)}
                      </span>
                    )}
                    <button
                      className={styles.sparkBtn}
                      onClick={() => handleTaskAI(t)}
                      title="Ask Alfred about this task"
                    >
                      ✨
                    </button>
                  </div>
                ))}
                {doneTasks.length > 0 && (
                  <details className={styles.doneSection}>
                    <summary className={styles.doneSummary}>
                      {doneTasks.length} completed
                    </summary>
                    {doneTasks.map(t => (
                      <div key={t.id} className={`${styles.taskRow} ${styles.taskRowDone}`}>
                        <span className={`material-symbols-outlined ${styles.taskIcon} ${styles.taskIconDone}`}>
                          check_circle
                        </span>
                        <span className={`${styles.taskName} ${styles.taskNameDone}`}>{t.name}</span>
                      </div>
                    ))}
                  </details>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
