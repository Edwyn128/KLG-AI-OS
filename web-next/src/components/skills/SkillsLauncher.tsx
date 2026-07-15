import { useEffect, useRef, useState } from 'react'
import { useUIStore } from '@/store/uiStore'
import { useChatStore } from '@/store/chatStore'
import { useMatterStore } from '@/store/matterStore'
import { KLG_SKILLS } from '@/data/skills'
import type { Skill, SkillCategory, SkillParam } from '@/types'
import styles from './SkillsLauncher.module.css'

const CATEGORIES: SkillCategory[] = ['ALL', 'INTAKE', 'RESEARCH', 'DRAFTING', 'QA', 'ARGUMENT', 'OPS', 'RECORD']

function resolvePrompt(prompt: string, matterName: string | undefined, params: Record<string, string>): string {
  let resolved = prompt.replace(/\{\{matter\}\}/gi, matterName ?? '[Matter Name]')
  for (const [key, value] of Object.entries(params)) {
    resolved = resolved.replace(`{{${key}}}`, value)
  }
  return resolved
}

export function SkillsLauncher() {
  const { skillsOpen, setSkillsOpen, setWorkspace } = useUIStore()
  const { setSkillTrigger } = useChatStore()
  const { selectedMatter } = useMatterStore()

  const [activeCategory, setActiveCategory] = useState<SkillCategory>('ALL')
  const [expanded, setExpanded] = useState(false)
  const [search, setSearch] = useState('')

  // Param form state
  const [paramSkill, setParamSkill] = useState<Skill | null>(null)
  const [paramValues, setParamValues] = useState<Record<string, string>>({})

  const searchRef = useRef<HTMLInputElement>(null)
  const firstParamRef = useRef<HTMLInputElement>(null)

  // Close on Escape
  useEffect(() => {
    if (!skillsOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (paramSkill) { setParamSkill(null); return }
        handleClose()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skillsOpen, paramSkill])

  // Auto-focus search when expanding
  useEffect(() => {
    if (expanded && skillsOpen && !paramSkill) {
      setTimeout(() => searchRef.current?.focus(), 60)
    }
  }, [expanded, skillsOpen, paramSkill])

  // Auto-focus first param input when param form opens
  useEffect(() => {
    if (paramSkill) {
      setTimeout(() => firstParamRef.current?.focus(), 60)
    }
  }, [paramSkill])

  function handleClose() {
    setSkillsOpen(false)
    setExpanded(false)
    setSearch('')
    setActiveCategory('ALL')
    setParamSkill(null)
    setParamValues({})
  }

  function handleSkillClick(skill: Skill) {
    if (skill.params && skill.params.length > 0) {
      setParamSkill(skill)
      setParamValues({})
      return
    }
    fireSkill(skill, {})
  }

  function fireSkill(skill: Skill, params: Record<string, string>) {
    const resolved = resolvePrompt(skill.prompt, selectedMatter?.name, params)
    handleClose()
    setWorkspace('chat')
    setSkillTrigger({ prompt: resolved, displayName: skill.name })
  }

  const byCategory = activeCategory === 'ALL'
    ? KLG_SKILLS
    : KLG_SKILLS.filter(s => s.category === activeCategory)

  const filtered = !search.trim()
    ? byCategory
    : byCategory.filter(s =>
        s.name.toLowerCase().includes(search.toLowerCase()) ||
        s.desc.toLowerCase().includes(search.toLowerCase())
      )

  const canSubmitParams = paramSkill
    ? !(paramSkill.params ?? []).some((p: SkillParam) => p.required && !paramValues[p.key]?.trim())
    : false

  return (
    <>
      {skillsOpen && (
        <div className={`${styles.popup} ${expanded ? styles.popupExpanded : ''}`}>
          {/* Header */}
          <div className={styles.popupHeader}>
            {paramSkill ? (
              <button className={styles.paramBack} onClick={() => setParamSkill(null)}>
                <span className="material-symbols-outlined">arrow_back</span>
                {paramSkill.name}
              </button>
            ) : (
              <span className={styles.popupTitle}>Skills</span>
            )}
            <div className={styles.headerActions}>
              {!paramSkill && (
                <button
                  className={styles.iconBtn}
                  onClick={() => setExpanded(v => !v)}
                  title={expanded ? 'Compact view' : 'Expand — search & details'}
                  aria-label={expanded ? 'Compact view' : 'Expand'}
                >
                  <span className="material-symbols-outlined">
                    {expanded ? 'close_fullscreen' : 'open_in_full'}
                  </span>
                </button>
              )}
              <button
                className={styles.iconBtn}
                onClick={handleClose}
                aria-label="Close skills"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
          </div>

          {/* Matter chip */}
          <div className={`${styles.matterChip} ${!selectedMatter ? styles.matterChipEmpty : ''}`}>
            <span className="material-symbols-outlined">folder_open</span>
            {selectedMatter ? selectedMatter.name : 'No matter selected — select one in the dashboard'}
          </div>

          {/* Param form (replaces skill list when a parameterized skill is clicked) */}
          {paramSkill ? (
            <div className={styles.paramForm}>
              {paramSkill.params!.map((p: SkillParam, i: number) => (
                <div key={p.key} className={styles.paramField}>
                  <label className={styles.paramLabel}>{p.label}</label>
                  <input
                    ref={i === 0 ? firstParamRef : undefined}
                    className={styles.paramInput}
                    placeholder={p.placeholder}
                    value={paramValues[p.key] ?? ''}
                    onChange={e => setParamValues(v => ({ ...v, [p.key]: e.target.value }))}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && canSubmitParams) fireSkill(paramSkill, paramValues)
                    }}
                  />
                </div>
              ))}
              {paramSkill.requiresFile && (
                <div className={styles.fileHint}>
                  <span className="material-symbols-outlined">attach_file</span>
                  {paramSkill.fileHint ?? 'Attach a file in chat after sending'}
                </div>
              )}
              <button
                className={styles.paramSend}
                onClick={() => fireSkill(paramSkill, paramValues)}
                disabled={!canSubmitParams}
              >
                <span className="material-symbols-outlined">send</span>
                Send to Alfred
              </button>
            </div>
          ) : (
            <>
              {/* Search — expanded only */}
              {expanded && (
                <div className={styles.searchRow}>
                  <span className={`material-symbols-outlined ${styles.searchIcon}`}>search</span>
                  <input
                    ref={searchRef}
                    className={styles.searchInput}
                    type="text"
                    placeholder="Search skills…"
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                  />
                  {search && (
                    <button className={styles.searchClear} onClick={() => setSearch('')} aria-label="Clear search">
                      <span className="material-symbols-outlined">close</span>
                    </button>
                  )}
                </div>
              )}

              {/* Category chips */}
              <div className={styles.categoryRow}>
                {CATEGORIES.map(cat => (
                  <button
                    key={cat}
                    className={`${styles.catChip} ${activeCategory === cat ? styles.catActive : ''}`}
                    onClick={() => setActiveCategory(cat)}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Skill list */}
              <ul className={styles.skillList}>
                {filtered.length === 0 ? (
                  <li className={styles.emptyRow}>No skills match "{search}"</li>
                ) : (
                  filtered.map(skill => (
                    <li key={skill.id}>
                      <button
                        className={styles.skillRow}
                        onClick={() => handleSkillClick(skill)}
                      >
                        <span className={styles.skillIcon}>{skill.icon}</span>
                        <div className={styles.skillInfo}>
                          <span className={styles.skillName}>{skill.name}</span>
                          <span className={styles.skillDesc}>{skill.desc}</span>
                        </div>
                        <div className={styles.skillMeta}>
                          <span className={styles.skillTime}>{skill.time}</span>
                          <span className={styles.skillCat}>{skill.category}</span>
                          {skill.requiresFile && (
                            <span className={styles.fileChip} title={skill.fileHint ?? 'Requires file attachment'}>
                              <span className="material-symbols-outlined">attach_file</span>
                            </span>
                          )}
                          {skill.params && skill.params.length > 0 && (
                            <span className={styles.paramChip} title="Requires input before sending">
                              <span className="material-symbols-outlined">edit_note</span>
                            </span>
                          )}
                        </div>
                      </button>
                    </li>
                  ))
                )}
              </ul>
            </>
          )}
        </div>
      )}

      <button
        className={`${styles.fab} ${skillsOpen ? styles.fabOpen : ''}`}
        onClick={() => skillsOpen ? handleClose() : setSkillsOpen(true)}
        aria-label={skillsOpen ? 'Close skills' : 'Open skills'}
        title="Skills"
      >
        <span className="material-symbols-outlined">bolt</span>
      </button>
    </>
  )
}
