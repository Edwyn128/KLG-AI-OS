# KLG AI OS — Frontend Redesign Brief (Handoff Prompt)

> **Audience:** the design agent responsible for the new reactive UI (web + mobile).
> **Purpose:** this document is your complete picture of the EXISTING front end — its
> visual design system, every screen and interaction, and the backend contracts the
> new design must wire into. Read it fully before producing the new design.
>
> **Your mandate:** redesign the KLG AI OS web tool as a reactive, dynamic interface
> that works as both a web app and a future mobile (client-facing) app. The chosen
> stack is React + Vite + TypeScript, with React Native + Expo as the mobile target.
> You own the new visual/interaction design. You do NOT own the backend — every API
> contract in section 5 is fixed and must be respected exactly.
>
> Companion document: `docs/plans/alfred-reactive-ui-plan.md` (the engineering
> implementation plan — phases, file structure, technical risk mitigations).

---

## 1. What this product is

KLG AI OS is the internal AI hub of Kowal Law Group, a California appellate firm.
The web tool ("Skills OS") is the front door to two AI agents:

- **Alfred** — executive assistant. Reads/writes the firm's Notion workspace
  (matters, deadlines, comms log), answers questions, runs operational agents.
  Multi-model: the user picks Claude / GPT-4o / Gemini / Perplexity per conversation.
- **Bloodhound** — external surveillance engine. Tracks cases, doctrines, and
  organizations in the legal landscape; maintains a tiered Watch List in Notion;
  runs feed scans (RSS + CourtListener).

Backend: Python FastAPI, deployed on Railway, single service that also serves the
front end. Notion is the source of truth for all data; Slack supplies case-channel
activity. There is no frontend database — everything is fetched live.

Current front end: ONE file, `web/index.html` (~2,170 lines HTML + vanilla JS) plus
`web/static/style.css` (~1,790 lines). No framework, no build step. DOM updates via
`innerHTML` string templates and manual class toggling. This is what you are replacing.

---

## 2. Current visual design system

Keep the brand feel unless you have a strong reason to change it; evolve, don't discard.

### Palette (CSS custom properties, dark theme only)

| Token | Value | Use |
|---|---|---|
| `--bg-base` | `#080c14` | App background (deep navy-black) |
| `--bg-panel` | `#0d1220` | Sidebars, panels |
| `--bg-card` | `#111827` | Cards, message bubbles |
| `--bg-input` | `#1a2236` | Inputs, badges |
| `--bg-hover` | `#1e2a40` | Hover states |
| `--border` | `rgba(255,255,255,0.07)` | Hairline borders everywhere |
| `--text-primary` | `#f0f4ff` | Headings, body |
| `--text-secondary` | `#a8b5ce` | Secondary copy |
| `--text-muted` / `--text-dim` | `#5a6a85` / `#3d4f68` | Labels, hints |
| `--accent` | `#5b8af0` | **KLG Sapphire** — Alfred, primary actions, active states |
| `--bh-accent` | `#f0a040` | **Amber** — everything Bloodhound |
| `--urgent` / `--warning` / `--ok` | `#f05252` / `#f0b040` / `#40c080` | Deadline urgency, status |

### Typography & geometry
- **Inter** (300–800) for UI; **JetBrains Mono** for dates, code, prompts.
- Small, dense type: 9–13px range, generous letter-spacing on uppercase labels.
- Radii: 4 / 8 / 12 / 16px; pill (999px) for badges.
- Glassmorphism touches: `backdrop-filter: blur()` on header, toolbars, modals.
- Micro-animations: message slide-in (220ms), typing dots, shimmer skeletons,
  pulsing status dot, flashing OVERDUE badge, hover lifts (`translateY(-2px)`).
- Easing: `cubic-bezier(0.4,0,0.2,1)`; modal pop uses a spring-ish overshoot curve.

### Responsive behavior today
- **≤1100px (tablet):** right panel dropped, header meta hidden, sidebar narrows.
- **≤768px (mobile):** sidebars become fixed slide-in drawers (translateX, overlay
  scrim below the 52px header), workspace tabs switch to short labels, case-file
  columns stack, hamburger toggles appear.
- **≤480px:** single-column user grid, tighter header.

Your new design must treat mobile as a first-class layout, not a degradation —
it becomes the basis of the client-facing mobile app.

---

## 3. Screens and how everything works today

A 52px fixed header is always visible: status dot (backend health, polled via
`GET /health`), brand block, workspace tabs, live clock, user chip, badge.
Below it, exactly one of four workspaces is shown (tab switching toggles
`display` — no routing, no URLs; the new design should introduce real routes).

### 3.1 Login / user picker (modal, blocks everything)
- Grid of 7 named team members (Tim, Edwyn, William, Brittney, Ted, Stu, Richard)
  with initial-avatar, name, role.
- Pick a name → password field appears → password verified against
  `GET /auth/check` with a Basic header. On success, name + password are stored
  in `localStorage` (`klg_user`, `klg_password`) and the modal closes.
- Identity persists per browser. Only admin users (Tim, Edwyn, Stu — flagged in a
  client-side array) can reopen the picker from the header chip to switch users;
  switching always forces re-entry of the password.
- Any API 401 clears the stored password and re-shows the modal.
- **Design note:** this auth model is a known security weakness and is scheduled
  for replacement in the client-facing phase. Design the login surface so the
  identity/credential step is swappable (e.g., a self-contained auth screen/flow),
  but do NOT invent a new auth protocol — the new front end speaks the same
  Basic-auth contract for now (section 5.1).

### 3.2 Chat Workspace (default, 3-column desktop grid: 280px | 1fr | 300px)

**Left sidebar — Matters list**
- Category filter pills: Cases / Support / Ops / Think Tank / All
  (maps to `GET /alfred/matters?category=…`).
- Matter cards: name, priority badge (High/Medium/Low color-coded), status text,
  stage tag, deadline countdown badge (OVERDUE / TODAY / Nd, urgency-colored).
- Clicking a matter card does NOT navigate — it injects a canned prompt into chat:
  "Alfred, what is the current status and what is pending on {name}?" and sends it.
- Refresh button; auto-refresh every 5 minutes; shimmer skeletons while loading.
- On mobile: slide-in drawer via hamburger in the chat toolbar.

**Center — Chat panel**
- Toolbar: Alfred/Bloodhound segmented toggle (switching agents clears the visible
  conversation context and swaps theme accent sapphire↔amber, placeholder text,
  and hint line), and a model dropdown (9 options; changing model resets history).
- Two separate message containers (one per agent), each seeded with a welcome
  message listing example prompts.
- Messages: avatar (initial letter), bubble with asymmetric radii (user right-aligned
  green-tinted, agent left-aligned card-colored), basic markdown (bold, code blocks,
  line breaks), and "via {tool name}" badges under agent replies showing which
  backend tools were called.
- **Streaming:** Alfred responses stream token-by-token (see 5.2). The UI shows a
  3-dot typing indicator during tool execution, then a live-updating bubble as
  text arrives, then a final formatting pass + tool badges when done. Bloodhound
  uses plain request/response (no stream).
- Input: auto-growing textarea (max 120px), Enter sends / Shift+Enter newline,
  send button disabled while a response is in flight, status hint line underneath
  ("Alfred is thinking…" / "Bloodhound is scanning…").

**Right panel — Deadlines + actions (desktop only today)**
- "Upcoming Deadlines (7 days)" list from `GET /alfred/deadlines?days=7`: matter
  name, mono date, countdown pill (OVERDUE flashes). Clicking one asks Alfred
  what's pending before the deadline.
- "Run Agents" buttons: Bloodhound Feed Scan (`POST /bloodhound/scan` — switches
  to Bloodhound chat, posts progress + a formatted scan-summary message),
  Deadline Watch (`POST /alfred/agents/deadline-watch`), Weekly Agenda and
  Bloodhound Status (canned chat prompts).
- "Quick Ask" canned-prompt buttons + link to `/docs` (FastAPI Swagger).
- **This panel disappears below 1100px with no mobile equivalent — a known gap
  your redesign should fix** (deadlines are the highest-value data in the app).

### 3.3 Skills Navigator
- A static, frontend-only registry (`KLG_SKILLS`, 12 entries) of firm workflows:
  id, name, category (INTAKE/RESEARCH/DRAFTING/QA/ARGUMENT/OPS), icon, mode
  (research/drafting/analysis/ops), time estimate, owner, description, a workflow
  checklist (5–6 steps), and a launch prompt.
- Layout: filter pill bar + responsive card grid (auto-fill 220px min) + a 360px
  detail panel showing the selected skill's full checklist and launch prompt.
- "Launch Skill in Alfred" → switches to Chat, selects Alfred, sends the skill's
  launch prompt. This cross-workspace launch action is core UX — preserve it.
- No backend call anywhere in this workspace. The data lives in the bundle.

### 3.4 Case Files
- Left: case list (same `GET /alfred/matters?category=Case+Project` data) with
  stage tags and deadline badges. Loaded on first visit; selection state resets
  every time you enter the tab.
- Selecting a case calls `GET /cases/{page_id}` and renders:
  - **Case header:** name, stage/status/priority badges, assignee, court deadline
    (urgent-styled, with "in N days / N days overdue" label), target date,
    "Open in Notion ↗" link.
  - **Left column:** properties grid (status, priority, stage, assignee, category,
    last edited), summary text, page notes (plain-text Notion body).
  - **Right column:** shared documents/images grid (Slack files via an
    authenticated proxy URL, lightbox on click, lazy loading, broken images
    self-hide) and a Slack message feed (author, #channel badge, timestamp,
    Slack-flavored markup: @mentions, links, bold; reply counts). Three distinct
    empty states: Slack not configured / no channel found (with instructions to
    invite the bot) / no messages.
  - **Footer:** "Ask Alfred About This Matter" → canned briefing prompt in chat.

### 3.5 Activity Log (admin-only: Tim and Stu)
- Tab is hidden for everyone else (client-side check — backend also enforces it).
- Feed from `GET /alfred/activity?days=N` (7/14/30/60 selector): each entry has an
  agent avatar (Alfred sapphire / Bloodhound red / huddle green 🎙), title
  ("{user} → {agent}" or huddle name), relative timestamp, 2-line clamped message
  preview, tool badges, model badge. Filters: All / Chats / Huddles / Other.

### 3.6 Global patterns worth preserving
- **askAlfred(prompt)** — the universal action: from any workspace, jump to chat,
  select Alfred, send a prepared prompt. Matters, deadlines, skills, and case
  files all funnel into it.
- Shimmer skeletons for every async load; distinct error states inline (never
  blocking dialogs); offline status dot when the backend is unreachable.
- Escape closes the lightbox; drawer scrim closes drawers.

---

## 4. Known UX gaps the redesign should solve (beyond "make it reactive")

1. No routing/deep links — can't link to a case, a skill, or a conversation.
2. Conversation history is lost on reload (lives only in a JS variable).
3. Right panel (deadlines!) has no mobile presence.
4. Agent switch and model switch silently destroy conversation context.
5. Streaming renders raw text then "jumps" to formatted markdown at the end.
6. No optimistic/disabled states on several buttons; double-submit is possible
   on agent triggers.
7. Accessibility: no focus management in modals/drawers, no `role="log"` on chat,
   no reduced-motion support, contrast of dim text likely fails WCAG AA.
8. Skills registry is hardcoded in the page — design for it as data (a typed
   module now, an endpoint later).

---

## 5. Backend contracts — FIXED, do not redesign these

All requests are same-origin to the FastAPI service. OpenAPI docs at `/docs`.

### 5.1 Auth (every endpoint except `/`, `/health`, `/static/*`, `/slack/events`)
- HTTP Basic on every request: `Authorization: Basic base64(username:password)`.
  The username is the picked team-member name; the backend validates against a
  master password or a per-user password map (env-configured). POSTs are
  rate-limited per IP.
- `GET /auth/check` → `{"authenticated": true}` (200) or 401. Used to validate
  credentials at login.
- 401 on any call means credentials are invalid/expired → clear stored password,
  return to login.
- Constraint for the new code: credential storage and header construction must
  live in exactly one auth module + one API client (so the future client-facing
  auth replacement is a two-file swap).

### 5.2 Chat
- `POST /alfred/chat` — body `{message: string (≤4000), user: string, model: string,
  history: any[]}`. Response `{response, user, tools_used: string[], history: any[]}`.
  Used today for Bloodhound conversations (`model` may be empty for default).
- `POST /alfred/chat/stream` — same body; responds with SSE (`text/event-stream`)
  over a **POST fetch + ReadableStream** (EventSource won't work: no POST, no
  Authorization header). Lines:
  - `: ping` comment first (anti-buffering; ignore non-`data:` lines)
  - `data: {"delta": "text chunk"}` — incremental tokens
  - `data: {"done": true, "tools_used": [...], "history": [...]}` — final event
  - `data: {"error": "..."}` — failure
  Quirk: Railway's proxy may terminate the stream ungracefully AFTER completion —
  a network error after streaming has started must NOT surface as a user-facing
  error.
- **`history` is an opaque contract.** It is a serialized pydantic-ai message
  array. Store it, send it back verbatim on the next turn, never parse or
  transform it. Reset to `[]` to start fresh (new conversation, agent switch,
  model switch). Treat it as `unknown[]` in TypeScript.
- Supported `model` values: `claude-sonnet-4-6`, `extended-thinking`,
  `claude-opus-4-8`, `gpt-4o`, `gpt-4o-mini`, `gemini-2.0-flash`,
  `gemini-1.5-pro`, `sonar-pro`, `sonar-reasoning-pro`, `""` (default).

### 5.3 Data endpoints
- `GET /alfred/matters?category={Case Project|Case Support|Operations|Think Tank|all}`
  → `{count, matters: [...]}`. Matter objects are flattened Notion properties with
  these keys used by the UI: `id`, `Project name`, `Status`, `Priority`
  (High/Medium/Low), `Case Stage`, `Category`, `Target Date` and/or
  `date:Target Date:start` (ISO date — check both keys), `Assignee` (string[]),
  `Summary`, `Next Court Deadline`, `Next Deadline Info`, `url` (Notion link),
  `last_edited_time`.
- `GET /alfred/deadlines?days=7` → same matter shape, filtered to upcoming targets.
- `GET /alfred/activity?days=N` → `{entries: [...]}`; entry fields: `type`
  (chat|huddle|other), `agent`, `user`, `name`, `message`, `response_summary`,
  `meeting_date`, `created_time` (ISO), `tools` (string[]), `model`.
  **403 for non-admin users — backend allowlist is Tim and Stu.** UI gating is
  cosmetic; the backend is the enforcement point.
- `GET /cases/{page_id}` → `{matter: {…}, page_content: string, slack: {channel:
  {id,name,found} | {found:false,name:null} | null, messages: [{user, text, ts
  (unix-seconds string), channel, reply_count}], files: [{id, name, type,
  is_image, user, proxy_url}], error: string|null}}`. Render Slack text with
  Slack markup conventions (`<@U…|name>` mentions, `<url|label>` links, `*bold*`).
  Images load through `proxy_url` (`GET /slack/file/{file_id}` — authenticated
  server-side proxy; never expects a Slack token in the browser).
- `POST /bloodhound/scan` → `{total_fetched, new_signals, added_count,
  skipped_count, added_cases: [{case_name, court, tier ('1'|'2'|'3'), nexus,
  notion_url}]}`. Long-running (up to ~1 min). Tier icons today: 🔴 1, 🟡 2, ⚪ 3.
- `POST /alfred/agents/deadline-watch` → `{status: "success", message}` (also
  exist: `/alfred/agents/weekly-agenda`, `/alfred/agents/hygiene-scan`,
  `/alfred/agents/case-checkin`, `/alfred/agents/huddle-import` — same trigger
  pattern, available for new UI affordances).
- `GET /health` → `{status:"ok", …}` — unauthenticated; drives the status dot.

### 5.4 Security constraints (from the June 2026 audit — binding on the new UI)
- All server-sourced strings (Notion, Slack, chat) are untrusted: render through
  React's default escaping; `dangerouslySetInnerHTML` only in one sanitized
  markdown utility (DOMPurify).
- The production deploy will set a CSP (`script-src 'self'`): no inline scripts,
  no inline event handlers — which a Vite build satisfies by default.
- Do not display or log credentials; do not spread auth-header construction
  beyond the API client.
- Client-mode/confidentiality: the future mobile app is client-facing; design
  information hierarchy so privileged internal data (other matters, activity log,
  team chatter) is structurally separated from what a client persona could see.

---

## 6. What you deliver

1. **Design system:** tokens (color, type, spacing, radius, motion) as a themable
   layer — must work in React (web) and React Native (mobile); keep the KLG
   sapphire/amber dual-agent identity and dark-first aesthetic.
2. **Screen designs (web + mobile)** for: login/identity, Chat (with streaming,
   agent/model switching, matters, deadlines — including a mobile-native answer
   for the deadlines panel), Skills Navigator, Case Files, Activity Log.
3. **Interaction specs:** streaming message lifecycle (typing → live tokens →
   finalized markdown + tool badges), cross-workspace askAlfred flow, drawer/
   navigation model with real routes, loading/empty/error states for every fetch,
   reduced-motion variants.
4. **Component inventory** mapped to the implementation plan's structure, flagging
   which components are shared with the future React Native app.

Constraints recap: backend contracts in section 5 are immutable; auth UI must be
swappable; accessibility to WCAG AA; the firm writing style applies to all UI
copy (no throat-clearing, active verbs, no spaces around em dashes).
