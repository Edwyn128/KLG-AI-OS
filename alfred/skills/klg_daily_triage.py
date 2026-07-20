"""
alfred/skills/klg_daily_triage.py — Daily operational triage for the KLG team.

Cross-cutting skill that surfaces urgent deadlines, priority conflicts, team
workload imbalances, and comms log items needing action. Six modes:

  full-triage        (default) — all four pillars + Notion project page
  morning-triage     — quick: today's tasks, urgent deadlines, top inbox items
  weekly-planning    — full week capacity, deadline overlay, time-block suggestions
  team-pulse         — cross-team task status, bottlenecks, overdue items
  comms-log-only     — just the Notion Comms Log triage and report
  slack-standup      — formatted standup for Slack #klg-internal

Adapts the Claude.ai klg-daily-triage skill for Alfred's tool set:
  Motion/Zapier → get_upcoming_deadlines + get_matter_tasks + get_team_workload
  Outlook/M365  → email pillar gracefully skipped (not available in Alfred)
  Notion        → search_notion (Comms Log DB + Projects DB)
  Slack         → send_slack_message

Notion database IDs (production):
  Comms Log:  2e40fc06-a06c-8197-a806-c1f6f28a847c
  Projects:   01c88dba-9dd8-4715-82f4-335837d3fa89
  Case Portal: 2da0fc06-a06c-8033-978b-000bd2803cd4

Motion assignee IDs:
  Tim:      bK4I5zZ4MKQkYX1SsaVyV7WoHnn1
  Brittney: WSOQbtHisLdCnjGSfMrNCK3rikP2
  Ted:      nzsyuTkRPodyVOEfhaJDfy3F5hl1
  William:  vWYPVO9qNGMyT8CpqTEzro6eGz63
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_COMMS_LOG_DB = "2e40fc06-a06c-8197-a806-c1f6f28a847c"
_PROJECTS_DB = "01c88dba-9dd8-4715-82f4-335837d3fa89"

_PRIORITY_WATCHLIST = [
    "HB Voter ID",
    "cert petition",
    "oral argument",
]


def _detect_mode(instruction: str) -> str:
    text = instruction.lower()
    if any(k in text for k in ("standup", "stand-up", "post to slack", "post standup")):
        return "slack-standup"
    if any(k in text for k in ("weekly", "plan my week", "week planning", "time block")):
        return "weekly-planning"
    if any(k in text for k in ("team pulse", "team status", "who's overloaded", "bottleneck")):
        return "team-pulse"
    if any(k in text for k in ("comms log", "comms-log", "communications log", "comms log only")):
        return "comms-log-only"
    if any(k in text for k in ("morning", "start my day", "good morning", "what's on my plate", "what do i need")):
        return "morning-triage"
    return "full-triage"


_COMMS_BUCKETS = """\
COMMS LOG — SIX CLASSIFICATION BUCKETS:

When reviewing Notion Comms Log entries, classify each into exactly one bucket:

  Bucket 1 — Action: assign/delegate
    Someone needs to own this; route to Brittney or William.
    Examples: client sends documents for filing, co-counsel requests team action,
    download links not yet processed (→ William), court filings with new deadlines.

  Bucket 2 — Action: Tim must handle
    Requires attorney judgment. Escalate to Tim.
    Examples: client asks substantive legal question, co-counsel requests Tim's
    strategy input, pinned entries (Pin = YES).

  Bucket 3 — Action: new PC intake
    New potential client. Trigger intake workflow.
    Examples: referral mentioning new case, Clio Grow notification,
    party not found in Case Portal.

  Bucket 4 — Informational: team is handling
    Workflow in progress, no intervention needed.
    Examples: Brittney is most recent KLG sender with no open client question,
    retainer/AdobeSign sent awaiting signature, William executing research task.

  Bucket 5 — Informational: no action needed
    FYI, resolved, directive sent.
    Examples: Tim's outbound directive with no pending question,
    client acknowledgment/thank-you, email recall notification, newsletter.

  Bucket 6 — Strategy/follow-up
    Direction set; verify at next meeting.
    Examples: attorney discussed approach and set direction, "please handle"
    directive without confirmed execution.

RULE: When uncertain, default to Bucket 1 (assign/delegate to Brittney),
NOT Bucket 2. Keep Tim's list short.

THREAD DEDUPLICATION: Group entries by subject root and Reply To chain.
Present only the most recent entry per thread in the report. Do NOT delete
older entries — deduplication is report-layer only.
"""

_DEADLINE_HYGIENE = """\
DEADLINE HYGIENE — THREE FILTERS before reporting anything as "overdue":

  Filter 1 — Stale deadline: deadline in the past on an active project
    → Classify as DATA QUALITY issue, not missed deadline
    → Add to Data Hygiene Punch List for Brittney

  Filter 2 — "Their deadline": task names containing "their," "opposing,"
    "other side," "respondent's" (when KLG is not that party)
    → Classify as MONITORING deadline, not KLG action item

  Filter 3 — Cascade dependency / illogical order:
    Known dependency chains:
    Opposing brief → Response plan → First draft → Second review → Cite check → Filing
    Record designation → Record prep → Record received → Briefing
    If a task is due before its logical predecessor: flag as cascade error

Output buckets:
  🔴 Real overdue — genuine missed deadline → Tim's attention
  ⚠ Data quality — stale or cascade error → Brittney cleanup punch list
  📅 Monitoring — their deadline → track only
"""

_PRIORITY_DRIFT = f"""\
PRIORITY DRIFT DETECTION:
Cross-reference deadlines and tasks against these high-priority matters:
{chr(10).join(f'  - {m}' for m in _PRIORITY_WATCHLIST)}

Flag any high-priority matter where no task has moved to "In Progress"
or "Completed" in the last 14 days:

  ⚠️ PRIORITY DRIFT: [Matter] — no task progress in [N] days.
  This is a high-priority matter at risk of stalling while lower-priority
  urgent requests consume capacity.
"""

_TRIAGE_PROMPT = """\
You are Alfred, KLG's AI Operating System. Today is {today}.
Mode: {mode}

KLG team: Tim Kowal (partner), Brittney (paralegal), Ted (associate), William (associate).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — FETCH LIVE DATA (use your tools now)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{tool_instructions}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — PRIOR TRIAGE LOOP (close out last week)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Call search_notion with query "Comms Log Triage In progress" in the Projects
database ({projects_db}) to find last week's triage report page.
If found:
  - Note any unchecked action items from last week — carry them forward
    with a "↩ Carried over from [date]" marker.
  - Do NOT modify last week's page — just read and carry items forward.
If not found: proceed without prior loop.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — SYNTHESIZE TRIAGE REPORT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{pillars}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTION:
{instruction}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WRITING RULES:
- Em dashes without spaces—like this
- Lead every section with the finding, not the setup
- Active verbs. No "therefore," "furthermore," "clearly," "as such"
- CRITICAL: never invent deadlines, matter names, or comms entries
  Flag anything unverifiable: [VERIFY]
- End with NEXT STEPS (≤5 items, ranked by urgency)
- Note: email/Outlook pillar is not available in Alfred; skip gracefully

DRAFT — attorney review required before acting on triage findings.
"""

_PILLAR_PRIORITY = """\
## PILLAR 1 — PRIORITY PROTECTION
""" + _PRIORITY_DRIFT + """
Also flag: matters with imminent deadlines (≤7 days) not marked High/Critical.
"""

_PILLAR_DEADLINE = """\
## PILLAR 2 — DEADLINE AUDIT
""" + _DEADLINE_HYGIENE + """
For each bucket:
  🔴 URGENT (≤7 days): name matter, deadline type, date, responsible attorney
  🟡 APPROACHING (8–30 days): list matter + date
  🟢 ON TRACK (>30 days): list only
  ⚠ DATA QUALITY: compile into punch list for Brittney
"""

_PILLAR_WORKLOAD = """\
## PILLAR 3 — WORKLOAD CHECK
Review team task distribution from get_team_workload:
- Who has the heaviest open task count?
- Any attorney with >4 active urgent matters? (overload risk)
- Unassigned tasks or tasks with approaching deadlines?
- Recommend task rebalancing if workload is significantly uneven.
Name individuals by role (Tim, Brittney, Ted, William) — not generic "attorney."
"""

_PILLAR_COMMS = f"""\
## PILLAR 4 — COMMS LOG TRIAGE (Notion DB: {_COMMS_LOG_DB})
Pull entries where Actions field is empty, created in last 5 days.
Group by thread (subject root + Reply To chain).
Present only the most recent entry per thread.

{_COMMS_BUCKETS}

Format each classified entry as:
  [Bucket N] Matter/context — specific instruction to Brittney — [VERIFY if uncertain]

After classifying all entries, produce a summary:
  Total entries reviewed: N
  Bucket 1 (assign/delegate): N
  Bucket 2 (Tim must handle): N
  Bucket 3 (new PC intake): N
  Bucket 4 (info, team handling): N
  Bucket 5 (info, no action): N
  Bucket 6 (strategy/follow-up): N
"""

_STANDUP_FORMAT = """\
Generate a Slack-ready standup. Paste-ready, under 300 words.

*KLG Daily Triage — {today}*

*🔴 Urgent (≤7 days):*
• [Matter] — [Deadline type, date] — [Assignee]

*🟡 Approaching (8–30 days):*
• [Matter] — [Deadline type, date]

*📋 Action Items (Comms Log Bucket 1–2):*
• [Item — Assignee — deadline if any]

*⚠ Flags:*
• [Priority drift, data quality issues, overload]

Facts only. No narrative. If data is missing, omit the section.
"""

_MORNING_FORMAT = """\
Quick morning triage (≤5 min):
1. List the 3 most urgent deadlines today and this week.
2. List the top 3 priority drift risks (high-priority matters stalling).
3. List any Comms Log Bucket 1–2 items from the last 48 hours.
4. One recommended first action for Tim this morning.
Keep it under 200 words. Facts only.
"""

_WEEKLY_FORMAT = """\
Weekly planning triage:
1. Full deadline map for the next 14 days by attorney.
2. Capacity check: who is overcommitted this week?
3. Priority drift: any high-priority matter with no task progress in 14+ days?
4. Comms Log: summarize open action items.
5. Recommended task moves or time blocks (offer to send to Slack or log to Notion).
"""

_TEAM_PULSE_FORMAT = """\
Team pulse — cross-team status:
For each team member (Tim, Brittney, Ted, William):
  - Open task count
  - Overdue tasks (real, not stale)
  - Tasks due this week
Flag bottlenecks: 3+ overdue tasks, 5+ due this week, unassigned approaching deadlines.
"""

_TOOL_INSTRUCTIONS = {
    "full-triage": f"""\
1. get_upcoming_deadlines() — all upcoming court/filing deadlines
2. get_team_workload() — team task distribution
3. get_matter_tasks() for any matter flagged as high priority
4. search_notion query="comms log recent unactioned" database_id="{_COMMS_LOG_DB}" — last 5 days
5. recall_notes query="triage" — any Alfred notes flagged for today
""",
    "morning-triage": f"""\
1. get_upcoming_deadlines() — focus on next 7 days
2. search_notion query="comms log urgent" database_id="{_COMMS_LOG_DB}" — last 48 hours
""",
    "weekly-planning": f"""\
1. get_upcoming_deadlines() — next 14 days
2. get_team_workload() — full team capacity
3. get_matter_tasks() for high-priority matters
""",
    "team-pulse": """\
1. get_team_workload() — full cross-team distribution
2. get_upcoming_deadlines() — flag who owns approaching deadlines
""",
    "comms-log-only": f"""\
1. search_notion query="comms log recent" database_id="{_COMMS_LOG_DB}" — last 5 days
2. search_notion query="Comms Log Triage In progress" database_id="{_PROJECTS_DB}" — prior triage page
""",
    "slack-standup": f"""\
1. get_upcoming_deadlines() — urgent and approaching
2. search_notion query="comms log action needed" database_id="{_COMMS_LOG_DB}" — last 5 days
""",
}


class KLGDailyTriage(Skill):
    name = "klg-daily-triage"
    required_tools = [
        "get_upcoming_deadlines",
        "get_team_workload",
        "search_notion",
        "get_matter_tasks",
        "send_slack_message",
        "recall_notes",
    ]
    description = (
        "Cross-cutting daily operational triage: surface urgent deadlines, priority drift, "
        "team workload imbalances, and Notion Comms Log items needing action. "
        "Modes: full-triage (default), morning-triage, weekly-planning, team-pulse, "
        "comms-log-only, slack-standup."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        from datetime import date as _date
        today = _date.today().strftime("%A, %B %d, %Y")
        instruction = ctx.user_instruction.strip()
        mode = _detect_mode(instruction)

        pillar_map = {
            "full-triage": "\n".join([_PILLAR_PRIORITY, _PILLAR_DEADLINE, _PILLAR_WORKLOAD, _PILLAR_COMMS]),
            "morning-triage": _MORNING_FORMAT,
            "weekly-planning": _WEEKLY_FORMAT,
            "team-pulse": _TEAM_PULSE_FORMAT,
            "comms-log-only": _PILLAR_COMMS,
            "slack-standup": _STANDUP_FORMAT.format(today=today),
        }
        pillars = pillar_map.get(mode, pillar_map["full-triage"])
        tool_instructions = _TOOL_INSTRUCTIONS.get(mode, _TOOL_INSTRUCTIONS["full-triage"])

        prompt = _TRIAGE_PROMPT.format(
            today=today,
            mode=mode,
            projects_db=_PROJECTS_DB,
            tool_instructions=tool_instructions,
            pillars=pillars,
            instruction=instruction or "(none — run standard triage)",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=f"Daily triage ({mode}) complete for {today}.",
            output=f"**KLG Daily Triage — {today}**\n\n{output_text}",
            next_action=(
                "Post to Slack: 'Alfred, post this standup to #klg-internal'."
                if mode == "slack-standup"
                else (
                    "Assign action items from Bucket 1–2. "
                    "Send Data Hygiene Punch List to Brittney via Slack. "
                    "Re-run with 'comms-log-only' to drill into classification."
                )
            ),
            success=True,
        )
