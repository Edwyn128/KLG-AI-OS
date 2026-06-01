"""
agents — Layer 3 background agents for the KLG AI OS.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT LAYER 3 AGENTS ARE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Layer 3 agents are the firm's "always-on" hygiene and visibility layer.
They run on a schedule, read Notion (Layer 1), and post to Slack.

THE CRITICAL CONSTRAINT: Layer 3 agents READ but NEVER WRITE to Notion.
Only Layer 2 skills (Alfred) write to project pages. This separation
keeps the audit trail clean: if a Notion page changes unexpectedly,
it's always because a skill ran — never because a background agent
quietly modified something.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THREE AGENTS IN THIS PACKAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  scheduler.py       — APScheduler setup. Registers all agents on their
                       cron schedules and starts the scheduler alongside FastAPI.

  deadline_watch.py  — DAILY. Posts to matter-specific Slack channels if a
                       matter has a deadline in the next 7 days. The morning
                       briefing the firm needs without Tim having to check.

  weekly_agenda.py   — MONDAY MORNING. Posts a full weekly agenda to
                       #case-management: all active matters, sorted by priority
                       and deadline. Replaces the Monday morning status hunt.
"""
