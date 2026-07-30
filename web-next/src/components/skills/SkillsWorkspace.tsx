import { useState } from 'react'
import { KLG_SKILLS } from '@/data/skills'
import { useChatStore } from '@/store/chatStore'
import { useUIStore } from '@/store/uiStore'
import { useMatterStore } from '@/store/matterStore'
import type { Skill } from '@/types'
import styles from './SkillsWorkspace.module.css'

const CATEGORIES = ['ALL', 'INTAKE', 'RESEARCH', 'DRAFTING', 'QA', 'ARGUMENT', 'OPS', 'RECORD'] as const
type Category = (typeof CATEGORIES)[number]

function resolvePrompt(prompt: string, matter?: string, params?: Record<string, string>): string {
  let p = prompt
  if (matter) p = p.replace('{{matter}}', matter)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      p = p.replace(`{{${k}}}`, v)
    }
  }
  return p
}

function SkillCard({ skill }: { skill: Skill }) {
  const { setSkillTrigger } = useChatStore()
  const { setWorkspace } = useUIStore()
  const { selectedMatter } = useMatterStore()
  const [expanded, setExpanded] = useState(false)
  const [paramValue, setParamValue] = useState('')

  const param = skill.params?.[0] ?? null

  function launch() {
    const params = param ? { [param.key]: paramValue } : {}
    const prompt = resolvePrompt(skill.prompt, selectedMatter?.name, params)
    setSkillTrigger({ prompt, displayName: skill.name })
    setWorkspace('chat')
  }

  function handleLaunchClick() {
    if (!param) {
      launch()
      return
    }
    if (!expanded) {
      setExpanded(true)
      return
    }
    if (paramValue.trim()) {
      launch()
    } else {
      setExpanded(false)
      setParamValue('')
    }
  }

  const btnLabel = expanded
    ? (param && paramValue.trim() ? 'Send' : 'Cancel')
    : null

  return (
    <div className={`${styles.card} ${expanded ? styles.cardExpanded : ''}`}>
      <div className={styles.cardTop}>
        <span className={styles.cardIcon}>{skill.icon}</span>
        <div className={styles.cardInfo}>
          <span className={styles.cardName}>{skill.name}</span>
          <span className={styles.cardMeta}>{skill.owner} · {skill.time}</span>
        </div>
        <button className={styles.launchBtn} onClick={handleLaunchClick}>
          {btnLabel ?? (
            <>
              <span className="material-symbols-outlined">bolt</span>
              Launch
            </>
          )}
        </button>
      </div>
      <p className={styles.cardDesc}>{skill.desc}</p>
      {!expanded && skill.requiresFile && (
        <span className={styles.fileHint}>
          <span className="material-symbols-outlined" style={{ fontSize: 11 }}>attach_file</span>
          {skill.fileHint || 'File required — attach in Chat before launching'}
        </span>
      )}
      {expanded && param && (
        <div className={styles.paramRow}>
          <input
            className={styles.paramInput}
            autoFocus
            placeholder={param.placeholder}
            value={paramValue}
            onChange={e => setParamValue(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && paramValue.trim()) launch()
              if (e.key === 'Escape') { setExpanded(false); setParamValue('') }
            }}
          />
          {paramValue.trim() && (
            <button className={styles.sendBtn} onClick={launch}>
              <span className="material-symbols-outlined">send</span>
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function SkillsWorkspace() {
  const [category, setCategory] = useState<Category>('ALL')
  const [search, setSearch] = useState('')

  const filtered = KLG_SKILLS.filter(s => {
    if (category !== 'ALL' && s.category !== category) return false
    if (search) {
      const q = search.toLowerCase()
      return (
        s.name.toLowerCase().includes(q) ||
        s.desc.toLowerCase().includes(q) ||
        s.owner.toLowerCase().includes(q)
      )
    }
    return true
  })

  return (
    <div className={styles.workspace}>
      <div className={styles.header}>
        <div className={styles.searchRow}>
          <span className="material-symbols-outlined" style={{ fontSize: 16, color: 'var(--text-muted)', flexShrink: 0 }}>search</span>
          <input
            className={styles.searchInput}
            placeholder="Search skills…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <button className={styles.clearSearch} onClick={() => setSearch('')} aria-label="Clear search">
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>close</span>
            </button>
          )}
        </div>
        <div className={styles.cats}>
          {CATEGORIES.map(c => (
            <button
              key={c}
              className={`${styles.catChip} ${category === c ? styles.catActive : ''}`}
              onClick={() => setCategory(c)}
            >
              {c}
            </button>
          ))}
        </div>
      </div>

      <div className={styles.grid}>
        {filtered.length === 0 ? (
          <div className={styles.empty}>
            <span className="material-symbols-outlined">search_off</span>
            <p>No skills match &ldquo;{search}&rdquo;</p>
          </div>
        ) : (
          filtered.map(skill => <SkillCard key={skill.id} skill={skill} />)
        )}
      </div>
    </div>
  )
}
