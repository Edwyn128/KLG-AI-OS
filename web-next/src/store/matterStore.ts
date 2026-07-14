import { create } from 'zustand'
import type { Matter, Task } from '@/types'

interface MatterStore {
  selectedMatter: Matter | null
  tasks: Task[]
  tasksLoading: boolean

  setSelectedMatter: (m: Matter | null) => void
  setTasks: (tasks: Task[]) => void
  setTasksLoading: (v: boolean) => void
  updateTaskOptimistic: (id: string, fields: Partial<Task>) => void
  updateMatterOptimistic: (fields: Partial<Matter>) => void
  addTaskOptimistic: (task: Task) => void
}

export const useMatterStore = create<MatterStore>((set) => ({
  selectedMatter: null,
  tasks: [],
  tasksLoading: false,

  setSelectedMatter: (m) => set({ selectedMatter: m, tasks: [], tasksLoading: false }),
  setTasks: (tasks) => set({ tasks }),
  setTasksLoading: (v) => set({ tasksLoading: v }),

  updateTaskOptimistic: (id, fields) =>
    set((s) => ({
      tasks: s.tasks.map((t) => (t.id === id ? { ...t, ...fields } : t)),
    })),

  updateMatterOptimistic: (fields) =>
    set((s) => ({
      selectedMatter: s.selectedMatter ? { ...s.selectedMatter, ...fields } : null,
    })),

  addTaskOptimistic: (task) =>
    set((s) => ({ tasks: [...s.tasks, task] })),
}))
