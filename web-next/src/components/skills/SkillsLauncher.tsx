import { useEffect, useRef, useState } from 'react'
import { useUIStore } from '@/store/uiStore'
import { useChatStore } from '@/store/chatStore'
import { KLG_SKILLS } from '@/data/skills'
import type { Skill, SkillCategory } from '@/types'
import styles from './SkillsLauncher.module.css'

const CATEGORIES: SkillCategory[] = ['ALL', 'INTAKE', 'RESEARCH', 'DRAFTING', 'QA', 'ARGUMENT', 'OPS', 'RECORD']

export function SkillsLauncher() {
  const { skillsOpen, setSkillsOpen, setWorkspace } = useUIStore()
  const { setSkillTrigger } = useChatStore()

  const [activeCategory, setActiveCategory] = useState<SkillCategory>('ALL')
  const [expanded, setExpanded] = useState(false)
  const [search, setSearch] = useState('')

  const searchRef = useRef<HTMLInputElement>(null)

  // Close on Escape
  useEffect(() => {
    if (!skillsOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skillsOpen])

  // Auto-focus search when expanding
  useEffect(() => {
    if (expanded && skillsOpen) {
      setTimeout(() => searchRef.current?.focus(), 60)
    }
  }, [expanded, skillsOpen])

  function handleClose() {
    setSkillsOpen(false)
    setExpanded(false)
    setSearch('')
    setActiveCategory('ALL')
  }

  function handleSkillClick(skill: Skill) {
    handleClose()
    setWorkspace('chat')
    setSkillTrigger({ prompt: skill.prompt, displayName: skill.name })
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

  return (
    <>
      {skillsOpen && (
        <div className={`${styles.popup} ${expanded ? styles.popupExpanded : ''}`}>
          {/* Header */}
          <div className={styles.popupHeader}>
            <span className={styles.popupTitle}>Skills</span>
            <div className={styles.headerActions}>
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
              <button
                className={styles.iconBtn}
                onClick={handleClose}
                aria-label="Close skills"
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </div>
          </div>

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
                    </div>
                  </button>
                </li>
              ))
            )}
          </ul>
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
