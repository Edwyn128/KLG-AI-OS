"""
agents/deadline_watch.py — Daily deadline-watch background agent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS AGENT DOES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Every morning (8 AM Pacific by default), this agent:

  1. Queries the Notion Projects database for all matters with deadlines
     in the next 7 days (using ProjectPages.get_matters_with_upcoming_deadlines)
  2. Formats a clear, concise briefing — matter name, deadline, days remaining
  3. Posts it to the #case-management Slack channel

The goal: the team should never be surprised by an upcoming deadline.
Tim should not need to check Notion every morning to know what's urgent.

LAYER 3 CONSTRAINT: This agent reads Notion but NEVER writes to it.
It posts to Slack only. If Tim wants to update a matter based on this
briefing, he tells Alfred, who runs a skill that updates Notion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FALLBACK BEHAVIOR (when Slack is not configured)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If SLACK_BOT_TOKEN is empty in .env (e.g., during local development),
the agent logs the briefing to the console instead of posting to Slack.
This means you can run and test the agent locally without needing a live
Slack workspace.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from config import settings
from notion_bridge.project_pages import _PROP_DEADLINE, _PROP_COURT_DEADLINE

logger = logging.getLogger(__name__)


async def run_deadline_watch(
    project_pages: Any,  # ProjectPages — typed loosely to avoid circular import at module load
    slack_client: Any | None = None,
) -> str:
    """
    Execute the daily deadline-watch scan and post results to Slack.

    This is the function registered with APScheduler. It is called once per day
    automatically. It can also be called manually from the API for testing.

    Args:
        project_pages: A ProjectPages instance. Passed in from the FastAPI
                       app state rather than imported here to avoid circular deps.
        slack_client:  An initialized slack_sdk.WebClient, or None if Slack
                       is not configured. If None, output goes to the console log.

    Returns:
        The Slack message text that was sent (or would have been sent).
        Useful for testing and for the API endpoint that lets you trigger
        this agent manually from the web UI.
    """
    logger.info("DeadlineWatch agent starting...")

    today = date.today()
    matters = await project_pages.get_matters_with_upcoming_deadlines(days=7)

    if not matters:
        message = (
            f"*KLG Daily Deadline Watch — {today.strftime('%A, %B %d')}*\n"
            f"No matters with deadlines in the next 7 days. Clear horizon. ✓"
        )
        logger.info("DeadlineWatch: No upcoming deadlines found.")
        await _post_or_log(message, slack_client)
        return message

    matter_lines: list[str] = []
    for matter in matters:
        name        = matter.get("Project name", "Unknown matter")
        status      = matter.get("Status", "Unknown")
        priority    = matter.get("Priority", "")
        case_stage  = matter.get("Case Stage") or ""
        court_date  = matter.get(_PROP_COURT_DEADLINE) or ""
        court_info  = ""  # "Next Deadline Info" property does not exist in Notion schema
        target_date = matter.get(_PROP_DEADLINE) or ""

        # Prefer Next Court Deadline when set — it is the hard legal deadline.
        # Fall back to Deadline (internal project milestone).
        if court_date:
            deadline_str  = court_date
            deadline_type = "Court"
        else:
            deadline_str  = target_date
            deadline_type = "Target"

        days_remaining = _days_until(deadline_str)
        urgency_prefix = _urgency_emoji(days_remaining)

        if deadline_str:
            try:
                deadline_date    = date.fromisoformat(deadline_str[:10])
                deadline_display = deadline_date.strftime("%a %b %d")
            except ValueError:
                deadline_display = deadline_str

            days_str = (
                "TODAY"
                if days_remaining == 0
                else f"in {days_remaining} day{'s' if days_remaining != 1 else ''} ({deadline_display})"
            )
        else:
            days_str = "date not set"

        # Build line — include case stage and court deadline context when available
        stage_tag = f" [{case_stage}]" if case_stage else ""
        info_line = f"\n   _{court_info}_" if court_info and court_info != "No upcoming court deadline" else ""

        matter_lines.append(
            f"{urgency_prefix} *{name}*{stage_tag} — {deadline_type} deadline {days_str} | {status} | {priority}{info_line}"
        )

    matters_block = "\n".join(matter_lines)

    message = (
        f"*KLG Daily Deadline Watch — {today.strftime('%A, %B %d')}*\n"
        f"*{len(matters)} matter{'s' if len(matters) != 1 else ''} with deadlines in the next 7 days:*\n\n"
        f"{matters_block}\n\n"
        f"_→ Ask Alfred for details on any matter. Notion is the source of truth._"
    )

    await _post_or_log(message, slack_client)
    logger.info("DeadlineWatch: Posted %d-matter briefing.", len(matters))
    return message


def _days_until(date_str: str) -> int:
    """
    Calculate days between today and a date string.

    Args:
        date_str: ISO 8601 date string (e.g., "2026-05-14" or "2026-05-14T00:00:00Z").
                  We only use the first 10 characters (the date part).

    Returns:
        Number of days until the deadline. Negative if past. 0 if today.
        Returns 999 if the date string is empty or unparseable.
    """
    if not date_str:
        return 999
    try:
        deadline = date.fromisoformat(date_str[:10])
        return (deadline - date.today()).days
    except ValueError:
        return 999


def _urgency_emoji(days_remaining: int) -> str:
    """
    Return an emoji that visually signals deadline urgency.

    The emoji appears at the start of each matter line in Slack, making
    urgency scannable at a glance — no need to read the date.

    Args:
        days_remaining: Days until deadline (from _days_until).

    Returns:
        🔴 (0–2 days), 🟡 (3–5 days), 🟢 (6–7 days), ⚪ (unknown/far)
    """
    if days_remaining <= 0:
        return "🔴"  # Today or past due
    elif days_remaining <= 2:
        return "🔴"  # 1-2 days — critical
    elif days_remaining <= 5:
        return "🟡"  # 3-5 days — urgent
    else:
        return "🟢"  # 6-7 days — on radar


async def _post_or_log(message: str, slack_client: Any | None) -> None:
    """
    Post a message to Slack, or log it to the console if Slack isn't configured.

    This abstraction means the rest of the agent code doesn't need to branch
    on whether Slack is configured — it just calls _post_or_log().

    Args:
        message:      The formatted Slack message text (supports Slack markdown).
        slack_client: Initialized slack_sdk.WebClient, or None.
    """
    if slack_client and settings.slack_bot_token:
        try:
            await slack_client.chat_postMessage(
                channel=settings.slack_case_management_channel,
                text=message,
            )
            logger.info(
                "DeadlineWatch: Posted to Slack channel '%s'",
                settings.slack_case_management_channel,
            )
        except Exception as e:
            # A Slack posting failure should not crash the agent run.
            # Log the error and fall through to console logging.
            logger.error("Slack post failed: %s. Falling back to console log.", e)
            logger.info("DEADLINE WATCH OUTPUT:\n%s", message)
    else:
        # Development mode: Slack not configured, log to console.
        # The message is still formatted as it would appear in Slack.
        logger.info(
            "Slack not configured (SLACK_BOT_TOKEN empty). Console output:\n%s",
            message,
        )
