"""
mcp_server.py — MCP server exposing KLG Alfred's skills as model-agnostic tools.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT IS MCP?
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The Model Context Protocol (MCP) is an open standard that lets any AI model
call external tools over a standard interface. This server exposes Alfred's
skills so that:

  - Claude (via Claude Code or the API) can call them natively
  - GPT-4 / o3 can call them through an MCP-compatible bridge
  - Any other MCP client (future models, internal tools) can call them

SKILL PORTABILITY:
  The skills in this file are the same actions Alfred performs — they read
  from Notion, query Bloodhound's Watch List, search SharePoint. The model
  driving the calls doesn't matter — the tools work the same way.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

As a stdio MCP server (Claude Code / Claude Desktop):
    python mcp_server.py

Configure in Claude Code (.claude/mcp.json or via /mcp add):
    {
      "klg-alfred": {
        "command": "python",
        "args": ["C:/Users/Stu/klg-ai-os/mcp_server.py"],
        "cwd": "C:/Users/Stu/klg-ai-os"
      }
    }

Configure in Claude Desktop (claude_desktop_config.json):
    {
      "mcpServers": {
        "klg-alfred": {
          "command": "python",
          "args": ["C:/Users/Stu/klg-ai-os/mcp_server.py"]
        }
      }
    }

For GPT-4 / OpenAI via MCP bridge (e.g. openai-mcp-bridge):
    python -m openai_mcp_bridge --server "python mcp_server.py"
    Then pass the resulting tool definitions to the OpenAI API as function_tools.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOLS EXPOSED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  find_matter           — Look up a KLG matter by name in Notion
  get_matter_summary    — Get full details + page content for a matter
  get_upcoming_deadlines — Matters with deadlines in the next N days
  get_all_active_matters — All active matters (for workload / prioritization)
  search_notion         — Full-text search across all Notion pages
  get_watch_list        — Bloodhound's Watch List (cases being tracked)
  search_sharepoint     — Search KLG's SharePoint document library
  log_action_to_matter  — Write a timestamped note to a matter's Notion page
  update_matter_status  — Change a matter's status in Notion
"""

from __future__ import annotations

import asyncio
import logging

from mcp.server.fastmcp import FastMCP

# ── Initialize shared resources ───────────────────────────────────────────────
# These are created once at module load and reused across all tool calls.
# This mirrors how main.py initializes them for the FastAPI server.

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Lazy initialization — don't import heavy modules at load time.
# They're initialized on first tool call.
_bridge = None
_project_pages = None
_watch_list = None
_sharepoint = None


def _get_notion():
    global _bridge, _project_pages, _watch_list
    if _bridge is None:
        from notion_bridge.client import NotionBridge
        from notion_bridge.project_pages import ProjectPages
        from notion_bridge.watch_list import WatchList
        _bridge = NotionBridge()
        _project_pages = ProjectPages(_bridge)
        _watch_list = WatchList(_bridge)
    return _bridge, _project_pages, _watch_list


def _get_sharepoint():
    global _sharepoint
    if _sharepoint is None:
        from sharepoint_bridge.client import SharePointBridge
        _sharepoint = SharePointBridge()
    return _sharepoint


# ── MCP Server ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "KLG Alfred",
    instructions=(
        "You are connected to KLG Alfred — the Kowal Law Group AI Operating System. "
        "These tools give you read/write access to KLG's Notion matter database, "
        "Bloodhound's Watch List, and the SharePoint document library. "
        "All matter data is privileged and confidential. "
        "Never invent matter state — use the tools to retrieve current data."
    ),
)


# ─────────────────────────────────────────────────────────────────────────────
# NOTION — MATTER TOOLS
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def find_matter(matter_name: str) -> str:
    """
    Find a KLG matter project page by name in Notion.

    Returns the matter's key properties: status, priority, target date, URL.
    Use get_matter_summary to get the full page content including case notes.

    Args:
        matter_name: Full or partial matter name, e.g. "Petersen", "Smith v. City"
    """
    _, project_pages, _ = _get_notion()
    matter = await project_pages.find_matter(matter_name)

    if not matter:
        return f"No matter found matching '{matter_name}' in Notion."

    return (
        f"Matter: {matter.get('Project name', 'Unknown')}\n"
        f"Status: {matter.get('Status', 'N/A')}\n"
        f"Priority: {matter.get('Priority', 'N/A')}\n"
        f"Target Date: {matter.get('Target Date', 'N/A')}\n"
        f"ID: {matter.get('id', '')}\n"
        f"URL: {matter.get('url', '')}"
    )


@mcp.tool()
async def get_matter_summary(matter_name: str) -> str:
    """
    Get the full current state of a KLG matter, including properties and page body.

    Returns structured properties (status, deadline, priority) AND the free-text
    body (case notes, current theory, open questions). Use this when you need
    the full picture of a matter, not just its key properties.

    Args:
        matter_name: Full or partial matter name.
    """
    _, project_pages, _ = _get_notion()
    matter = await project_pages.find_matter(matter_name)

    if not matter:
        return f"No matter found matching '{matter_name}'."

    return await project_pages.get_matter_summary(matter["id"])


@mcp.tool()
async def get_upcoming_deadlines(days_ahead: int = 7) -> str:
    """
    Return all KLG matters with deadlines in the next N days.

    Args:
        days_ahead: How many days ahead to look. Default 7 (one week).
    """
    _, project_pages, _ = _get_notion()
    matters = await project_pages.get_matters_with_upcoming_deadlines(days_ahead)

    if not matters:
        return f"No matters with deadlines in the next {days_ahead} days."

    lines = [f"Matters due in {days_ahead} days ({len(matters)}):\n"]
    for m in matters:
        name = m.get("Project name", "Unknown")
        deadline = m.get("Target Date", "No date")
        status = m.get("Status", "?")
        url = m.get("url", "")
        lines.append(f"  • {name} — {deadline} | {status}\n    {url}")

    return "\n".join(lines)


@mcp.tool()
async def get_all_active_matters() -> str:
    """
    Return all active (In progress, Planning, Paused) KLG matters.

    Useful for workload overview, prioritization, and finding which matters
    need attention. Sorted by priority (High first).
    """
    _, project_pages, _ = _get_notion()
    matters = await project_pages.get_all_active_matters()

    if not matters:
        return "No active matters found."

    lines = [f"Active matters ({len(matters)}):\n"]
    for m in matters:
        name = m.get("Project name", "Unknown")
        status = m.get("Status", "?")
        priority = m.get("Priority", "")
        deadline = m.get("Target Date", "None set")
        url = m.get("url", "")
        lines.append(
            f"  • {name}\n"
            f"    {priority} priority | {status} | Due: {deadline}\n"
            f"    {url}"
        )

    return "\n".join(lines)


@mcp.tool()
async def search_notion(query: str) -> str:
    """
    Full-text search across all Notion pages the KLG integration can access.

    Use for finding documents, memos, research notes, or any page not
    directly accessible as a matter project page.

    Args:
        query: Search terms — case name, document title, concept, or keyword.
    """
    bridge, _, _ = _get_notion()
    results = await bridge.search(query)

    if not results:
        return f"No Notion pages found matching '{query}'."

    lines = [f"Notion search: '{query}' — {len(results)} results\n"]
    for r in results[:10]:
        title = r.get("Project name") or r.get("title") or "(Untitled)"
        url = r.get("url", "")
        edited = r.get("last_edited_time", "")[:10]
        lines.append(f"  • {title}\n    {url}  (edited {edited})")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# BLOODHOUND — WATCH LIST
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_watch_list(tier: str = "", issue_keyword: str = "") -> str:
    """
    Query Bloodhound's Watch List of cases being actively tracked.

    Args:
        tier:           Filter by tier: "1" (KLG core), "2" (adjacent),
                        "3" (ambient). Leave empty for all tiers.
        issue_keyword:  Filter by issue area keyword, e.g. "First Amendment",
                        "supersedeas". Client-side filter — case-insensitive substring match.
    """
    _, _, watch_list = _get_notion()
    cases = await watch_list.get_active_cases(tier=tier or None)

    if not cases:
        return "Bloodhound Watch List is empty."

    if issue_keyword:
        kw = issue_keyword.lower()
        cases = [
            c for c in cases
            if any(kw in area.lower() for area in (c.get("Issue Area") or []))
        ]
        if not cases:
            return f"No Watch List cases matching issue keyword '{issue_keyword}'."

    lines = [f"Watch List — {len(cases)} cases:\n"]
    for c in cases:
        name = c.get("Case Name", "Unknown")
        court = c.get("Court", "N/A")
        case_tier = c.get("Tier", "?")
        status = c.get("Status", "Watching")
        issues = ", ".join(c.get("Issue Area") or []) or "N/A"
        nexus = c.get("KLG Nexus Note", "")
        url = c.get("url", "")
        entry = (
            f"  • {name} ({court}) — Tier {case_tier}, {status}\n"
            f"    Issues: {issues}\n"
        )
        if nexus:
            entry += f"    KLG Nexus: {nexus}\n"
        entry += f"    {url}"
        lines.append(entry)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# SHAREPOINT
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def search_sharepoint(query: str, folder_path: str = "") -> str:
    """
    Search KLG's SharePoint document library for briefs, exhibits, and files.

    Args:
        query:       Search terms, e.g. "Petersen respondent brief 2026".
        folder_path: Optional subfolder to scope the search, e.g. "/Matters/Petersen".
    """
    sp = _get_sharepoint()

    if folder_path:
        items = await sp.list_folder(folder_path)
        if not items:
            return f"No files found in SharePoint folder '{folder_path}'."
        lines = [f"SharePoint '{folder_path}' ({len(items)} items):\n"]
        for item in items:
            icon = "📁" if item["type"] == "folder" else "📄"
            modified = item.get("lastModifiedDateTime", "")[:10]
            lines.append(f"  {icon} {item['name']}  (modified {modified})\n    {item['webUrl']}")
        return "\n".join(lines)

    results = await sp.search_files(query)
    if not results:
        return f"No SharePoint files found matching '{query}'."

    lines = [f"SharePoint search '{query}' ({len(results)} files):\n"]
    for r in results:
        name = r.get("name", "Unknown")
        url = r.get("webUrl", "")
        modified = r.get("lastModifiedDateTime", "")[:10]
        parent = r.get("parentPath", "").split("root:")[-1] or "/"
        lines.append(f"  📄 {name}  ({modified})\n    {parent}\n    {url}")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# WRITE TOOLS (Layer 1 updates)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
async def log_action_to_matter(
    matter_name: str,
    skill_name: str,
    action_description: str,
) -> str:
    """
    Append a timestamped action note to a matter's Notion project page.

    Use after completing work on a matter to keep the audit trail current.
    This is Step 4 of the Alfred skill lifecycle (Update Layer 1).

    Args:
        matter_name:        The matter to log to.
        skill_name:         Skill or action name, e.g. "klg-brief-elevation".
        action_description: One-sentence description of what was done.
    """
    _, project_pages, _ = _get_notion()
    matter = await project_pages.find_matter(matter_name)

    if not matter:
        return f"Matter '{matter_name}' not found in Notion."

    await project_pages.log_skill_action(
        page_id=matter["id"],
        skill_name=skill_name,
        action_summary=action_description,
    )

    return (
        f"Logged to {matter.get('Project name', matter_name)}: "
        f"{action_description}"
    )


@mcp.tool()
async def update_matter_status(matter_name: str, new_status: str) -> str:
    """
    Update the status of a KLG matter project page.

    Valid statuses: Planning, In progress, Paused, Backlog, Done, Canceled

    Args:
        matter_name: The matter to update.
        new_status:  The new status value.
    """
    _, project_pages, _ = _get_notion()
    matter = await project_pages.find_matter(matter_name)

    if not matter:
        return f"Matter '{matter_name}' not found in Notion."

    old_status = matter.get("Status", "Unknown")
    await project_pages.update_matter_status(matter["id"], new_status)
    await project_pages.log_skill_action(
        page_id=matter["id"],
        skill_name="mcp-status-update",
        action_summary=f"Status changed: '{old_status}' → '{new_status}'.",
    )

    return (
        f"{matter.get('Project name', matter_name)}: "
        f"'{old_status}' → '{new_status}'"
    )


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
