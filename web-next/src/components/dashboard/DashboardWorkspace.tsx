import { useEffect, useState } from 'react'
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

type ViewMode = 'kanban' | 'grid' | 'list'

function formatDate(dateStr?: string): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
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
  const [viewMode, setViewMode] = useState<ViewMode>('kanban')
  const [searchQuery, setSearchQuery] = useState('')
  const [stageFilter, setStageFilter] = useState<string>('all')

  const { isAdmin, isSuperAdmin } = useAuthStore()
  const { selectedMatter, setSelectedMatter, setTasks, setTasksLoading } = useMatterStore()

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

  // Filter matters based on search query and stage
  const filteredMatters = matters.filter(m => {
    const matchesSearch = searchQuery === '' || 
      m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (m.assignee && m.assignee.toLowerCase().includes(searchQuery.toLowerCase()))
    
    const matchesStage = stageFilter === 'all' || (m.case_stage || 'Other') === stageFilter
    return matchesSearch && matchesStage
  })

  // Calculate Metrics
  const activeCount = matters.filter(m => (m.status ?? '').toLowerCase().includes('active') || (m.status ?? '').toLowerCase().includes('in progress')).length
  const urgentCount = matters.filter(m => m.days_until != null && m.days_until <= 7).length
  const pendingCount = matters.filter(m => (m.status ?? '').toLowerCase().includes('pending') || (m.status ?? '').toLowerCase().includes('paused')).length

  // Group matters by stage for Kanban
  const grouped: Record<string, Matter[]> = {}
  for (const m of filteredMatters) {
    const stage = m.case_stage || 'Other'
    if (!grouped[stage]) grouped[stage] = []
    grouped[stage].push(m)
  }

  const orderedStages = [
    ...KLG_STAGES.filter(s => grouped[s] || stageFilter === 'all'),
    ...Object.keys(grouped).filter(s => !KLG_STAGES.includes(s)),
  ]

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.topHeader}>
          <div className={styles.metricsGrid}>
            {[0, 1, 2, 3].map(i => <div key={i} className={styles.metricCard} style={{ height: 50, opacity: 0.5 }} />)}
          </div>
        </div>
        <div className={styles.detailEmpty}>
          <span className="material-symbols-outlined">gavel</span>
          <p>Loading matters & active cases…</p>
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

  return (
    <div className={styles.container}>
      {/* Dynamic Top Header with Metrics & Control Filters */}
      <div className={styles.topHeader}>
        <div className={styles.metricsGrid}>
          <div className={styles.metricCard}>
            <div className={styles.metricIcon}>
              <span className="material-symbols-outlined">folder_open</span>
            </div>
            <div className={styles.metricInfo}>
              <span className={styles.metricValue}>{matters.length}</span>
              <span className={styles.metricLabel}>Total Matters</span>
            </div>
          </div>

          <div className={styles.metricCard}>
            <div className={`${styles.metricIcon} ${styles.active}`}>
              <span className="material-symbols-outlined">bolt</span>
            </div>
            <div className={styles.metricInfo}>
              <span className={styles.metricValue}>{activeCount}</span>
              <span className={styles.metricLabel}>Active Briefs</span>
            </div>
          </div>

          <div className={styles.metricCard}>
            <div className={`${styles.metricIcon} ${styles.urgent}`}>
              <span className="material-symbols-outlined">event_upcoming</span>
            </div>
            <div className={styles.metricInfo}>
              <span className={styles.metricValue}>{urgentCount}</span>
              <span className={styles.metricLabel}>Critical (&lt;7 Days)</span>
            </div>
          </div>

          <div className={styles.metricCard}>
            <div className={`${styles.metricIcon} ${styles.bh}`}>
              <span className="material-symbols-outlined">pending_actions</span>
            </div>
            <div className={styles.metricInfo}>
              <span className={styles.metricValue}>{pendingCount}</span>
              <span className={styles.metricLabel}>Pending Review</span>
            </div>
          </div>
        </div>

        {/* Filter Controls Row */}
        <div className={styles.controlsRow}>
          <div className={styles.searchBox}>
            <span className={`material-symbols-outlined ${styles.searchIcon}`}>search</span>
            <input
              type="text"
              placeholder="Search matters, attorneys, or courts…"
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
            />
          </div>

          <select
            className={styles.filterSelect}
            value={stageFilter}
            onChange={e => setStageFilter(e.target.value)}
          >
            <option value="all">All Stages</option>
            {KLG_STAGES.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>

          {(isAdmin || isSuperAdmin) && (
            <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={showArchived}
                onChange={e => setShowArchived(e.target.checked)}
              />
              Show Archived
            </label>
          )}

          <div className={styles.viewToggleGroup}>
            <button
              className={`${styles.viewBtn} ${viewMode === 'kanban' ? styles.active : ''}`}
              onClick={() => setViewMode('kanban')}
              title="Kanban Board View"
            >
              <span className="material-symbols-outlined">view_column</span>
            </button>
            <button
              className={`${styles.viewBtn} ${viewMode === 'grid' ? styles.active : ''}`}
              onClick={() => setViewMode('grid')}
              title="Grid Card View"
            >
              <span className="material-symbols-outlined">grid_view</span>
            </button>
            <button
              className={`${styles.viewBtn} ${viewMode === 'list' ? styles.active : ''}`}
              onClick={() => setViewMode('list')}
              title="Dense List View"
            >
              <span className="material-symbols-outlined">format_list_bulleted</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Workspace Body */}
      <div className={styles.workspaceBody}>
        {/* Kanban Board View */}
        {viewMode === 'kanban' && (
          <div className={styles.kanbanBoard}>
            {orderedStages.map(stage => {
              const stageMatters = grouped[stage] || []
              return (
                <div key={stage} className={styles.kanbanColumn}>
                  <div className={styles.columnHeader}>
                    <span>{stage}</span>
                    <span className={styles.columnBadge}>{stageMatters.length}</span>
                  </div>
                  <div className={styles.columnCards}>
                    {stageMatters.map(m => (
                      <div
                        key={m.id}
                        className={`${styles.kanbanCard} ${selectedMatter?.id === m.id ? styles.active : ''}`}
                        onClick={() => handleSelectMatter(m)}
                      >
                        <div className={styles.cardHeader}>
                          <span className={styles.cardTitle}>{m.name}</span>
                          <span className={`${styles.urgencyDot} ${urgencyDotClass(m.days_until)}`} />
                        </div>
                        <div className={styles.cardMeta}>
                          {m.assignee ? <span className={styles.chip}>{m.assignee}</span> : <span />}
                          <span>{formatDate(m.next_court_deadline ?? m.target_date)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* Grid View */}
        {viewMode === 'grid' && (
          <div className={styles.gridView}>
            {filteredMatters.map(m => (
              <div
                key={m.id}
                className={styles.gridCard}
                onClick={() => handleSelectMatter(m)}
              >
                <div className={styles.cardHeader}>
                  <span className={styles.cardTitle}>{m.name}</span>
                  <span className={`${styles.statusBadge} ${statusClass(m.status)}`}>{m.status ?? 'Active'}</span>
                </div>
                <div className={styles.cardMeta}>
                  <span>Stage: <strong>{m.case_stage ?? 'Setup'}</strong></span>
                  <span className={`${styles.urgencyDot} ${urgencyDotClass(m.days_until)}`} />
                </div>
                <div className={styles.cardMeta}>
                  <span>{m.assignee ? `Lead: ${m.assignee}` : 'Unassigned'}</span>
                  <span>{formatDate(m.next_court_deadline ?? m.target_date)}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* List View */}
        {viewMode === 'list' && (
          <div className={styles.listView}>
            {filteredMatters.map(m => (
              <div
                key={m.id}
                className={styles.listRow}
                onClick={() => handleSelectMatter(m)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className={`${styles.urgencyDot} ${urgencyDotClass(m.days_until)}`} />
                  <span className={styles.cardTitle}>{m.name}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 11, color: 'var(--text-muted)' }}>
                  <span>{m.case_stage ?? 'In Progress'}</span>
                  <span>{m.assignee ?? 'Unassigned'}</span>
                  <span>{formatDate(m.next_court_deadline ?? m.target_date)}</span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Selected Matter Detail Panel / Drawer */}
        {selectedMatter && (
          <div className={styles.detailDrawer}>
            <MatterDetailPanel />
          </div>
        )}
      </div>
    </div>
  )
}
