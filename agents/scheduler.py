"""
agents/scheduler.py — APScheduler setup for all Layer 3 background agents.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This module configures APScheduler to run the Layer 3 background agents
on their scheduled cadences:

  1. DEADLINE WATCH  — Daily at 8:00 AM Pacific.
                       Posts upcoming deadlines (next 7 days) to Slack.

  2. WEEKLY AGENDA   — Monday at 7:30 AM Pacific.
                       Posts the full weekly matter agenda to #case-management.

  3. HYGIENE SCAN    — Monday at 8:00 AM Pacific (after the agenda).
                       Scans for stale matters, missing dates, incomplete owners.
                       Posts anomalies to #case-management.

  4. CASE CHECK-IN   — Monday at 9:00 AM Pacific and Thursday at 9:00 AM Pacific.
                       Posts a check-in message to each active matter's Slack channel,
                       asking the team for weekly updates. Replies @mentioning Alfred
                       are auto-logged to Notion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW THE SCHEDULER INTEGRATES WITH FASTAPI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

APScheduler's AsyncIOScheduler runs inside the same event loop as FastAPI.
This means:
  - No separate process or worker needed
  - Agents can call async functions (Notion API, Slack API) natively
  - The scheduler starts with the FastAPI app and stops with it

The scheduler is started in main.py's lifespan() context manager — it starts
when FastAPI boots and shuts down cleanly when FastAPI stops.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIMEZONE NOTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All cron schedules below use "America/Los_Angeles" (Pacific time) because
that's where the KLG team operates. APScheduler handles DST transitions
automatically when you specify a timezone string.

If the server is deployed in a different timezone (e.g., a Vercel or Railway
server in UTC), the timezone string still works correctly — APScheduler
converts internally. Never hardcode UTC offsets like "-08:00" because they
break during daylight saving time.
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Pacific Time — all agent schedules are specified in this timezone
PACIFIC_TZ = "America/Los_Angeles"


def create_scheduler(
    project_pages: Any,  # ProjectPages
    slack_client: Any | None = None,
    watch_list: Any | None = None,  # WatchList — for Bloodhound daily scan
) -> AsyncIOScheduler:
    """
    Create and configure the APScheduler instance with all three agents.

    This function is called once in main.py's lifespan() handler. It returns
    a configured (but not yet started) scheduler. The caller is responsible
    for calling scheduler.start() and scheduler.shutdown().

    WHY PASS project_pages AND slack_client AS ARGUMENTS?
        The scheduler needs access to the Notion bridge and Slack client to
        pass to each agent's run function. Rather than importing them at
        module level (which would cause import cycles and make testing harder),
        we pass them in at scheduler creation time. The scheduler stores them
        in closures inside the job functions.

    Args:
        project_pages: Initialized ProjectPages instance (from NotionBridge).
        slack_client:  Initialized slack_sdk.WebClient, or None if Slack
                       is not configured.

    Returns:
        Configured AsyncIOScheduler, ready to start. Jobs are registered
        but not running yet.
    """
    from agents.case_checkin import run_case_checkin
    from agents.deadline_watch import run_deadline_watch
    from api.routes.bloodhound import run_bloodhound_scan

    scheduler = AsyncIOScheduler(
        # Use Pacific timezone as the scheduler's default — individual jobs
        # can override this, but having a sensible default prevents accidents.
        timezone=PACIFIC_TZ,
    )

    # ── Job 0: Daily Bloodhound Scan ─────────────────────────────────────────
    # Runs every morning at 7:00 AM Pacific — before the deadline watch.
    # Fetches feeds, triages signals, writes relevant cases to Notion Watch List,
    # and posts a summary to #case-management if anything was found.
    # Skipped gracefully if watch_list is not configured.
    #
    if watch_list:
        scheduler.add_job(
            func=run_bloodhound_scan,
            trigger=CronTrigger(hour=7, minute=0, timezone=PACIFIC_TZ),
            kwargs={"watch_list": watch_list, "slack_client": slack_client},
            id="bloodhound_scan_daily",
            name="Daily Bloodhound Feed Scan",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("Scheduler: Registered 'bloodhound_scan_daily' at 07:00 Pacific daily.")
    else:
        logger.info(
            "Scheduler: Bloodhound scan not scheduled — NOTION_WATCH_LIST_DB_ID not configured."
        )

    # ── Job 1: Daily Deadline Watch ───────────────────────────────────────────
    # Runs every morning at 8:00 AM Pacific.
    # Posts to #case-management: all matters with deadlines in the next 7 days.
    #
    # CronTrigger parameters:
    #   hour="8"        → at 8 AM
    #   minute="0"      → on the hour exactly
    #   day_of_week="*" → every day (Monday through Sunday)
    #
    scheduler.add_job(
        func=run_deadline_watch,
        trigger=CronTrigger(hour=8, minute=0, timezone=PACIFIC_TZ),
        args=[project_pages, slack_client],
        id="deadline_watch_daily",
        name="Daily Deadline Watch",
        # Replace the previous job with the same ID if it exists (prevents
        # duplicate jobs if the scheduler is recreated without a full restart).
        replace_existing=True,
        # If the server was down during a scheduled run (e.g., overnight restart),
        # run the missed job once immediately on next boot — so the team still
        # gets their morning briefing even if the server bounced at 7:55 AM.
        misfire_grace_time=3600,  # 1 hour grace window
    )
    logger.info("Scheduler: Registered 'deadline_watch_daily' at 08:00 Pacific daily.")

    # ── Job 2: Weekly Monday Agenda ───────────────────────────────────────────
    # Runs Monday morning at 7:30 AM Pacific (30 minutes before the deadline watch).
    # Posts a full weekly overview to #case-management.
    #
    # day_of_week="mon" → Monday only (APScheduler uses 3-letter abbreviations)
    #
    scheduler.add_job(
        func=_run_weekly_agenda,
        trigger=CronTrigger(
            day_of_week="mon", hour=7, minute=30, timezone=PACIFIC_TZ
        ),
        args=[project_pages, slack_client],
        id="weekly_agenda_monday",
        name="Monday Morning Weekly Agenda",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler: Registered 'weekly_agenda_monday' at 07:30 Pacific Mondays.")

    # ── Job 3: Project Hygiene Scan ───────────────────────────────────────────
    # Runs Monday morning at 8:15 AM Pacific (after the agenda and deadline watch).
    # Scans for hygiene issues: stale matters, missing dates, owner gaps.
    #
    scheduler.add_job(
        func=_run_hygiene_scan,
        trigger=CronTrigger(
            day_of_week="mon", hour=8, minute=15, timezone=PACIFIC_TZ
        ),
        args=[project_pages, slack_client],
        id="hygiene_scan_weekly",
        name="Weekly Project Hygiene Scan",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler: Registered 'hygiene_scan_weekly' at 08:15 Pacific Mondays.")

    # ── Job 4: Monday Case Check-in ───────────────────────────────────────────
    # Posts a brief status check-in to each active matter's Slack channel.
    # Team replies mentioning @Alfred are auto-logged to that matter's Notion page.
    #
    # Runs at 9:00 AM Pacific on Mondays (after agenda and hygiene scan).
    #
    scheduler.add_job(
        func=run_case_checkin,
        trigger=CronTrigger(
            day_of_week="mon", hour=9, minute=0, timezone=PACIFIC_TZ
        ),
        args=[project_pages, slack_client],
        id="case_checkin_monday",
        name="Monday Case Check-in",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler: Registered 'case_checkin_monday' at 09:00 Pacific Mondays.")

    # ── Job 5: Thursday Case Check-in ────────────────────────────────────────
    # Same check-in cadence as Monday, mid-week touchpoint.
    #
    scheduler.add_job(
        func=run_case_checkin,
        trigger=CronTrigger(
            day_of_week="thu", hour=9, minute=0, timezone=PACIFIC_TZ
        ),
        args=[project_pages, slack_client],
        id="case_checkin_thursday",
        name="Thursday Case Check-in",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info("Scheduler: Registered 'case_checkin_thursday' at 09:00 Pacific Thursdays.")

    return scheduler


async def _run_weekly_agenda(
    project_pages: Any,
    slack_client: Any | None,
) -> None:
    """
    Weekly Monday morning agenda: all active matters, sorted by priority.

    Posts a structured overview of the firm's full caseload to #case-management
    so the week starts with a shared picture of what's active and what's pressing.

    This is intentionally simple for v1 — a formatted list of all active matters
    grouped by priority. Future versions can add AI synthesis ("here are the
    three things that need the most attention this week").
    """
    from config import settings
    from datetime import date

    logger.info("WeeklyAgenda agent starting...")

    matters = await project_pages.get_all_active_matters()

    if not matters:
        message = (
            f"*KLG Monday Morning Agenda — {date.today().strftime('%B %d, %Y')}*\n"
            "No active matters found. Check the Projects database in Notion."
        )
    else:
        # Group by priority for a structured overview
        high = [m for m in matters if m.get("Priority") == "High"]
        medium = [m for m in matters if m.get("Priority") == "Medium"]
        other = [m for m in matters if m.get("Priority") not in ("High", "Medium")]

        def format_matter_line(m: dict) -> str:
            name = m.get("Project name", "Unknown")
            status = m.get("Status", "?")
            deadline = (
                m.get("date:Target Date:start") or m.get("Target Date") or "No date"
            )
            return f"  • *{name}* — {status} | Next deadline: {deadline[:10] if deadline else 'N/A'}"

        sections: list[str] = [
            f"*KLG Monday Morning Agenda — {date.today().strftime('%B %d, %Y')}*",
            f"_{len(matters)} active matter{'s' if len(matters) != 1 else ''} total_\n",
        ]

        if high:
            sections.append(f"*🔴 High Priority ({len(high)})*")
            sections.extend(format_matter_line(m) for m in high)
            sections.append("")

        if medium:
            sections.append(f"*🟡 Medium Priority ({len(medium)})*")
            sections.extend(format_matter_line(m) for m in medium)
            sections.append("")

        if other:
            sections.append(f"*⚪ Other Active ({len(other)})*")
            sections.extend(format_matter_line(m) for m in other)

        sections.append(
            "\n_→ Ask Alfred for details on any matter or to surface this week's priorities._"
        )
        message = "\n".join(sections)

    if slack_client and settings.slack_bot_token:
        try:
            await slack_client.chat_postMessage(
                channel=settings.slack_case_management_channel,
                text=message,
            )
            logger.info("WeeklyAgenda: Posted to Slack.")
        except Exception as e:
            logger.error("WeeklyAgenda: Slack post failed: %s", e)
            logger.info("WEEKLY AGENDA OUTPUT:\n%s", message)
    else:
        logger.info("WEEKLY AGENDA OUTPUT:\n%s", message)


async def _run_hygiene_scan(
    project_pages: Any,
    slack_client: Any | None,
) -> None:
    """
    Weekly hygiene scan: surface stale or incomplete matter pages.

    Checks each active matter for common hygiene issues:
      - No Target Date set
      - Last edited more than 14 days ago (possibly stale/forgotten)
      - Status is "Blocked" (may need attention)
      - Priority not set

    Posts a concise anomaly report to Slack if any issues are found.
    If everything looks clean, posts a one-line "all clear."
    """
    from config import settings
    from datetime import date, datetime, timezone

    logger.info("HygieneScan agent starting...")

    matters = await project_pages.get_all_active_matters()
    issues: list[str] = []

    for matter in matters:
        name = matter.get("Project name", "Unknown")
        url = matter.get("url", "")
        anomalies: list[str] = []

        # Check: No target date
        has_date = (
            matter.get("date:Target Date:start")
            or matter.get("Target Date")
        )
        if not has_date:
            anomalies.append("no target date")

        # Check: Stale (not edited in 14+ days)
        last_edited = matter.get("last_edited_time", "")
        if last_edited:
            try:
                edited_dt = datetime.fromisoformat(last_edited.replace("Z", "+00:00"))
                days_since_edit = (datetime.now(timezone.utc) - edited_dt).days
                if days_since_edit >= 14:
                    anomalies.append(f"not edited in {days_since_edit} days")
            except ValueError:
                pass

        # Check: Blocked status
        if matter.get("Status") == "Blocked":
            anomalies.append("status is Blocked")

        # Check: No priority
        if not matter.get("Priority"):
            anomalies.append("no priority set")

        if anomalies:
            issues.append(
                f"  ⚠️ *{name}*: {', '.join(anomalies)}\n    {url}"
            )

    if not issues:
        message = (
            f"*KLG Project Hygiene Scan — {date.today().strftime('%B %d, %Y')}*\n"
            f"All {len(matters)} active matters look clean. No anomalies found. ✓"
        )
    else:
        message = (
            f"*KLG Project Hygiene Scan — {date.today().strftime('%B %d, %Y')}*\n"
            f"Found {len(issues)} matter{'s' if len(issues) != 1 else ''} with hygiene issues:\n\n"
            + "\n\n".join(issues)
            + "\n\n_→ Ask Alfred to update any of these matters._"
        )

    if slack_client and settings.slack_bot_token:
        try:
            await slack_client.chat_postMessage(
                channel=settings.slack_case_management_channel,
                text=message,
            )
            logger.info("HygieneScan: Posted to Slack.")
        except Exception as e:
            logger.error("HygieneScan: Slack post failed: %s", e)
            logger.info("HYGIENE SCAN OUTPUT:\n%s", message)
    else:
        logger.info("HYGIENE SCAN OUTPUT:\n%s", message)
