import { useEffect, useState } from 'react'
import { fetchMatters, fetchDeadlines } from '@/api/client'
import type { Matter, DeadlineItem } from '@/types'
import styles from './DashboardWorkspace.module.css'

function urgencyClass(daysUntil?: number): string {
  if (daysUntil == null) return ''
  if (daysUntil <= 7)  return styles.urgentRed
  if (daysUntil <= 30) return styles.urgentAmber
  return styles.urgentGreen
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function statusClass(status?: string): string {
  const s = (status ?? '').toLowerCase()
  if (s.includes('active') || s.includes('open'))   return styles.statusActive
  if (s.includes('pending') || s.includes('draft')) return styles.statusPending
  if (s.includes('closed') || s.includes('done'))   return styles.statusClosed
  return styles.statusDefault
}

function WorkloadSection({ matters }: { matters: Matter[] }) {
  const byAssignee: Record<string, number> = {}
  for (const m of matters) {
    const name = m.assignee ?? 'Unassigned'
    byAssignee[name] = (byAssignee[name] ?? 0) + 1
  }
  const entries = Object.entries(byAssignee).sort((a, b) => b[1] - a[1])
  if (!entries.length) return null

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Workload</h2>
      <ul className={styles.workloadList}>
        {entries.map(([name, count]) => (
          <li key={name} className={styles.workloadRow}>
            <span className={styles.workloadAvatar}>{name[0]?.toUpperCase() ?? '?'}</span>
            <span className={styles.workloadName}>{name}</span>
            <span className={styles.workloadCount}>{count} {count === 1 ? 'matter' : 'matters'}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function DashboardWorkspace() {
  const [matters, setMatters] = useState<Matter[]>([])
  const [deadlines, setDeadlines] = useState<DeadlineItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([fetchMatters(), fetchDeadlines()])
      .then(([mRes, dRes]) => {
        if (cancelled) return
        setMatters(mRes.matters)
        setDeadlines(dRes)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load dashboard data')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div className={styles.container}>
        {[0, 1, 2].map(i => (
          <div key={i} className={`${styles.section} ${styles.skeletonSection}`}>
            <div className={`${styles.skeletonBar} ${styles.skeletonTitle}`} />
            {[0, 1, 2, 3].map(j => (
              <div key={j} className={`${styles.skeletonBar} ${styles.skeletonRow}`} />
            ))}
          </div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className={styles.container}>
        <div className={styles.errorCard}>
          <span className="material-symbols-outlined">error_outline</span>
          <p>Could not load matters — check your connection.</p>
          <p className={styles.errorDetail}>{error}</p>
        </div>
      </div>
    )
  }

  const sorted = Array.isArray(deadlines)
    ? [...deadlines].sort((a, b) => (a.days_until ?? 9999) - (b.days_until ?? 9999))
    : []

  return (
    <div className={styles.container}>
      {/* Active Matters */}
      <section className={`${styles.section} ${styles.mattersSection}`}>
        <h2 className={styles.sectionTitle}>Active Matters</h2>
        {matters.length === 0 ? (
          <p className={styles.empty}>No active matters.</p>
        ) : (
          <ul className={styles.matterList}>
            {matters.map(m => (
              <li key={m.id} className={styles.matterCard}>
                <div className={styles.matterTop}>
                  <span className={styles.matterName}>{m.name}</span>
                  {m.status && (
                    <span className={`${styles.statusBadge} ${statusClass(m.status)}`}>
                      {m.status}
                    </span>
                  )}
                </div>
                <div className={styles.matterMeta}>
                  {m.case_stage && <span className={styles.metaChip}>{m.case_stage}</span>}
                  {m.assignee   && <span className={styles.metaChip}>{m.assignee}</span>}
                  {(m.next_court_deadline || m.target_date) && (
                    <span className={`${styles.metaChip} ${styles.deadlineChip}`}>
                      <span className="material-symbols-outlined" style={{ fontSize: 12 }}>calendar_today</span>
                      {formatDate(m.next_court_deadline ?? m.target_date)}
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Upcoming Deadlines */}
      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Upcoming Deadlines</h2>
        {sorted.length === 0 ? (
          <p className={styles.empty}>No upcoming deadlines.</p>
        ) : (
          <ul className={styles.deadlineList}>
            {sorted.map(d => (
              <li key={d.id} className={styles.deadlineRow}>
                <span className={`${styles.urgencyDot} ${urgencyClass(d.days_until)}`} />
                <span className={styles.deadlineName}>{d.name}</span>
                <span className={styles.deadlineDate}>
                  {formatDate(d.next_court_deadline ?? d.target_date)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Workload by Attorney */}
      <WorkloadSection matters={matters} />
    </div>
  )
}
