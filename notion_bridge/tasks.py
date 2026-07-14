"""
notion_bridge/tasks.py — Task management for KLG matter project pages.

Tasks are stored inside each matter's Notion page, in one of two forms:

  1. Child database — an inline Notion table embedded in the page.
     Detected via a child_database block in the page's children.
     Provides full structured fields: Stage, Status, Assignee, Deadline, etc.

  2. To-do blocks — checkbox items in the page body.
     Detected when no child_database block is present.
     Provides name and checked state only (lower fidelity).

This module auto-detects which pattern a matter page uses and provides a
unified interface for reading, creating, and updating tasks.
"""

from __future__ import annotations

import logging
from typing import Any

from notion_bridge.client import NotionBridge

logger = logging.getLogger(__name__)


def _normalize_task(task_id: str, data: dict, *, is_block: bool = False) -> dict:
    """Normalize a task from a DB row or a to_do block to a consistent frontend shape."""
    if is_block:
        text = ""
        for rt in data.get("to_do", {}).get("rich_text", []):
            text += rt.get("plain_text", "")
        checked = data.get("to_do", {}).get("checked", False)
        return {
            "id": task_id,
            "name": text,
            "stage": "",
            "status": "Done" if checked else "To Do",
            "assignee": "",
            "deadline": None,
            "eta": None,
            "duration": None,
            "priority": "",
            "is_block": True,
        }

    def _assignee(val: Any) -> str:
        if isinstance(val, list):
            return ", ".join(str(v) for v in val if v)
        return str(val) if val else ""

    def _date(val: Any) -> str | None:
        if not val:
            return None
        # strip range notation ("2026-08-01 → 2026-08-15")
        return str(val).split(" → ")[0]

    status = data.get("Status") or data.get("status") or "To Do"
    name = (
        data.get("Name")
        or data.get("Task name")
        or data.get("Task Name")
        or data.get("name")
        or ""
    )

    return {
        "id": task_id,
        "name": name,
        "stage": data.get("Stage") or data.get("stage") or "",
        "status": status,
        "assignee": _assignee(data.get("Assignee") or data.get("assignee") or ""),
        "deadline": _date(data.get("Deadline") or data.get("deadline")),
        "eta": _date(data.get("ETA") or data.get("eta")),
        "duration": data.get("Duration") or data.get("duration"),
        "priority": data.get("Priority") or data.get("priority") or "",
        "is_block": False,
    }


class TaskPages:
    """
    High-level interface to tasks stored inside KLG matter project pages.

    Supports child-database and to-do-block storage patterns transparently.
    Instantiate with a NotionBridge; does not require a separate database ID.
    """

    def __init__(self, bridge: NotionBridge) -> None:
        self._bridge = bridge

    async def get_tasks_for_matter(self, matter_id: str) -> list[dict]:
        """
        Return all tasks for a matter, normalized to a consistent shape.

        Prefers the child database path (full structure). Falls back to
        to_do blocks when no inline database is present.
        """
        try:
            blocks = await self._bridge.get_page_blocks(matter_id)
        except Exception as e:
            logger.warning("get_tasks_for_matter: could not fetch blocks for %s: %s", matter_id, e)
            return []

        child_db = next((b for b in blocks if b.get("type") == "child_database"), None)
        if child_db:
            try:
                return await self._tasks_from_db(child_db["id"])
            except Exception as e:
                logger.warning(
                    "get_tasks_for_matter: child DB %s failed, falling back to todos: %s",
                    child_db["id"][:8], e,
                )

        return self._tasks_from_todos(blocks)

    async def _tasks_from_db(self, db_id: str) -> list[dict]:
        rows = await self._bridge.query_database(
            database_id=db_id,
            sorts=[{"property": "Stage", "direction": "ascending"}],
        )
        return [
            _normalize_task(row["id"], row, is_block=False)
            for row in rows
            if row.get("id")
        ]

    def _tasks_from_todos(self, blocks: list[dict]) -> list[dict]:
        return [
            _normalize_task(b["id"], b, is_block=True)
            for b in blocks
            if b.get("type") == "to_do" and b.get("id")
        ]

    async def create_task(
        self,
        matter_id: str,
        name: str,
        stage: str = "",
        assignee: str = "",
        deadline: str | None = None,
        eta: str | None = None,
        duration: int | None = None,
        priority: str = "",
    ) -> dict:
        """
        Create a new task for a matter.

        Appends a DB row if the page has an inline task database;
        otherwise appends a to_do block to the page body.
        """
        try:
            blocks = await self._bridge.get_page_blocks(matter_id)
        except Exception:
            blocks = []

        child_db = next((b for b in blocks if b.get("type") == "child_database"), None)

        if child_db:
            return await self._create_db_task(
                child_db["id"], name, stage, assignee, deadline, eta, duration, priority
            )
        return await self._create_todo_task(matter_id, name)

    async def _create_db_task(
        self,
        db_id: str,
        name: str,
        stage: str,
        assignee: str,
        deadline: str | None,
        eta: str | None,
        duration: int | None,
        priority: str,
    ) -> dict:
        properties: dict[str, Any] = {
            "Name": {"title": [{"text": {"content": name}}]},
        }
        if stage:
            properties["Stage"] = {"select": {"name": stage}}
        if priority:
            properties["Priority"] = {"select": {"name": priority}}
        if deadline:
            properties["Deadline"] = {"date": {"start": deadline}}
        if eta:
            properties["ETA"] = {"date": {"start": eta}}
        if duration is not None:
            properties["Duration"] = {"number": duration}

        raw = await self._bridge.create_page(database_id=db_id, properties=properties)
        return _normalize_task(raw.get("id", ""), raw, is_block=False)

    async def _create_todo_task(self, matter_id: str, name: str) -> dict:
        await self._bridge._client.blocks.children.append(
            block_id=matter_id,
            children=[{
                "object": "block",
                "type": "to_do",
                "to_do": {
                    "rich_text": [{"type": "text", "text": {"content": name}}],
                    "checked": False,
                },
            }],
        )
        return {
            "id": "",
            "name": name,
            "stage": "",
            "status": "To Do",
            "assignee": "",
            "deadline": None,
            "eta": None,
            "duration": None,
            "priority": "",
            "is_block": True,
        }

    async def update_task(
        self,
        task_id: str,
        is_block: bool,
        status: str | None = None,
        name: str | None = None,
        stage: str | None = None,
        assignee: str | None = None,
        deadline: str | None = None,
        eta: str | None = None,
        duration: int | None = None,
        priority: str | None = None,
    ) -> dict:
        """
        Update a task. Routes to block update or page property update based on is_block.
        """
        if is_block:
            block_props: dict[str, Any] = {}
            to_do_data: dict[str, Any] = {}
            if name is not None:
                to_do_data["rich_text"] = [{"type": "text", "text": {"content": name}}]
            if status is not None:
                to_do_data["checked"] = status.lower() in ("done", "complete", "completed")
            if to_do_data:
                block_props["to_do"] = to_do_data
            if block_props:
                updated = await self._bridge.update_block(task_id, **block_props)
                return _normalize_task(task_id, updated, is_block=True)
            return {}

        properties: dict[str, Any] = {}
        if name is not None:
            properties["Name"] = {"title": [{"text": {"content": name}}]}
        if status is not None:
            properties["Status"] = {"status": {"name": status}}
        if stage is not None:
            properties["Stage"] = {"select": {"name": stage}}
        if priority is not None:
            properties["Priority"] = {"select": {"name": priority}}
        if deadline is not None:
            properties["Deadline"] = {"date": {"start": deadline}} if deadline else {"date": None}
        if eta is not None:
            properties["ETA"] = {"date": {"start": eta}} if eta else {"date": None}
        if duration is not None:
            properties["Duration"] = {"number": duration}
        if not properties:
            return {}
        updated = await self._bridge.update_page(task_id, properties=properties)
        return _normalize_task(task_id, updated, is_block=False)

    async def delete_task(self, task_id: str, is_block: bool) -> None:
        """Mark a task complete (soft-delete). Does not remove the block/row from Notion."""
        if is_block:
            await self._bridge.update_block(task_id, to_do={"checked": True})
        else:
            await self._bridge.update_page(
                task_id,
                properties={"Status": {"status": {"name": "Done"}}},
            )
