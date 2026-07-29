import { useEffect, useMemo, useState } from 'react'
import { fetchMatters } from '@/api/client'
import { useUIStore } from '@/store/uiStore'
import { useChatStore } from '@/store/chatStore'
import { useAuthStore } from '@/store/authStore'
import type { Matter } from '@/types'
import styles from './DeadlinesWorkspace.module.css'

type FilterMode = 'all' | 'overdue' | 'week' | 'month' | 'mine'

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr + 'T12:00:00')
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function daysLabel(days?: number | null): string {
  if (days == null) return '—'
  if (days === 0) return 'Today'
  if (days < 0) return `${Math.abs(days)}d overdue`
  return `${days}d`
}

function urgencyClass(days?: number | null): string {
  if (days == null) return ''
  if (days <= 0) return styles.overdue
  if (days <= 7) return styles.urgent
  if (days <= 30) return styles.soon
  return ''
}

function passesFilter(m: Matter, filter: FilterMode, myName: string): boolean {
  if (filter === 'all') return true
  if (filter === 'mine') return (m.assignee ?? '').toLowerCase().includes(myName.toLowerCase())
  const days = m.days_until ?? null
  if (filter === 'overdue') return days != null && days < 0
  if (filter === 'week') return days != null && days >= 0 && days <= 7
  if (filter === 'month') return days != null && days >= 0 && days <= 30
  return true
}

export function DeadlinesWorkspace() {
  const { user } = useAuthStore()
  const { setWorkspace } = useUIStore()
  const { setDraftInput } = useChatStore()

  const [matters, setMatters] = useState<Matter[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterMode>('all')
  const [search, setSearch] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchMatters()
      .then(data => {
        if (cancelled) return
        const list = Array.isArray(data) ? data : (data.matters ?? [])
        // Sort by days_until: overdue first, then soonest, then no-date at end
        list.sort((a, b) => {
          const da = a.days_until ?? 9999
          const db = b.days_until ?? 9999
          return da - db
        })
        setMatters(list)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load matters')
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [])

  const myName = user ?? ''

  const filtered = useMemo(() => {
    let list = matters.filter(m => passesFilter(m, filter, myName))
    if (search.trim()) {
      const q = search.trim().toLowerCase()
      list = list.filter(m => (m.name ?? '').toLowerCase().includes(q))
    }
    return list
  }, [matters, filter, search, myName])

  function handleAI(matter: Matter) {
    setDraftInput(`Alfred, give me a status update on the ${matter.name} matter — what are the key deadlines and what should the team focus on?`)
    setWorkspace('chat')
  }

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
          {[0, 1, 2, 3, 4, 5, 6].map(i => (
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
          <select
            className={styles.select}
            value={filter}
            onChange={e => setFilter(e.target.value as FilterMode)}
          >
            <option value="all">All matters</option>
            <option value="overdue">Overdue</option>
            <option value="week">Due this week</option>
            <option value="month">Due this month</option>
            <option value="mine">Assigned to me</option>
          </select>

          <div className={styles.searchWrap}>
            <span className="material-symbols-outlined" style={{ fontSize: 14, color: 'var(--text-muted)' }}>search</span>
            <input
              className={styles.searchInput}
              placeholder="Search matters…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* ── Column headers ───────────────────────────────── */}
      <div className={styles.colHeaders}>
        <span className={styles.colName}>MATTER</span>
        <span className={styles.colStage}>STAGE</span>
        <span className={styles.colAssignee}>ASSIGNEE</span>
        <span className={styles.colDeadline}>COURT DEADLINE</span>
        <span className={styles.colTarget}>TARGET DATE</span>
        <span className={styles.colDays}>DAYS</span>
        <span className={styles.colAi} />
      </div>

      {/* ── Table body ───────────────────────────────────── */}
      <div className={styles.tableBody}>
        {filtered.length === 0 ? (
          <div className={styles.emptyState}>
            <span className="material-symbols-outlined">event_available</span>
            <p>No matters match the current filters.</p>
          </div>
        ) : (
          filtered.map(matter => (
            <div
              key={matter.id}
              className={`${styles.matterRow} ${urgencyClass(matter.days_until)}`}
            >
              <span className={`${styles.colName} ${styles.matterName}`}>
                {matter.url ? (
                  <a href={matter.url} target="_blank" rel="noreferrer" className={styles.matterLink}>
                    {matter.name}
                  </a>
                ) : matter.name}
              </span>

              <span className={`${styles.colStage} ${styles.cell}`}>
                {matter.case_stage || '—'}
              </span>

              <span className={`${styles.colAssignee} ${styles.cell}`}>
                {matter.assignee ? (
                  <span className={styles.assigneeChip}>
                    {matter.assignee.split(/[,\s]+/)[0]}
                  </span>
                ) : '—'}
              </span>

              <span className={`${styles.colDeadline} ${styles.cell} ${urgencyClass(matter.days_until)}`}>
                {formatDate(matter.next_court_deadline)}
              </span>

              <span className={`${styles.colTarget} ${styles.cell}`}>
                {formatDate(matter.target_date)}
              </span>

              <span className={`${styles.colDays} ${styles.cell}`}>
                {matter.days_until != null ? (
                  <span className={`${styles.daysBadge} ${urgencyClass(matter.days_until)}`}>
                    {daysLabel(matter.days_until)}
                  </span>
                ) : '—'}
              </span>

              <span className={styles.colAi}>
                <button
                  className={styles.sparkBtn}
                  onClick={() => handleAI(matter)}
                  title="Ask Alfred about this matter"
                >
                  ✨
                </button>
              </span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
