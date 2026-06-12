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

import html
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
# Reverse map: channel name → channel ID (used when files.list returns plain names)
_CHANNEL_NAME_TO_ID: dict[str, str] = {v[0]: k for k, v in CHANNEL_MAP.items()}
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

# Format from message bodies/canvas text: "Huddle notes: 6/6/26 in <#C0AA65K626B>"
# Also handles "<#ID|name>" (Slack appends display name after pipe in some contexts)
_TITLE_RE = re.compile(
    r"Huddle\s+notes?:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+in\s+<#([A-Z0-9]+)(?:\|[^>]*)?>",
    re.IGNORECASE,
)
# Format from files.list: "Huddle notes: 6/6/26 in #case-management" (plain channel name)
_TITLE_NAME_RE = re.compile(
    r"Huddle\s+notes?:\s*(\d{1,2}/\d{1,2}/\d{2,4})\s+in\s+#([\w-]+)",
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

    Returns a summary dict: {"imported": [...], "skipped": int, "errors": [...],
    "diag": {...}} so callers (manual trigger endpoint) can surface the result.
    """
    result: dict[str, Any] = {"imported": [], "skipped": 0, "errors": [], "diag": {}}

    if not slack_client:
        result["diag"] = {"skipped_reason": "slack_client is None — SLACK_BOT_TOKEN not set in Railway"}
        logger.info("HuddleImport: Slack not configured — skipping.")
        return result

    if not settings.notion_comms_log_db_id:
        result["diag"] = {"skipped_reason": "NOTION_COMMS_LOG_DB_ID not set in Railway env vars"}
        logger.info("HuddleImport: NOTION_COMMS_LOG_DB_ID not set — skipping.")
        return result

    logger.info("HuddleImport: Starting...")

    # ── Step 1: Search Slack for recent huddle canvases ────────────────────────
    files, diag = await _search_huddle_files(slack_client)
    result["diag"] = diag

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
            diag.setdefault("skipped_titles", [])
            if len(diag["skipped_titles"]) < 5:
                diag["skipped_titles"].append(name[:120])
            continue

        meeting_date, channel_id = parsed_title

        # Resolve channel name and portal URL
        if channel_id in CHANNEL_MAP:
            channel_name, portal_url = CHANNEL_MAP[channel_id]
        else:
            channel_name, portal_url = await _resolve_unknown_channel(slack_client, channel_id)

        # Build Notion title — en-dash U+2013 is required; hyphen breaks duplicate check
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


async def _search_huddle_files(slack_client: Any) -> tuple[list[dict] | None, dict]:
    """
    Find huddle canvas files via two parallel tracks:

    Track 1 — files.list per channel (primary):
        Directly queries the channel's file list for canvas files whose title
        contains "huddle". Does not depend on message structure or reply counts.
        Requires: files:read (already granted).

    Track 2 — conversations.history + thread scanning (fallback):
        Scans recent messages for huddle-related content and checks their threads
        for the "AI huddle notes are ready" canvas-link notification.
        Key fix: no longer gates on reply_count > 0 — Slack omits that field on
        system/subtype messages even when a thread reply exists, which was causing
        every huddle message to be silently skipped.
        Requires: channels:history or groups:history.

    Returns (found_files, diag_dict).
    """
    import time

    oldest_ts = time.time() - 7 * 24 * 3600
    oldest_str = str(oldest_ts)
    found: list[dict] = []
    seen_ids: set[str] = set()

    diag: dict = {
        "channels_scanned": 0,
        "channels_skipped": [],
        "messages_checked": 0,
        "huddle_candidates": 0,
        "threads_fetched": 0,
        "canvas_links_found": 0,
        "files_list_hits": 0,
        "search_messages_hits": 0,
        "channel_errors": {},
    }

    _CANVAS_LINK_RE = re.compile(r"/docs/[A-Z0-9]+/([A-Z0-9]+)", re.IGNORECASE)

    # ── Track 1: search.messages with content_types="files" ──────────────────
    # search.messages requires a USER token (xoxp-) — bot tokens (xoxb-) get
    # not_allowed_token_type, always. Skip it entirely on bot tokens; files.list
    # below is the working track for this app's bot-token setup.
    token = getattr(slack_client, "token", "") or ""
    if token.startswith("xoxb-"):
        diag["search_messages_skipped"] = "bot token — search.messages needs a user token"
    else:
        try:
            s_resp = await slack_client.search_messages(
                query="huddle",
                content_types="files",
                sort="timestamp",
                sort_dir="desc",
                count=20,
            )
            matches = (s_resp.get("messages") or {}).get("matches") or []
            for match in matches:
                for f in match.get("files", []):
                    fid = f.get("id", "")
                    title = (f.get("title") or f.get("name") or "")
                    if fid and fid not in seen_ids and "huddle" in title.lower():
                        found.append(f)
                        seen_ids.add(fid)
                        diag["search_messages_hits"] += 1
                        logger.debug("HuddleImport: Track1 search.messages: %s — %s", fid, title)
            logger.info(
                "HuddleImport: search.messages returned %d match(es), %d huddle file(s)",
                len(matches), diag["search_messages_hits"],
            )
        except Exception as se:
            logger.warning("HuddleImport: search.messages failed (%s) — falling back to per-channel tracks", se)
            diag["channel_errors"]["_search_messages"] = str(se)[:200]

    for channel_id in CHANNEL_MAP:
        channel_name = CHANNEL_MAP[channel_id][0]

        # ── Track 1: files.list ───────────────────────────────────────────────
        # Directly lists canvas files shared in this channel. Much simpler than
        # scanning message history — doesn't depend on reply_count or subtypes.
        try:
            fl_resp = await slack_client.files_list(
                channel=channel_id,
                ts_from=str(int(oldest_ts)),
                count=50,
            )
            for f in fl_resp.get("files", []):
                fid = f.get("id", "")
                title = (f.get("title") or f.get("name") or "").lower()
                if fid and fid not in seen_ids and "huddle" in title:
                    found.append(f)
                    seen_ids.add(fid)
                    diag["files_list_hits"] += 1
                    logger.debug("HuddleImport: Track1 files.list hit: %s (%s)", fid, title)
        except Exception as fle:
            logger.debug("HuddleImport: files.list failed for #%s: %s", channel_name, fle)

        # ── Track 2: conversations.history + thread scanning ──────────────────
        try:
            cursor = None
            channel_msgs = 0
            while True:
                kwargs: dict = {"channel": channel_id, "oldest": oldest_str, "limit": 200}
                if cursor:
                    kwargs["cursor"] = cursor
                resp = await slack_client.conversations_history(**kwargs)

                for msg in resp.get("messages", []):
                    channel_msgs += 1

                    # Fallback: direct files array (works on some bot token configs)
                    for f in msg.get("files", []):
                        fid = f.get("id", "")
                        name = (f.get("name") or f.get("title") or "").lower()
                        if fid and fid not in seen_ids and "huddle" in name:
                            found.append(f)
                            seen_ids.add(fid)
                            logger.debug("HuddleImport: Found via files[]: %s", fid)

                    text_lower = msg.get("text", "").lower()
                    looks_like_huddle = (
                        "huddle" in text_lower
                        or msg.get("subtype") in ("huddle_thread", "bot_message")
                        or msg.get("user") == "USLACKBOT"
                    )
                    if not looks_like_huddle:
                        continue

                    # Always check the thread for huddle-looking messages.
                    # Do NOT gate on reply_count — Slack omits that field on system
                    # messages (subtype=huddle_thread etc.) even when replies exist.
                    diag["huddle_candidates"] += 1
                    thread_ts = msg.get("ts", "")
                    try:
                        t_resp = await slack_client.conversations_replies(
                            channel=channel_id, ts=thread_ts, limit=20,
                        )
                        diag["threads_fetched"] += 1
                        for reply in t_resp.get("messages", [])[1:]:  # skip parent
                            reply_text = reply.get("text", "")
                            if "huddle notes" not in reply_text.lower():
                                continue
                            m = _CANVAS_LINK_RE.search(reply_text)
                            if not m:
                                continue
                            diag["canvas_links_found"] += 1
                            fid = m.group(1).upper()
                            if fid in seen_ids:
                                continue
                            try:
                                fi_resp = await slack_client.files_info(file=fid)
                                f = fi_resp.get("file") or {}
                                if f:
                                    found.append(f)
                                    seen_ids.add(fid)
                                    logger.debug(
                                        "HuddleImport: Track2 thread hit: %s in #%s",
                                        fid, channel_name,
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

            diag["channels_scanned"] += 1
            diag["messages_checked"] += channel_msgs
            logger.debug("HuddleImport: #%s — %d messages scanned.", channel_name, channel_msgs)

        except Exception as e:
            err = str(e)
            diag["channel_errors"][channel_name] = err[:200]
            if "missing_scope" in err:
                scope_msg = (
                    f"Missing Slack scope on #{channel_name} — "
                    "add 'channels:history' (public) or 'groups:history' (private) "
                    "to Bot Token Scopes and reinstall the app."
                )
                logger.warning("HuddleImport: %s Error: %s", scope_msg, err)
                found.append({"_scope_error": scope_msg})
                break
            elif "not_in_channel" in err or "channel_not_found" in err:
                diag["channels_skipped"].append(f"{channel_name}: not_in_channel")
                logger.debug("HuddleImport: Bot not in %s — skipping.", channel_id)
            else:
                diag["channels_skipped"].append(f"{channel_name}: {err[:80]}")
                logger.warning("HuddleImport: history error for %s: %s", channel_id, e)

    logger.info(
        "HuddleImport: Found %d canvas(es). Scanned %d/%d channels, %d messages, "
        "%d huddle candidates, %d threads fetched.",
        len(found), diag["channels_scanned"], len(CHANNEL_MAP),
        diag["messages_checked"], diag["huddle_candidates"], diag["threads_fetched"],
    )
    return found, diag


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
    # Slack HTML-escapes file titles in API responses: files.list returns
    # "Huddle notes: 5/15/26 in &lt;#C07Q5784258&gt;". Unescape before matching —
    # without this, every canvas fails the title regexes and import finds nothing.
    name = html.unescape(name)

    # Format 1: "<#CHANNELID>" or "<#CHANNELID|name>" — from message bodies / canvas text
    m = _TITLE_RE.search(name)
    if m:
        date_str, channel_id = m.group(1), m.group(2)
        try:
            fmt = "%m/%d/%y" if len(date_str.split("/")[-1]) <= 2 else "%m/%d/%Y"
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d"), channel_id
        except ValueError:
            return None

    # Format 2: "#channel-name" (plain text) — returned by files.list
    m = _TITLE_NAME_RE.search(name)
    if m:
        date_str, ch_name = m.group(1), m.group(2).lower()
        channel_id = _CHANNEL_NAME_TO_ID.get(ch_name, ch_name)
        try:
            fmt = "%m/%d/%y" if len(date_str.split("/")[-1]) <= 2 else "%m/%d/%Y"
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%Y-%m-%d"), channel_id
        except ValueError:
            return None

    # Format 3: sanitized name "_headphones__Huddle_notes__6_8_26_in___C09GT3XBKD0_"
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

    # Transcript file ID — on the LAST line of the canvas, different from canvas ID.
    # Format: "![FXXXXXXX](https://kowallawgroup.slack.com/files/USLACKBOT/FXXXXXXX/huddle_transcript)"
    last_line = content.strip().split("\n")[-1]
    m = re.search(r"/(F[A-Z0-9]+)/huddle_transcript", last_line)
    if not m:
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

    # Comms Log schema (verified against the live DB and its 94 existing huddle
    # entries): "Comm Date" is a RICH_TEXT property (not date) and "Team Portal"
    # is a RELATION (not url). Sending date/url payloads makes Notion reject the
    # whole create with a validation error — which silently zeroed every import.
    properties["Comm Date"] = {"rich_text": [{"text": {"content": meeting_date}}]}

    portal_page_id = _portal_page_id(portal_url)
    if portal_page_id:
        properties["Team Portal"] = {"relation": [{"id": portal_page_id}]}

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

    # Notion's create_page API accepts max 100 blocks per request.
    # If the full property set is rejected (schema drift), retry with the
    # minimal set so one renamed property can't zero the whole import again.
    try:
        await bridge.create_page(
            database_id=settings.notion_comms_log_db_id,
            properties=properties,
            children=blocks[:100],
        )
    except Exception as first_err:
        # Most likely failure: the Team Portal page isn't shared with the
        # integration (ObjectNotFound on the relation). Drop the relation but
        # keep everything else before falling all the way back to Name+Summary.
        logger.warning(
            "HuddleImport: create_page rejected for '%s' (%s) — retrying without Team Portal",
            title, first_err,
        )
        without_portal = {k: v for k, v in properties.items() if k != "Team Portal"}
        try:
            await bridge.create_page(
                database_id=settings.notion_comms_log_db_id,
                properties=without_portal,
                children=blocks[:100],
            )
        except Exception as second_err:
            logger.warning(
                "HuddleImport: still rejected for '%s' (%s) — retrying with minimal properties",
                title, second_err,
            )
            minimal = {
                "Name": properties["Name"],
                "Summary": properties["Summary"],
            }
            await bridge.create_page(
                database_id=settings.notion_comms_log_db_id,
                properties=minimal,
                children=blocks[:100],
            )


def _portal_page_id(portal_url: str) -> str | None:
    """Extract the Notion page ID from a portal URL as a dashed UUID.

    "https://www.notion.so/3250fc06a06c80c29d28da7c0b81c6b8"
        → "3250fc06-a06c-80c2-9d28-da7c0b81c6b8"
    The Team Portal relation needs the page ID, not the URL.
    """
    m = re.search(r"([0-9a-f]{32})", portal_url)
    if not m:
        return None
    h = m.group(1)
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


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
