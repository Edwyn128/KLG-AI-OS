# KLG AI Operating System

**KLG AI OS** is the firm-wide AI infrastructure for Kowal Law Group. It consists of two paired Phase 2 architectures—Alfred and Bloodhound—built on top of a shared Notion workspace.

## What's in This Repo

```
klg-ai-os/
├── alfred/        # Routing layer application (Layer 2 — Alfred's brain)
├── bloodhound/    # Surveillance engine
├── skills/        # KLG SKILL.md files — loaded per-query by the routing layer
└── docs/          # Architecture and integration documentation
```

## Alfred — Inward-Facing Executive Assistant

Alfred is the conversational surface the KLG team uses to access the firm's institutional memory, active matters, and workflow infrastructure. It routes queries to the right KLG skill, then dispatches to the appropriate model (Claude, ChatGPT, etc.).

**Three-layer architecture:**
- **Layer 1 — Interface:** Custom web app (deep work) + Slack bot (`#alfred-quick-query`) for quick queries
- **Layer 2 — Routing:** This repo. Classifies queries, selects skills from `skills/`, routes to models, orchestrates braiding
- **Layer 3 — Models:** Claude API (primary), ChatGPT API (braiding/review), others as needed

## Bloodhound — Outward-Facing Research Engine

Bloodhound tracks cases, doctrinal issues, attorneys, and thought leaders across the legal landscape. It feeds signal back to Alfred during case assessments and surfaces opportunities for content, amicus work, and networking.

## Skills

All KLG skills are `.md` files in `skills/`. The routing layer reads the correct skill file on each API call and injects it as the system prompt.

**Promotion path:** Develop skill in Claude.ai → copy text to `skills/<skill-name>.md` → commit → Alfred loads it automatically on next call.

## Environment Setup

Copy `.env.example` to `.env` and fill in your keys before running locally.

```bash
cp .env.example .env
```

Required variables: `NOTION_TOKEN`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`. See `.env.example` for the full list.

## Notion Integration

Both Alfred and Bloodhound connect to the KLG Notion workspace via the **KLG AI OS** internal integration token (`NOTION_TOKEN`). See `docs/notion-integration.md` for the full database access map and setup steps.

## Documentation

- `docs/architecture.md` — Full three-layer architecture spec
- `docs/notion-integration.md` — Database access map, integration setup, new database schemas
