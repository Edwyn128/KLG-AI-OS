"""
notion_bridge/watch_list.py — Read and write Bloodhound's Watch List database.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The Watch List database is Bloodhound's primary output store. Every case that
Bloodhound detects and decides is worth tracking gets one row here.

DATABASE SCHEMA (as designed in the Bloodhound architecture doc):

  Property          Type          Notes
  ──────────────────────────────────────────────────────────────────────────
  Case Name         title         e.g., "HB v. California"
  Court             select        e.g., "9th Cir.", "Cal. Ct. App.", "SCOTUS"
  Docket No.        rich_text     e.g., "23-1234"
  Issue Area        multi_select  e.g., ["First Amendment", "Public Employee Speech"]
  Tier              select        "1", "2", or "3" (signal importance)
  Source            rich_text     Where Bloodhound found this (RSS URL, org name)
  Procedural Posture select       e.g., "Briefing", "Argued", "Decided"
  Next Deadline     date          Next known filing or argument date
  KLG Nexus Note   rich_text     Why this matters to KLG specifically
  Status            select        "Watching", "Engaged", "Closed"

TIER DEFINITIONS:
  Tier 1 — Highest priority. Issues KLG has litigated or core to the firm's
            practice. These stay on the list permanently (never auto-closed).
  Tier 2 — Medium. Doctrines adjacent to KLG's practice that warrant monitoring.
  Tier 3 — Ambient. Broadly relevant but low immediate priority.
"""

from __future__ import annotations

import logging
from typing import Any

from notion_bridge.client import NotionBridge
from config import settings

logger = logging.getLogger(__name__)

# Valid tier values — enforced so Bloodhound can't accidentally create a Tier 4
VALID_TIERS = {"1", "2", "3"}

# Valid status values matching the Notion select options
VALID_STATUSES = {"Watching", "Engaged", "Closed"}


class WatchList:
    """
    High-level interface for Bloodhound's Watch List Notion database.

    Bloodhound's feed ingestor calls add_case() when it detects a new case.
    The triage logic calls update_case_status() when a case's importance changes.
    Alfred calls get_tier_one_cases() during case assessments ("what does
    Bloodhound know about this doctrine?").
    """

    def __init__(self, bridge: NotionBridge) -> None:
        """
        Args:
            bridge: Initialized NotionBridge. Injected so tests can mock it.
        """
        self._bridge = bridge

    async def add_case(
        self,
        case_name: str,
        court: str,
        issue_areas: list[str],
        tier: str,
        source: str,
        docket_no: str = "",
        procedural_posture: str = "",
        klg_nexus_note: str = "",
    ) -> dict[str, Any]:
        """
        Add a new case to the Watch List.

        Called by Bloodhound's feed ingestor after triage determines a detected
        case is worth tracking. Returns the created page dict so the caller
        can confirm the row was created and log the Notion URL.

        Args:
            case_name:          The case name as it will appear in Notion.
                                Use the official caption format: "Party A v. Party B"
            court:              The court string matching an existing select option.
                                Must match exactly — Notion rejects unknown options.
                                Common values: "9th Cir.", "Cal. Ct. App. (1st)",
                                "Cal. Ct. App. (4th)", "SCOTUS", "N.D. Cal."
            issue_areas:        List of doctrinal issues this case touches.
                                Each string must match an existing multi_select option.
            tier:               Signal importance tier: "1", "2", or "3".
                                Tier 1 = core KLG issue, Tier 3 = ambient monitor.
            source:             Where Bloodhound found this case. Include enough
                                detail to re-find the source later:
                                  "PLF press release — https://pacificlegal.org/..."
                                  "CourtListener RECAP — docket search 'supersedeas'"
            docket_no:          Court docket number. Empty string if unknown.
            procedural_posture: Current stage of the case. Examples:
                                "Briefing", "Argued", "Decided", "Cert. pending"
            klg_nexus_note:     WHY this case matters to KLG specifically.
                                This is the most important field for Alfred to
                                use when surfacing this case during matter planning.

        Returns:
            The newly created Notion page as a flat dict.

        Raises:
            ValueError: If tier or any required string is empty.
        """
        if tier not in VALID_TIERS:
            raise ValueError(
                f"Invalid tier '{tier}'. Must be one of: {VALID_TIERS}. "
                "Tier 1 = core KLG issue, Tier 2 = adjacent doctrine, "
                "Tier 3 = ambient monitor."
            )

        if not case_name.strip():
            raise ValueError("case_name cannot be empty.")

        # Build the Notion property payload in the API's expected format.
        # Each property type has its own structure — this is why we have
        # extract_property() in the other direction.
        properties: dict[str, Any] = {
            "Case Name": {
                "title": [{"text": {"content": case_name}}]
            },
            "Court": {
                "select": {"name": court}
            },
            "Issue Area": {
                "multi_select": [{"name": area} for area in issue_areas]
            },
            "Tier": {
                "select": {"name": tier}
            },
            "Status": {
                "select": {"name": "Watching"}  # All new cases start as Watching
            },
        }

        # Only add optional fields if they have content — sending empty rich_text
        # is harmless but clutters the Notion page
        if docket_no:
            properties["Docket No."] = {
                "rich_text": [{"text": {"content": docket_no}}]
            }
        if procedural_posture:
            properties["Procedural Posture"] = {
                "select": {"name": procedural_posture}
            }
        if source:
            properties["Source"] = {
                "rich_text": [{"text": {"content": source}}]
            }
        if klg_nexus_note:
            properties["KLG Nexus Note"] = {
                "rich_text": [{"text": {"content": klg_nexus_note}}]
            }

        page = await self._bridge.create_page(
            database_id=settings.notion_watch_list_db_id,
            properties=properties,
        )

        logger.info(
            "WatchList.add_case: Added '%s' (Tier %s, %s) → %s",
            case_name,
            tier,
            court,
            page.get("url", ""),
        )
        return page

    async def get_tier_one_cases(self) -> list[dict[str, Any]]:
        """
        Return all Tier 1 cases currently on the Watch List.

        Alfred calls this during case assessment to answer: "What does Bloodhound
        know about this doctrine?" Tier 1 cases represent the firm's most important
        ongoing surveillance targets — core issues KLG has litigated.

        Returns:
            List of Watch List rows (flat dicts) where Tier = "1".
            Sorted alphabetically by case name for readability.
        """
        cases = await self._bridge.query_database(
            database_id=settings.notion_watch_list_db_id,
            filter={
                "and": [
                    {"property": "Tier", "select": {"equals": "1"}},
                    {"property": "Status", "select": {"does_not_equal": "Closed"}},
                ]
            },
        )
        cases.sort(key=lambda c: c.get("Case Name") or "")
        return cases

    async def get_active_cases(self, tier: str | None = None) -> list[dict[str, Any]]:
        """
        Return all active (non-Closed) Watch List cases, optionally filtered by tier.

        Used by the weekly Bloodhound deep-review cadence to produce the
        triage digest — a list of everything currently being tracked for
        Tim to review and re-prioritize.

        Args:
            tier: If provided, return only cases of this tier ("1", "2", or "3").
                  If None, return all tiers.

        Returns:
            List of active Watch List cases.
        """
        base_filter: dict[str, Any] = {
            "property": "Status",
            "select": {"does_not_equal": "Closed"},
        }

        if tier:
            combined_filter = {
                "and": [
                    base_filter,
                    {"property": "Tier", "select": {"equals": tier}},
                ]
            }
        else:
            combined_filter = base_filter

        cases = await self._bridge.query_database(
            database_id=settings.notion_watch_list_db_id,
            filter=combined_filter,
        )
        cases.sort(key=lambda c: (c.get("Tier") or "9", c.get("Case Name") or ""))
        return cases

    async def update_case_status(
        self,
        page_id: str,
        new_status: str,
        update_note: str = "",
    ) -> None:
        """
        Update a Watch List case's status and optionally add a note.

        Status transitions:
          Watching  → Engaged   (KLG is actively involved — amicus, client, etc.)
          Watching  → Closed    (Case resolved or no longer relevant)
          Engaged   → Closed    (Matter concluded)

        Args:
            page_id:     Notion page ID of the Watch List row.
            new_status:  New status value. Must be "Watching", "Engaged", or "Closed".
            update_note: Optional note to append to the page explaining why the
                         status changed. Becomes part of the audit trail.
        """
        if new_status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{new_status}'. Must be one of: {VALID_STATUSES}"
            )

        await self._bridge.update_page(
            page_id=page_id,
            properties={"Status": {"select": {"name": new_status}}},
        )

        if update_note:
            await self._bridge.append_block(page_id, update_note)

        logger.info("WatchList case %s status → '%s'", page_id[:8], new_status)
