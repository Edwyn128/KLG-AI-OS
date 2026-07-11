import { create } from 'zustand'
import type { Agent, ChatMessage, FileToken } from '@/types'

const MODELS = [
  { value: 'claude-sonnet-4-6',  label: 'Claude Sonnet 4.6',   provider: 'anthropic' },
  { value: 'claude-opus-4-8',    label: 'Claude Opus 4.8',     provider: 'anthropic' },
  { value: 'gpt-4o',             label: 'GPT-4o',              provider: 'openai'    },
  { value: 'gpt-4o-mini',        label: 'GPT-4o Mini',         provider: 'openai'    },
  { value: 'gemini-2.0-flash',   label: 'Gemini 2.0 Flash',   provider: 'google'    },
  { value: 'sonar-pro',          label: 'Perplexity Sonar Pro', provider: 'perplexity' },
] as const

export type ModelValue = (typeof MODELS)[number]['value']

interface ChatState {
  currentAgent: Agent
  selectedModel: ModelValue
  isLoading: boolean

  // Alfred conversation
  alfredMessages: ChatMessage[]
  alfredHistory: unknown[]

  // Bloodhound conversation
  bloodhoundMessages: ChatMessage[]

  // File attachments pending next send
  pendingFiles: FileToken[]

  // Available models list
  models: typeof MODELS

  // Draft input pre-filled by Skills launcher
  draftInput: string

  // Actions
  setAgent: (agent: Agent) => void
  setModel: (model: ModelValue) => void
  setLoading: (loading: boolean) => void
  addMessage: (agent: Agent, msg: ChatMessage) => void
  updateStreamingMessage: (id: string, text: string) => void
  finalizeMessage: (id: string, toolsUsed: string[]) => void
  setAlfredHistory: (history: unknown[]) => void
  addPendingFile: (file: FileToken) => void
  removePendingFile: (token: string) => void
  clearPendingFiles: () => void
  clearChat: (agent: Agent) => void
  setDraftInput: (v: string) => void
}

export const useChatStore = create<ChatState>((set, get) => ({
  currentAgent: 'alfred',
  selectedModel: 'claude-sonnet-4-6',
  isLoading: false,
  alfredMessages: [],
  alfredHistory: [],
  bloodhoundMessages: [],
  pendingFiles: [],
  models: MODELS,
  draftInput: '',

  setAgent: (agent) => set({ currentAgent: agent }),
  setModel: (model) => set({ selectedModel: model }),
  setLoading: (loading) => set({ isLoading: loading }),

  addMessage: (agent, msg) => {
    if (agent === 'alfred') {
      set(s => ({ alfredMessages: [...s.alfredMessages, msg] }))
    } else {
      set(s => ({ bloodhoundMessages: [...s.bloodhoundMessages, msg] }))
    }
  },

  updateStreamingMessage: (id, text) => {
    set(s => ({
      alfredMessages: s.alfredMessages.map(m =>
        m.id === id ? { ...m, text, isStreaming: true } : m
      ),
    }))
  },

  finalizeMessage: (id, toolsUsed) => {
    set(s => ({
      alfredMessages: s.alfredMessages.map(m =>
        m.id === id ? { ...m, isStreaming: false, toolsUsed } : m
      ),
    }))
  },

  setAlfredHistory: (history) => set({ alfredHistory: history }),

  addPendingFile: (file) => set(s => ({ pendingFiles: [...s.pendingFiles, file] })),

  removePendingFile: (token) =>
    set(s => ({ pendingFiles: s.pendingFiles.filter(f => f.token !== token) })),

  clearPendingFiles: () => set({ pendingFiles: [] }),

  clearChat: (agent) => {
    if (agent === 'alfred') {
      set({ alfredMessages: [], alfredHistory: [] })
    } else {
      set({ bloodhoundMessages: [] })
    }
  },

  setDraftInput: (v) => set({ draftInput: v }),
}))
