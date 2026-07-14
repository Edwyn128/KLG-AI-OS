# KLG AI Operating System

Alfred — the firm's multi-model AI assistant — plus Bloodhound, background agents, and a full web interface for Kowal Law Group's California appellate practice.

**Production:** `https://klg-ai-os-production.up.railway.app`  
**Deploy:** `git push origin main` → Railway auto-redeploys (~2 min)  
**Access:** Password-protected. Master password in Railway env var `APP_PASSWORD`.

---

## What this is

A four-layer operating system for a boutique appellate firm:

| Layer | Description |
|---|---|
| 0 | Source-of-truth data — Notion, SharePoint, court dockets (read-only) |
| 1 | Notion project pages — the AI-readable visibility scaffold |
| 2 | Claude skills — 5-step lifecycle: Locate → Read → Work → Update L1 → Queue next |
| 3 | Background agents — deadline watch, agenda digest, hygiene (read L1, post to Slack) |

**Alfred** is the inward-facing executive assistant: chat interface, Notion read/write, skill routing, file analysis, multi-model switching.  
**Bloodhound** is the outward-facing surveillance engine: RSS + CourtListener feeds, Claude triage, Watch List maintenance.

---

## Architecture

```
web-next/          React + Vite + TypeScript frontend
├── src/
│   ├── components/
│   │   ├── dashboard/   Matter list + per-matter task panel
│   │   ├── chat/        Alfred chat with SSE streaming
│   │   ├── skills/      Skills launcher popup
│   │   └── layout/      App shell, nav, auth modal
│   ├── store/           Zustand stores (chat, matter, UI state)
│   ├── api/             API client functions
│   └── types/           Shared TypeScript types

api/               FastAPI backend (Python)
├── routes/
│   ├── alfred.py        Matter CRUD, task CRUD, chat endpoints
│   ├── bloodhound.py    Scan trigger, watch list
│   └── slack.py         Slack Events API handler
└── main.py              App entry, auth middleware, scheduler

alfred/            Alfred agent
├── agent.py             PydanticAI agent, @tool definitions
└── model_factory.py     Multi-model routing (Claude, GPT-4o, Gemini)

bloodhound/        Bloodhound agent
└── agent.py             RSS triage, CourtListener queries

notion_bridge/     Notion API wrapper
├── client.py            NotionBridge — page reads, block ops
└── tasks.py             TaskPages — per-matter task auto-detection + CRUD

agents/            Background scheduler
└── scheduler.py         APScheduler jobs (Bloodhound 7AM, Deadline 8AM, etc.)

skills/            Skill prompt library
└── *.md                 Individual skill definition files
```

---

## Local development

**Requirements:** Python 3.11+, Node 20+

```bash
# Backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # fill in keys (see Environment Variables below)
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd web-next
npm install
npm run dev                  # proxies /api → localhost:8000
```

Open `http://localhost:5173`.

---

## Deployment

Railway handles everything. No manual steps after a push.

```bash
git add <files>
git commit -m "your message"
git push origin main
# Railway builds and redeploys automatically
```

One uvicorn worker only — `--workers 2` caused 502s on Railway. The APScheduler background jobs run in the same process.

---

## Environment variables

Set these in Railway → KLG AI OS → Variables.

### Required

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key — get from console.anthropic.com |
| `NOTION_TOKEN` | Notion integration token (starts `ntn_A42282...`) |
| `NOTION_PROJECTS_DB_ID` | Notion Projects database ID |
| `NOTION_WATCH_LIST_DB_ID` | Notion Watch List database ID |
| `NOTION_ISSUES_DB_ID` | Notion Issues database ID |
| `NOTION_COMMS_LOG_DB_ID` | Notion Comms Log database ID |
| `APP_PASSWORD` | Master password for all users |

### Optional — unlock features

| Variable | Feature unlocked |
|---|---|
| `TAVILY_API_KEY` | Alfred internet search (get free key at tavily.com) |
| `OPENAI_API_KEY` | GPT-4o and GPT-4o mini in model switcher |
| `GOOGLE_API_KEY` | Gemini 2.0 Flash in model switcher |
| `PERPLEXITY_API_KEY` | Perplexity sonar models in model switcher |
| `SLACK_BOT_TOKEN` | Slack bot responses |
| `SLACK_SIGNING_SECRET` | Slack webhook verification |
| `APP_PASSWORDS` | Per-user passwords (JSON map: `{"tim":"...", "brittney":"..."}`) |
| `NOTION_ALFRED_NOTES_DB_ID` | Alfred persistent memory between sessions |
| `NOTION_SYSTEM_STATE_DB_ID` | Alfred internal state tracking |

---

## Notion databases

All four core databases must be shared with the Notion integration (Notion UI → ... → Connections → connect the integration).

| Database | Env var |
|---|---|
| Projects | `NOTION_PROJECTS_DB_ID` |
| Watch List | `NOTION_WATCH_LIST_DB_ID` |
| Issues | `NOTION_ISSUES_DB_ID` |
| Comms Log | `NOTION_COMMS_LOG_DB_ID` |

---

## Slack setup

1. Add `SLACK_BOT_TOKEN` and `SLACK_SIGNING_SECRET` to Railway.
2. In Slack app settings → Event Subscriptions, set Request URL: `https://klg-ai-os-production.up.railway.app/slack/events`
3. Subscribe to: `app_mention`, `message.channels`, `message.groups`
4. Invite `@Alfred` to relevant channels: `#case-management`, `#alfred`, per-case channels (`#riva-fourjays`, etc.)

---

## Authentication

- All API endpoints require HTTP Basic auth except `/`, `/health`, `/static/`, `/slack/events`
- Frontend uses a custom password modal — no browser native dialog
- `APP_PASSWORD` is a master override (works for any username)
- `APP_PASSWORDS` is a per-user JSON map: `{"tim": "password1", "brittney": "password2"}`
- Admin users (Tim, Edwyn, Stu) can switch identity via a clickable chip in the header
- If `APP_PASSWORDS` contains escaped quotes or newlines (Railway raw editor bug), delete the variable entirely and re-enter as a single clean JSON line

---

## Background jobs

Defined in `agents/scheduler.py`. All times Pacific.

| Job | Schedule |
|---|---|
| Bloodhound scan | Daily 7:00 AM |
| Deadline watch | Daily 8:00 AM |
| Weekly agenda digest | Monday 7:30 AM |
| Hygiene sweep | Monday 8:15 AM |

---

## Known issues and open items

| Issue | Status |
|---|---|
| `/alfred/chat` endpoints have no auth guard | Fix needed before firm-wide rollout |
| Perplexity `sonar-pro` routes to Anthropic (dead code bug) | Fix in `alfred/agent.py` |
| SharePoint access | Awaiting Ozzy's Azure admin consent |
| Alfred Notes + System State Notion databases | Not yet created |
| `TAVILY_API_KEY` not set | Alfred internet search non-functional |

---

## Team

| Person | Role | App access |
|---|---|---|
| Tim | Managing attorney | Admin |
| Edwyn | Systems partner, build lead | Admin |
| Stu | Operations | Admin |
| Brittney | Paralegal, primary daily user | Standard |
| Ted / William / Richard | Staff | Standard (identity-locked) |
| Ozzy | External IT (Azure/SharePoint) | n/a |

---

## Technical notes

- Notion API pinned to version `2022-06-28` — do not change (2025 version removed `/databases/{id}/query`)
- Single uvicorn worker only — multiple workers break APScheduler
- `WWW-Authenticate` header deliberately omitted from 401 responses (prevents browser native dialog)
- Task storage auto-detection: `TaskPages` reads each matter's page blocks and routes to inline DB query or to-do block parsing depending on what it finds
- Project categories: Case Project, Case Support, Operations, Think Tank — all endpoints default to Case Project; pass `?category=all` for all matters
