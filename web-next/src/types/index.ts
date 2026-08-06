// =============================================================================
// KLG AI OS — TypeScript types
// =============================================================================

export type Workspace = 'today' | 'matters' | 'chat' | 'deadlines' | 'bloodhound' | 'admin' | 'accounting' | 'skills'

export type Agent = 'alfred' | 'bloodhound'

export type SkillCategory = 'ALL' | 'INTAKE' | 'RESEARCH' | 'DRAFTING' | 'QA' | 'ARGUMENT' | 'OPS' | 'RECORD'

export type SkillMode = 'research' | 'drafting' | 'analysis' | 'ops'

// ── Skill ────────────────────────────────────────────────────────────────────

export interface SkillParam {
  key: string
  label: string
  placeholder: string
  required: boolean
}

export interface Skill {
  id: string
  name: string
  category: Exclude<SkillCategory, 'ALL'>
  icon: string
  mode: SkillMode
  time: string
  owner: string
  desc: string
  checklist: string[]
  prompt: string
  params?: SkillParam[]
  requiresFile?: boolean
  fileHint?: string
}

// ── Bloodhound Watch List ─────────────────────────────────────────────────────

export interface WatchCase {
  id: string
  case_name: string
  court: string
  tier: string
  issue_areas: string[]
  status: 'Watching' | 'Engaged' | 'Closed'
  procedural_posture: string
  next_deadline: string | null
  nexus_note: string
  docket_no: string
  url: string
}

// ── User ─────────────────────────────────────────────────────────────────────

export interface KLGUser {
  name: string
  role: string
  admin: boolean
  isClient?: boolean
  allowedMatters?: string[]
}

// ── Matter ───────────────────────────────────────────────────────────────────

export interface Matter {
  id: string
  name: string
  status?: string
  project_status?: string
  priority?: string
  case_stage?: string
  assignee?: string
  target_date?: string
  next_court_deadline?: string
  category?: string
  last_edited_time?: string
  url?: string
  summary?: string
  days_until?: number
  // Extended fields (returned by GET /alfred/matters/{id})
  slack_channel?: string
  clio_url?: string
  completion?: number
}

// ── Task ─────────────────────────────────────────────────────────────────────

export interface Task {
  id: string
  name: string
  stage: string
  status: 'To Do' | 'In Progress' | 'Done'
  assignee?: string
  deadline?: string | null
  eta?: string | null
  start_date?: string | null
  completed_at?: string | null
  duration?: number | null
  priority?: string
  matter_id?: string
  matter_name?: string
  is_block?: boolean
}

// ── File attachments ──────────────────────────────────────────────────────────

export interface FileAttachment {
  filename: string
  content_b64: string
  mime_type: string
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export type MessageRole = 'user' | 'alfred' | 'bloodhound'

export interface ChatMessage {
  id: string
  role: MessageRole
  text: string
  name: string
  toolsUsed?: string[]
  fileAttachments?: FileAttachment[]
  isStreaming?: boolean
}

export interface FileToken {
  token: string
  filename: string
}

// ── API Responses ─────────────────────────────────────────────────────────────

export interface ChatResponse {
  response: string
  user: string
  tools_used: string[]
  history: unknown[]
}

export interface UploadResponse {
  file_token: string
  filename: string
  size_bytes: number
}

export interface MatterListResponse {
  matters: Matter[]
  count: number
}

export interface DeadlineItem {
  id: string
  name: string
  next_court_deadline?: string
  target_date?: string
  priority?: string
  days_until?: number
}

export interface ActivityEntry {
  id?: string
  agent?: string
  user?: string
  name?: string
  message?: string
  response?: string
  tools?: string[]
  model?: string
  created_time?: string
}

// ── Case Detail ───────────────────────────────────────────────────────────────

export interface CaseDetail {
  id: string
  name: string
  status?: string
  priority?: string
  case_stage?: string
  assignee?: string
  target_date?: string
  next_court_deadline?: string
  category?: string
  url?: string
  summary?: string
  notes?: string
  slack_files?: SlackFile[]
  slack_messages?: SlackMessage[]
}

export interface SlackFile {
  id: string
  name?: string
  title?: string
  mimetype?: string
  url_private?: string
  thumb_800?: string
}

export interface SlackMessage {
  ts: string
  user?: string
  text?: string
  files?: SlackFile[]
}

// ── SSE Events ────────────────────────────────────────────────────────────────

export interface SSEDelta   { delta: string }
export interface SSEDone    { done: true; tools_used: string[]; history: unknown[]; file_attachments?: FileAttachment[] }
export interface SSEError   { error: string }
export type SSEEvent = SSEDelta | SSEDone | SSEError
