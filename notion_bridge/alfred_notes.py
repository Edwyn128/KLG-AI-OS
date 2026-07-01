"""
notion_bridge/alfred_notes.py — Alfred's persistent cross-session memory layer.

Alfred Notes is a Notion database where Alfred stores facts he discovers across
conversations: matter-specific observations, attorney preferences, opposing counsel
behavior patterns, and ambient firm knowledge.

Unlike conversation history (in-session only), Alfred Notes persists indefinitely
and surfaces in every future conversation as additional context.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NOTION DATABASE SCHEMA (create once in Notion UI)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Database name: Alfred Notes

Properties:
  Name (title)        — short label for the note, e.g. "Tim: prefers firm deadlines"
  Category (select)   — Preference | Matter | OppCounsel | Deadline | FirmKnowledge | Other
  Matter (text)       — matter name this note relates to (blank = firm-wide)
  Body (rich_text)    — full note content (up to 2000 chars)
  Recorded By (text)  — who triggered the save ("Alfred" or user name)
  Active (checkbox)   — true by default; set false to retire a note without deleting it

Set env var NOTION_ALFRED_NOTES_DB_ID to the database ID once created.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import logging
from typing import Any

from config import settings
from notion_bridge.client import NotionBridge

logger = logging.getLogger(__name__)

# Valid categories — enforced client-side; Notion will reject unknowns on create.
VALID_CATEGORIES = {"Preference", "Matter", "OppCounsel", "Deadline", "FirmKnowledge", "Other"}


class AlfredNotes:
    """
    High-level interface to the Alfred Notes Notion database.

    Injected into AlfredDependencies when NOTION_ALFRED_NOTES_DB_ID is set.
    """

    def __init__(self, bridge: NotionBridge) -> None:
        self._bridge = bridge
        self._db_id = settings.notion_alfred_notes_db_id

    # ─────────────────────────────────────────────────────────────────────────
    # WRITE
    # ─────────────────────────────────────────────────────────────────────────

    async def save(
        self,
        label: str,
        body: str,
        category: str = "Other",
        matter: str = "",
        recorded_by: str = "Alfred",
    ) -> str:
        """
        Save a note to the Alfred Notes database.

        Returns the Notion page ID of the created note, or "" on failure.
        """
        if not self._db_id:
            logger.warning("AlfredNotes.save: NOTION_ALFRED_NOTES_DB_ID not set")
            return ""

        if category not in VALID_CATEGORIES:
            category = "Other"

        try:
            page = await self._bridge.create_page(
                database_id=self._db_id,
                properties={
                    "Name": {"title": [{"text": {"content": label[:200]}}]},
                    "Category": {"select": {"name": category}},
                    "Matter": {"rich_text": [{"text": {"content": matter[:200]}}]},
                    "Body": {"rich_text": [{"text": {"content": body[:2000]}}]},
                    "Recorded By": {"rich_text": [{"text": {"content": recorded_by[:100]}}]},
                    "Active": {"checkbox": True},
                },
            )
            page_id = page.get("id", "")
            logger.info(
                "AlfredNotes.save: created note '%s' [%s] for matter='%s' (page %s)",
                label[:60], category, matter[:40], page_id[:8],
            )
            return page_id
        except Exception as e:
            logger.warning("AlfredNotes.save failed (non-fatal): %s", e)
            return ""

    async def retire(self, page_id: str) -> None:
        """Mark a note inactive (soft-delete) without removing it from Notion."""
        if not self._db_id:
            return
        try:
            await self._bridge.update_page(
                page_id=page_id,
                properties={"Active": {"checkbox": False}},
            )
        except Exception as e:
            logger.warning("AlfredNotes.retire failed (non-fatal): %s", e)

    # ─────────────────────────────────────────────────────────────────────────
    # READ
    # ─────────────────────────────────────────────────────────────────────────

    async def recall(
        self,
        matter: str = "",
        category: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Retrieve active notes, optionally filtered by matter and/or category.

        Args:
            matter:   Matter name to filter on (substring match — done client-side).
            category: Category to filter on (exact match — server-side filter).
            limit:    Max notes to return.

        Returns:
            List of note dicts: {id, label, body, category, matter, recorded_by}
        """
        if not self._db_id:
            return []

        notion_filter: dict[str, Any] = {"property": "Active", "checkbox": {"equals": True}}

        if category and category in VALID_CATEGORIES:
            notion_filter = {
                "and": [
                    notion_filter,
                    {"property": "Category", "select": {"equals": category}},
                ]
            }

        try:
            raw = await self._bridge.query_database(
                database_id=self._db_id,
                filter=notion_filter,
                sorts=[{"timestamp": "created_time", "direction": "descending"}],
                page_size=min(limit * 3, 100),
            )
        except Exception as e:
            logger.warning("AlfredNotes.recall failed (non-fatal): %s", e)
            return []

        notes = []
        for item in raw:
            note_matter = item.get("Matter", "")
            if matter and matter.lower() not in (note_matter or "").lower():
                continue
            notes.append({
                "id": item.get("id", ""),
                "label": item.get("Name", ""),
                "body": item.get("Body", ""),
                "category": item.get("Category", "Other"),
                "matter": note_matter,
                "recorded_by": item.get("Recorded By", "Alfred"),
                "created_time": item.get("created_time", ""),
            })
            if len(notes) >= limit:
                break

        return notes

    async def recall_for_context(self, matter: str = "", limit: int = 10) -> str:
        """
        Return a formatted string of notes ready to inject as Alfred context.

        The string is intentionally short — it goes into every Alfred system
        prompt for relevant matters, so brevity matters more than completeness.
        """
        notes = await self.recall(matter=matter, limit=limit)
        if not notes:
            return ""

        lines = ["**Alfred Notes (persistent memory):**"]
        for n in notes:
            scope = f" [{n['matter']}]" if n["matter"] else " [firm-wide]"
            lines.append(f"• [{n['category']}{scope}] {n['label']}: {n['body']}")
        return "\n".join(lines)
