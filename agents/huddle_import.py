"""
agents/huddle_import.py — Slack huddle canvas → Notion Comms Log importer.

Searches Slack for recent huddle summary canvases, checks for duplicates in
the Notion Comms Log, reads each new canvas, and creates a structured Comms
Log entry with attendees, notes, action items, and a transcript link.

Posts a brief import report to #klg-systems-development when complete.

Schedule: weekdays at 12:30 PM Pacific (via APScheduler in scheduler.py).
Manual trigger: POST /alfred/agents/huddle-import

Required Slack scopes (add to your Slack app if not already present):
    search:read   — allows search.files to find huddle canvases
    files:read    — allows files.info and downloading canvas content
    channels:read — needed to resolve unknown channel IDs to names
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

import httpx

from config import settings
from notion_bridge.client import NotionBridge

logger = logging.getLogger(__name__)

# ── Channel ID → (name, team_portal_url) ─────────────────────────────────────
CHANNEL_MAP: dict[str, tuple[str, str]] = {
    "C07Q5784258": ("all-kowallawgroup",        "https://www.notion.so/3250fc06a06c80c29d28da7c0b81c6b8"),
    "C0AA65K626B": ("case-management",          "https://www.notion.so/3250fc06a06c80c29d28da7c0b81c6b8"),
    "C0A8RNA7GAW": ("attorney-roundtable",      "https://www.notion.so/3250fc06a06c80c29d28da7c0b81c6b8"),
    "C09GT3XBKD0": ("klg-content-and-events",  "https://www.notion.so/3250fc06a06c805ba048e3590c18c611"),
    "C0A0L00GVP0": ("collections",             "https://www.notion.so/3250fc06a06c803f8fe8eda3c69d6f2f"),
    "C09H4U8GRHA": ("klg-systems-development", "https://www.notion.so/3250fc06a06c80809620c8d30818a292"),
    "C0B504U3VMZ": ("pc-portal",              "https://www.notion.so/3250fc06a06c80c29d28da7c0b81c6b8"),
}
DEFAULT_PORTAL = "https://www.notion.so/3250fc06a06c80c29d28da7c0b81c6b8"
REPORT_CHANNEL = "C09H4U8GRHA"  # klg-systems-development

# ── Slack user ID → real name ─────────────────────────────────────────────────
USER_MAP: dict[str, str] = {
    "U07PYJDNGT0": "Tim",
    "U097FMSH3V4": "William Hernandez",
    "U09EKSYTF6K": "Brittney Bishop",
    "U09EKSXH7GX": "Ted Davis",
    "U09QF69M1C6": "Richard J. Radcliffe",
    "U0A9PC7MK2N": "Josué Cardona",
    "U0AS9KZQ69X": "Edwyn Sierra",
    "U09EKSVG5FZ": "Andi Kowal",
}

# Title pattern: "Huddle notes: 6/6/26 in <#C0AA65K626B>"
_TITLE_RE = re.compile(
    r"Huddle\s+notes?:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+in\s+<#([A-Z0-9]+)>",
    re.IGNORECASE,
)
# Skip phrases — huddle was too short to generate meaningful notes
_SKIP_PHRASES = [
    "not enough to generate",
    "too short to summarize",
    "no notes generated",
    "meeting was too short",
]


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


async def run_huddle_import(
    bridge: NotionBridge,
    slack_client: Any | None,
) -> dict[str, Any]:
    """
    Run the huddle canvas import cycle.

    Returns a summary dict: {"imported": [...], "skipped": int, "errors": [...]}
    so callers (manual trigger endpoint) can surface the result to the user.
    """
    result: dict[str, Any] = {"imported": [], "skipped": 0, "errors": []}

    if not slack_client:
        logger.info("HuddleImport: Slack not configured — skipping.")
        return result

    if not settings.notion_comms_log_db_id:
        logger.info("HuddleImport: NOTION_COMMS_LOG_DB_ID not set — skipping.")
        return result

    logger.info("HuddleImport: Starting...")

    # ── Step 1: Search Slack for recent huddle canvases ────────────────────────
    files = await _search_huddle_files(slack_client)
    if files is None:
        result["errors"].append("Slack search failed — check server logs for scope errors")
        await _post_report(slack_client, result)
        return result

    # Surface any scope errors discovered during channel scanning
    scope_errors = [f["_scope_error"] for f in files if f.get("_scope_error")]
    if scope_errors:
        result["errors"].extend(scope_errors)
        await _post_report(slack_client, result)
        return result

    logger.info("HuddleImport: Found %d file(s) matching 'Huddle notes'", len(files))

    # ── Step 2–6: Process each file ──────────────────────────────────────────
    seen_titles: set[str] = set()

    # Filter out any diagnostic sentinel objects added during search
    files = [f for f in files if not f.get("_scope_error")]

    for file in files:
        canvas_id = file.get("id", "")
        # Try title (raw) before name (sanitized) — title preserves original chars
        name = file.get("title") or file.get("name") or ""

        parsed_title = _parse_huddle_title(name)
        if not parsed_title:
            logger.debug("HuddleImport: Skipping '%s' — doesn't match title format", name)
            result["skipped"] += 1
            continue

        meeting_date, channel_id = parsed_title

        # Resolve channel name and portal URL
        if channel_id in CHANNEL_MAP:
            channel_name, portal_url = CHANNEL_MAP[channel_id]
        else:
            channel_name, portal_url = await _resolve_unknown_channel(slack_client, channel_id)

        # Build Notion title — detect same-day duplicates and add (PM) suffix
        base_title = f"Huddle – #{channel_name} – {meeting_date}"
        notion_title = base_title

        if base_title in seen_titles or await _is_duplicate(bridge, base_title):
            pm_title = f"{base_title} (PM)"
            if await _is_duplicate(bridge, pm_title):
                logger.info("HuddleImport: Already in Notion — skipping '%s' (PM)", base_title)
                result["skipped"] += 1
                continue
            notion_title = pm_title

        # Read canvas content
        content = await _read_canvas_content(slack_client, canvas_id)
        if not content:
            logger.warning("HuddleImport: Could not read canvas %s — skipping '%s'", canvas_id, notion_title)
            result["errors"].append(f"{notion_title}: canvas unreadable")
            continue

        # Skip near-empty huddles
        if any(phrase in content.lower() for phrase in _SKIP_PHRASES):
            logger.info("HuddleImport: Minimal content — skipping '%s'", notion_title)
            result["skipped"] += 1
            continue

        # Parse and create Notion entry
        try:
            parsed = _parse_canvas(content)
            await _create_notion_entry(
                bridge=bridge,
                title=notion_title,
                meeting_date=meeting_date,
                portal_url=portal_url,
                parsed=parsed,
            )
            seen_titles.add(base_title)
            result["imported"].append(notion_title)
            logger.info("HuddleImport: Created '%s'", notion_title)
        except Exception as e:
            logger.error("HuddleImport: Failed to create '%s': %s", notion_title, e, exc_info=True)
            result["errors"].append(f"{notion_title}: {e}")

    # Post report to Slack
    await _post_report(slack_client, result)
    logger.info(
        "HuddleImport complete: %d imported, %d skipped, %d errors",
        len(result["imported"]), result["skipped"], len(result["errors"]),
    )
    return result


# =============================================================================
# SLACK HELPERS
# =============================================================================


async def _search_huddle_files(slack_client: Any) -> list[dict] | None:
    """
    Find huddle canvas files by scanning channel history and thread replies.

    Bot tokens don't receive the `files` array on Slackbot huddle messages via
    conversations.history. The reliable signal is the thread reply Slackbot
    posts when the canvas is ready: "AI huddle notes are ready... View AI Notes"
    with the file ID embedded in the link as /docs/TEAM_ID/FILE_ID.

    Strategy:
      1. Scan each channel's history for the last 7 days.
      2. For any Slackbot message that has thread replies, fetch those replies.
      3. In the replies, look for the "huddle notes are ready" notification and
         extract the file ID from the /docs/ URL.
      4. Fetch the full file object via files.info.

    Fallback: also check msg["files"] directly in case Slack ever returns them.

    Requires: channels:history (have it), files:read (have it).
    """
    import time

    oldest = str(time.time() - 7 * 24 * 3600)  # 7 days back
    found: list[dict] = []
    seen_ids: set[str] = set()

    # Regex to extract file ID from Slack canvas URL in thread reply text:
    # <https://workspace.slack.com/docs/TEAM_ID/FILE_ID|View AI Notes>
    _CANVAS_LINK_RE = re.compile(r"/docs/[A-Z0-9]+/([A-Z0-9]+)", re.IGNORECASE)

    for channel_id in CHANNEL_MAP:
        try:
            cursor = None
            while True:
                kwargs: dict = {"channel": channel_id, "oldest": oldest, "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = await slack_client.conversations_history(**kwargs)

                for msg in resp.get("messages", []):
                    # Fallback: direct files array (works for some bot token configs)
                    for f in msg.get("files", []):
                        fid = f.get("id", "")
                        name = (f.get("name") or f.get("title") or "").lower()
                        if fid and fid not in seen_ids and "huddle" in name:
                            found.append(f)
                            seen_ids.add(fid)
                            logger.debug("HuddleImport: Found via files[]: %s", fid)

                    # Primary: any message with thread replies could be a huddle thread.
                    # Avoid relying on user ID or subtype — Slack returns huddle system
                    # messages differently for bot tokens vs user tokens.
                    has_replies = msg.get("reply_count", 0) > 0 or msg.get("reply_users_count", 0) > 0
                    text_lower = msg.get("text", "").lower()
                    # Quick pre-filter: only dig into threads that look huddle-related
                    looks_like_huddle = (
                        "huddle" in text_lower
                        or msg.get("subtype") in ("huddle_thread", "bot_message")
                        or msg.get("user") == "USLACKBOT"
                    )
                    if not (has_replies and looks_like_huddle):
                        continue

                    # Fetch thread replies to find the canvas-ready notification
                    thread_ts = msg.get("ts", "")
                    try:
                        t_resp = await slack_client.conversations_replies(
                            channel=channel_id, ts=thread_ts, limit=20,
                        )
                        for reply in t_resp.get("messages", [])[1:]:  # skip parent
                            reply_text = reply.get("text", "")
                            if "huddle notes" not in reply_text.lower():
                                continue
                            m = _CANVAS_LINK_RE.search(reply_text)
                            if not m:
                                continue
                            fid = m.group(1).upper()
                            if fid in seen_ids:
                                continue
                            # Fetch the full file object
                            try:
                                fi_resp = await slack_client.files_info(file=fid)
                                f = fi_resp.get("file") or {}
                                if f:
                                    found.append(f)
                                    seen_ids.add(fid)
                                    logger.debug(
                                        "HuddleImport: Found via thread reply: %s in %s",
                                        fid, channel_id,
                                    )
                            except Exception as fe:
                                logger.warning(
                                    "HuddleImport: files_info failed for %s: %s", fid, fe
                                )
                    except Exception as te:
                        logger.debug(
                            "HuddleImport: thread fetch failed %s/%s: %s",
                            channel_id, thread_ts, te,
                        )

                meta = resp.get("response_metadata") or {}
                cursor = meta.get("next_cursor")
                if not cursor:
                    break

        except Exception as e:
            err = str(e)
            if "missing_scope" in err:
                msg = f"Missing Slack scope — add 'channels:history' to Bot Token Scopes and reinstall the app."
                logger.warning("HuddleImport: %s Channel: %s. Error: %s", msg, channel_id, err)
                found.append({"_scope_error": msg})  # surfaces in result for diagnosis
                break  # no point checking other channels
            elif "not_in_channel" in err or "channel_not_found" in err:
                logger.debug("HuddleImport: Bot not in %s — skipping.", channel_id)
            else:
                logger.warning("HuddleImport: history error for %s: %s", channel_id, e)

    logger.info("HuddleImport: Found %d huddle canvas(es) across all channels.", len(found))
    return found


async def _resolve_unknown_channel(
    slack_client: Any, channel_id: str
) -> tuple[str, str]:
    """Resolve a channel ID not in CHANNEL_MAP. Falls back to ID if lookup fails."""
    try:
        info = await slack_client.conversations_info(channel=channel_id)
        name = (info.get("channel") or {}).get("name") or channel_id
        logger.info("HuddleImport: Resolved unknown channel %s → #%s", channel_id, name)
        return name, DEFAULT_PORTAL
    except Exception:
        return channel_id, DEFAULT_PORTAL


async def _read_canvas_content(slack_client: Any, canvas_id: str) -> str | None:
    """
    Read the text content of a Slack canvas file via files.info.

    Tries in order:
      1. file.content / file.plain_text (returned inline when accessible)
      2. Download from file.url_private with the bot token Authorization header
    """
    try:
        resp = await slack_client.files_info(file=canvas_id)
        file_data = resp.get("file") or {}

        # Try inline content fields first
        for field in ("content", "plain_text"):
            content = file_data.get(field, "")
            if content and len(content.strip()) > 20:
                return content

        # Fall back to downloading from url_private
        url = file_data.get("url_private_download") or file_data.get("url_private")
        token = getattr(slack_client, "token", None)
        if url and token:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as http:
                r = await http.get(url, headers={"Authorization": f"Bearer {token}"})
                if r.status_code == 200 and len(r.text.strip()) > 20:
                    return r.text
                logger.warning(
                    "HuddleImport: Canvas %s download returned status %d", canvas_id, r.status_code
                )

        return None

    except Exception as e:
        err = str(e)
        if "missing_scope" in err:
            logger.error(
                "HuddleImport: Cannot read canvas — missing scope. "
                "Add 'files:read' to your Slack app's bot token scopes. Error: %s",
                err,
            )
        else:
            logger.warning("HuddleImport: Could not read canvas %s: %s", canvas_id, e)
        return None


# =============================================================================
# CONTENT PARSING
# =============================================================================


def _parse_huddle_title(name: str) -> tuple[str, str] | None:
    """
    Parse a Slack huddle file name to (YYYY-MM-DD, channel_id).

    Handles two formats returned by the Slack API:
      Raw title:       "Huddle notes: 6/6/26 in <#C0AA65K626B>"
      Sanitized name:  "_headphones__Huddle_notes__6_8_26_in___C09GT3XBKD0_"
                       (Slack replaces special chars with underscores in the
                        file.name field; the title field keeps the original)

    Checks file.title first (via the `title` key), falls back to reconstructing
    from the sanitized name by treating it as the raw string.
    Returns None if no recognisable date + channel ID can be extracted.
    """
    # Try the raw format first (works when file.title is the original string)
    m = _TITLE_RE.search(name)
    if m:
        date_str, channel_id = m.group(1), m.group(2)
        try:
            fmt = "%m/%d/%y" if len(date_str.split("/")[-1]) <= 2 else "%m/%d/%Y"
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d"), channel_id
        except ValueError:
            return None

    # Sanitized fallback: "_headphones__Huddle_notes__6_8_26_in___C09GT3XBKD0_"
    # Extract date (digits separated by underscores where slashes were) and channel ID
    # Pattern: ..._M_D_YY_in___CHANNEL_ID_
    san = re.search(
        r"[Hh]uddle[_\s][Nn]otes[_\s]+(\d{1,2})[_/](\d{1,2})[_/](\d{2,4})[_\s]+in[_\s]+([A-Z0-9]{9,12})",
        name,
    )
    if san:
        month, day, year, channel_id = san.group(1), san.group(2), san.group(3), san.group(4)
        date_str = f"{month}/{day}/{year}"
        try:
            fmt = "%m/%d/%y" if len(year) <= 2 else "%m/%d/%Y"
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d"), channel_id
        except ValueError:
            pass

    return None


def _resolve_users(text: str, extra_map: dict[str, str] | None = None) -> str:
    """
    Replace all Slack user ID formats with real names.

    Handles:
      <@U07PYJDNGT0>               → Tim
      <@U07PYJDNGT0|displayname>   → Tim
      [@Name](slackUser://UXXXXXXX) → Tim (markdown link format)
    Unrecognized IDs are left as-is (they'll be visible in the Notion page).
    """
    resolved = {**USER_MAP, **(extra_map or {})}

    def _sub(m: re.Match) -> str:
        uid = m.group(1)
        return resolved.get(uid, uid)

    # <@UXXXXXXX> and <@UXXXXXXX|name>
    text = re.sub(r"<@([A-Z0-9]+)(?:\|[^>]*)?>", _sub, text)
    # [@Name](slackUser://UXXXXXXX) markdown link format
    text = re.sub(
        r"\[@[^\]]*\]\(slackUser://([A-Z0-9]+)\)",
        lambda m: resolved.get(m.group(1), m.group(1)),
        text,
    )
    return text


def _parse_canvas(content: str) -> dict[str, Any]:
    """
    Extract structured data from huddle canvas markdown.

    Returns a dict with keys:
      time_range   — "9:00 AM – 9:45 AM" or ""
      attendees    — ["Tim", "William Hernandez", ...]
      summary      — full notes section as a string
      action_items — ["Task 1", "Task 2", ...]
      transcript_id — "F1234567890" or ""
    """
    content = _resolve_users(content)

    result: dict[str, Any] = {
        "time_range": "",
        "attendees": [],
        "summary": "",
        "action_items": [],
        "transcript_id": "",
    }

    # Time range — "9:00 AM – 9:45 AM" or "9:00AM-9:15AM"
    m = re.search(
        r"(?:Huddle\s+summary|summary)[:\s*]*"
        r"((?:\d{1,2}:\d{2}\s*[AP]M\s*[–—\-]+\s*\d{1,2}:\d{2}\s*[AP]M))",
        content,
        re.IGNORECASE,
    )
    if m:
        result["time_range"] = m.group(1).strip()

    # Transcript file ID from markdown image link: ![...](…/FXXXXXXX/…)
    m = re.search(r"!\[[^\]]*\]\([^)]*/(F[A-Z0-9]+)[^)]*\)", content)
    if m:
        result["transcript_id"] = m.group(1)

    # Split into sections using ## headers
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in content.split("\n"):
        h = re.match(r"^#{1,3}\s+(.*)", line)
        if h:
            current = h.group(1).strip().lower()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)

    # Attendees — split on commas and newlines
    att_raw = "\n".join(sections.get("attendees", []))
    result["attendees"] = [
        a.strip()
        for a in re.split(r"[,\n]", att_raw)
        if a.strip() and not a.strip().startswith("#")
    ]

    # Summary section
    result["summary"] = "\n".join(sections.get("summary", [])).strip()

    # Action items — lines matching "- [ ] ..." or "• [ ] ..."
    ai_key = next(
        (k for k in sections if "action" in k), None
    )
    if ai_key:
        result["action_items"] = [
            re.sub(r"^\s*[-•]\s*\[[ xX]\]\s*", "", line).strip()
            for line in sections[ai_key]
            if re.match(r"\s*[-•]\s*\[", line) and line.strip()
        ]

    return result


# =============================================================================
# NOTION HELPERS
# =============================================================================


async def _is_duplicate(bridge: NotionBridge, title: str) -> bool:
    """Return True if a Comms Log entry with this exact title already exists."""
    try:
        existing = await bridge.query_database(
            database_id=settings.notion_comms_log_db_id,
            filter={"property": "Name", "title": {"equals": title}},
            page_size=1,
        )
        return len(existing) > 0
    except Exception as e:
        logger.warning("HuddleImport: Duplicate check failed for '%s': %s", title, e)
        return False


async def _create_notion_entry(
    bridge: NotionBridge,
    title: str,
    meeting_date: str,
    portal_url: str,
    parsed: dict[str, Any],
) -> None:
    """Create a new Comms Log page for a huddle."""

    # ── Properties ─────────────────────────────────────────────────────────────
    actions_summary = (
        "\n".join(f"• {a}" for a in parsed["action_items"])[:500]
        if parsed["action_items"]
        else "No action items recorded."
    )

    properties: dict[str, Any] = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Actions": {"select": {"name": "N/A"}},
        "Summary": {"rich_text": [{"text": {"content": actions_summary}}]},
    }

    # These properties exist on the Comms Log DB per the original skill spec.
    # Wrapped individually so a property name mismatch only skips that one field.
    try:
        properties["Comm Date"] = {"date": {"start": meeting_date}}
    except Exception:
        pass

    try:
        properties["Team Portal"] = {"url": portal_url}
    except Exception:
        pass

    # ── Page body blocks ────────────────────────────────────────────────────────
    blocks: list[dict] = []

    # Huddle Summary section
    blocks.append(_heading("Huddle Summary"))
    if parsed["time_range"]:
        blocks.append(_paragraph(parsed["time_range"]))

    # Attendees section
    if parsed["attendees"]:
        blocks.append(_heading("Attendees"))
        blocks.append(_paragraph(", ".join(parsed["attendees"])))

    # Summary section (preserve bullet structure)
    if parsed["summary"]:
        blocks.append(_heading("Summary"))
        for line in parsed["summary"].split("\n"):
            line = line.strip()
            if not line:
                continue
            if re.match(r"^#{1,3}\s", line):
                blocks.append(_heading(line.lstrip("#").strip(), level=3))
            elif re.match(r"^[-•]\s", line):
                blocks.append(_bullet(line[2:].strip()))
            else:
                blocks.append(_paragraph(line))

    # Action items section
    if parsed["action_items"]:
        blocks.append(_heading("Action Items"))
        for item in parsed["action_items"]:
            blocks.append(_bullet(item))

    # Transcript section
    blocks.append({"object": "block", "type": "divider", "divider": {}})
    blocks.append(_heading("Transcript"))
    if parsed["transcript_id"]:
        url = (
            f"https://kowallawgroup.slack.com/files/USLACKBOT"
            f"/{parsed['transcript_id']}/huddle_transcript"
        )
        blocks.append(_paragraph(f"View full huddle transcript in Slack: {url}"))
    else:
        blocks.append(_paragraph("No transcript link found in canvas."))

    # Notion's create_page API accepts max 100 blocks per request
    await bridge.create_page(
        database_id=settings.notion_comms_log_db_id,
        properties=properties,
        children=blocks[:100],
    )


# ── Notion block constructors ─────────────────────────────────────────────────

def _heading(text: str, level: int = 2) -> dict:
    t = {1: "heading_1", 2: "heading_2", 3: "heading_3"}.get(level, "heading_2")
    return {"object": "block", "type": t, t: {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}}


def _paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
    }


def _bullet(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]},
    }


# =============================================================================
# SLACK REPORT
# =============================================================================


async def _post_report(slack_client: Any, result: dict[str, Any]) -> None:
    """Post import summary to #klg-systems-development."""
    today = date.today().strftime("%B %d, %Y")
    imported = result["imported"]
    skipped  = result["skipped"]
    errors   = result["errors"]

    if imported:
        lines = "\n".join(f"  – {t}" for t in imported)
        error_line = ""
        if errors:
            detail = f" — {errors[0]}" if len(errors) == 1 else ""
            error_line = f"\n• ❌ Errors: {len(errors)}{detail}"
        message = (
            f"🤖 *Huddle Import – {today}*\n"
            f"• ✅ Imported: {len(imported)}\n{lines}\n"
            f"• ⏭️ Skipped (already in Notion or minimal): {skipped}"
            f"{error_line}"
        )
    else:
        message = f"🤖 *Huddle Import – {today}*\n• No new huddles found. Notion is up to date."

    try:
        await slack_client.chat_postMessage(channel=REPORT_CHANNEL, text=message)
    except Exception as e:
        logger.error("HuddleImport: Could not post report to Slack: %s", e)
