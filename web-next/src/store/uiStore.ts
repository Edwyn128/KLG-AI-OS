import { create } from 'zustand'
import type { Workspace } from '@/types'

interface UIState {
  activeWorkspace: Workspace
  skillsOpen: boolean
  isOnline: boolean
  clock: string

  setWorkspace: (ws: Workspace) => void
  setSkillsOpen: (open: boolean) => void
  setOnline: (online: boolean) => void
  setClock: (time: string) => void
}

export const useUIStore = create<UIState>((set) => ({
  activeWorkspace: 'dashboard',
  skillsOpen: false,
  isOnline: true,
  clock: '',

  setWorkspace:  (ws)     => set({ activeWorkspace: ws }),
  setSkillsOpen: (open)   => set({ skillsOpen: open }),
  setOnline:     (online) => set({ isOnline: online }),
  setClock:      (time)   => set({ clock: time }),
}))
