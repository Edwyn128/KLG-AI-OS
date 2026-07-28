import { useEffect, useMemo, useRef, useState } from 'react'
import { fetchAllTasks } from '@/api/client'
import { useUIStore } from '@/store/uiStore'
import { useChatStore } from '@/store/chatStore'
import { useAuthStore } from '@/store/authStore'
import type { Task } from '@/types'
import styles from './DeadlinesWorkspace.module.css'

const KLG_STAGES = [
  'Matter Intake & Setup',
  'Pleadings & Notices',
  'Brief Preparation & Drafting',
  'Cites & Compliance',
  'Review & Finalization',
  'Contingency Tasks',
]

type GroupMode = 'matter_stage' | 'stage_matter' | 'assignee'
type FilterMode = 'all' | 'overdue' | 'week' | 'month' | 'mine'

interface TaskRow extends Task {
  matter_name: string
}

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function formatDuration(mins?: number | null): string {
  if (!mins) return '—'
  if (mins < 60) return `${mins}m`
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return m ? `${h}h ${m}m` : `${h}h`
}

function daysUntil(dateStr?: string | null): number | null {
  if (!dateStr) return null
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return null
  return Math.ceil((d.getTime() - Date.now()) / 86400000)
}

function urgencyColor(days: number | null): string {
  if (days == null) return ''
  if (days <= 0) return styles.overdue
  if (days <= 7) return styles.urgent
  if (days <= 30) return styles.soon
  return ''
}

function passesDateFilter(task: TaskRow, filter: FilterMode, myName: string): boolean {
  if (filter === 'all') return true
  if (filter === 'mine') return (task.assignee ?? '').toLowerCase().includes(myName.toLowerCase())
  const days = daysUntil(task.deadline ?? task.eta)
  if (filter === 'overdue') return days != null && days < 0
  if (filter === 'week') return days != null && days >= 0 && days <= 7
  if (filter === 'month') return days != null && days >= 0 && days <= 30
  return true
}

export function DeadlinesWorkspace() {
  const { user } = useAuthStore()
  const { setWorkspace } = useUIStore()
  const { setDraftInput } = useChatStore()

  const [allTasks, setAllTasks] = useState<TaskRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [groupBy, setGroupBy] = useState<GroupMode>('matter_stage')
  const [filter, setFilter] = useState<FilterMode>('all')
  const [showCompleted, setShowCompleted] = useState(true)
  const [search, setSearch] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [activeAI, setActiveAI] = useState<string | null>(null)
  const aiInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchAllTasks()
      .then(tasks => {
        if (cancelled) return
        setAllTasks(tasks as TaskRow[])
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load tasks')
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    if (activeAI && aiInputRef.current) {
      aiInputRef.current.focus()
    }
  }, [activeAI])

  const myName = user ?? ''

  const filtered = useMemo(() => {
    let tasks = allTasks
    if (!showCompleted) tasks = tasks.filter(t => t.status !== 'Done')
    tasks = tasks.filter(t => passesDateFilter(t, filter, myName))
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      tasks = tasks.filter(t =>
        t.name.toLowerCase().includes(q) ||
        (t.matter_name ?? '').toLowerCase().includes(q)
      )
    }
    return tasks
  }, [allTasks, showCompleted, filter, search, myName])

  function toggleCollapse(key: string) {
    setCollapsed(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  function handleTaskAI(task: TaskRow, msg?: string) {
    const context = `Alfred, regarding task "${task.name}"${task.matter_name ? ` on the ${task.matter_name} matter` : ''}: ${msg ?? 'what do you suggest?'}`
    setDraftInput(context)
    setWorkspace('chat')
    setActiveAI(null)
  }

  // ── Build grouped structure ──────────────────────────────

  interface StageGroup {
    stage: string
    tasks: TaskRow[]
    done: number
    total: number
    urgentDeadline: string | null
  }

  interface MatterGroup {
    matter: string
    stages: StageGroup[]
    total: number
    urgentDeadline: string | null
  }

  const groups: MatterGroup[] = useMemo(() => {
    if (groupBy === 'matter_stage') {
      const byMatter: Record<string, TaskRow[]> = {}
      for (const t of filtered) {
        const m = t.matter_name || 'Unknown Matter'
        if (!byMatter[m]) byMatter[m] = []
        byMatter[m].push(t)
      }

      return Object.entries(byMatter).map(([matter, tasks]) => {
        const byStage: Record<string, TaskRow[]> = {}
        for (const t of tasks) {
          const s = t.stage || 'Other'
          if (!byStage[s]) byStage[s] = []
          byStage[s].push(t)
        }

        const stageKeys = [
          ...KLG_STAGES.filter(s => byStage[s]),
          ...Object.keys(byStage).filter(s => !KLG_STAGES.includes(s)),
        ]

        const stages: StageGroup[] = stageKeys.map(stage => {
          const stageTasks = byStage[stage]
          const done = stageTasks.filter(t => t.status === 'Done').length
          const deadlines = stageTasks
            .map(t => t.deadline ?? t.eta)
            .filter(Boolean)
            .sort()
          return {
            stage,
            tasks: stageTasks,
            done,
            total: stageTasks.length,
            urgentDeadline: deadlines[0] ?? null,
          }
        })

        const allDeadlines = tasks.map(t => t.deadline ?? t.eta).filter(Boolean).sort()
        return {
          matter,
          stages,
          total: tasks.length,
          urgentDeadline: allDeadlines[0] ?? null,
        }
      })
    }

    // Fallback: flat single group for other modes
    const allStages: Record<string, TaskRow[]> = {}
    for (const t of filtered) {
      const s = t.stage || 'Other'
      if (!allStages[s]) allStages[s] = []
      allStages[s].push(t)
    }
    const stageKeys = [
      ...KLG_STAGES.filter(s => allStages[s]),
      ...Object.keys(allStages).filter(s => !KLG_STAGES.includes(s)),
    ]
    return [{
      matter: 'All Matters',
      stages: stageKeys.map(stage => ({
        stage,
        tasks: allStages[stage],
        done: allStages[stage].filter(t => t.status === 'Done').length,
        total: allStages[stage].length,
        urgentDeadline: allStages[stage].map(t => t.deadline ?? t.eta).filter(Boolean).sort()[0] ?? null,
      })),
      total: filtered.length,
      urgentDeadline: null,
    }]
  }, [filtered, groupBy])

  // ── Render ────────────────────────────────────────────────

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.toolbar}>
          <div className={styles.toolbarTitle}>
            <span className="material-symbols-outlined">event_upcoming</span>
            Deadlines
          </div>
        </div>
        <div className={styles.skeletonWrap}>
          {[0, 1, 2, 3, 4, 5].map(i => (
            <div key={i} className={styles.skeletonRow} style={{ width: `${70 + (i % 3) * 10}%` }} />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.errorCard}>
          <span className="material-symbols-outlined">error_outline</span>
          <p>{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.container}>
      {/* ── Toolbar ─────────────────────────────────────── */}
      <div className={styles.toolbar}>
        <div className={styles.toolbarTitle}>
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>event_upcoming</span>
          Deadlines
          <span className={styles.taskBadge}>{filtered.length}</span>
        </div>

        <div className={styles.toolbarControls}>
          {/* Group by */}
          <select
            className={styles.select}
            value={groupBy}
            onChange={e => setGroupBy(e.target.value as GroupMode)}
          >
            <option value="matter_stage">Group: Matter → Stage</option>
            <option value="stage_matter">Group: Stage → Matter</option>
            <option value="assignee">Group: Assignee</option>
          </select>

          {/* Filter */}
          <select
            className={styles.select}
            value={filter}
            onChange={e => setFilter(e.target.value as FilterMode)}
          >
            <option value="all">All tasks</option>
            <option value="overdue">Overdue</option>
            <option value="week">Due this week</option>
            <option value="month">Due this month</option>
            <option value="mine">My tasks</option>
          </select>

          {/* Show completed toggle */}
          <label className={styles.toggleLabel}>
            <input
              type="checkbox"
              checked={showCompleted}
              onChange={e => setShowCompleted(e.target.checked)}
            />
            Show done
          </label>

          {/* Search */}
          <div className={styles.searchWrap}>
            <span className="material-symbols-outlined" style={{ fontSize: 14, color: 'var(--text-muted)' }}>search</span>
            <input
              className={styles.searchInput}
              placeholder="Search tasks…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* ── Column headers ───────────────────────────────── */}
      <div className={styles.colHeaders}>
        <span className={styles.colName}>NAME</span>
        <span className={styles.colEta}>ETA</span>
        <span className={styles.colAssignee}>ASSIGNEE</span>
        <span className={styles.colDuration}>DURATION</span>
        <span className={styles.colDeadline}>DEADLINE</span>
        <span className={styles.colStart}>START</span>
        <span className={styles.colAi} />
      </div>

      {/* ── Table body ───────────────────────────────────── */}
      <div className={styles.tableBody}>
        {groups.length === 0 ? (
          <div className={styles.emptyState}>
            <span className="material-symbols-outlined">task_alt</span>
            <p>No tasks match the current filters.</p>
          </div>
        ) : (
          groups.map(matterGroup => (
            <div key={matterGroup.matter} className={styles.matterGroup}>
              {/* Matter header */}
              <button
                className={styles.matterHeader}
                onClick={() => toggleCollapse(`matter:${matterGroup.matter}`)}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
                  {collapsed.has(`matter:${matterGroup.matter}`) ? 'chevron_right' : 'expand_more'}
                </span>
                <span className={styles.matterName}>{matterGroup.matter}</span>
                <span className={styles.matterCount}>{matterGroup.total} tasks</span>
                {matterGroup.urgentDeadline && (
                  <span className={`${styles.matterDeadline} ${urgencyColor(daysUntil(matterGroup.urgentDeadline))}`}>
                    {formatDate(matterGroup.urgentDeadline)}
                  </span>
                )}
              </button>

              {!collapsed.has(`matter:${matterGroup.matter}`) && (
                <div className={styles.stageList}>
                  {matterGroup.stages.map(sg => (
                    <div key={sg.stage} className={styles.stageGroup}>
                      {/* Stage header */}
                      <button
                        className={styles.stageHeader}
                        onClick={() => toggleCollapse(`stage:${matterGroup.matter}:${sg.stage}`)}
                      >
                        <span className="material-symbols-outlined" style={{ fontSize: 13 }}>
                          {collapsed.has(`stage:${matterGroup.matter}:${sg.stage}`) ? 'chevron_right' : 'expand_more'}
                        </span>
                        <span className={styles.stageName}>{sg.stage}</span>
                        <span className={styles.stageCount}>
                          {sg.total} task{sg.total !== 1 ? 's' : ''} · {sg.done}/{sg.total} done
                        </span>
                        {sg.urgentDeadline && (
                          <span className={`${styles.stageDeadline} ${urgencyColor(daysUntil(sg.urgentDeadline))}`}>
                            {formatDate(sg.urgentDeadline)}
                          </span>
                        )}
                      </button>

                      {!collapsed.has(`stage:${matterGroup.matter}:${sg.stage}`) && (
                        <div className={styles.taskRows}>
                          {sg.tasks.map((task, idx) => (
                            <div key={task.id} className={`${styles.taskRow} ${task.status === 'Done' ? styles.taskDone : ''}`}>
                              <span className={styles.taskNum}>{idx + 1}</span>
                              <span className={`material-symbols-outlined ${styles.taskCheck}`}>
                                {task.status === 'Done' ? 'check_circle' : task.status === 'In Progress' ? 'pending' : 'radio_button_unchecked'}
                              </span>
                              <span className={`${styles.colName} ${styles.taskName}`}>{task.name}</span>
                              <span className={`${styles.colEta} ${styles.taskCell}`}>{formatDate(task.eta)}</span>
                              <span className={`${styles.colAssignee} ${styles.taskCell}`}>
                                {task.assignee ? (
                                  <span className={styles.assigneeChip}>
                                    {task.assignee.split(/[,\s]+/)[0]}
                                  </span>
                                ) : '—'}
                              </span>
                              <span className={`${styles.colDuration} ${styles.taskCell}`}>{formatDuration(task.duration)}</span>
                              <span className={`${styles.colDeadline} ${styles.taskCell} ${urgencyColor(daysUntil(task.deadline))}`}>
                                {formatDate(task.deadline)}
                              </span>
                              <span className={`${styles.colStart} ${styles.taskCell}`}>{formatDate(task.start_date)}</span>
                              <span className={styles.colAi}>
                                {activeAI === task.id ? (
                                  <div className={styles.aiPopup}>
                                    <span className={styles.aiPopupTitle}>Ask Alfred…</span>
                                    <div className={styles.aiChips}>
                                      <button className={styles.aiChip} onClick={() => handleTaskAI(task, 'When should I work on this?')}>When to work on this?</button>
                                      <button className={styles.aiChip} onClick={() => handleTaskAI(task, 'Who should handle this?')}>Who should handle it?</button>
                                      <button className={styles.aiChip} onClick={() => handleTaskAI(task, 'What do I need to complete this?')}>What do I need?</button>
                                    </div>
                                    <div className={styles.aiInputRow}>
                                      <input
                                        ref={aiInputRef}
                                        className={styles.aiInput}
                                        placeholder="or type…"
                                        onKeyDown={e => {
                                          if (e.key === 'Enter' && e.currentTarget.value.trim()) {
                                            handleTaskAI(task, e.currentTarget.value.trim())
                                          }
                                          if (e.key === 'Escape') setActiveAI(null)
                                        }}
                                      />
                                      <button className={styles.aiSend} onClick={() => {
                                        const el = aiInputRef.current
                                        if (el?.value.trim()) handleTaskAI(task, el.value.trim())
                                      }}>
                                        <span className="material-symbols-outlined" style={{ fontSize: 14 }}>send</span>
                                      </button>
                                    </div>
                                    <button className={styles.aiClose} onClick={() => setActiveAI(null)}>
                                      <span className="material-symbols-outlined" style={{ fontSize: 13 }}>close</span>
                                    </button>
                                  </div>
                                ) : (
                                  <button
                                    className={styles.sparkBtn}
                                    onClick={() => setActiveAI(task.id)}
                                    title="Ask Alfred about this task"
                                  >
                                    ✨
                                  </button>
                                )}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
