import type { KLGUser } from '@/types'

export const KLG_USERS: KLGUser[] = [
  { name: 'Tim',      role: 'Managing Attorney', admin: true  },
  { name: 'Edwyn',    role: 'Systems Partner',   admin: true  },
  { name: 'William',  role: 'Research',          admin: false },
  { name: 'Brittney', role: 'Paralegal',         admin: false },
  { name: 'Ted',      role: 'Associate',         admin: false },
  { name: 'Richard',  role: 'Of Counsel',        admin: false },
]

export const ACTIVITY_ADMINS = new Set(['Tim', 'Edwyn'])

export function isAdmin(name: string): boolean {
  return KLG_USERS.find(u => u.name === name)?.admin ?? false
}

export function isActivityAdmin(name: string): boolean {
  return ACTIVITY_ADMINS.has(name)
}
