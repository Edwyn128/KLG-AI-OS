import { useEffect, useState } from 'react'
import { fetchWatchList, triggerBloodhoundScan } from '@/api/client'
import type { WatchCase } from '@/types'
import styles from './BloodhoundWorkspace.module.css'

const TIER_LABELS: Record<string, string> = {
  '1': 'Tier 1 — Core KLG Issues',
  '2': 'Tier 2 — Adjacent Doctrine',
  '3': 'Tier 3 — Ambient Monitor',
}

const STATUS_CLASS: Record<string, string> = {
  Watching: styles.statusWatching,
  Engaged:  styles.statusEngaged,
  Closed:   styles.statusClosed,
}

function formatDate(d: string | null | undefined): string {
  if (!d) return ''
  const dt = new Date(d)
  if (isNaN(dt.getTime())) return d
  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function CaseCard({ c }: { c: WatchCase }) {
  const [open, setOpen] = useState(false)

  return (
    <div className={styles.card}>
      <button className={styles.cardHeader} onClick={() => setOpen(v => !v)}>
        <div className={styles.cardMain}>
          <span className={styles.caseName}>{c.case_name || '—'}</span>
          <div className={styles.cardMeta}>
            {c.court && <span className={styles.metaChip}>{c.court}</span>}
            {c.procedural_posture && <span className={styles.metaChip}>{c.procedural_posture}</span>}
            {c.next_deadline && (
              <span className={`${styles.metaChip} ${styles.deadlineChip}`}>
                {formatDate(c.next_deadline)}
              </span>
            )}
          </div>
        </div>
        <div className={styles.cardRight}>
          <span className={`${styles.statusBadge} ${STATUS_CLASS[c.status] ?? ''}`}>{c.status}</span>
          <span className="material-symbols-outlined" style={{ fontSize: 16, color: 'var(--text-muted)' }}>
            {open ? 'expand_less' : 'expand_more'}
          </span>
        </div>
      </button>

      {c.issue_areas.length > 0 && (
        <div className={styles.issueRow}>
          {c.issue_areas.map(a => (
            <span key={a} className={styles.issueChip}>{a}</span>
          ))}
        </div>
      )}

      {open && (
        <div className={styles.cardBody}>
          {c.docket_no && (
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>Docket</span>
              <span className={styles.detailVal}>{c.docket_no}</span>
            </div>
          )}
          {c.nexus_note && (
            <div className={styles.detailRow}>
              <span className={styles.detailLabel}>KLG Nexus</span>
              <span className={styles.detailVal}>{c.nexus_note}</span>
            </div>
          )}
          {c.url && (
            <a className={styles.notionLink} href={c.url} target="_blank" rel="noopener noreferrer">
              Open in Notion
              <span className="material-symbols-outlined" style={{ fontSize: 12 }}>open_in_new</span>
            </a>
          )}
        </div>
      )}
    </div>
  )
}

function TierGroup({ tier, cases, defaultOpen }: { tier: string; cases: WatchCase[]; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className={styles.tierGroup}>
      <button className={styles.tierHeader} onClick={() => setOpen(v => !v)}>
        <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
          {open ? 'expand_more' : 'chevron_right'}
        </span>
        <span className={styles.tierLabel}>{TIER_LABELS[tier] ?? `Tier ${tier}`}</span>
        <span className={styles.tierCount}>{cases.length}</span>
      </button>
      {open && (
        <div className={styles.tierBody}>
          {cases.map(c => <CaseCard key={c.id} c={c} />)}
        </div>
      )}
    </div>
  )
}

export function BloodhoundWorkspace() {
  const [cases, setCases] = useState<WatchCase[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanResult, setScanResult] = useState<{ added_count: number; new_signals: number } | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchWatchList()
      .then(data => { if (!cancelled) setCases(data) })
      .catch((e: unknown) => { if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function handleScan() {
    setScanning(true)
    setScanResult(null)
    try {
      const result = await triggerBloodhoundScan()
      setScanResult(result)
      // Refresh list after scan
      const updated = await fetchWatchList()
      setCases(updated)
    } catch {
      setError('Scan failed — check server logs.')
    } finally {
      setScanning(false)
    }
  }

  // Group by tier
  const grouped: Record<string, WatchCase[]> = {}
  for (const c of cases) {
    const tier = c.tier || '3'
    if (!grouped[tier]) grouped[tier] = []
    grouped[tier].push(c)
  }
  const orderedTiers = ['1', '2', '3'].filter(t => grouped[t])

  return (
    <div className={styles.container}>
      {/* Header bar */}
      <div className={styles.topBar}>
        <div className={styles.topBarLeft}>
          <span className={styles.topBarTitle}>Bloodhound</span>
          <span className={styles.topBarSub}>Case surveillance &amp; watch list</span>
        </div>
        <div className={styles.topBarRight}>
          {scanResult && (
            <span className={styles.scanBadge}>
              +{scanResult.added_count} added from {scanResult.new_signals} signals
            </span>
          )}
          <button
            className={styles.scanBtn}
            onClick={handleScan}
            disabled={scanning || loading}
          >
            <span className="material-symbols-outlined">{scanning ? 'hourglass_empty' : 'radar'}</span>
            {scanning ? 'Scanning…' : 'Run Scan'}
          </button>
        </div>
      </div>

      {/* Content */}
      <div className={styles.body}>
        {loading && (
          <div className={styles.emptyState}>
            <span className="material-symbols-outlined">hourglass_empty</span>
            <p>Loading watch list…</p>
          </div>
        )}

        {!loading && error && (
          <div className={styles.emptyState}>
            <span className="material-symbols-outlined">error_outline</span>
            <p>{error}</p>
          </div>
        )}

        {!loading && !error && cases.length === 0 && (
          <div className={styles.emptyState}>
            <span className="material-symbols-outlined">search_off</span>
            <p>Watch List is empty.</p>
            <p className={styles.emptyHint}>Run a scan to detect and triage new cases from CourtListener and RSS feeds.</p>
          </div>
        )}

        {!loading && !error && orderedTiers.map((tier, i) => (
          <TierGroup
            key={tier}
            tier={tier}
            cases={grouped[tier]}
            defaultOpen={i === 0}
          />
        ))}
      </div>
    </div>
  )
}
