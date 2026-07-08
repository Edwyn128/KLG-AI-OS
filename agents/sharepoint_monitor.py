"""
agents/sharepoint_monitor.py — Layer 3 background agent: SharePoint change monitor.

Polls the SharePoint /Matters folder for file and folder changes via Microsoft
Graph delta, maps each change to a KLG matter, and posts a Slack notification
to #sharepoint-activity (SHAREPOINT_MONITOR_CHANNEL).

The delta link is persisted in Notion (SystemState) so tracking resumes
correctly across Railway redeploys without replaying old changes.

FIRST RUN:
  If no delta link is stored, the agent initialises the delta baseline
  (using ?token=latest — skips all existing files) and posts a confirmation
  to Slack. No change events are fired on first run.

SUBSEQUENT RUNS (every 30 min via Railway Cron or APScheduler):
  Returns only items changed since the last run.

Trigger manually: POST /alfred/agents/sharepoint-monitor
"""
from __future__ import annotations

import logging
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

_STATE_KEY = "sharepoint_delta_link"


async def run_sharepoint_monitor(
    sharepoint: Any | None,
    system_state: Any | None,
    slack_client: Any | None,
) -> str:
    """
    Run one SharePoint delta check cycle.

    Args:
        sharepoint:   SharePointBridge instance (None → no-op with log warning)
        system_state: SystemState instance for persisting the delta link
                      (None → delta link is not persisted; works but resets on restart)
        slack_client: Slack AsyncWebClient (None → log only, no Slack post)

    Returns:
        Summary string describing what happened (used by the trigger endpoint).
    """
    from sharepoint_bridge.delta_monitor import DeltaMonitor, format_slack_message

    if not sharepoint:
        return "SharePoint not configured — skipped."

    monitor = DeltaMonitor(sharepoint=sharepoint, folder=settings.sharepoint_monitor_folder)

    # Load stored delta link (None on first run)
    delta_link: str | None = None
    if system_state:
        delta_link = await system_state.get(_STATE_KEY)

    is_first_run = delta_link is None
    events, new_link = await monitor.poll(delta_link)

    if not new_link:
        # Delta link expired or SharePoint unreachable — reset next run
        if system_state:
            await system_state.set(_STATE_KEY, "")
        msg = "SharePoint delta link invalid or expired — reset for next run."
        logger.warning(msg)
        return msg

    # Persist the new delta link
    if system_state:
        await system_state.set(_STATE_KEY, new_link)

    # ── First run: just confirm initialisation ────────────────────────────────
    if is_first_run:
        init_msg = (
            ":white_check_mark: *SharePoint Monitor* initialised.\n"
            f"Watching `{settings.sharepoint_monitor_folder}` for changes.\n"
            "Future changes will appear here automatically."
        )
        await _post(slack_client, init_msg)
        logger.info("SharePoint monitor: baseline initialised (first run).")
        return "Initialised delta baseline — no events on first run."

    # ── Subsequent runs ────────────────────────────────────────────────────────
    if not events:
        logger.info("SharePoint monitor: no changes detected.")
        return "No changes detected."

    message = format_slack_message(events)
    await _post(slack_client, message)

    summary = f"{len(events)} change(s) across {len({e.matter for e in events})} matter(s)."
    logger.info("SharePoint monitor: %s", summary)
    return summary


async def _post(slack_client: Any | None, text: str) -> None:
    """Post a message to the configured SharePoint monitor channel."""
    channel = settings.sharepoint_monitor_channel
    if not channel:
        logger.info("SHAREPOINT_MONITOR_CHANNEL not set — logging only:\n%s", text)
        return
    if not slack_client:
        logger.info("Slack not configured — SharePoint monitor message:\n%s", text)
        return
    try:
        await slack_client.chat_postMessage(channel=channel, text=text)
        logger.info("SharePoint monitor: posted to %s", channel)
    except Exception as e:
        logger.warning("SharePoint monitor: Slack post failed (non-fatal): %s", e)
