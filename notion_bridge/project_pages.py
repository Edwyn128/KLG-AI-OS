"""
notion_bridge/project_pages.py — Read and write KLG Layer 1 project pages.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This module provides high-level functions for working with KLG's matter project
pages — the Layer 1 Notion database that holds the firm's active matters.

While client.py provides generic Notion API primitives (get_page, query_database,
etc.), THIS module knows about KLG's specific database schema:

  - What properties exist on a project page (Status, Priority, Target Date, etc.)
  - How to format a matter summary for Alfred to reason over
  - How to query for matters with upcoming deadlines (used by deadline-watch agent)
  - How to write back a skill update note to a matter page

SEPARATION OF CONCERNS:
  client.py   → generic Notion API operations (knows nothing about KLG)
  project_pages.py → KLG-specific matter logic (knows the schema)
  alfred/     → AI reasoning and skill execution (calls this module)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    from notion_bridge.project_pages import ProjectPages
    from notion_bridge import NotionBridge

    bridge = NotionBridge()
    pages = ProjectPages(bridge)

    # Alfred answering "What's pending on Petersen?"
    matter = await pages.find_matter("Petersen")
    summary = await pages.get_matter_summary(matter["id"])

    # Deadline-watch agent getting all matters with deadlines this week
    urgent = await pages.get_matters_with_upcoming_deadlines(days=7)

    # Skill writing back after completing work
    await pages.log_skill_action(matter["id"], "klg-brief-elevation", "Filed brief.")
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from notion_bridge.client import NotionBridge
from config import settings

logger = logging.getLogger(__name__)


class ProjectPages:
    """
    High-level interface for KLG's matter project pages (Layer 1 database).

    Every method in this class corresponds to a real workflow need:
      - Alfred skills call find_matter() and get_matter_summary() to understand case state
      - The deadline-watch agent calls get_matters_with_upcoming_deadlines()
      - Skills call log_skill_action() to leave an audit trail after completing work
      - Skills call update_matter_status() to move a matter forward in the pipeline

    Args:
        bridge: An initialized NotionBridge instance. We accept it as a
                constructor argument (dependency injection) rather than creating
                it internally so tests can pass a mock bridge without hitting
                the real Notion API.
    """

    def __init__(self, bridge: NotionBridge) -> None:
        self._bridge = bridge

    async def find_matter(self, name: str) -> dict[str, Any] | None:
        """
        Find a matter project page by searching for its name.

        This is the most common entry point for Alfred skills. When Tim says
        "Alfred, what's pending on Petersen?", Alfred calls this with "Petersen"
        to locate the project page before reading its state.

        SEARCH STRATEGY:
            We use Notion's full-text search first (fast, handles partial matches).
            If that returns multiple results (e.g., searching "Smith" when there
            are three Smith matters), we return the most recently edited one and
            log a warning so the caller knows to be more specific.

        Args:
            name: The matter name or a fragment of it. Case-insensitive.

        Returns:
            A flat dict of the matter's properties (from page_to_dict), or
            None if no matching matter is found.
        """
        results = await self._bridge.search(name, filter_type="page")

        if not results:
            logger.info("find_matter('%s'): no results found", name)
            return None

        if len(results) > 1:
            logger.warning(
                "find_matter('%s'): %d results found, returning most recently edited. "
                "Consider using a more specific name.",
                name,
                len(results),
            )

        # Results are sorted by relevance by Notion's search engine.
        # Take the first one (most relevant match).
        return results[0]

    async def get_matter_summary(self, page_id: str) -> str:
        """
        Get a complete text summary of a matter for Alfred to reason over.

        This combines the structured properties (status, deadlines, priority)
        with the free-text body content (case notes, current theory) into a
        single string that Alfred can include in its context window.

        WHY WE COMBINE BOTH:
            Properties give the structured state (Status = "In progress",
            Target Date = "2026-06-30"). The page body often has rich context
            that doesn't fit in a structured field — current legal theory,
            last action taken, open questions. Alfred needs both to give
            Tim a useful answer.

        Args:
            page_id: The Notion page ID of the matter.

        Returns:
            A multi-section text string with properties and body content.
            Safe to paste directly into an AI prompt as context.
        """
        # Fetch both the structured properties and the block content in parallel.
        # asyncio.gather() runs both API calls concurrently — saves ~500ms per query.
        import asyncio
        props_dict, body_text = await asyncio.gather(
            self._bridge.get_page(page_id),
            self._bridge.get_page_content(page_id),
        )

        name        = props_dict.get("Project name", "Unknown")
        status      = props_dict.get("Status", "N/A")
        priority    = props_dict.get("Priority", "N/A")
        category    = props_dict.get("Category", "N/A")
        case_stage  = props_dict.get("Case Stage") or "N/A"
        assignees   = props_dict.get("Assignee") or []
        target_date = props_dict.get("date:Target Date:start") or props_dict.get("Target Date") or "N/A"
        court_date  = props_dict.get("Next Court Deadline") or None
        court_info  = props_dict.get("Next Deadline Info") or ""
        completion  = props_dict.get("Completion")
        blocking    = props_dict.get("Is Blocking") or []
        blocked_by  = props_dict.get("Blocked By") or []

        # Days-remaining helper for court deadline
        def _days_label(d: str) -> str:
            try:
                delta = (date.fromisoformat(d[:10]) - date.today()).days
                if delta < 0:    return f"{d[:10]} (OVERDUE by {abs(delta)} days)"
                if delta == 0:   return f"{d[:10]} (TODAY)"
                if delta == 1:   return f"{d[:10]} (TOMORROW)"
                return f"{d[:10]} ({delta} days away)"
            except ValueError:
                return d

        lines = [
            f"=== MATTER: {name} ===",
            f"Status:               {status}",
            f"Priority:             {priority}",
            f"Case Stage:           {case_stage}",
            f"Category:             {category}",
            f"Assignee:             {', '.join(assignees) if assignees else 'Unassigned'}",
            f"Target Date:          {target_date}",
            f"Next Court Deadline:  {_days_label(court_date) if court_date else 'None set'}",
        ]

        if court_info and court_info != "No upcoming court deadline":
            lines.append(f"Deadline Info:        {court_info}")

        if completion is not None:
            lines.append(f"Completion:           {int(completion)}%" if isinstance(completion, (int, float)) else f"Completion:           N/A")

        if blocking:
            lines.append(f"Is Blocking:          {len(blocking)} related matter(s)")
        if blocked_by:
            lines.append(f"Blocked By:           {len(blocked_by)} matter(s)")

        lines += [
            f"Notion URL:           {props_dict.get('url', 'N/A')}",
            f"Last Edited:          {props_dict.get('last_edited_time', 'N/A')}",
        ]

        summary_prop = props_dict.get("Summary")
        if summary_prop:
            lines.append(f"\nSummary:\n{summary_prop}")

        if body_text.strip():
            lines.append(f"\nPage Content:\n{body_text}")
        else:
            lines.append("\n(No page body content — properties only)")

        return "\n".join(lines)

    # ── KLG Project Categories ────────────────────────────────────────────────
    # The Projects database mixes four types of work. Callers should pass the
    # relevant category (or None to get everything).
    #
    #   "Case Project"  — active client legal matters (court deadlines matter)
    #   "Case Support"  — research, briefs, support tasks tied to case projects
    #   "Operations"    — firm admin, potential clients, networking, business dev
    #   "Think Tank"    — CALP podcast episodes, amicus briefs, scholarship
    #
    CATEGORY_CASE_PROJECT = "Case Project"
    CATEGORY_CASE_SUPPORT = "Case Support"
    CATEGORY_OPERATIONS   = "Operations"
    CATEGORY_THINK_TANK   = "Think Tank"

    async def get_matters_with_upcoming_deadlines(
        self,
        days: int = 7,
        category: str | None = "Case Project",
    ) -> list[dict[str, Any]]:
        """
        Query the Projects database for matters with deadlines in the next N days.

        This is the primary data source for the daily deadline-watch background
        agent. It returns all matters where Target Date falls between today
        and today + N days, sorted by deadline (soonest first).

        Args:
            days:     Number of days ahead to look. Default 7 (one week).
            category: Filter by project category. Defaults to "Case Project"
                      (actual client matters). Pass None to include all types.

        Returns:
            List of matter dicts sorted by Target Date ascending (soonest first).
        """
        today = date.today().isoformat()
        cutoff = (date.today() + timedelta(days=days)).isoformat()

        # Run two queries and merge — one for Target Date, one for Next Court
        # Deadline. The pinned Notion API version (2022-06-28) doesn't support
        # deep compound filter nesting, so we keep each query simple.
        import asyncio

        not_done = {
            "or": [
                {"property": "Status", "status": {"equals": "In progress"}},
                {"property": "Status", "status": {"equals": "Planning"}},
                {"property": "Status", "status": {"equals": "Paused"}},
            ]
        }
        category_clause = (
            [{"property": "Category", "select": {"equals": category}}]
            if category else []
        )

        def _build(date_prop: str) -> dict:
            return {"and": [
                {"property": date_prop, "date": {"on_or_after": today}},
                {"property": date_prop, "date": {"on_or_before": cutoff}},
                not_done,
                *category_clause,
            ]}

        results_by_target, results_by_court = await asyncio.gather(
            self._bridge.query_database(
                database_id=settings.notion_projects_db_id,
                filter=_build("Target Date"),
                sorts=[{"property": "Target Date", "direction": "ascending"}],
            ),
            self._bridge.query_database(
                database_id=settings.notion_projects_db_id,
                filter=_build("Next Court Deadline"),
                sorts=[{"property": "Next Court Deadline", "direction": "ascending"}],
            ),
        )

        # Deduplicate by page ID, preserve earliest-deadline order
        seen: set[str] = set()
        combined: list[dict] = []
        for m in results_by_target + results_by_court:
            if m["id"] not in seen:
                seen.add(m["id"])
                combined.append(m)

        # Sort by the earliest of the two deadline fields
        def _earliest(m: dict) -> str:
            td = m.get("Target Date") or "9999-12-31"
            cd = m.get("Next Court Deadline") or "9999-12-31"
            return min(str(td)[:10], str(cd)[:10])

        combined.sort(key=_earliest)

        logger.info(
            "get_matters_with_upcoming_deadlines(days=%d, category=%s): found %d (target=%d, court=%d)",
            days, category, len(combined), len(results_by_target), len(results_by_court),
        )
        return combined

    async def get_all_active_matters(
        self,
        category: str | None = "Case Project",
    ) -> list[dict[str, Any]]:
        """
        Return all matters currently in an active status.

        Args:
            category: Filter by project category. Defaults to "Case Project"
                      (actual client legal matters). Pass None for all types.
                      Use the CATEGORY_* class constants for valid values.

        Returns:
            List of active matter dicts sorted by Priority descending.
        """
        conditions: list[dict] = [
            {
                "or": [
                    {"property": "Status", "status": {"equals": "In progress"}},
                    {"property": "Status", "status": {"equals": "Planning"}},
                    {"property": "Status", "status": {"equals": "Paused"}},
                ]
            }
        ]
        if category:
            conditions.append(
                {"property": "Category", "select": {"equals": category}}
            )

        db_filter = {"and": conditions} if len(conditions) > 1 else conditions[0]

        return await self._bridge.query_database(
            database_id=settings.notion_projects_db_id,
            filter=db_filter,
            sorts=[{"property": "Priority", "direction": "descending"}],
        )

    async def update_matter_status(self, page_id: str, new_status: str) -> None:
        """
        Update the Status property of a matter project page.

        Skills call this as part of Step 4 of the skill lifecycle (Update Layer 1)
        when a matter moves to a new stage — e.g., from "In progress" to
        "Review needed" after Alfred drafts a document.

        Args:
            page_id:    The matter's Notion page ID.
            new_status: The new status value. Must match an existing option in
                        the Status select property (Notion rejects unknown values).
                        Common values: "In progress", "Review needed", "Done",
                        "Blocked", "Archived".
        """
        await self._bridge.update_page(
            page_id=page_id,
            properties={
                "Status": {"status": {"name": new_status}}
            },
        )
        logger.info("Matter %s status → '%s'", page_id[:8], new_status)

    async def log_skill_action(
        self,
        page_id: str,
        skill_name: str,
        action_summary: str,
    ) -> None:
        """
        Append a timestamped skill execution note to a matter's page body.

        Every time a skill completes Step 4 (Update Layer 1), it calls this to
        leave an audit trail. This answers the question "what has Alfred done
        on this matter?" without cluttering the structured properties.

        The note format is:
            [2026-05-11 14:32 UTC] klg-brief-elevation: Brief filed. Awaiting court confirmation.

        Args:
            page_id:        The matter page to append to.
            skill_name:     The name of the skill that ran (e.g., "klg-brief-elevation").
            action_summary: A one-sentence description of what the skill did.
        """
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        note = f"[{timestamp}] {skill_name}: {action_summary}"

        await self._bridge.append_block(page_id, note)
        logger.info("Logged skill action to matter %s: %s", page_id[:8], note)
