"""
sharepoint_bridge/delta_monitor.py — SharePoint change detection and Slack formatting.

Polls the Microsoft Graph delta endpoint for file and folder changes under
/Matters, classifies each change by matter name, and formats Slack notifications.

FLOW:
  1. DeltaMonitor.poll() — calls SharePointBridge.poll_delta() to get raw changes
  2. _classify() — maps each Graph driveItem to a ChangeEvent (matter name, type, etc.)
  3. format_slack_blocks() — groups events by matter and returns Slack message blocks

Used by agents/sharepoint_monitor.py on every cron run.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Root folder path inside SharePoint (must match SHAREPOINT_MONITOR_FOLDER in config)
_DRIVE_ROOT_PREFIX = "/drive/root:"

# Regex to detect potential-client folders (e.g. "PC - Jones" or "PC-Smith")
_PC_PREFIX_RE = re.compile(r"^PC[\s\-–_]", re.IGNORECASE)


@dataclass
class ChangeEvent:
    """A single file or folder change detected via Graph delta."""
    name: str
    matter: str                     # top-level folder name under /Matters
    is_potential_client: bool
    change_type: str                # "added" | "modified" | "deleted"
    item_type: str                  # "file" | "folder"
    modified_by: str                # display name or "Unknown"
    web_url: str
    path: str                       # full parentReference.path value


def _extract_matter(parent_path: str, monitor_folder: str) -> str:
    """
    Extract the matter (top-level folder) name from a Graph parentReference path.

    parent_path  = "/drive/root:/Matters/Doe v. Smith/Briefs"
    monitor_folder = "/Matters"
    → "Doe v. Smith"
    """
    prefix = f"{_DRIVE_ROOT_PREFIX}{monitor_folder}/"
    # Normalize: remove leading slash from monitor_folder if present
    if not monitor_folder.startswith("/"):
        prefix = f"{_DRIVE_ROOT_PREFIX}/{monitor_folder}/"

    if parent_path.startswith(prefix):
        rest = parent_path[len(prefix):]
        return rest.split("/")[0] if rest else ""

    # Item IS the folder at the monitor root level (e.g., a new matter folder)
    root_path = f"{_DRIVE_ROOT_PREFIX}{monitor_folder}"
    if parent_path.rstrip("/") == root_path.rstrip("/"):
        return ""  # The item name itself is the matter folder

    return ""


def _classify(item: dict[str, Any], monitor_folder: str) -> ChangeEvent | None:
    """
    Convert a raw Graph driveItem dict into a ChangeEvent.
    Returns None if the item doesn't belong to a recognisable matter.
    """
    name = item.get("name", "")
    parent_path = (item.get("parentReference") or {}).get("path", "")
    web_url = item.get("webUrl", "")
    is_deleted = "deleted" in item

    # Determine matter name
    matter = _extract_matter(parent_path, monitor_folder)

    # If parent_path IS the monitor root, the item is a top-level matter folder
    root_norm = f"{_DRIVE_ROOT_PREFIX}{monitor_folder}".rstrip("/")
    if not matter and parent_path.rstrip("/") == root_norm:
        matter = name  # The new/deleted item IS the matter folder

    if not matter:
        return None

    is_pc = bool(_PC_PREFIX_RE.match(matter))

    if is_deleted:
        change_type = "deleted"
    elif item.get("createdDateTime") == item.get("lastModifiedDateTime"):
        change_type = "added"
    else:
        change_type = "modified"

    item_type = "folder" if "folder" in item else "file"

    modifier = (
        (item.get("lastModifiedBy") or {})
        .get("user", {})
        .get("displayName", "Unknown")
    )

    return ChangeEvent(
        name=name,
        matter=matter,
        is_potential_client=is_pc,
        change_type=change_type,
        item_type=item_type,
        modified_by=modifier,
        web_url=web_url,
        path=parent_path,
    )


def format_slack_message(events: list[ChangeEvent]) -> str:
    """
    Format a list of ChangeEvents into a Slack message string.

    Groups by matter. Caps at 8 changes per matter and 6 matters per message
    to keep notifications readable.
    """
    if not events:
        return ""

    # Group by matter, preserve insertion order
    by_matter: dict[str, list[ChangeEvent]] = {}
    for ev in events:
        by_matter.setdefault(ev.matter, []).append(ev)

    lines: list[str] = ["*SharePoint Activity*\n"]
    matter_count = 0

    for matter, evs in by_matter.items():
        if matter_count >= 6:
            remaining = len(by_matter) - matter_count
            lines.append(f"_…and {remaining} more matter(s) with changes_")
            break

        is_pc = evs[0].is_potential_client
        icon = "⚠️" if is_pc else "📂"
        pc_tag = " _(Potential Client)_" if is_pc else ""
        n = len(evs)
        change_word = "change" if n == 1 else "changes"
        lines.append(f"{icon} *{matter}*{pc_tag} — {n} {change_word}")

        shown = evs[:8]
        for ev in shown:
            type_icon = "🗂️" if ev.item_type == "folder" else "📄"
            by = f" by {ev.modified_by}" if ev.modified_by != "Unknown" else ""
            if ev.web_url:
                item_label = f"<{ev.web_url}|`{ev.name}`>"
            else:
                item_label = f"`{ev.name}`"
            lines.append(f"  • {type_icon} {item_label} — {ev.change_type}{by}")

        if len(evs) > 8:
            lines.append(f"  _…and {len(evs) - 8} more_")

        lines.append("")
        matter_count += 1

    return "\n".join(lines).strip()


class DeltaMonitor:
    """
    Orchestrates a single delta poll cycle.

    Usage (from agents/sharepoint_monitor.py):
        monitor = DeltaMonitor(sharepoint=deps.sharepoint, folder="/Matters")
        events, new_link = await monitor.poll(current_delta_link)
        message = format_slack_message(events)
    """

    def __init__(self, sharepoint: Any, folder: str = "/Matters") -> None:
        self._sp = sharepoint
        self._folder = folder

    async def poll(
        self, delta_link: str | None = None
    ) -> tuple[list[ChangeEvent], str]:
        """
        Run one delta poll.

        delta_link=None → first run: initialises delta state, returns no events.
        delta_link=<url> → subsequent runs: returns only items changed since last call.

        Returns:
            (events, new_delta_link)
            events is empty on first run or when nothing changed.
            new_delta_link must be stored for the next call.
        """
        if self._sp is None:
            logger.warning("DeltaMonitor.poll: SharePoint not configured")
            return [], ""

        raw_items, new_link = await self._sp.poll_delta(
            folder_path=self._folder,
            delta_link=delta_link,
        )

        if not new_link:
            # poll_delta returns empty string when the delta link expired or
            # SharePoint is unconfigured — caller should handle the reset.
            return [], ""

        # On first init, raw_items is empty (token=latest) — skip classification.
        events: list[ChangeEvent] = []
        for item in raw_items:
            ev = _classify(item, self._folder)
            if ev:
                events.append(ev)

        logger.info(
            "DeltaMonitor.poll: %d raw items → %d classified events",
            len(raw_items), len(events),
        )
        return events, new_link
