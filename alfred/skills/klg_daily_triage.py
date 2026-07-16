"""
alfred/skills/klg_daily_triage.py — Daily operational triage for the KLG team.

Cross-cutting skill that surfaces urgent deadlines, priority conflicts, team
workload imbalances, and comms log items needing action. Six modes:

  full-triage        (default) — all four pillars
  priority-check     — matter priority vs. deadline alignment
  deadline-audit     — deadline completeness and urgency scan
  comms-log-triage   — classify Notion Comms Log entries by action needed
  workload-check     — team load balance
  slack-standup      — formatted standup post for Slack
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_COMMS_LOG_DB = "2e40fc06-a06c-8197-a806-c1f6f28a847c"


def _detect_mode(instruction: str) -> str:
    text = instruction.lower()
    if any(k in text for k in ("standup", "stand-up", "post to slack", "send to slack", "post standup")):
        return "slack-standup"
    if any(k in text for k in ("comms log", "comms-log", "communication log", "communications log")):
        return "comms-log-triage"
    if any(k in text for k in ("deadline", "due date", "overdue", "filing")):
        return "deadline-audit"
    if any(k in text for k in ("priority", "urgent", "critical", "protect")):
        return "priority-check"
    if any(k in text for k in ("workload", "capacity", "bandwidth", "team load", "who has")):
        return "workload-check"
    return "full-triage"


_PILLAR_PRIORITY = """\
## PILLAR 1 — PRIORITY PROTECTION
Review active matters for priority/deadline mismatches:
- Which matters have deadlines ≤7 days AND are not flagged Critical or High?
- Any matter flagged Critical with NO deadline visible? (gap risk)
- Matters where stated priority contradicts deadline urgency?
- What needs Tim's personal attention today?

Flag each mismatch clearly: matter name → issue → recommended correction.
"""

_PILLAR_DEADLINE = """\
## PILLAR 2 — DEADLINE AUDIT
For every deadline retrieved:
- Confirm matter name, deadline type (brief, argument, response, extension), and date
- 🔴 URGENT: ≤7 days — name the responsible attorney and confirm the task is in progress
- 🟡 APPROACHING: 8–30 days — confirm assignment and next milestone
- 🟢 ON TRACK: >30 days — list only, no action needed
- ⚠ GAP: any active matter with no visible deadline — flag for Tim to verify

Do not invent deadlines. If data is missing, flag [VERIFY].
"""

_PILLAR_WORKLOAD = """\
## PILLAR 3 — WORKLOAD CHECK
Review team task distribution:
- Who has the heaviest open task count right now?
- Any attorney with >4 active urgent matters? (potential overload)
- Unassigned tasks or tasks assigned to someone with no recent activity?
- Recommend task rebalancing if workload is significantly uneven.

Name individuals by role (Tim, Brittney, Ted, William) — not generic "attorney."
"""

_PILLAR_COMMS = f"""\
## PILLAR 4 — COMMS LOG TRIAGE (Notion DB: {_COMMS_LOG_DB})
Classify each recent comms log entry (last 7 days) into one bucket:
  A) Needs action today — response due, pending decision, unresolved question
  B) Pending — waiting on client, court, or opposing counsel
  C) Informational — logged for record, no action needed
  D) Stale — last entry >14 days with no resolution (follow up now)
  E) Completed — can be archived

For every A and D entry: name the assignee and state the specific next action.
Do not invent communications. If entries are not retrieved, say so and flag [VERIFY].
"""

_STANDUP_FORMAT = """\
## SLACK STANDUP FORMAT
Generate a Slack-ready standup message. Paste-ready, under 300 words.

Format exactly:
*KLG Daily Triage — {{today}}*

*🔴 Urgent (≤7 days):*
• [Matter Name] — [Deadline type, date] — [Assignee]

*🟡 Approaching (8–30 days):*
• [Matter Name] — [Deadline type, date]

*📋 Action Items from Comms Log:*
• [Item — Assignee — Due]

*⚠ Flags:*
• [Any priority gap, overload warning, or missing deadline]

Facts only. No narrative. If data is missing, omit that section rather than guessing.
"""


_TRIAGE_PROMPT = """\
You are Alfred, KLG's AI Operating System. Today is {today}.

Run a KLG daily triage in mode: {mode}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — USE YOUR TOOLS TO FETCH CURRENT DATA

Call these tools now to gather live data before writing the report:

1. get_upcoming_deadlines() — retrieve all upcoming court and filing deadlines
2. get_team_workload() — retrieve current task distribution across the team
3. search_notion with query "comms log recent" and database_id="{comms_db}" — retrieve \
last 7 days of Comms Log entries
4. recall_notes with query "triage" — check for any Alfred notes flagged for today

If a tool returns no data, note that clearly in the relevant section rather than omitting it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — SYNTHESIZE INTO TRIAGE REPORT

KLG Team: Tim Kowal (partner), Brittney (paralegal), Ted (associate), William (associate).

{pillars}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTION FROM USER:
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WRITING RULES:
- Em dashes without spaces—like this
- Lead every section with the finding, not the setup
- Active verbs. No "therefore," "furthermore," "clearly," "as such"
- CRITICAL: never invent deadlines, matter names, or comms entries
  Flag anything unverifiable: [VERIFY]
- End with NEXT STEPS (≤5 items, ranked by urgency)

DRAFT — attorney review required before acting on triage findings.
"""


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
        "Cross-cutting daily operational triage: surface urgent deadlines, priority conflicts, "
        "team workload imbalances, and comms log items needing action. "
        "Modes: full-triage (default), priority-check, deadline-audit, comms-log-triage, "
        "workload-check, slack-standup."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        from datetime import date as _date
        today = _date.today().strftime("%A, %B %d, %Y")
        instruction = ctx.user_instruction.strip()
        mode = _detect_mode(instruction)

        if mode == "full-triage":
            pillars = "\n".join([
                _PILLAR_PRIORITY, _PILLAR_DEADLINE,
                _PILLAR_WORKLOAD, _PILLAR_COMMS,
            ])
        elif mode == "slack-standup":
            pillars = _STANDUP_FORMAT.replace("{today}", today)
        elif mode == "comms-log-triage":
            pillars = _PILLAR_COMMS
        elif mode == "deadline-audit":
            pillars = _PILLAR_DEADLINE
        elif mode == "priority-check":
            pillars = _PILLAR_PRIORITY
        elif mode == "workload-check":
            pillars = _PILLAR_WORKLOAD
        else:
            pillars = "\n".join([_PILLAR_PRIORITY, _PILLAR_DEADLINE, _PILLAR_WORKLOAD, _PILLAR_COMMS])

        prompt = _TRIAGE_PROMPT.format(
            today=today,
            mode=mode,
            comms_db=_COMMS_LOG_DB,
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
                else "Assign action items. Re-run with 'comms-log-triage' to drill deeper on Bucket A items."
            ),
            success=True,
        )
