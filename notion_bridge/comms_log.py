"""
notion_bridge/comms_log.py — Interface to the KLG Comms Log database.

The Comms Log is a Notion database where every email sent to
CaseFile@KowalLawGroup.com or Events@KowalLawGroup.com lands automatically
(forwarded via notionsender.com). Each row represents one communication:
an email, call note, or meeting note.

Alfred reads this to:
  - Surface unprocessed communications that need a response (Actions = Respond)
  - Pull the email thread for a specific matter (via Projects relation)
  - Show pinned / high-priority items
  - Give Tim a morning brief of what came in overnight

Alfred writes to this to:
  - Mark a communication as Done after the team handles it
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings
from notion_bridge.client import NotionBridge

logger = logging.getLogger(__name__)


class CommsLog:
    """
    High-level interface to the KLG Comms Log Notion database.

    Instantiated once at startup and injected into AlfredDependencies.
    All read operations return flat dicts (same format as NotionBridge.query_database).
    """

    def __init__(self, bridge: NotionBridge) -> None:
        self._bridge = bridge
        self._db_id = settings.notion_comms_log_db_id

    # ─────────────────────────────────────────────────────────────────────────
    # READ OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────

    async def get_pending(self) -> list[dict[str, Any]]:
        """
        Return all communications with Actions = 'Respond' — items the team
        still needs to reply to or act on.

        Sorted newest first so the most recent unresponded comms surface first.
        """
        if not self._db_id:
            return []

        return await self._bridge.query_database(
            database_id=self._db_id,
            filter={"property": "Actions", "select": {"equals": "Respond"}},
            sorts=[{"property": "Created", "direction": "descending"}],
        )

    async def get_recent(self, days: int = 7) -> list[dict[str, Any]]:
        """
        Return all communications created in the last N days, newest first.

        Used for morning briefings: "Alfred, what came in this week?"
        """
        if not self._db_id:
            return []

        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        return await self._bridge.query_database(
            database_id=self._db_id,
            filter={
                "property": "Created",
                "created_time": {"on_or_after": since},
            },
            sorts=[{"property": "Created", "direction": "descending"}],
        )

    async def get_for_matter(self, project_page_id: str) -> list[dict[str, Any]]:
        """
        Return all communications linked to a specific matter project page
        via the Projects relation.

        Args:
            project_page_id: The Notion page ID of the matter's project page.

        Returns:
            List of comms for that matter, newest first.
        """
        if not self._db_id:
            return []

        return await self._bridge.query_database(
            database_id=self._db_id,
            filter={
                "property": "Projects",
                "relation": {"contains": project_page_id},
            },
            sorts=[{"property": "Created", "direction": "descending"}],
        )

    async def get_pinned(self) -> list[dict[str, Any]]:
        """
        Return all pinned communications (Pin = true).

        The team uses Pin to flag items that need to stay visible
        regardless of triage status.
        """
        if not self._db_id:
            return []

        return await self._bridge.query_database(
            database_id=self._db_id,
            filter={"property": "Pin", "checkbox": {"equals": True}},
            sorts=[{"property": "Created", "direction": "descending"}],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # WRITE OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────

    async def mark_done(self, page_id: str) -> None:
        """
        Set a communication's Actions field to 'Done'.

        Called by Alfred after the team confirms they've handled a comm.
        """
        await self._bridge.update_page(
            page_id=page_id,
            properties={"Actions": {"select": {"name": "Done"}}},
        )
        logger.info("CommsLog: marked comm %s as Done", page_id[:8])

    async def add_note(self, page_id: str, note: str) -> None:
        """
        Append a note to a communication's Notes field.

        Used by Alfred to record what action was taken or what the comm means
        for a matter, without overwriting any existing notes.
        """
        existing = await self._bridge.get_page(page_id)
        current_notes = existing.get("Notes", "") or ""
        separator = "\n\n" if current_notes else ""
        updated = f"{current_notes}{separator}{note}"

        await self._bridge.update_page(
            page_id=page_id,
            properties={
                "Notes": {"rich_text": [{"text": {"content": updated[:2000]}}]}
            },
        )

    async def log_interaction(
        self,
        user: str,
        agent: str,
        message: str,
        response: str,
        tools_used: list[str],
        model: str = "",
    ) -> None:
        """Log an Alfred/Bloodhound chat interaction to the Comms Log DB."""
        if not self._db_id:
            return
        tools_str = ", ".join(tools_used) if tools_used else "none"
        title = f"Alfred chat — {user}"
        try:
            await self._bridge.create_page(
                database_id=self._db_id,
                properties={
                    "Name": {"title": [{"text": {"content": title}}]},
                    "Email Text": {"rich_text": [{"text": {"content": message[:2000]}}]},
                    "Summary": {"rich_text": [{"text": {"content": response[:2000]}}]},
                    "Notes": {"rich_text": [{"text": {"content": f"Tools: {tools_str} | Model: {model} | Agent: {agent}"}}]},
                    "Actions": {"select": {"name": "N/A"}},
                },
            )
        except Exception as e:
            logger.warning("CommsLog.log_interaction failed (non-fatal): %s", e)
