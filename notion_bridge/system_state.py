"""
notion_bridge/system_state.py — Lightweight KV store backed by Notion.

Persists system-level tokens and state that must survive Railway redeploys.
Currently used by the SharePoint delta monitor to store its delta link so
change tracking resumes correctly after a deploy rather than re-scanning.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTION DATABASE SCHEMA (create once in Notion UI)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Database name: KLG System State

Properties:
  Name  (title)      — key string, e.g. "sharepoint_delta_link"
  Value (rich_text)  — stored value (up to 2000 chars)

Set env var NOTION_SYSTEM_STATE_DB_ID to the database ID once created.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import logging

from config import settings
from notion_bridge.client import NotionBridge

logger = logging.getLogger(__name__)


class SystemState:
    """
    Thin KV wrapper over a Notion database.

    get(key)        → str | None
    set(key, value) → None   (creates or updates the row)

    All operations are best-effort: failures log a warning and return
    gracefully so a misconfigured DB never takes down the app.
    """

    def __init__(self, bridge: NotionBridge) -> None:
        self._bridge = bridge
        self._db_id = settings.notion_system_state_db_id

    async def get(self, key: str) -> str | None:
        """Return the stored value for key, or None if not found."""
        if not self._db_id:
            return None
        try:
            rows = await self._bridge.query_database(
                database_id=self._db_id,
                filter={"property": "Name", "title": {"equals": key}},
                page_size=1,
            )
            if rows:
                return rows[0].get("Value") or None
        except Exception as e:
            logger.warning("SystemState.get(%r) failed (non-fatal): %s", key, e)
        return None

    async def set(self, key: str, value: str) -> None:
        """Create or update the row for key with the given value."""
        if not self._db_id:
            return
        try:
            # Check whether the row already exists so we can update vs. create.
            rows = await self._bridge.query_database(
                database_id=self._db_id,
                filter={"property": "Name", "title": {"equals": key}},
                page_size=1,
            )
            props = {
                "Value": {"rich_text": [{"text": {"content": value[:2000]}}]},
            }
            if rows:
                page_id = rows[0].get("id", "")
                if page_id:
                    await self._bridge.update_page(page_id=page_id, properties=props)
                    logger.debug("SystemState.set: updated key=%r", key)
                    return
            # Row doesn't exist — create it.
            await self._bridge.create_page(
                database_id=self._db_id,
                properties={
                    "Name": {"title": [{"text": {"content": key[:200]}}]},
                    **props,
                },
            )
            logger.debug("SystemState.set: created key=%r", key)
        except Exception as e:
            logger.warning("SystemState.set(%r) failed (non-fatal): %s", key, e)
