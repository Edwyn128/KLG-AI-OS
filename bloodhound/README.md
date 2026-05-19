# Bloodhound — Surveillance Engine

This directory contains the Bloodhound surveillance engine: the outward-facing system that monitors the legal landscape and brings signal back to KLG.

## What It Does

Bloodhound actively tracks cases, doctrinal issues, attorneys, and thought leaders across the legal landscape. It populates and maintains two Notion databases: the **Watch List** and **Issues & Causes**.

**Use cases:**
- Podcast guest and episode topic pipeline (CALP)
- Doctrinal threads for articles and scholarship
- Amicus brief opportunity surfacing
- Issue-and-contact relations for networking and events
- Active-matter feedback loop: flags Watch List items that match issues in current case assessments

## Data Flow

```
Intake sources (via Comms Log)
  - Legal newsletters
  - CourtListener alerts
  - Movement-org press releases (PLF, IJ, NCLA, FIRE, Cato)
        │
        ▼
  Comms Log (Notion)
        │
        ▼
  Bloodhound triage
        │
   ┌────┴────┐
   │         │
   ▼         ▼
Watch List   Issues & Causes
(Notion)     (Notion)
        │
        ▼
  Alfred reads Watch List
  during case assessments
```

## Notion Databases

Bloodhound owns two Notion databases:

- **Watch List** — one row per case being tracked (schema in `docs/notion-integration.md`)
- **Issues & Causes** — one row per doctrinal issue area KLG cares about (evergreen)

It also reads/writes the existing **Contacts** database for speaker and co-counsel relations.

## Environment

Requires `NOTION_TOKEN`. See `.env.example` at the repo root.
