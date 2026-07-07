import { create } from 'zustand'
import { getStoredUser, getStoredPassword, saveCredentials, clearCredentials } from '@/api/client'
import { isAdmin, isActivityAdmin } from '@/data/users'

interface AuthState {
  user: string
  isAuthenticated: boolean
  showLogin: boolean

  // Derived
  isAdmin: boolean
  isActivityAdmin: boolean

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
  },

  logout: () => {
    clearCredentials()
    set({ isAuthenticated: false, showLogin: true, isAdmin: false, isActivityAdmin: false })
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
      })
    } else if (user) {
      // User selected but no password yet
      set({ user, showLogin: true })
    } else {
      set({ showLogin: true })
    }
  },
}))
