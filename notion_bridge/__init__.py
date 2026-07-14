"""
notion_bridge — The KLG AI OS connection layer to Notion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS PACKAGE IS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This package is the ONLY place in the codebase that talks directly to the
Notion API. Every other module (Alfred, Bloodhound, the background agents,
the API routes) calls functions in this package instead of touching the
Notion SDK directly.

WHY THIS SEPARATION MATTERS:
  - If Notion changes their API (it has happened), we fix it in one package,
    not scattered across twenty files.
  - All retry logic, error handling, and rate-limit back-off lives here.
    Callers don't need to think about 429s.
  - We can swap Notion for a different database (or add a local cache) by
    changing this package without touching anything else.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE FOUR-LAYER MODEL (as it relates to this package)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Layer 0 — Source-of-truth data (Case Portal, SharePoint, court docket).
             READ-ONLY for this package. Never write back to Layer 0.

  Layer 1 — Notion project pages (this package owns Layer 1 I/O).
             Skills READ Layer 1 context, then WRITE updates after doing work.
             Background agents READ Layer 1 but NEVER write to it.

  Layer 2 — Skills (Alfred). Calls this package to read/write Layer 1.

  Layer 3 — Background agents. Calls this package read-only, then post to Slack.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODULES IN THIS PACKAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  client.py          — Async Notion API client with retry logic.
                       Everything else in this package uses this client.

  project_pages.py   — Reads and writes Layer 1 project pages (active matters).
                       Used by Alfred skills and background agents.

  watch_list.py      — Reads and writes Bloodhound's Watch List database.
                       Used by Bloodhound's feed ingestor and triage logic.

  comms_log.py       — Reads and writes the KLG Comms Log database.
                       Emails sent to CaseFile@KowalLawGroup.com land here.
                       Alfred reads this for triage and matter-linked comms.
"""

from notion_bridge.client import NotionBridge
from notion_bridge.comms_log import CommsLog
from notion_bridge.tasks import TaskPages

__all__ = ["NotionBridge", "CommsLog", "TaskPages"]
