import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import { useChatStore } from '@/store/chatStore'
import { apiFetch } from '@/api/client'
import type { ChatMessage, SSEEvent, UploadResponse } from '@/types'
import styles from './ChatWorkspace.module.css'

function genId(): string {
  return `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
}

export function ChatWorkspace() {
  const { user } = useAuthStore()
  const {
    alfredMessages,
    alfredHistory,
    pendingFiles,
    isLoading,
    selectedModel,
    models,
    draftInput,
    setModel,
    setLoading,
    addMessage,
    updateStreamingMessage,
    finalizeMessage,
    setAlfredHistory,
    addPendingFile,
    removePendingFile,
    clearPendingFiles,
    clearChat,
    setDraftInput,
  } = useChatStore()

  const [text, setText] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Pre-fill from Skills launcher
  useEffect(() => {
    if (!draftInput) return
    setText(draftInput)
    setDraftInput('')
    textareaRef.current?.focus()
  }, [draftInput, setDraftInput])

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [alfredMessages])

  async function handleSend() {
    const msg = text.trim()
    if (!msg || isLoading) return

    setText('')
    const fileTokens = pendingFiles.map(f => f.token)
    clearPendingFiles()

    const userMsgId = genId()
    addMessage('alfred', {
      id: userMsgId,
      role: 'user',
      text: msg,
      name: user || 'You',
    })

    const alfredMsgId = genId()
    addMessage('alfred', {
      id: alfredMsgId,
      role: 'alfred',
      text: '',
      name: 'Alfred',
      isStreaming: true,
    })

    setLoading(true)

    try {
      const res = await apiFetch('/alfred/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: msg,
          model: selectedModel,
          history: alfredHistory,
          file_tokens: fileTokens,
        }),
      })

      const contentType = res.headers.get('content-type') ?? ''

      if (contentType.includes('text/event-stream')) {
        const reader = res.body!.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let accumulated = ''

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.startsWith('data:')) continue
            const payload = line.slice(5).trim()
            if (!payload) continue
            try {
              const event: SSEEvent = JSON.parse(payload)
              if ('delta' in event) {
                accumulated += event.delta
                updateStreamingMessage(alfredMsgId, accumulated)
              } else if ('done' in event) {
                finalizeMessage(alfredMsgId, event.tools_used)
                setAlfredHistory(event.history)
                setLoading(false)
              } else if ('error' in event) {
                finalizeMessage(alfredMsgId, [])
                addMessage('alfred', {
                  id: genId(),
                  role: 'alfred',
                  text: `Error: ${event.error}`,
                  name: 'Alfred',
                })
                setLoading(false)
              }
            } catch {
              // Malformed SSE line — skip
            }
          }
        }
        // Ensure loading cleared if stream ended without done event
        setLoading(false)
        if (accumulated) finalizeMessage(alfredMsgId, [])
      } else {
        const data = await res.json()
        const responseText: string = data.response ?? data.error ?? 'No response received.'
        updateStreamingMessage(alfredMsgId, responseText)
        finalizeMessage(alfredMsgId, data.tools_used ?? [])
        setAlfredHistory(data.history ?? [])
        setLoading(false)
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Request failed'
      updateStreamingMessage(alfredMsgId, `Alfred encountered an error: ${message}`)
      finalizeMessage(alfredMsgId, [])
      setLoading(false)
    }
  }

  async function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''

    try {
      const form = new FormData()
      form.append('file', file)
      const res = await apiFetch('/alfred/upload', { method: 'POST', body: form })
      if (!res.ok) throw new Error('Upload failed')
      const data: UploadResponse = await res.json()
      addPendingFile({ token: data.file_token, filename: data.filename })
    } catch (err: unknown) {
      console.error('File upload error:', err)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className={styles.container}>
      {/* Toolbar */}
      <div className={styles.toolbar}>
        <select
          className={styles.modelSelect}
          value={selectedModel}
          onChange={e => setModel(e.target.value as typeof selectedModel)}
        >
          {models.map(m => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>

        <button
          className={styles.clearBtn}
          onClick={() => clearChat('alfred')}
          title="Clear conversation"
        >
          <span className="material-symbols-outlined">delete_sweep</span>
        </button>
      </div>

      {/* Message list */}
      <div className={styles.messages}>
        {alfredMessages.length === 0 ? (
          <div className={styles.empty}>
            <span className="material-symbols-outlined">smart_toy</span>
            <p>Send a message to Alfred</p>
          </div>
        ) : (
          alfredMessages.map((msg: ChatMessage) => (
            <div
              key={msg.id}
              className={`${styles.message} ${msg.role === 'user' ? styles.user : styles.alfred}`}
            >
              <div className={styles.bubble}>
                {msg.text}
                {msg.isStreaming && <span className={styles.cursor}>|</span>}
              </div>
              {msg.toolsUsed && msg.toolsUsed.length > 0 && (
                <div className={styles.toolsUsed}>
                  {msg.toolsUsed.map(t => (
                    <span key={t} className={styles.toolChip}>{t}</span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Pending files */}
      {pendingFiles.length > 0 && (
        <div className={styles.filesStrip}>
          {pendingFiles.map(f => (
            <span key={f.token} className={styles.fileChip}>
              <span className="material-symbols-outlined" style={{ fontSize: 12 }}>attach_file</span>
              {f.filename}
              <button
                className={styles.fileRemove}
                onClick={() => removePendingFile(f.token)}
                aria-label={`Remove ${f.filename}`}
              >
                <span className="material-symbols-outlined">close</span>
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Input bar */}
      <div className={styles.inputBar}>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          onChange={handleFileSelect}
          accept=".pdf,.doc,.docx,.txt,.md"
        />
        <button
          className={styles.attachBtn}
          onClick={() => fileInputRef.current?.click()}
          title="Attach file"
          disabled={isLoading}
        >
          <span className="material-symbols-outlined">attach_file</span>
        </button>

        <textarea
          ref={textareaRef}
          className={styles.textarea}
          placeholder="Message Alfred…"
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={isLoading}
        />

        <button
          className={styles.sendBtn}
          onClick={handleSend}
          disabled={isLoading || !text.trim()}
          title="Send"
        >
          {isLoading
            ? <span className="material-symbols-outlined">hourglass_empty</span>
            : <span className="material-symbols-outlined">send</span>
          }
        </button>
      </div>
    </div>
  )
}
