import { create } from 'zustand'
import type { Workspace } from '@/types'

const COMPACT_KEY = 'klg_compact'

function loadCompact(): boolean {
  try { return localStorage.getItem(COMPACT_KEY) === '1' } catch { return false }
}

function applyCompact(v: boolean): void {
  if (typeof document === 'undefined') return
  if (v) {
    document.documentElement.setAttribute('data-compact', '')
  } else {
    document.documentElement.removeAttribute('data-compact')
  }
}

interface UIState {
  activeWorkspace: Workspace
  skillsOpen:      boolean
  isOnline:        boolean
  clock:           string
  compact:         boolean

  setWorkspace:   (ws: Workspace) => void
  setSkillsOpen:  (open: boolean) => void
  setOnline:      (online: boolean) => void
  setClock:       (time: string) => void
  toggleCompact:  () => void
  hydrateCompact: () => void
}

export const useUIStore = create<UIState>((set, get) => ({
  activeWorkspace: 'dashboard',
  skillsOpen:      false,
  isOnline:        true,
  clock:           '',
  compact:         false,

  setWorkspace:  (ws)     => set({ activeWorkspace: ws }),
  setSkillsOpen: (open)   => set({ skillsOpen: open }),
  setOnline:     (online) => set({ isOnline: online }),
  setClock:      (time)   => set({ clock: time }),

  toggleCompact: () => {
    const next = !get().compact
    try { localStorage.setItem(COMPACT_KEY, next ? '1' : '0') } catch {}
    applyCompact(next)
    set({ compact: next })
  },

  hydrateCompact: () => {
    const v = loadCompact()
    applyCompact(v)
    set({ compact: v })
  },
}))
