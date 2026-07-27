import styles from './AccountingWorkspace.module.css'

export function AccountingWorkspace() {
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className="material-symbols-outlined">receipt_long</span>
        <h1>Accounting</h1>
      </div>
      <div className={styles.placeholder}>
        <span className="material-symbols-outlined">construction</span>
        <p>Collections integration — coming soon</p>
      </div>
    </div>
  )
}
