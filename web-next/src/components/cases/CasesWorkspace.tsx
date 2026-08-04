import { useState } from 'react'
import styles from './CasesWorkspace.module.css'

interface CaseFolder {
  id: string
  name: string
  court: string
  docketNo: string
  filesCount: number
  lastModified: string
  category: string
}

const SAMPLE_CASE_FOLDERS: CaseFolder[] = [
  { id: '1', name: 'Smith v. City of Los Angeles', court: '2nd District Court of Appeal', docketNo: 'B312894', filesCount: 14, lastModified: '2 hours ago', category: 'Civil Appeal' },
  { id: '2', name: 'In re Marriage of Davis', court: '4th District Court of Appeal', docketNo: 'G059421', filesCount: 8, lastModified: 'Yesterday', category: 'Family Law' },
  { id: '3', name: 'Apex Corp v. Zenith Holdings', court: 'California Supreme Court', docketNo: 'S274192', filesCount: 22, lastModified: '3 days ago', category: 'Commercial Litigation' },
  { id: '4', name: 'People v. Henderson', court: '1st District Court of Appeal', docketNo: 'A163012', filesCount: 11, lastModified: 'Aug 1, 2026', category: 'Criminal Appeal' },
]

export function CasesWorkspace() {
  const [search, setSearch] = useState('')

  const filteredFolders = SAMPLE_CASE_FOLDERS.filter(f =>
    f.name.toLowerCase().includes(search.toLowerCase()) ||
    f.docketNo.toLowerCase().includes(search.toLowerCase()) ||
    f.court.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.titleGroup}>
          <span className={`material-symbols-outlined ${styles.titleIcon}`}>folder_open</span>
          <h1>Appellate Case Files & Records</h1>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <input
            type="text"
            placeholder="Filter by case, docket #, or court…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              background: 'var(--bg-input)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              color: 'var(--text-primary)',
              fontSize: 12,
              padding: '6px 12px',
              outline: 'none',
              width: 260,
            }}
          />
        </div>
      </div>

      <div className={styles.metricsGrid}>
        <div className={styles.metricCard}>
          <span className="material-symbols-outlined" style={{ fontSize: 24, color: 'var(--accent)' }}>library_books</span>
          <div>
            <div className={styles.metricValue}>4 Active Record Folders</div>
            <div className={styles.metricLabel}>Notion & SharePoint Connected</div>
          </div>
        </div>
        <div className={styles.metricCard}>
          <span className="material-symbols-outlined" style={{ fontSize: 24, color: 'var(--steel)' }}>description</span>
          <div>
            <div className={styles.metricValue}>55 Case Documents</div>
            <div className={styles.metricLabel}>Indexed for Alfred Search</div>
          </div>
        </div>
        <div className={styles.metricCard}>
          <span className="material-symbols-outlined" style={{ fontSize: 24, color: 'var(--bh-accent)' }}>cloud_sync</span>
          <div>
            <div className={styles.metricValue}>Sync Active</div>
            <div className={styles.metricLabel}>CourtListener & Notion API</div>
          </div>
        </div>
      </div>

      <div className={styles.sectionTitle}>Appellate Case Folders</div>
      <div className={styles.folderGrid}>
        {filteredFolders.map(folder => (
          <div key={folder.id} className={styles.folderCard}>
            <div className={styles.folderHeader}>
              <span className={styles.folderName}>{folder.name}</span>
              <span className={styles.docBadge}>{folder.category}</span>
            </div>
            <div className={styles.folderMeta}>
              <span>Docket: <strong>{folder.docketNo}</strong></span>
              <span>{folder.filesCount} Documents</span>
            </div>
            <div className={styles.folderMeta}>
              <span>{folder.court}</span>
              <span>Updated {folder.lastModified}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
