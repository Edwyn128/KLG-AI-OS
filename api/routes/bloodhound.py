"""
api/routes/bloodhound.py — FastAPI routes for Bloodhound (surveillance engine).

Endpoints:
  POST /bloodhound/scan
      Run a feed scan across all RSS and CourtListener alerts,
      triage each new item using the Bloodhound LLM agent,
      write relevant cases to the Notion Watch List,
      and post summaries of tracked cases to Slack.
"""

from __future__ import annotations

import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from config import settings
from bloodhound.feed_ingestor import FeedIngestor
from bloodhound.agent import get_triage_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bloodhound", tags=["Bloodhound"])


# =============================================================================
# RESPONSES
# =============================================================================

class TrackedCaseSummary(BaseModel):
    case_name: str
    court: str
    tier: str
    issue_areas: list[str]
    nexus: str
    notion_url: str

class ScanResponse(BaseModel):
    status: str
    total_fetched: int
    new_signals: int
    added_count: int
    added_cases: list[TrackedCaseSummary] = Field(default_factory=list)
    skipped_count: int


# =============================================================================
# DEPENDENCIES
# =============================================================================

def get_deps(request: Request):
    """Retrieves the unified deps (containing bridge and watch_list) from app state."""
    return request.app.state.alfred_deps


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/scan", response_model=ScanResponse, summary="Scan external feeds and triage new signals")
async def run_surveillance_scan(
    request: Request,
    deps=Depends(get_deps),
) -> ScanResponse:
    """
    Run the Bloodhound surveillance scanning pipeline.

    This endpoint:
      1. Pulls currently tracked case URLs from the Notion Watch List (to prevent duplicates).
      2. Fetches RSS opinion feeds & CourtListener keyword alerts.
      3. Triages each new signal using the Claude-powered BloodhoundTriageAgent.
      4. Saves relevant cases directly to the Notion Watch List database.
      5. Posts a structured amicus/surveillance alert to the #case-management Slack channel.
    """
    logger.info("Bloodhound scan endpoint triggered.")

    try:
        # 1. Fetch existing tracked cases to get their URLs
        active_cases = await deps.watch_list.get_active_cases()
        known_urls = {c.get("url") or c.get("Source") or "" for c in active_cases}
        # Clean up URLs (extract raw URL if in description text)
        cleaned_urls = set()
        for url in known_urls:
            url_str = str(url).strip()
            # If the source text contains a link, parse it out or keep raw url
            if "http" in url_str:
                parts = url_str.split("http")
                actual_url = "http" + parts[1].split()[0]
                cleaned_urls.add(actual_url.strip("()[]<>,"))
            else:
                cleaned_urls.add(url_str)

        # 2. Initialize FeedIngestor with known URLs
        ingestor = FeedIngestor(known_urls=cleaned_urls)
        
        # 3. Fetch all feeds (RSS + CourtListener alerts)
        new_signals = await ingestor.run_daily_scan()
        await ingestor.close()

        added_cases = []
        skipped_count = 0

        # Slack client check
        slack_client = getattr(request.app.state, "slack_client", None)

        # 4. Triage each new signal
        for signal in new_signals:
            prompt = signal.to_triage_prompt()
            logger.info("Triaging signal: '%s'", signal.title[:50])

            try:
                # Run through the Pydantic AI agent
                result = await get_triage_agent().run(prompt)
                decision = result.data

                if decision.is_relevant:
                    logger.info("Signal relevant. Adding to Notion: '%s'", decision.case_name)

                    # Add case to Notion Watch List
                    notion_page = await deps.watch_list.add_case(
                        case_name=decision.case_name,
                        court=decision.court or signal.court or "Cal. Ct. App.",
                        issue_areas=decision.issue_areas,
                        tier=decision.suggested_tier,
                        source=signal.source_url,
                        docket_no=decision.docket_no or signal.docket_no,
                        procedural_posture=decision.procedural_posture or "Briefing",
                        klg_nexus_note=decision.klg_nexus_note,
                    )

                    notion_url = notion_page.get("url", "")

                    added_cases.append(TrackedCaseSummary(
                        case_name=decision.case_name,
                        court=decision.court,
                        tier=decision.suggested_tier,
                        issue_areas=decision.issue_areas,
                        nexus=decision.klg_nexus_note,
                        notion_url=notion_url
                    ))

                    # Post update to Slack
                    if slack_client and settings.slack_bot_token:
                        slack_message = (
                            f"🔍 *Bloodhound Surveillance Alert: New Case Tracked*\n"
                            f"• *Case*: {decision.case_name}\n"
                            f"• *Court*: {decision.court} | *Docket*: {decision.docket_no or 'N/A'}\n"
                            f"• *Tier*: {decision.suggested_tier} | *Issues*: {', '.join(decision.issue_areas)}\n"
                            f"• *KLG Nexus*: {decision.klg_nexus_note}\n"
                            f"• *Notion Link*: {notion_url}"
                        )
                        try:
                            await slack_client.chat_postMessage(
                                channel=settings.slack_case_management_channel,
                                text=slack_message,
                            )
                        except Exception as se:
                            logger.error("Failed to post Bloodhound case to Slack: %s", se)

                else:
                    logger.info("Signal skipped: '%s' (Reason: %s)", signal.title[:50], decision.reasoning)
                    skipped_count += 1

            except Exception as e:
                logger.error("Error triaging signal '%s': %s", signal.title[:50], e, exc_info=True)
                skipped_count += 1

        return ScanResponse(
            status="success",
            total_fetched=len(new_signals) + skipped_count, # raw estimate
            new_signals=len(new_signals),
            added_count=len(added_cases),
            added_cases=added_cases,
            skipped_count=skipped_count
        )

    except Exception as ex:
        logger.error("Bloodhound scan failed: %s", ex, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Bloodhound scan failed: {type(ex).__name__}: {ex}"
        )


# =============================================================================
# WATCH LIST READ ENDPOINT
# =============================================================================

def _normalize_watch_case(c: dict) -> dict:
    """Normalize a raw Notion Watch List page dict to a clean frontend shape."""
    issue_areas = c.get("Issue Area") or []
    if isinstance(issue_areas, str):
        issue_areas = [issue_areas] if issue_areas else []
    elif not isinstance(issue_areas, list):
        issue_areas = []

    next_deadline = c.get("Next Deadline")
    if isinstance(next_deadline, dict):
        next_deadline = next_deadline.get("start")

    return {
        "id": c.get("id", ""),
        "case_name": c.get("Case Name") or "",
        "court": c.get("Court") or "",
        "tier": c.get("Tier") or "",
        "issue_areas": [str(a) for a in issue_areas if a],
        "status": c.get("Status") or "Watching",
        "procedural_posture": c.get("Procedural Posture") or "",
        "next_deadline": str(next_deadline) if next_deadline else None,
        "nexus_note": c.get("KLG Nexus Note") or "",
        "docket_no": c.get("Docket No.") or "",
        "url": c.get("url") or "",
    }


@router.get("/watch-list", summary="Return the active Bloodhound Watch List")
async def get_watch_list(
    deps=Depends(get_deps),
    tier: str | None = None,
) -> dict:
    """
    Return all active (non-Closed) Watch List cases from Notion,
    optionally filtered by tier ("1", "2", or "3").

    Cases are sorted by tier then case name.
    """
    try:
        cases = await deps.watch_list.get_active_cases(tier=tier)
        normalized = [_normalize_watch_case(c) for c in cases]
        return {"count": len(normalized), "cases": normalized}
    except Exception as e:
        logger.error("get_watch_list error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred. Check server logs.")


# =============================================================================
# SCHEDULER-CALLABLE WRAPPER
# Imported by agents/scheduler.py for the daily cron job.
# Mirrors the endpoint logic but accepts deps directly instead of via Request.
# =============================================================================

async def run_bloodhound_scan(watch_list: Any, slack_client: Any | None = None) -> None:
    """
    Standalone scan pipeline callable by APScheduler.

    Same logic as the POST /bloodhound/scan endpoint but takes dependencies
    directly so the scheduler doesn't need a FastAPI Request object.
    """
    from bloodhound.feed_ingestor import FeedIngestor
    from bloodhound.agent import get_triage_agent

    logger.info("Bloodhound scheduled scan starting...")

    try:
        active_cases = await watch_list.get_active_cases()
        known_urls: set[str] = set()
        for c in active_cases:
            src = str(c.get("Source") or c.get("url") or "").strip()
            if "http" in src:
                parts = src.split("http")
                known_urls.add(("http" + parts[1].split()[0]).strip("()[]<>,"))

        ingestor = FeedIngestor(known_urls=known_urls)
        new_signals = await ingestor.run_daily_scan()
        await ingestor.close()

        added: list[dict] = []
        for signal in new_signals:
            try:
                result = await get_triage_agent().run(signal.to_triage_prompt())
                decision = result.data
                if not decision.is_relevant:
                    continue
                notion_page = await watch_list.add_case(
                    case_name=decision.case_name,
                    court=decision.court or signal.court or "",
                    issue_areas=decision.issue_areas,
                    tier=decision.suggested_tier,
                    source=signal.source_url,
                    docket_no=decision.docket_no or signal.docket_no,
                    procedural_posture=decision.procedural_posture or "Briefing",
                    klg_nexus_note=decision.klg_nexus_note,
                )
                added.append({"case_name": decision.case_name, "url": notion_page.get("url", "")})
                if slack_client and settings.slack_bot_token:
                    await slack_client.chat_postMessage(
                        channel=settings.slack_case_management_channel,
                        text=(
                            f"🐕 *Bloodhound Daily Scan — New case added*\n"
                            f"• *{decision.case_name}* ({decision.court}) — Tier {decision.suggested_tier}\n"
                            f"• {decision.klg_nexus_note}\n"
                            f"• {notion_page.get('url', '')}"
                        ),
                    )
            except Exception as e:
                logger.error("Triage error for '%s': %s", signal.title[:50], e)

        logger.info("Scheduled scan complete: %d cases added.", len(added))

    except Exception as e:
        logger.error("Scheduled Bloodhound scan failed: %s", e, exc_info=True)
