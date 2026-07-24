import React, { useState } from 'react'
import { useAuthStore } from '@/store/authStore'
import { useUIStore } from '@/store/uiStore'
import { verifyCredentials } from '@/api/client'
import { KLG_USERS } from '@/data/users'
import styles from './LoginModal.module.css'

export function LoginModal() {
  const { user, setUser, login, showLogin } = useAuthStore()
  const { hydrateCompact } = useUIStore()
  const [step, setStep] = useState<'method' | 'name' | 'password'>(user ? 'password' : 'method')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Restore compact preference whenever the login modal mounts
  React.useEffect(() => { hydrateCompact() }, [hydrateCompact])

  if (!showLogin) return null

  function selectUser(name: string) {
    setUser(name)
    setStep('password')
    setError('')
    setPassword('')
  }

  function goToPassword() {
    setStep('name')
    setError('')
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

        {step === 'method' ? (
          <>
            <p className={styles.prompt}>How would you like to sign in?</p>
            <div className={styles.methodGrid}>
              <a href="/auth/microsoft" className={styles.msBtn}>
                <svg className={styles.msLogo} viewBox="0 0 21 21" aria-hidden="true">
                  <rect x="0"  y="0"  width="10" height="10" fill="#F25022"/>
                  <rect x="11" y="0"  width="10" height="10" fill="#7FBA00"/>
                  <rect x="0"  y="11" width="10" height="10" fill="#00A4EF"/>
                  <rect x="11" y="11" width="10" height="10" fill="#FFB900"/>
                </svg>
                Sign in with Microsoft
              </a>
              <button className={styles.pwBtn} onClick={goToPassword}>
                <span className={styles.pwIcon}>🔑</span>
                Sign in with password
              </button>
            </div>
          </>
        ) : step === 'name' ? (
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
            <button className={styles.backBtn} onClick={() => setStep('method')}>← Back</button>
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
