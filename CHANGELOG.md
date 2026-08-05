# KLG AI OS — Changelog

Three agents collaborate on this project. Each entry is tagged by who did the work:

- **[Backend]** — Claude Code (VS Code) — API, Python, Notion bridge, scheduler, auth, security
- **[Frontend]** — Antigravity — UI design, components, CSS, mobile layout, design system
- **[Manager]** — Claude Desktop — architecture decisions, cross-agent coordination, specs

Entries without a tag are mixed-agent or pre-multi-agent-setup commits.

---

## 2026-08-04

- **[Frontend]** `db6a80f` — Mobile layout, dynamic multi-view dashboard, and backend agent spec

## 2026-08-03

- **[Backend]** `3fee643` — **Hotfix (P0):** `get_all_active_matters()` was reading `"Status"` — the real Notion property is `"Matter Status"`. Silently returned zero matters to every caller (Matters tab, Deadlines tab, Alfred chat, all scheduled agents). Fixed property key + threaded `archived` param through to DB layer so `?archived=true` now works.
- **[Backend]** `4c53b0b` — Slack agents (hygiene scan, weekly agenda, case check-in) now filter to Active/On Hold matters only. Added `SLACK_HYGIENE_ENABLED` and `SLACK_CHECKIN_ENABLED` Railway flags to disable agents without deploys.
- **[Backend]** `f25d493` — Deadlines tab active filter: switched from denylist to allowlist (only explicit Active/On Hold statuses pass). Empty status no longer silently joins the Active group.
- **[Backend]** `2ff4a48` — Security audit: fixed 8 of 11 findings (security headers middleware, SSO Bearer JWT auth, SSE error masking, debug schema endpoint gating, 403 for client sessions on briefing, generic 500s on upload/deadlines, `NotionBridge()` init fix in admin routes).

## 2026-07-31

- **[Backend]** `7174d32` — Removed Stu from README admin list
- **[Backend]** `7fd247b` — Fixed Opus 4.8 / newer Claude models crashing with `thinking.type=enabled`
- **[Backend]** `90421a0` — Fixed orphaned `tool_result` crash in Alfred conversation history
- **[Frontend]** `16e14c5` — Deadlines: robust status normalization for Active/On Hold grouping
- **[Frontend]** `864fbde` — Deadlines: show all On Hold matters regardless of whether they have a deadline date
- **[Frontend]** `cf06faa` — Deadlines: grouped view with Active/On Hold sections and per-group row numbers
- **[Frontend]** `bb06a46` — Deadlines tab default filter now matches Notion's "Matter Deadlines" view
- **[Backend]** `56e3a29` — Removed Stu login; gated Admin tab on master password (Tim/Edwyn only)

## 2026-07-30

- **[Backend]** `c6f5639` — Renamed `"Target Date"` → `"Deadline"` throughout codebase to match actual Notion schema
- **[Backend]** `2873f64` — Added `/alfred/debug/schema` endpoint to inspect live Projects DB property names
- **[Backend]** `eaeae44` — Removed Notion server-side sorts on `Target Date` / `Next Court Deadline` (properties didn't exist, causing silent 400s)
- **[Backend]** `bcd1b47` — Completed skills layer (32 skills total)
- **[Frontend]** `e1556ee` — Matter edit failures now surface to user; assignee edits deferred to Notion with tooltip
- **[Backend]** `980791a` — Skill imports isolated in `try/except` so one broken skill cannot crash the entire skill registry
- **[Backend]** `a400f21` — All user-visible date computations now use Pacific time (`ZoneInfo("America/Los_Angeles")`) instead of UTC `date.today()`

## 2026-07-29

- **[Frontend]** `9ec44a1` — Matters tab: auto-fetches tasks and scrolls to the matter when navigating from Deadlines
- **[Frontend]** `223b1f5` — Deadlines: matter name navigates to Matters tab; Notion link surfaces as hover icon
- **[Backend]** `9d59417` — Matter status filter reads `"Matter Status"` (first occurrence of this bug, before the 08-03 hotfix consolidated it)
- **[Backend]** `984b82b` — Removed debug endpoint that referenced undefined `require_auth` (was crashing boot)
- **[Frontend]** `90a74c6` — Deadlines tab shows matter properties instead of raw task hierarchy

## 2026-07-27

- **[Backend]** `6670d22` — Deadlines + Today tabs: read tasks from Projects pages, not template DBs
- **[Backend]** `d418b2b` — Fixed six bugs in `tasks.py` that silently emptied Deadlines + Today tabs
- **[Frontend]** `67db478` — Today, Deadlines, Admin tabs added; dark mode; active-only matters filter

## 2026-07-24

- **[Frontend]** `bd7d18e` — Bloodhound workspace tab: watch list UI + backend read endpoint
- **[Frontend]** `a336e66` — Compact/full layout toggle; two-option login screen; SSO token hydration
- **[Backend]** `1ac5b2a` — Alfred Slack connect mode; Microsoft SSO; JWT auth backend

## 2026-07-23

- **[Backend]** `dfbffc9` — Skills simulation harness (`simulate_skills.py`)
- **[Backend]** `97474c0` — Skills Phase 4: 10 new KLG skills (32 total)

## 2026-07-22

- **[Backend]** `0868389` — Client-facing Alfred: scoped mode, tool guards, per-matter isolation

## 2026-07-21

- **[Backend]** `6b2690c` — Security hardening round 2
- **[Backend]** `e2b1ead` — Security hardening: path traversal, error leaks, auth, performance

## 2026-07-20

- **[Backend]** `e2be26f` — Auth fix: case-insensitive username lookup + Railway escape sequence handling
- **[Backend]** `200a897` — Matter task seeding; Slack connect mode; Skills Phase 3 rewrites

## 2026-07-16

- **[Backend]** `b4483fe` — Skills Phase 3: daily triage, prebill audit, research compilation, brief assembly
- **[Backend]** `581f1e8` — Slack parity: @mention resolution, channel context, file reading
- **[Backend]** `6ce24e1` — Skills Phase 2 complete; fixed prompt-too-long error
- **[Backend]** `1ff45f3` — Skills Phase 2: scoped tool access for research skills

## 2026-07-15

- **[Backend]** `e3b923e` — Skills: matter substitution, param forms, prompt rewrites
- **[Frontend]** `977b588` — All matter fields editable inline from the dashboard

## 2026-07-14

- **[Backend]** `824c685` / `cde4234` — README: full Alfred tool reference, architecture, env vars, setup
- **[Frontend]** `dcfd28e` — Per-matter task dashboard; backend task CRUD

## 2026-07-13

- **[Frontend]** `495588d` — Skills launcher: compact + expanded two-mode design
- **[Backend]** `54d6c48` — Billing-error detection; Slack error messages
- **[Frontend]** `dd574fa` — Dashboard field mapping; chat streaming; skills auto-send; Perplexity routing

## 2026-07-10

- **[Backend]** `f6e5d42` — Fixed blank screen: deadlines API returns wrapped object, not array
- **[Backend]** `ef9def7` — Removed Status filter from matter queries (property not yet in DB at that point)
- **[Frontend]** `bb98595` — Web UI redesign: Dashboard landing page, real Chat, Skills popup
- **[Backend]** `9bf6b11` — Rate-limit fallback: detect `ModelHTTPError`, add Haiku as first fallback
- **[Backend]** `d1bb477` — Switched to `pydantic-ai-slim` with minimal extras

---

## How to update this file

Add a new date section at the top for each session's work. Use the tag that matches the agent:
- `[Backend]` for API, Python, Notion bridge, scheduler, auth, security changes
- `[Frontend]` for UI, components, CSS, layout, design changes
- `[Manager]` for architecture decisions, cross-agent coordination, specs written

Format: `- **[Tag]** \`commit-hash\` — short description`
