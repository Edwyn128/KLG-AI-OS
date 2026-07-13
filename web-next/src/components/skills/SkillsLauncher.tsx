import { useEffect, useState } from 'react'
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

  // Close on Escape
  useEffect(() => {
    if (!skillsOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSkillsOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [skillsOpen, setSkillsOpen])

  const filtered = activeCategory === 'ALL'
    ? KLG_SKILLS
    : KLG_SKILLS.filter(s => s.category === activeCategory)

  function handleSkillClick(skill: Skill) {
    setSkillsOpen(false)
    setWorkspace('chat')
    setSkillTrigger({ prompt: skill.prompt, displayName: skill.name })
  }

  return (
    <>
      {skillsOpen && (
        <div className={styles.popup}>
          <div className={styles.popupHeader}>
            <span className={styles.popupTitle}>Skills</span>
            <button className={styles.closeBtn} onClick={() => setSkillsOpen(false)} aria-label="Close skills">
              <span className="material-symbols-outlined">close</span>
            </button>
          </div>

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

          <ul className={styles.skillList}>
            {filtered.map(skill => (
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
            ))}
          </ul>
        </div>
      )}

      <button
        className={`${styles.fab} ${skillsOpen ? styles.fabOpen : ''}`}
        onClick={() => setSkillsOpen(!skillsOpen)}
        aria-label={skillsOpen ? 'Close skills' : 'Open skills'}
        title="Skills"
      >
        <span className="material-symbols-outlined">bolt</span>
      </button>
    </>
  )
}
