import { useEffect, useRef, useState } from 'react'
import { fetchMatters, fetchMatterDetail, fetchMatterTasks } from '@/api/client'
import { useMatterStore } from '@/store/matterStore'
import { useAuthStore } from '@/store/authStore'
import type { Matter } from '@/types'
import { MatterDetailPanel } from './MatterDetailPanel'
import styles from './DashboardWorkspace.module.css'

const KLG_STAGES = [
  'Matter Intake & Setup',
  'Pleadings & Notices',
  'Brief Preparation & Drafting',
  'Cites & Compliance',
  'Review & Finalization',
  'Contingency Tasks',
]

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function urgencyDotClass(daysUntil?: number): string {
  if (daysUntil == null) return ''
  if (daysUntil <= 7) return styles.urgentRed
  if (daysUntil <= 30) return styles.urgentAmber
  return styles.urgentGreen
}

function statusClass(status?: string): string {
  const s = (status ?? '').toLowerCase()
  if (s.includes('active') || s.includes('open') || s.includes('in progress')) return styles.statusActive
  if (s.includes('pending') || s.includes('draft') || s.includes('paused')) return styles.statusPending
  if (s.includes('closed') || s.includes('done') || s.includes('canceled')) return styles.statusClosed
  return styles.statusDefault
}

export function DashboardWorkspace() {
  const [matters, setMatters] = useState<Matter[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)

  const { isAdmin, isSuperAdmin } = useAuthStore()
  const { selectedMatter, setSelectedMatter, setTasks, setTasksLoading, tasks, tasksLoading } = useMatterStore()
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchMatters(showArchived)
      .then(res => {
        if (cancelled) return
        setMatters(res.matters)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : 'Failed to load matters')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [showArchived])

  async function handleSelectMatter(m: Matter) {
    setSelectedMatter(m)
    setTasksLoading(true)
    try {
      const [detail, tasks] = await Promise.all([
        fetchMatterDetail(m.id),
        fetchMatterTasks(m.id),
      ])
      setSelectedMatter(detail)
      setTasks(tasks)
    } catch {
      setTasks([])
    } finally {
      setTasksLoading(false)
    }
  }

  // When this workspace opens with a pre-selected matter (navigated from Deadlines),
  // fetch its tasks if they haven't been loaded yet.
  useEffect(() => {
    if (selectedMatter && tasks.length === 0 && !tasksLoading) {
      handleSelectMatter(selectedMatter)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedMatter?.id])

  // Scroll the selected matter row into view once the list is rendered.
  useEffect(() => {
    if (!selectedMatter || !listRef.current) return
    const el = listRef.current.querySelector<HTMLElement>(`[data-matter-id="${selectedMatter.id}"]`)
    if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [selectedMatter?.id, loading])

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={`${styles.listPanel} ${styles.skeletonPanel}`}>
          {[0, 1, 2, 3, 4].map(i => (
            <div key={i} className={styles.skeletonCard} />
          ))}
        </div>
        <div className={`${styles.detailPanel} ${styles.detailEmpty}`}>
          <span className="material-symbols-outlined">gavel</span>
          <p>Loading matters…</p>
        </div>
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

  // Group matters by case_stage, ordering by KLG_STAGES then ungrouped
  const grouped: Record<string, Matter[]> = {}
  for (const m of matters) {
    const stage = m.case_stage || 'Other'
    if (!grouped[stage]) grouped[stage] = []
    grouped[stage].push(m)
  }

  const orderedStages = [
    ...KLG_STAGES.filter(s => grouped[s]),
    ...Object.keys(grouped).filter(s => !KLG_STAGES.includes(s)),
  ]

  // Sort matters within each stage by urgency
  for (const stage of orderedStages) {
    grouped[stage].sort((a, b) => (a.days_until ?? 9999) - (b.days_until ?? 9999))
  }

  const deadlines: Matter[] = matters
    .filter(m => m.days_until != null && m.days_until <= 30)
    .sort((a, b) => (a.days_until ?? 9999) - (b.days_until ?? 9999))
    .slice(0, 5)

  return (
    <div className={styles.container}>
      {/* Left: matter list */}
      <div className={styles.listPanel}>
        {/* Admin-only: show archived toggle */}
        {(isAdmin || isSuperAdmin) && (
          <div className={styles.archiveToggleRow}>
            <label className={styles.archiveToggle}>
              <input
                type="checkbox"
                checked={showArchived}
                onChange={e => setShowArchived(e.target.checked)}
              />
              <span>Show archived matters</span>
            </label>
          </div>
        )}
        {/* Upcoming deadlines strip */}
        {deadlines.length > 0 && (
          <div className={styles.deadlineStrip}>
            <span className={styles.stripLabel}>Next deadlines</span>
            {deadlines.map(d => (
              <span
                key={d.id}
                className={styles.stripItem}
                onClick={() => {
                  const m = matters.find(x => x.id === d.id)
                  if (m) handleSelectMatter(m)
                }}
              >
                <span className={`${styles.urgencyDot} ${urgencyDotClass(d.days_until)}`} />
                <span className={styles.stripName}>{d.name}</span>
                <span className={styles.stripDate}>{formatDate(d.next_court_deadline ?? d.target_date)}</span>
              </span>
            ))}
          </div>
        )}

        {/* Grouped matter list */}
        <div className={styles.matterList} ref={listRef}>
          {orderedStages.map(stage => (
            <div key={stage} className={styles.stageGroup}>
              <div className={styles.stageHeader}>{stage}</div>
              {grouped[stage].map(m => (
                <button
                  key={m.id}
                  data-matter-id={m.id}
                  className={`${styles.matterRow} ${selectedMatter?.id === m.id ? styles.matterRowActive : ''}`}
                  onClick={() => handleSelectMatter(m)}
                >
                  <span className={`${styles.urgencyBar} ${urgencyDotClass(m.days_until)}`} />
                  <div className={styles.matterRowContent}>
                    <span className={styles.matterName}>{m.name}</span>
                    <div className={styles.matterRowMeta}>
                      {m.assignee && <span className={styles.metaChip}>{m.assignee}</span>}
                      {(m.next_court_deadline || m.target_date) && (
                        <span className={styles.metaChipDate}>
                          {formatDate(m.next_court_deadline ?? m.target_date)}
                        </span>
                      )}
                    </div>
                  </div>
                  {m.status && (
                    <span className={`${styles.statusBadge} ${statusClass(m.status)}`}>
                      {m.status}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* Right: detail panel */}
      <div className={styles.detailPanel}>
        {selectedMatter ? (
          <MatterDetailPanel />
        ) : (
          <div className={styles.detailEmpty}>
            <span className="material-symbols-outlined">gavel</span>
            <p>Select a matter to view details and tasks</p>
          </div>
        )}
      </div>
    </div>
  )
}
