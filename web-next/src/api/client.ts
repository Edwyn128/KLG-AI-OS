// =============================================================================
// KLG AI OS — API Client
// Thin wrapper around fetch that injects Basic Auth and handles 401s.
// =============================================================================

import { useAuthStore } from '@/store/authStore'
import type { MatterListResponse, DeadlineItem, Matter, Task } from '@/types'

const AUTH_STORAGE_KEY_USER = 'klg_user'
const AUTH_STORAGE_KEY_PASS = 'klg_password'

// Read auth directly from localStorage so this works outside React context.
export function getStoredUser(): string {
  return localStorage.getItem(AUTH_STORAGE_KEY_USER) ?? ''
}
export function getStoredPassword(): string {
  return localStorage.getItem(AUTH_STORAGE_KEY_PASS) ?? ''
}
export function saveCredentials(user: string, password: string): void {
  localStorage.setItem(AUTH_STORAGE_KEY_USER, user)
  localStorage.setItem(AUTH_STORAGE_KEY_PASS, password)
}
export function clearCredentials(): void {
  localStorage.removeItem(AUTH_STORAGE_KEY_PASS)
}

function buildAuthHeader(): string | null {
  const user = getStoredUser()
  const pass = getStoredPassword()
  if (!pass) return null
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

export async function fetchMatters(): Promise<MatterListResponse> {
  const res = await apiFetch('/alfred/matters')
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
