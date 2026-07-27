import { useEffect, useState } from 'react'
import {
  fetchAdminUsers, createAdminUser, patchAdminUser, deleteAdminUser,
  type KLGUser,
} from '@/api/client'
import styles from './AdminWorkspace.module.css'

const ROLES = ['Managing Attorney', 'Systems Partner', 'Associate', 'Paralegal', 'Of Counsel', 'Admin', 'Client']

const PERMISSION_FLAGS: { key: keyof KLGUser; label: string }[] = [
  { key: 'is_admin',          label: 'Admin (Bloodhound, activity log)' },
  { key: 'is_accounting',     label: 'Accounting tab' },
  { key: 'can_create_matters', label: 'Create matters' },
  { key: 'can_edit_matters',   label: 'Edit matters' },
  { key: 'can_create_tasks',   label: 'Create tasks' },
  { key: 'can_edit_tasks',     label: 'Edit tasks' },
  { key: 'can_complete_tasks', label: 'Complete tasks' },
  { key: 'can_delete_tasks',   label: 'Delete tasks' },
]

function roleBadgeClass(role: string): string {
  const r = role.toLowerCase()
  if (r.includes('attorney') || r.includes('partner')) return styles.roleAttorney
  if (r.includes('admin')) return styles.roleAdmin
  if (r.includes('client')) return styles.roleClient
  return styles.roleDefault
}

// ── User list item ────────────────────────────────────────────────────────────

function UserListItem({
  user, selected, onSelect,
}: {
  user: KLGUser; selected: boolean; onSelect: () => void
}) {
  return (
    <button
      className={`${styles.userRow} ${selected ? styles.userRowActive : ''} ${!user.active ? styles.userRowInactive : ''}`}
      onClick={onSelect}
    >
      <div className={styles.userAvatar}>
        {(user.display_name || user.name)[0]?.toUpperCase() ?? '?'}
      </div>
      <div className={styles.userRowInfo}>
        <span className={styles.userName}>{user.display_name || user.name}</span>
        <span className={styles.userLogin}>{user.name}</span>
      </div>
      <span className={`${styles.roleBadge} ${roleBadgeClass(user.role)}`}>{user.role || 'No role'}</span>
      {!user.active && (
        <span className={styles.inactivePill}>Inactive</span>
      )}
    </button>
  )
}

// ── User edit panel ───────────────────────────────────────────────────────────

function UserEditPanel({
  user, onSave, onDeactivate, onClose,
}: {
  user: KLGUser
  onSave: (updated: KLGUser) => void
  onDeactivate: () => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState<KLGUser>({ ...user })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function update<K extends keyof KLGUser>(key: K, value: KLGUser[K]) {
    setDraft(prev => ({ ...prev, [key]: value }))
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const updated = await patchAdminUser(user.id, draft)
      onSave(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function handleDeactivate() {
    if (!window.confirm(`Deactivate ${user.display_name || user.name}? They won't be able to log in.`)) return
    setSaving(true)
    try {
      await deleteAdminUser(user.id)
      onDeactivate()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Deactivate failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.editPanel}>
      <div className={styles.editHeader}>
        <div className={styles.editAvatar}>
          {(draft.display_name || draft.name)[0]?.toUpperCase() ?? '?'}
        </div>
        <div>
          <div className={styles.editName}>{draft.display_name || draft.name}</div>
          <div className={styles.editLogin}>{draft.name}</div>
        </div>
        <button className={styles.closeBtn} onClick={onClose} title="Close">
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>close</span>
        </button>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.editSection}>
        <label className={styles.editLabel}>Display name</label>
        <input
          className={styles.editInput}
          value={draft.display_name}
          onChange={e => update('display_name', e.target.value)}
        />
      </div>

      <div className={styles.editSection}>
        <label className={styles.editLabel}>Role</label>
        <select
          className={styles.editSelect}
          value={draft.role}
          onChange={e => update('role', e.target.value)}
        >
          <option value="">— Select role —</option>
          {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>

      <div className={styles.editSection}>
        <label className={styles.editLabel}>Email</label>
        <input
          className={styles.editInput}
          type="email"
          value={draft.email}
          onChange={e => update('email', e.target.value)}
        />
      </div>

      <div className={styles.editSection}>
        <label className={styles.editLabel}>Allowed matters (client only)</label>
        <input
          className={styles.editInput}
          placeholder="Matter Name 1, Matter Name 2"
          value={draft.allowed_matters}
          onChange={e => update('allowed_matters', e.target.value)}
        />
      </div>

      <div className={styles.editSection}>
        <label className={styles.editLabel}>Permissions</label>
        <div className={styles.permGrid}>
          {PERMISSION_FLAGS.map(({ key, label }) => (
            <label key={key} className={styles.permRow}>
              <input
                type="checkbox"
                checked={!!draft[key]}
                onChange={e => update(key, e.target.checked as KLGUser[typeof key])}
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </div>

      <div className={styles.editActions}>
        <button
          className={styles.saveBtn}
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
        {user.active && (
          <button
            className={styles.deactivateBtn}
            onClick={handleDeactivate}
            disabled={saving}
          >
            Deactivate
          </button>
        )}
      </div>
    </div>
  )
}

// ── Add user form ─────────────────────────────────────────────────────────────

function AddUserForm({
  onCreated, onCancel,
}: {
  onCreated: (user: KLGUser) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    if (!name.trim()) return
    setSaving(true)
    setError(null)
    try {
      const user = await createAdminUser({
        name: name.trim().toLowerCase(),
        display_name: displayName.trim() || name.trim(),
        role,
        active: true,
        is_admin: false, is_super_admin: false, is_accounting: false,
        can_create_matters: false, can_edit_matters: false,
        can_create_tasks: true, can_edit_tasks: true, can_complete_tasks: true, can_delete_tasks: false,
        email: '', allowed_matters: '',
      })
      onCreated(user)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={styles.addForm}>
      <div className={styles.addFormTitle}>New user</div>
      {error && <div className={styles.errorBanner}>{error}</div>}
      <input
        className={styles.editInput}
        placeholder="Login username (lowercase)"
        value={name}
        onChange={e => setName(e.target.value)}
        autoFocus
      />
      <input
        className={styles.editInput}
        placeholder="Display name"
        value={displayName}
        onChange={e => setDisplayName(e.target.value)}
      />
      <select
        className={styles.editSelect}
        value={role}
        onChange={e => setRole(e.target.value)}
      >
        <option value="">— Role —</option>
        {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
      </select>
      <div className={styles.addFormActions}>
        <button className={styles.saveBtn} onClick={handleCreate} disabled={saving || !name.trim()}>
          {saving ? 'Creating…' : 'Create'}
        </button>
        <button className={styles.cancelBtn} onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function AdminWorkspace() {
  const [users, setUsers] = useState<KLGUser[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [addingUser, setAddingUser] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    fetchAdminUsers()
      .then(list => {
        if (cancelled) return
        setUsers(list)
        if (list.length === 0) {
          setNotice('No users found. The KLG Users database may not be configured yet — set NOTION_USERS_DB_ID in Railway.')
        }
      })
      .catch((e: unknown) => {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : 'Failed to load users'
        if (msg.includes('not configured')) {
          setNotice('NOTION_USERS_DB_ID not configured. Set it in Railway env vars to enable user management.')
          setUsers([])
        } else {
          setError(msg)
        }
      })
      .finally(() => { if (!cancelled) setLoading(false) })

    return () => { cancelled = true }
  }, [])

  const selectedUser = users.find(u => u.id === selectedId) ?? null
  const activeUsers = users.filter(u => u.active)
  const inactiveUsers = users.filter(u => !u.active)

  function handleSave(updated: KLGUser) {
    setUsers(prev => prev.map(u => u.id === updated.id ? updated : u))
  }

  function handleDeactivate() {
    setUsers(prev => prev.map(u => u.id === selectedId ? { ...u, active: false } : u))
    setSelectedId(null)
  }

  function handleCreated(user: KLGUser) {
    setUsers(prev => [...prev, user])
    setSelectedId(user.id)
    setAddingUser(false)
    setNotice(null)
  }

  return (
    <div className={styles.container}>
      {/* Left: user list */}
      <div className={styles.listPanel}>
        <div className={styles.listHeader}>
          <div className={styles.listTitle}>
            <span className="material-symbols-outlined" style={{ fontSize: 16 }}>admin_panel_settings</span>
            Users
            <span className={styles.userCount}>{activeUsers.length} active</span>
          </div>
          <button className={styles.addBtn} onClick={() => { setAddingUser(true); setSelectedId(null) }}>
            <span className="material-symbols-outlined" style={{ fontSize: 15 }}>person_add</span>
          </button>
        </div>

        {loading ? (
          <div className={styles.skeletonList}>
            {[0, 1, 2].map(i => <div key={i} className={styles.skeletonRow} />)}
          </div>
        ) : error ? (
          <div className={styles.listError}>
            <span className="material-symbols-outlined">error_outline</span>
            <p>{error}</p>
          </div>
        ) : (
          <div className={styles.userList}>
            {notice && (
              <div className={styles.noticeBanner}>
                <span className="material-symbols-outlined" style={{ fontSize: 14 }}>info</span>
                <p>{notice}</p>
              </div>
            )}

            {activeUsers.length > 0 && (
              <>
                <div className={styles.listSection}>Active</div>
                {activeUsers.map(u => (
                  <UserListItem
                    key={u.id}
                    user={u}
                    selected={u.id === selectedId}
                    onSelect={() => { setSelectedId(u.id); setAddingUser(false) }}
                  />
                ))}
              </>
            )}

            {inactiveUsers.length > 0 && (
              <>
                <div className={styles.listSection}>Inactive</div>
                {inactiveUsers.map(u => (
                  <UserListItem
                    key={u.id}
                    user={u}
                    selected={u.id === selectedId}
                    onSelect={() => { setSelectedId(u.id); setAddingUser(false) }}
                  />
                ))}
              </>
            )}
          </div>
        )}
      </div>

      {/* Right: detail / edit panel */}
      <div className={styles.detailPanel}>
        {addingUser ? (
          <AddUserForm
            onCreated={handleCreated}
            onCancel={() => setAddingUser(false)}
          />
        ) : selectedUser ? (
          <UserEditPanel
            key={selectedUser.id}
            user={selectedUser}
            onSave={handleSave}
            onDeactivate={handleDeactivate}
            onClose={() => setSelectedId(null)}
          />
        ) : (
          <div className={styles.detailEmpty}>
            <span className="material-symbols-outlined">manage_accounts</span>
            <p>Select a user to edit permissions</p>
            <button className={styles.addBtnLarge} onClick={() => setAddingUser(true)}>
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>person_add</span>
              Add user
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
