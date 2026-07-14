import { useState } from 'react'
import { useMatterStore } from '@/store/matterStore'
import { patchMatter, patchTask, deleteTask as apiDeleteTask, createTask } from '@/api/client'
import type { Task, Matter } from '@/types'
import styles from './MatterDetailPanel.module.css'

const KLG_STAGES = [
  'Matter Intake & Setup',
  'Pleadings & Notices',
  'Brief Preparation & Drafting',
  'Cites & Compliance',
  'Review & Finalization',
  'Contingency Tasks',
]

const STATUS_OPTIONS = ['In progress', 'Backlog', 'Planning', 'Paused', 'Review needed', 'Done', 'Canceled']
const PRIORITY_OPTIONS = ['Urgent', 'High', 'Medium', 'Low']

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── Stage Progress Bar ────────────────────────────────────────────────────────

function StageProgressBar({ currentStage }: { currentStage?: string }) {
  const mainStages = KLG_STAGES.slice(0, 5)
  const idx = mainStages.findIndex(s =>
    s.toLowerCase().includes((currentStage ?? '').toLowerCase().split(' ')[0].toLowerCase())
  )

  return (
    <div className={styles.stageBar}>
      {mainStages.map((s, i) => (
        <div
          key={s}
          className={`${styles.stagePill} ${i < idx ? styles.stageComplete : ''} ${i === idx ? styles.stageCurrent : ''}`}
          title={s}
        >
          <span className={styles.stagePillLabel}>{s}</span>
        </div>
      ))}
    </div>
  )
}

// ── Editable field ────────────────────────────────────────────────────────────

function EditableSelect({
  value, options, onChange, label,
}: {
  value?: string; options: string[]; onChange: (v: string) => void; label: string
}) {
  const [editing, setEditing] = useState(false)
  if (editing) {
    return (
      <select
        className={styles.inlineSelect}
        autoFocus
        value={value ?? ''}
        onChange={e => { onChange(e.target.value); setEditing(false) }}
        onBlur={() => setEditing(false)}
      >
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    )
  }
  return (
    <button className={styles.editableField} onClick={() => setEditing(true)} title={`Edit ${label}`}>
      {value || <span className={styles.emptyField}>—</span>}
    </button>
  )
}

// ── Task row ─────────────────────────────────────────────────────────────────

function TaskRow({ task, matterId }: { task: Task; matterId: string }) {
  const { updateTaskOptimistic } = useMatterStore()
  const [editingName, setEditingName] = useState(false)
  const [nameVal, setNameVal] = useState(task.name)

  async function toggleDone() {
    const newStatus = task.status === 'Done' ? 'To Do' : 'Done'
    updateTaskOptimistic(task.id, { status: newStatus as Task['status'] })
    try {
      await patchTask(task.id, { is_block: task.is_block, status: newStatus })
    } catch {
      updateTaskOptimistic(task.id, { status: task.status })
    }
  }

  async function saveName() {
    setEditingName(false)
    if (nameVal === task.name) return
    updateTaskOptimistic(task.id, { name: nameVal })
    try {
      await patchTask(task.id, { is_block: task.is_block, name: nameVal })
    } catch {
      updateTaskOptimistic(task.id, { name: task.name })
    }
  }

  async function handleDelete() {
    updateTaskOptimistic(task.id, { status: 'Done' })
    try {
      await apiDeleteTask(task.id, !!task.is_block)
    } catch {
      updateTaskOptimistic(task.id, { status: task.status })
    }
  }

  const isDone = task.status === 'Done'

  return (
    <div className={`${styles.taskRow} ${isDone ? styles.taskDone : ''}`}>
      <button
        className={`${styles.taskCheck} ${isDone ? styles.taskCheckDone : ''}`}
        onClick={toggleDone}
        aria-label={isDone ? 'Mark incomplete' : 'Mark complete'}
      >
        {isDone
          ? <span className="material-symbols-outlined">check_circle</span>
          : <span className="material-symbols-outlined">radio_button_unchecked</span>
        }
      </button>

      <div className={styles.taskInfo}>
        {editingName ? (
          <input
            className={styles.taskNameInput}
            autoFocus
            value={nameVal}
            onChange={e => setNameVal(e.target.value)}
            onBlur={saveName}
            onKeyDown={e => { if (e.key === 'Enter') saveName(); if (e.key === 'Escape') setEditingName(false) }}
          />
        ) : (
          <span
            className={styles.taskName}
            onDoubleClick={() => setEditingName(true)}
            title="Double-click to rename"
          >
            {task.name}
          </span>
        )}
        <div className={styles.taskMeta}>
          {task.assignee && <span className={styles.taskChip}>{task.assignee}</span>}
          {task.deadline && <span className={styles.taskChip}>{formatDate(task.deadline)}</span>}
          {task.duration && <span className={styles.taskChipMuted}>{task.duration}m</span>}
        </div>
      </div>

      <button className={styles.taskDelete} onClick={handleDelete} aria-label="Complete task" title="Mark done">
        <span className="material-symbols-outlined">close</span>
      </button>
    </div>
  )
}

// ── Add task row ──────────────────────────────────────────────────────────────

function AddTaskRow({ matterId, stage }: { matterId: string; stage: string }) {
  const { addTaskOptimistic } = useMatterStore()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleAdd() {
    if (!name.trim()) return
    setSaving(true)
    try {
      const task = await createTask(matterId, { name: name.trim(), stage })
      addTaskOptimistic(task)
      setName('')
      setOpen(false)
    } catch {
      // leave form open so user can retry
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button className={styles.addTaskBtn} onClick={() => setOpen(true)}>
        <span className="material-symbols-outlined">add</span>
        Add task
      </button>
    )
  }

  return (
    <div className={styles.addTaskForm}>
      <input
        className={styles.addTaskInput}
        autoFocus
        placeholder="Task name…"
        value={name}
        onChange={e => setName(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') handleAdd()
          if (e.key === 'Escape') { setOpen(false); setName('') }
        }}
        disabled={saving}
      />
      <button className={styles.addTaskSave} onClick={handleAdd} disabled={saving || !name.trim()}>
        {saving ? <span className="material-symbols-outlined">hourglass_empty</span> : <span className="material-symbols-outlined">check</span>}
      </button>
      <button className={styles.addTaskCancel} onClick={() => { setOpen(false); setName('') }}>
        <span className="material-symbols-outlined">close</span>
      </button>
    </div>
  )
}

// ── Matter metadata grid ──────────────────────────────────────────────────────

function MetaGrid({ matter }: { matter: Matter }) {
  const { updateMatterOptimistic } = useMatterStore()

  async function handleStatusChange(status: string) {
    updateMatterOptimistic({ status })
    try {
      await patchMatter(matter.id, { status })
    } catch {
      updateMatterOptimistic({ status: matter.status })
    }
  }

  async function handlePriorityChange(priority: string) {
    updateMatterOptimistic({ priority })
    try {
      await patchMatter(matter.id, { priority })
    } catch {
      updateMatterOptimistic({ priority: matter.priority })
    }
  }

  return (
    <div className={styles.metaGrid}>
      <div className={styles.metaCell}>
        <span className={styles.metaLabel}>Status</span>
        <EditableSelect
          value={matter.status}
          options={STATUS_OPTIONS}
          onChange={handleStatusChange}
          label="Status"
        />
      </div>
      <div className={styles.metaCell}>
        <span className={styles.metaLabel}>Priority</span>
        <EditableSelect
          value={matter.priority}
          options={PRIORITY_OPTIONS}
          onChange={handlePriorityChange}
          label="Priority"
        />
      </div>
      <div className={styles.metaCell}>
        <span className={styles.metaLabel}>Assignee</span>
        <span className={styles.metaValue}>{matter.assignee || '—'}</span>
      </div>
      <div className={styles.metaCell}>
        <span className={styles.metaLabel}>Deadline</span>
        <span className={styles.metaValue}>{formatDate(matter.next_court_deadline ?? matter.target_date)}</span>
      </div>
      {matter.url && (
        <div className={styles.metaCell}>
          <span className={styles.metaLabel}>Notion</span>
          <a className={styles.metaLink} href={matter.url} target="_blank" rel="noopener noreferrer">
            Open page
            <span className="material-symbols-outlined" style={{ fontSize: 12 }}>open_in_new</span>
          </a>
        </div>
      )}
      {matter.slack_channel && (
        <div className={styles.metaCell}>
          <span className={styles.metaLabel}>Slack</span>
          <span className={styles.metaValue}>{matter.slack_channel}</span>
        </div>
      )}
    </div>
  )
}

// ── Task group ────────────────────────────────────────────────────────────────

function TaskGroup({
  stage, tasks, matterId, defaultOpen,
}: {
  stage: string; tasks: Task[]; matterId: string; defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const doneCount = tasks.filter(t => t.status === 'Done').length

  return (
    <div className={styles.taskGroup}>
      <button className={styles.taskGroupHeader} onClick={() => setOpen(v => !v)}>
        <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
          {open ? 'expand_more' : 'chevron_right'}
        </span>
        <span className={styles.taskGroupTitle}>{stage}</span>
        <span className={styles.taskGroupCount}>{doneCount}/{tasks.length}</span>
      </button>
      {open && (
        <div className={styles.taskGroupBody}>
          {tasks.map(t => (
            <TaskRow key={t.id} task={t} matterId={matterId} />
          ))}
          <AddTaskRow matterId={matterId} stage={stage} />
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function MatterDetailPanel() {
  const { selectedMatter, tasks, tasksLoading } = useMatterStore()

  if (!selectedMatter) return null

  // Group tasks by stage
  const grouped: Record<string, Task[]> = {}
  for (const t of tasks) {
    const stage = t.stage || 'Other'
    if (!grouped[stage]) grouped[stage] = []
    grouped[stage].push(t)
  }

  const orderedStages = [
    ...KLG_STAGES.filter(s => grouped[s]),
    ...Object.keys(grouped).filter(s => !KLG_STAGES.includes(s) && grouped[s]),
  ]

  // Stages with no tasks yet — show empty group for standard stages
  const allStages = orderedStages.length > 0
    ? orderedStages
    : KLG_STAGES.slice(0, 5)

  return (
    <div className={styles.panel}>
      {/* Header */}
      <div className={styles.panelHeader}>
        <h2 className={styles.panelTitle}>{selectedMatter.name}</h2>
      </div>

      {/* Stage progress */}
      <StageProgressBar currentStage={selectedMatter.case_stage} />

      {/* Metadata grid */}
      <MetaGrid matter={selectedMatter} />

      {/* Task list */}
      <div className={styles.taskSection}>
        <div className={styles.taskSectionHeader}>
          <span className={styles.taskSectionTitle}>Tasks</span>
          {tasksLoading && (
            <span className={styles.loadingDot}>
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>hourglass_empty</span>
            </span>
          )}
        </div>

        {!tasksLoading && tasks.length === 0 && (
          <div className={styles.noTasks}>
            <p>No structured tasks found. Tasks may be stored as page notes.</p>
            <AddTaskRow matterId={selectedMatter.id} stage="Brief Preparation & Drafting" />
          </div>
        )}

        {allStages.map((stage, i) => (
          <TaskGroup
            key={stage}
            stage={stage}
            tasks={grouped[stage] ?? []}
            matterId={selectedMatter.id}
            defaultOpen={i === 0}
          />
        ))}
      </div>
    </div>
  )
}
