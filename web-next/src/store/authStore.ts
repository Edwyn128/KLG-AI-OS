import { create } from 'zustand'
import {
  getStoredUser, getStoredPassword, getStoredToken,
  saveCredentials, saveToken, clearCredentials, apiFetch,
} from '@/api/client'
import { isAdmin, isActivityAdmin } from '@/data/users'

interface AuthState {
  user: string
  isAuthenticated: boolean
  showLogin: boolean

  // Derived
  isAdmin: boolean
  isActivityAdmin: boolean
  isClient: boolean
  allowedMatters: string[]

  // Actions
  setUser:         (name: string) => void
  login:           (user: string, password: string) => void
  loginWithToken:  (token: string, username: string) => void
  logout:          () => void
  requireLogin:    () => void
  dismissLogin:    () => void
  hydrate:         () => void
}

function _resolveClientMode() {
  ;(async () => {
    try {
      const r = await apiFetch('/alfred/auth/me')
      if (r.ok) {
        const me = await r.json()
        useAuthStore.setState({ isClient: me.is_client ?? false, allowedMatters: me.allowed_matters ?? [] })
      }
    } catch {}
  })()
}

export const useAuthStore = create<AuthState>((set) => ({
  user: '',
  isAuthenticated: false,
  showLogin: false,
  isAdmin: false,
  isActivityAdmin: false,
  isClient: false,
  allowedMatters: [],

  setUser: (name) => set({ user: name }),

  login: (user, password) => {
    saveCredentials(user, password)
    set({
      user,
      isAuthenticated: true,
      showLogin: false,
      isAdmin: isAdmin(user),
      isActivityAdmin: isActivityAdmin(user),
    })
    _resolveClientMode()
  },

  loginWithToken: (token, username) => {
    saveToken(token, username)
    set({
      user: username,
      isAuthenticated: true,
      showLogin: false,
      isAdmin: isAdmin(username),
      isActivityAdmin: isActivityAdmin(username),
    })
    _resolveClientMode()
  },

  logout: () => {
    clearCredentials()
    set({
      user: '',
      isAuthenticated: false,
      showLogin: true,
      isAdmin: false,
      isActivityAdmin: false,
      isClient: false,
      allowedMatters: [],
    })
  },

  requireLogin: () => set({ showLogin: true, isAuthenticated: false }),
  dismissLogin: () => set({ showLogin: false }),

  hydrate: () => {
    // 1. Check for OAuth callback — #sso=<token>&user=<name> in the URL hash
    try {
      const hash = window.location.hash.slice(1)
      if (hash.includes('sso=')) {
        const params = new URLSearchParams(hash)
        const token = params.get('sso') || ''
        const username = params.get('user') || 'Team'
        if (token) {
          saveToken(token, username)
          // Clean the hash so a refresh doesn't re-process the token
          window.history.replaceState(null, '', window.location.pathname + window.location.search)
          useAuthStore.setState({
            user: username,
            isAuthenticated: true,
            showLogin: false,
            isAdmin: isAdmin(username),
            isActivityAdmin: isActivityAdmin(username),
            isClient: false,
            allowedMatters: [],
          })
          _resolveClientMode()
          return
        }
      }

      // Check for OAuth error in hash
      if (hash.includes('error=')) {
        const params = new URLSearchParams(hash)
        const error = params.get('error') || 'Sign-in failed'
        window.history.replaceState(null, '', window.location.pathname)
        console.warn('SSO error:', decodeURIComponent(error))
      }
    } catch {}

    // 2. Check for stored JWT session token
    const token = getStoredToken()
    if (token) {
      try {
        const parts = token.split('.')
        if (parts.length === 3) {
          // Decode payload (no verification — the server will reject expired tokens)
          const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')))
          const exp = payload.exp ?? 0
          if (exp > Date.now() / 1000) {
            const name = (payload.name || payload.sub || 'Team') as string
            useAuthStore.setState({
              user: name,
              isAuthenticated: true,
              showLogin: false,
              isAdmin: isAdmin(name),
              isActivityAdmin: isActivityAdmin(name),
              isClient: false,
              allowedMatters: [],
            })
            _resolveClientMode()
            return
          } else {
            clearCredentials()
          }
        }
      } catch { clearCredentials() }
    }

    // 3. Fall back to Basic Auth credentials
    const user = getStoredUser()
    const password = getStoredPassword()
    if (user && password) {
      useAuthStore.setState({
        user,
        isAuthenticated: true,
        showLogin: false,
        isAdmin: isAdmin(user),
        isActivityAdmin: isActivityAdmin(user),
        isClient: false,
        allowedMatters: [],
      })
    } else if (user) {
      useAuthStore.setState({ user, showLogin: true, isClient: false, allowedMatters: [] })
    } else {
      useAuthStore.setState({ showLogin: true, isClient: false, allowedMatters: [] })
    }
  },
}))
