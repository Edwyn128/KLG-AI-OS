"""
agents/case_checkin.py — Proactive case check-in agent (Layer 3).

Posts a check-in message to each active matter's Slack channel on a
scheduled cadence (Monday + Thursday mornings by default). The channel
is resolved from the matter's optional Notion 'Slack Channel' property
first, then falls back to a slugified version of the matter name.

This is pure Layer 3 behavior: reads Notion, posts to Slack, never
writes to Notion directly. Notion writes happen when the team @mentions
Alfred in a case channel in response to the check-in.

Channel resolution (two-step):
  1. Notion 'Slack Channel' property — explicit override for edge cases
  2. Slugified matter name — e.g. "Riva Fourjays" → #riva-fourjays

New matters are auto-discovered: as long as the Slack channel follows
the naming convention, Alfred finds it at the next check-in cycle with
zero manual configuration.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


def slugify(name: str) -> str:
    """Convert a matter name to a Slack-safe channel slug."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug)
    return slug[:80]


def resolve_channel_for_matter(matter: dict) -> str | None:
    """
    Return the Slack channel name (with # prefix) for a matter, or None.

    Checks the 'Slack Channel' Notion property first (explicit override),
    then falls back to slugifying the matter's Project name.
    """
    explicit = (matter.get("Slack Channel") or "").strip().lstrip("#")
    if explicit:
        return f"#{explicit}"

    name = (matter.get("Project name") or "").strip()
    if not name:
        return None

    slug = slugify(name)
    return f"#{slug}" if slug else None


async def resolve_matter_for_channel(
    channel_name: str,
    project_pages: Any,
) -> dict | None:
    """
    Inverse of resolve_channel_for_matter — find the Notion matter that
    maps to a given Slack channel name.

    Used by the Slack route to auto-log @mentions to the right matter page.
    Returns None if no active matter maps to this channel.
    """
    clean = channel_name.lstrip("#").lower()
    if not clean:
        return None

    matters = await project_pages.get_all_active_matters(category="Case Project")

    for matter in matters:
        # Check explicit property first
        explicit = (matter.get("Slack Channel") or "").strip().lstrip("#").lower()
        if explicit and explicit == clean:
            return matter

        # Check slugified name
        name = (matter.get("Project name") or "").strip()
        if name and slugify(name) == clean:
            return matter

    return None


async def run_case_checkin(
    project_pages: Any,
    slack_client: Any | None,
) -> None:
    """
    Post check-in messages to all active case channels.

    Queries Notion for active Case Project matters, resolves each matter's
    Slack channel, and posts a brief status check-in. Silently skips matters
    with no resolvable channel or where the channel doesn't exist in Slack
    (logs a warning instead of raising — a missing channel just means the
    team hasn't created it yet).
    """
    if not slack_client:
        logger.info("CaseCheckin: Slack not configured — skipping.")
        return

    logger.info("CaseCheckin agent starting...")

    matters = await project_pages.get_all_active_matters(category="Case Project")
    posted = 0
    skipped = 0

    today = date.today().strftime("%B %d")

    for matter in matters:
        channel = resolve_channel_for_matter(matter)
        if not channel:
            skipped += 1
            continue

        matter_name = matter.get("Project name", "this matter")
        status = matter.get("Status", "")
        deadline_raw = (
            matter.get("date:Target Date:start") or matter.get("Target Date") or ""
        )
        deadline = deadline_raw[:10] if deadline_raw else None
        priority = matter.get("Priority", "")

        lines = [f"*{matter_name}* — check-in ({today})"]
        meta = []
        if status:
            meta.append(f"Status: {status}")
        if priority:
            meta.append(f"Priority: {priority}")
        if deadline:
            meta.append(f"Next deadline: {deadline}")
        if meta:
            lines.append(" | ".join(meta))
        lines.append("Any updates? @Alfred [your update] to log it to Notion.")

        message = "\n".join(lines)

        try:
            resp = await slack_client.chat_postMessage(
                channel=channel, text=message
            )
            if resp.get("ok"):
                posted += 1
                logger.info("CaseCheckin: Posted to %s (%s)", channel, matter_name)
            else:
                error = resp.get("error", "unknown")
                if error == "channel_not_found":
                    logger.warning(
                        "CaseCheckin: Channel %s not found for '%s'. "
                        "Create the channel, invite @Alfred, or set the "
                        "'Slack Channel' property on the Notion page.",
                        channel,
                        matter_name,
                    )
                else:
                    logger.warning(
                        "CaseCheckin: %s → Slack error: %s", channel, error
                    )
                skipped += 1
        except Exception as e:
            logger.error("CaseCheckin: Error posting to %s: %s", channel, e)
            skipped += 1

    logger.info(
        "CaseCheckin complete: %d posted, %d skipped.", posted, skipped
    )
