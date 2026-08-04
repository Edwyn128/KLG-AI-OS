import styles from './AccountingWorkspace.module.css'

interface Invoice {
  id: string
  client: string
  matter: string
  amount: string
  dueDate: string
  status: 'Paid' | 'Pending' | 'Overdue'
}

const SAMPLE_INVOICES: Invoice[] = [
  { id: 'INV-2026-081', client: 'Smith Trust', matter: 'Smith v. City of Los Angeles', amount: '$12,450.00', dueDate: 'Aug 15, 2026', status: 'Pending' },
  { id: 'INV-2026-080', client: 'Davis Family', matter: 'In re Marriage of Davis', amount: '$4,800.00', dueDate: 'Aug 01, 2026', status: 'Paid' },
  { id: 'INV-2026-079', client: 'Apex Corp', matter: 'Apex Corp v. Zenith Holdings', amount: '$28,900.00', dueDate: 'Jul 28, 2026', status: 'Overdue' },
  { id: 'INV-2026-078', client: 'Henderson Defense', matter: 'People v. Henderson', amount: '$8,500.00', dueDate: 'Jul 15, 2026', status: 'Paid' },
]

export function AccountingWorkspace() {
  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <div className={styles.titleGroup}>
          <span className={`material-symbols-outlined ${styles.titleIcon}`}>receipt_long</span>
          <h1>Accounting & Retainers Dashboard</h1>
        </div>
      </div>

      <div className={styles.metricsGrid}>
        <div className={styles.metricCard}>
          <span className="material-symbols-outlined" style={{ fontSize: 24, color: 'var(--ok)' }}>attach_money</span>
          <div>
            <div className={styles.metricValue}>$54,650.00</div>
            <div className={styles.metricLabel}>Total Outstanding Invoices</div>
          </div>
        </div>

        <div className={styles.metricCard}>
          <span className="material-symbols-outlined" style={{ fontSize: 24, color: 'var(--bh-accent)' }}>account_balance</span>
          <div>
            <div className={styles.metricValue}>$185,000.00</div>
            <div className={styles.metricLabel}>Active Retainers Trust Balance</div>
          </div>
        </div>

        <div className={styles.metricCard}>
          <span className="material-symbols-outlined" style={{ fontSize: 24, color: 'var(--urgent)' }}>warning</span>
          <div>
            <div className={styles.metricValue}>1 Overdue Invoice</div>
            <div className={styles.metricLabel}>Requires Follow-up</div>
          </div>
        </div>
      </div>

      <div className={styles.sectionTitle}>Recent Invoices & Collections</div>
      <div className={styles.tableCard}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Invoice ID</th>
              <th>Client Name</th>
              <th>Matter Reference</th>
              <th>Amount</th>
              <th>Due Date</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {SAMPLE_INVOICES.map(inv => (
              <tr key={inv.id}>
                <td><strong>{inv.id}</strong></td>
                <td>{inv.client}</td>
                <td>{inv.matter}</td>
                <td>{inv.amount}</td>
                <td>{inv.dueDate}</td>
                <td>
                  <span className={`${styles.statusChip} ${inv.status === 'Paid' ? styles.statusPaid : inv.status === 'Pending' ? styles.statusPending : styles.statusOverdue}`}>
                    {inv.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
