import React, { useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import { verifyCredentials } from '@/api/client'
import { KLG_USERS } from '@/data/users'
import styles from './LoginModal.module.css'

export function LoginModal() {
  const { user, setUser, login, showLogin } = useAuthStore()
  const [step, setStep] = useState<'name' | 'password'>(user ? 'password' : 'name')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!showLogin) return null

  function selectUser(name: string) {
    setUser(name)
    setStep('password')
    setError('')
    setPassword('')
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault()
    if (!password.trim()) return
    setLoading(true)
    setError('')
    try {
      const ok = await verifyCredentials(user, password)
      if (ok) {
        login(user, password)
      } else {
        setError('Incorrect password. Try again.')
        setPassword('')
      }
    } catch {
      setError('Connection error. Check your network.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className={styles.overlay}>
      <div className={styles.modal}>
        <div className={styles.header}>
          <span className={styles.brand}>KLG</span>
          <span className={styles.subtitle}>AI Operating System</span>
        </div>

        {step === 'name' ? (
          <>
            <p className={styles.prompt}>Who are you?</p>
            <div className={styles.nameGrid}>
              {KLG_USERS.map(u => (
                <button
                  key={u.name}
                  className={styles.nameBtn}
                  onClick={() => selectUser(u.name)}
                >
                  <span className={styles.nameInitial}>{u.name[0]}</span>
                  <span className={styles.nameFull}>{u.name}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <p className={styles.prompt}>
              Welcome, <strong>{user}</strong>
            </p>
            <form onSubmit={handleLogin} className={styles.form}>
              <input
                type="password"
                className={styles.passwordInput}
                placeholder="Password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoFocus
                disabled={loading}
              />
              {error && <p className={styles.error}>{error}</p>}
              <button type="submit" className={styles.submitBtn} disabled={loading || !password}>
                {loading ? 'Verifying…' : 'Sign in'}
              </button>
            </form>
            <button className={styles.backBtn} onClick={() => setStep('name')}>
              ← Back
            </button>
          </>
        )}
      </div>
    </div>
  )
}
