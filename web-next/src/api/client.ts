// =============================================================================
// KLG AI OS — API Client
// Thin wrapper around fetch that injects Basic Auth and handles 401s.
// =============================================================================

import { useAuthStore } from '@/store/authStore'
import type { MatterListResponse, DeadlineItem, Matter, Task, WatchCase } from '@/types'

const AUTH_STORAGE_KEY_USER  = 'klg_user'
const AUTH_STORAGE_KEY_PASS  = 'klg_password'
const AUTH_STORAGE_KEY_TOKEN = 'klg_session_token'

// Read auth directly from localStorage so this works outside React context.
export function getStoredUser(): string {
  return localStorage.getItem(AUTH_STORAGE_KEY_USER) ?? ''
}
export function getStoredPassword(): string {
  return localStorage.getItem(AUTH_STORAGE_KEY_PASS) ?? ''
}
export function getStoredToken(): string {
  return localStorage.getItem(AUTH_STORAGE_KEY_TOKEN) ?? ''
}
export function saveCredentials(user: string, password: string): void {
  localStorage.setItem(AUTH_STORAGE_KEY_USER, user)
  localStorage.setItem(AUTH_STORAGE_KEY_PASS, password)
}
export function saveToken(token: string, username: string): void {
  localStorage.setItem(AUTH_STORAGE_KEY_TOKEN, token)
  localStorage.setItem(AUTH_STORAGE_KEY_USER, username)
  localStorage.removeItem(AUTH_STORAGE_KEY_PASS)
}
export function clearCredentials(): void {
  localStorage.removeItem(AUTH_STORAGE_KEY_PASS)
  localStorage.removeItem(AUTH_STORAGE_KEY_TOKEN)
}

function buildAuthHeader(): string | null {
  // Prefer OAuth JWT session token over Basic Auth
  const token = getStoredToken()
  if (token) return `Bearer ${token}`

  const pass = getStoredPassword()
  if (!pass) return null
  const user = getStoredUser()
  const credentials = user && user !== 'Team' ? `${user}:${pass}` : `klg:${pass}`
  return 'Basic ' + btoa(credentials)
}

export interface FetchOptions extends RequestInit {
  // Don't send auth header (e.g., for public endpoints)
  skipAuth?: boolean
}

/**
 * Authenticated fetch wrapper.
 * - Injects Basic Auth header automatically
 * - On 401: clears stored password and triggers login modal
 * - On network errors: throws with descriptive message
 */
export async function apiFetch(path: string, options: FetchOptions = {}): Promise<Response> {
  const { skipAuth, ...fetchOptions } = options

  const headers = new Headers(fetchOptions.headers)

  if (!skipAuth) {
    const auth = buildAuthHeader()
    if (auth) headers.set('Authorization', auth)
  }

  if (!(fetchOptions.body instanceof FormData)) {
    if (!headers.has('Content-Type') && fetchOptions.body) {
      headers.set('Content-Type', 'application/json')
    }
  }

  const response = await fetch(path, { ...fetchOptions, headers })

  if (response.status === 401) {
    clearCredentials()
    // Signal the auth store to show the login modal
    useAuthStore.getState().requireLogin()
    throw new Error('Session expired. Please log in again.')
  }

  return response
}

export async function fetchMatters(archived = false): Promise<MatterListResponse> {
  const res = await apiFetch(archived ? '/alfred/matters?archived=true' : '/alfred/matters')
  if (!res.ok) throw new Error('Failed to fetch matters')
  return res.json()
}

export async function fetchDeadlines(): Promise<DeadlineItem[]> {
  const res = await apiFetch('/alfred/deadlines')
  if (!res.ok) throw new Error('Failed to fetch deadlines')
  const data = await res.json()
  // Endpoint returns { matters: [...], count, days_ahead, category }
  return Array.isArray(data) ? data : (data.matters ?? [])
}

export async function fetchMatterDetail(id: string): Promise<Matter> {
  const res = await apiFetch(`/alfred/matters/${id}`)
  if (!res.ok) throw new Error('Failed to fetch matter detail')
  return res.json()
}

export async function fetchMatterTasks(id: string): Promise<Task[]> {
  const res = await apiFetch(`/alfred/matters/${id}/tasks`)
  if (!res.ok) throw new Error('Failed to fetch matter tasks')
  const data = await res.json()
  return Array.isArray(data) ? data : (data.tasks ?? [])
}

export async function patchMatter(id: string, fields: Partial<Matter>): Promise<Matter> {
  const res = await apiFetch(`/alfred/matters/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(fields),
  })
  if (!res.ok) throw new Error('Failed to update matter')
  return res.json()
}

export async function createTask(matterId: string, task: Partial<Task>): Promise<Task> {
  const res = await apiFetch(`/alfred/matters/${matterId}/tasks`, {
    method: 'POST',
    body: JSON.stringify(task),
  })
  if (!res.ok) throw new Error('Failed to create task')
  return res.json()
}

export async function patchTask(taskId: string, fields: Partial<Task> & { is_block?: boolean }): Promise<Task> {
  const res = await apiFetch(`/alfred/tasks/${taskId}`, {
    method: 'PATCH',
    body: JSON.stringify(fields),
  })
  if (!res.ok) throw new Error('Failed to update task')
  return res.json()
}

export async function deleteTask(taskId: string, isBlock = false): Promise<void> {
  const res = await apiFetch(`/alfred/tasks/${taskId}?is_block=${isBlock}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to delete task')
}

export interface KLGUser {
  id: string; name: string; display_name: string; role: string; email: string
  is_admin: boolean; is_super_admin: boolean; is_accounting: boolean
  can_create_matters: boolean; can_edit_matters: boolean
  can_create_tasks: boolean; can_edit_tasks: boolean
  can_complete_tasks: boolean; can_delete_tasks: boolean
  active: boolean; allowed_matters: string
}

export async function fetchAdminUsers(): Promise<KLGUser[]> {
  const res = await apiFetch('/admin/users')
  if (!res.ok) throw new Error('Failed to fetch users')
  const data = await res.json()
  return data.users ?? []
}

export async function createAdminUser(fields: Partial<KLGUser> & { name: string }): Promise<KLGUser> {
  const res = await apiFetch('/admin/users', { method: 'POST', body: JSON.stringify(fields) })
  if (!res.ok) throw new Error('Failed to create user')
  return res.json()
}

export async function patchAdminUser(id: string, fields: Partial<KLGUser>): Promise<KLGUser> {
  const res = await apiFetch(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(fields) })
  if (!res.ok) throw new Error('Failed to update user')
  return res.json()
}

export async function deleteAdminUser(id: string): Promise<void> {
  const res = await apiFetch(`/admin/users/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error('Failed to deactivate user')
}

export async function fetchTodayTasks(): Promise<{ user: string; tasks: Task[] }> {
  const res = await apiFetch('/alfred/today/tasks')
  if (!res.ok) throw new Error('Failed to fetch today tasks')
  return res.json()
}

export async function fetchTodayBriefing(): Promise<{ focus: string; user: string }> {
  const res = await apiFetch('/alfred/today/briefing')
  if (!res.ok) throw new Error('Failed to fetch today briefing')
  return res.json()
}

export async function fetchAllTasks(): Promise<(Task & { matter_name: string })[]> {
  const res = await apiFetch('/alfred/deadlines/tasks')
  if (!res.ok) throw new Error('Failed to fetch all tasks')
  const data = await res.json()
  return Array.isArray(data) ? data : (data.tasks ?? [])
}

export async function fetchWatchList(tier?: string): Promise<WatchCase[]> {
  const url = tier ? `/bloodhound/watch-list?tier=${tier}` : '/bloodhound/watch-list'
  const res = await apiFetch(url)
  if (!res.ok) throw new Error('Failed to fetch Watch List')
  const data = await res.json()
  return Array.isArray(data) ? data : (data.cases ?? [])
}

export async function triggerBloodhoundScan(): Promise<{ added_count: number; new_signals: number }> {
  const res = await apiFetch('/bloodhound/scan', { method: 'POST' })
  if (!res.ok) throw new Error('Bloodhound scan failed')
  return res.json()
}

/**
 * Verify credentials against the server.
 * Returns true if valid, false if invalid, throws on network error.
 */
export async function verifyCredentials(user: string, password: string): Promise<boolean> {
  const credentials = user && user !== 'Team' ? `${user}:${password}` : `klg:${password}`
  const response = await fetch('/auth/check', {
    headers: { Authorization: 'Basic ' + btoa(credentials) },
  })
  return response.ok
}
