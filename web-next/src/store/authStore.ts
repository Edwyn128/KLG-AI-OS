import { create } from 'zustand'
import { getStoredUser, getStoredPassword, saveCredentials, clearCredentials, apiFetch } from '@/api/client'
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
  setUser: (name: string) => void
  login: (user: string, password: string) => void
  logout: () => void
  requireLogin: () => void
  dismissLogin: () => void
  hydrate: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
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

    // Resolve client-mode status after credentials are saved so apiFetch
    // (which reads Basic Auth from localStorage) sends the right header.
    ;(async () => {
      try {
        const meResp = await apiFetch('/alfred/auth/me')
        if (meResp.ok) {
          const me = await meResp.json()
          set({ isClient: me.is_client ?? false, allowedMatters: me.allowed_matters ?? [] })
        }
      } catch {
        // Non-fatal — the UI falls back to treating the session as a firm user.
      }
    })()
  },

  logout: () => {
    clearCredentials()
    set({
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
    const user = getStoredUser()
    const password = getStoredPassword()
    if (user && password) {
      set({
        user,
        isAuthenticated: true,
        showLogin: false,
        isAdmin: isAdmin(user),
        isActivityAdmin: isActivityAdmin(user),
        isClient: false,
        allowedMatters: [],
      })
    } else if (user) {
      // User selected but no password yet
      set({ user, showLogin: true, isClient: false, allowedMatters: [] })
    } else {
      set({ showLogin: true, isClient: false, allowedMatters: [] })
    }
  },
}))
