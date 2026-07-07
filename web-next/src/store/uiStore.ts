import { create } from 'zustand'
import type { Workspace } from '@/types'

interface UIState {
  activeWorkspace: Workspace
  isOnline: boolean
  clock: string

  setWorkspace: (ws: Workspace) => void
  setOnline: (online: boolean) => void
  setClock: (time: string) => void
}

export const useUIStore = create<UIState>((set) => ({
  activeWorkspace: 'chat',
  isOnline: true,
  clock: '',

  setWorkspace: (ws) => set({ activeWorkspace: ws }),
  setOnline:    (online) => set({ isOnline: online }),
  setClock:     (time) => set({ clock: time }),
}))
