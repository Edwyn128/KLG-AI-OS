"""
notion_bridge/tasks.py — Task management for KLG matter project pages.

Tasks are stored inside each matter's Notion page, in one of two forms:

  1. Child database — an inline Notion table embedded in the page.
     Detected via a child_database block in the page's children.
     Provides full structured fields: Stage, Status, Assignee, Deadline, etc.

  2. To-do blocks — checkbox items in the page body.
     Detected when no child_database block is present.
     Provides name and checked state only (lower fidelity).

This module also supports seeding tasks from the KLG shared task-template
databases. When a new matter is opened, seed_from_template() copies all
template rows into the appropriate shared DB with the new matter linked via
the Projects relation.

KLG shared task-template database IDs:
  APPELLATE_TASKS_DB_ID   — "Appellate Briefing — Project Tasks"
  TRIAL_COURT_TASKS_DB_ID — "Trial Court Brief Preparation — Project Tasks"
"""

from __future__ import annotations

import logging
import re
from typing import Any

from notion_bridge.client import NotionBridge

logger = logging.getLogger(__name__)

# ── KLG shared task-template database IDs ────────────────────────────────────
APPELLATE_TASKS_DB_ID   = "69e011f7-740e-41ee-be6b-f5673b36c392"
TRIAL_COURT_TASKS_DB_ID = "deeacdf5-1c50-450b-bbc2-f6c14989aed2"

# Notion user ID → display name
_NOTION_USER_NAMES: dict[str, str] = {
    "b30c2eb6-779d-4d96-bdb9-2c3e81dced29": "Brittney",
    "d3dcab1b-be5a-4f73-b205-1b28e895742f": "Tim",
    "126d872b-594c-81f4-adf0-00020f9443eb": "Edwyn",
}

# Display name → Notion user UUID (for Notion API people filters, which require UUIDs)
_DISPLAY_TO_NOTION_ID: dict[str, str] = {v: k for k, v in _NOTION_USER_NAMES.items()}


def _parse_duration(val: Any) -> int | None:
    """
    Parse a duration value to total minutes.

    Handles:
      - int/float (assumed already in minutes)
      - strings like "30m", "2h", "1h 30m", "30 min", "2 hours", "90 minutes"
    Returns None if unparseable.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return int(val) if val else None
    s = str(val).lower().strip()
    if not s:
        return None
    total = 0
    h_match = re.search(r"(\d+)\s*h", s)
    m_match = re.search(r"(\d+)\s*m(?!o)", s)  # 'm' but not 'mo' (month)
    if h_match:
        total += int(h_match.group(1)) * 60
    if m_match:
        total += int(m_match.group(1))
    # Fallback: bare number — treat as minutes
    if not h_match and not m_match:
        bare = re.search(r"(\d+)", s)
        if bare:
            total = int(bare.group(1))
    return total if total else None


def _normalize_task(task_id: str, data: dict, *, is_block: bool = False) -> dict:
    """
    Normalize a task from a page_to_dict flat row or a to_do block to a consistent shape.

    IMPORTANT: `data` must be the flat dict returned by page_to_dict / query_database —
    NOT the raw Notion "properties" sub-dict. query_database already flattens properties
    to the top level, so callers should pass the row directly, not row.get("properties").
    """
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
            "start_date": None,
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
        # Strip range notation ("2026-08-01 → 2026-08-15")
        return str(val).split(" → ")[0].split("→")[0].strip()

    # Title field: template DBs call it "Task", matter child DBs call it "Name"
    name = (
        data.get("Task")
        or data.get("Name")
        or data.get("Task name")
        or data.get("Task Name")
        or data.get("name")
        or ""
    )

    status = data.get("Status") or data.get("status") or "To Do"

    completed_at = None
    if "done" in str(status).lower() or "complete" in str(status).lower():
        completed_at = data.get("last_edited_time")

    return {
        "id": task_id,
        "name": name,
        "stage": data.get("Stage") or data.get("stage") or "",
        "status": status,
        "assignee": _assignee(data.get("Assignee") or data.get("assignee") or ""),
        "deadline": _date(data.get("Deadline") or data.get("deadline")),
        "eta": _date(data.get("ETA") or data.get("eta")),
        "start_date": _date(data.get("Start Date") or data.get("start_date")),
        "completed_at": completed_at,
        "duration": _parse_duration(
            data.get("Duration") or data.get("Expected Duration") or data.get("duration")
        ),
        "priority": data.get("Priority") or data.get("priority") or "",
        "is_block": False,
    }


def _build_seed_properties(row: dict, matter_id: str) -> dict[str, Any]:
    """
    Build a Notion properties dict for a new task row cloned from a template row.

    Copies Task, Stage, Priority, Assignee, Expected Duration, Labels,
    Auto-scheduled?, and Todo Notes from the template. Always sets Status to
    "Not started" and Projects to [matter_id].
    """
    props: dict[str, Any] = {}

    # Title (required)
    task_name = row.get("Task") or row.get("Name") or ""
    props["Task"] = {"title": [{"text": {"content": task_name}}]}

    # Select fields
    if row.get("Stage"):
        props["Stage"] = {"select": {"name": row["Stage"]}}
    if row.get("Priority"):
        props["Priority"] = {"select": {"name": row["Priority"]}}

    # Status — always reset
    props["Status"] = {"status": {"name": "Not started"}}

    # People — Assignee stored as JSON array of "user://UUID" strings in flat dict
    assignee_raw = row.get("Assignee", "")
    if assignee_raw:
        import json
        try:
            people_list = json.loads(assignee_raw) if isinstance(assignee_raw, str) else assignee_raw
            people_ids = []
            for entry in (people_list if isinstance(people_list, list) else [people_list]):
                uid = str(entry).removeprefix("user://").strip()
                if uid:
                    people_ids.append({"id": uid})
            if people_ids:
                props["Assignee"] = {"people": people_ids}
        except Exception:
            pass

    # Rich text fields
    if row.get("Expected Duration"):
        props["Expected Duration"] = {
            "rich_text": [{"text": {"content": str(row["Expected Duration"])}}]
        }
    if row.get("Todo Notes"):
        props["Todo Notes"] = {
            "rich_text": [{"text": {"content": str(row["Todo Notes"])}}]
        }

    # Checkbox
    auto_sched = row.get("Auto-scheduled?")
    if auto_sched is not None:
        props["Auto-scheduled?"] = {"checkbox": auto_sched == "__YES__" or auto_sched is True}

    # Multi-select Labels — stored as JSON array of strings
    labels_raw = row.get("Labels", "")
    if labels_raw:
        import json
        try:
            labels = json.loads(labels_raw) if isinstance(labels_raw, str) else labels_raw
            if isinstance(labels, list) and labels:
                props["Labels"] = {"multi_select": [{"name": lbl} for lbl in labels]}
        except Exception:
            pass

    # Relation — link to the new matter
    props["Projects"] = {"relation": [{"id": matter_id}]}

    return props


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

    async def tasks_by_assignee(self, db_id: str, display_name: str) -> list[dict]:
        """
        Return tasks from a template DB assigned to a specific person.

        Uses the Notion user UUID for the filter (the API requires UUID, not display name).
        Falls back to fetching all tasks and filtering by assignee name if the UUID is unknown.
        """
        try:
            user_id = _DISPLAY_TO_NOTION_ID.get(display_name)

            if user_id:
                filter_body: dict | None = {
                    "property": "Assignee",
                    "people": {"contains": user_id},
                }
            else:
                filter_body = None

            rows = await self._bridge.query_database(db_id, filter=filter_body)

            result = []
            for row in rows:
                # If we couldn't filter in Notion, filter client-side by name
                if not user_id:
                    assignee_val = row.get("Assignee") or ""
                    assignee_str = (
                        ", ".join(str(v) for v in assignee_val)
                        if isinstance(assignee_val, list)
                        else str(assignee_val)
                    )
                    if display_name.lower() not in assignee_str.lower():
                        continue
                normalized = _normalize_task(row["id"], row)
                result.append(normalized)
            return result
        except Exception as exc:
            logger.warning("tasks_by_assignee error for %s: %s", display_name, exc)
            return []

    async def all_tasks_with_matter(self, db_id: str) -> list[dict]:
        """
        Return ALL tasks from a template DB, each annotated with matter_name from Projects.

        query_database returns flat dicts (page_to_dict already applied), so:
          - Task name is at row["Task"] or row["Name"]
          - Projects relation is at row["Projects"] — a list of page UUID strings
        """
        try:
            rows = await self._bridge.query_database(db_id)

            # Collect unique matter IDs from the Projects relation field.
            # page_to_dict extracts relation properties to a list of ID strings at the top level.
            matter_ids: set[str] = set()
            for row in rows:
                related = row.get("Projects") or []
                if isinstance(related, list):
                    for mid in related:
                        if mid:
                            matter_ids.add(mid)

            # Resolve matter names in parallel (one get_page per unique matter)
            matter_names: dict[str, str] = {}
            if matter_ids:
                import asyncio

                async def _resolve(mid: str) -> None:
                    try:
                        page = await self._bridge.get_page(mid)
                        # page is already a flat dict; "Project name" is the title field
                        matter_names[mid] = page.get("Project name") or ""
                    except Exception:
                        matter_names[mid] = ""

                await asyncio.gather(*[_resolve(mid) for mid in matter_ids])

            result = []
            for row in rows:
                task = _normalize_task(row["id"], row)
                # Attach matter_name and matter_id from the Projects relation
                related = row.get("Projects") or []
                matter_id = related[0] if isinstance(related, list) and related else ""
                task["matter_name"] = matter_names.get(matter_id, "")
                task["matter_id"] = matter_id
                result.append(task)
            return result
        except Exception as exc:
            logger.warning("all_tasks_with_matter error for db %s: %s", db_id, exc)
            return []

    async def seed_from_template(
        self,
        template_db_id: str,
        matter_id: str,
    ) -> list[dict]:
        """
        Seed tasks for a new matter from a KLG shared task-template database.

        Reads all rows in template_db_id and clones each one as a new row in
        the same database with the Projects relation set to matter_id. Status
        is always reset to "Not started" regardless of the template row's state.

        Idempotent: if any rows already link to matter_id, returns them without
        creating duplicates.
        """
        # ── Duplicate guard ───────────────────────────────────────────────────
        existing = await self._bridge.query_database(
            database_id=template_db_id,
            filter={"property": "Projects", "relation": {"contains": matter_id}},
        )
        if existing:
            logger.info(
                "seed_from_template: %d tasks already exist for matter %s — skipping.",
                len(existing), matter_id[:8],
            )
            return [_normalize_task(r["id"], r, is_block=False) for r in existing if r.get("id")]

        # ── Read template rows ────────────────────────────────────────────────
        template_rows = await self._bridge.query_database(database_id=template_db_id)
        if not template_rows:
            logger.warning("seed_from_template: no template rows found in DB %s", template_db_id[:8])
            return []

        created: list[dict] = []
        for row in template_rows:
            props = _build_seed_properties(row, matter_id)
            try:
                raw = await self._bridge.create_page(
                    database_id=template_db_id,
                    properties=props,
                )
                if raw.get("id"):
                    created.append(_normalize_task(raw["id"], raw, is_block=False))
            except Exception as e:
                logger.warning(
                    "seed_from_template: failed to create task '%s': %s",
                    row.get("Task") or row.get("Name") or "?", e,
                )

        logger.info(
            "seed_from_template: created %d/%d tasks for matter %s.",
            len(created), len(template_rows), matter_id[:8],
        )
        return created

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
            "start_date": None,
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
            to_do_data: dict[str, Any] = {}
            if name is not None:
                to_do_data["rich_text"] = [{"type": "text", "text": {"content": name}}]
            if status is not None:
                to_do_data["checked"] = status.lower() in ("done", "complete", "completed")
            if to_do_data:
                updated = await self._bridge.update_block(task_id, to_do=to_do_data)
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
