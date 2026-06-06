"""
api/routes/cases.py — Case File endpoints.

Provides rich case detail pages that combine Notion project data with
the live Slack activity from the case's dedicated channel.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENDPOINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  GET /cases/{page_id}
      Full case detail: Notion properties + page body + Slack activity.
      Includes the case's dedicated Slack channel messages, files, and
      images. Safe to call when Slack is not configured — returns an
      empty slack block rather than an error.

  GET /slack/file/{file_id}
      Authenticated proxy for Slack private files (images, PDFs).
      The Slack bot token is never exposed to the browser — the frontend
      fetches images through this endpoint, which adds the auth header
      server-side and streams the file back.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Cases"])


# =============================================================================
# DEPENDENCY
# =============================================================================

def get_deps(request: Request):
    return {
        "alfred_deps": request.app.state.alfred_deps,
        "slack_client": getattr(request.app.state, "slack_client", None),
    }


# =============================================================================
# ROUTES
# =============================================================================

@router.get("/cases/{page_id}", summary="Full case detail with Slack activity")
async def get_case_detail(
    page_id: str,
    deps=Depends(get_deps),
) -> dict[str, Any]:
    """
    Return full matter detail from Notion combined with live Slack activity.

    Response shape:
      {
        "matter": { ...all Notion properties... },
        "page_content": "...",
        "slack": {
          "channel": {"id": "...", "name": "...", "found": true},
          "messages": [...],
          "files": [{"id":"...", "name":"...", "type":"...", "proxy_url":"..."}],
          "error": null
        }
      }
    """
    alfred_deps = deps["alfred_deps"]
    slack_client = deps["slack_client"]

    # ── Notion: full matter properties + page body ────────────────────────────
    try:
        import asyncio
        matter, page_content = await asyncio.gather(
            alfred_deps.bridge.get_page(page_id),
            alfred_deps.bridge.get_page_content(page_id),
        )
    except Exception as e:
        logger.error("get_case_detail: Notion fetch failed for %s: %s", page_id, e)
        raise HTTPException(status_code=404, detail=f"Matter not found: {e}")

    # ── Slack: find channel + fetch activity ──────────────────────────────────
    slack_block: dict[str, Any] = {
        "channel": None,
        "messages": [],
        "files": [],
        "error": None,
    }

    if slack_client and settings.slack_bot_token:
        matter_name = matter.get("Project name", "")
        try:
            channel = await _find_case_channel(slack_client, matter_name)
            if channel:
                slack_block["channel"] = {
                    "id": channel["id"],
                    "name": channel["name"],
                    "found": True,
                }
                messages, files = await _fetch_channel_activity(
                    slack_client, channel["id"]
                )
                slack_block["messages"] = messages
                slack_block["files"] = files
            else:
                slack_block["channel"] = {"found": False, "name": None}
                # Fall back to a cross-channel search for the matter name
                slack_block["messages"] = await _search_slack_for_matter(
                    slack_client, matter_name
                )
        except Exception as e:
            logger.warning("get_case_detail: Slack fetch failed: %s", e)
            slack_block["error"] = str(e)
    else:
        slack_block["error"] = "Slack not configured"

    return {
        "matter": matter,
        "page_content": page_content,
        "slack": slack_block,
    }


@router.get("/slack/file/{file_id}", summary="Proxy authenticated Slack file download")
async def proxy_slack_file(file_id: str, request: Request) -> Response:
    """
    Proxy a Slack private file so the browser can display it without
    exposing the bot token. Returns the file with the correct Content-Type.
    """
    slack_client = getattr(request.app.state, "slack_client", None)
    if not slack_client or not settings.slack_bot_token:
        raise HTTPException(status_code=503, detail="Slack not configured")

    try:
        info = await slack_client.files_info(file=file_id)
        file_data = info.get("file", {})
        download_url = (
            file_data.get("url_private_download")
            or file_data.get("url_private")
        )
        if not download_url:
            raise HTTPException(status_code=404, detail="File URL not found")

        async with httpx.AsyncClient(follow_redirects=True) as http:
            resp = await http.get(
                download_url,
                headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                timeout=30,
            )
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "application/octet-stream")
        return Response(
            content=resp.content,
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("proxy_slack_file(%s): %s", file_id, e)
        raise HTTPException(status_code=502, detail=f"Could not fetch file: {e}")


# =============================================================================
# SLACK HELPERS
# =============================================================================

_NOISE_WORDS = {
    "v", "vs", "the", "and", "of", "in", "for", "case", "assessment",
    "evaluation", "appeal", "brief", "petition", "review", "matter",
    "strategy", "memo", "respondent", "appellant", "opening", "aob",
    "arb", "cal", "corp", "inc", "llc", "ltd",
}
_CASE_NUM_RE = re.compile(r'\b[bBcCgG]\d{5,}\b|\b\d{2}[A-Z]{2,}\d{5,}\b')


def _extract_keywords(matter_name: str) -> list[str]:
    """
    Pull meaningful words from a matter name for channel matching.

    "Four Jays v. Jones — AOB (B350887)" → ["four", "jays", "jones"]
    """
    name = matter_name.lower()
    name = _CASE_NUM_RE.sub("", name)
    name = re.sub(r"[—\-–]", " ", name)
    name = re.sub(r"[^\w\s]", " ", name)
    words = [
        w for w in name.split()
        if len(w) >= 3 and w not in _NOISE_WORDS and not w.isdigit()
    ]
    # Prefer the first few words (party names) over descriptive suffixes
    return words[:6]


async def _find_case_channel(slack_client: Any, matter_name: str) -> dict | None:
    """
    Find the Slack channel dedicated to this matter.

    Strategy: list all channels, score each by how many matter keywords
    appear in the channel name. Return the highest-scoring match above
    a minimum threshold.
    """
    keywords = _extract_keywords(matter_name)
    if not keywords:
        return None

    response = await slack_client.conversations_list(
        types="public_channel,private_channel",
        limit=200,
    )
    channels = response.get("channels", [])

    scored: list[tuple[int, dict]] = []
    for ch in channels:
        ch_name = ch.get("name", "").lower().replace("-", " ").replace("_", " ")
        score = sum(1 for kw in keywords if kw in ch_name)
        if score > 0:
            scored.append((score, ch))

    if not scored:
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_channel = scored[0]

    # Require at least 2 keyword matches, or 1 match when matter has ≤2 keywords
    threshold = 2 if len(keywords) > 2 else 1
    if best_score >= threshold:
        logger.info(
            "_find_case_channel('%s'): matched #%s (score=%d, keywords=%s)",
            matter_name[:40], best_channel["name"], best_score, keywords,
        )
        return best_channel

    return None


async def _fetch_channel_activity(
    slack_client: Any,
    channel_id: str,
    message_limit: int = 20,
) -> tuple[list[dict], list[dict]]:
    """
    Fetch recent messages and files from a Slack channel.

    Returns (messages, files) as plain dicts safe for JSON serialisation.
    Files include a proxy_url the frontend can use to display images.
    """
    import asyncio

    history_resp, files_resp = await asyncio.gather(
        slack_client.conversations_history(channel=channel_id, limit=message_limit),
        slack_client.files_list(channel=channel_id, count=20),
    )

    # ── Messages ──────────────────────────────────────────────────────────────
    raw_msgs = history_resp.get("messages", [])
    messages: list[dict] = []
    for m in raw_msgs:
        if m.get("subtype") in ("channel_join", "channel_leave", "bot_message"):
            continue
        messages.append({
            "ts":     m.get("ts", ""),
            "user":   m.get("user", ""),
            "text":   m.get("text", ""),
            "thread_ts": m.get("thread_ts"),
            "reply_count": m.get("reply_count", 0),
        })

    # ── Files ─────────────────────────────────────────────────────────────────
    raw_files = files_resp.get("files", [])
    files: list[dict] = []
    for f in raw_files:
        mime = f.get("mimetype", "")
        files.append({
            "id":        f.get("id", ""),
            "name":      f.get("name", ""),
            "type":      mime,
            "is_image":  mime.startswith("image/"),
            "size":      f.get("size", 0),
            "created":   f.get("created", 0),
            "user":      f.get("user", ""),
            "title":     f.get("title", ""),
            "proxy_url": f"/slack/file/{f['id']}",
        })

    return messages, files


async def _search_slack_for_matter(
    slack_client: Any,
    matter_name: str,
    limit: int = 10,
) -> list[dict]:
    """
    Fall-back: search all accessible Slack channels for messages mentioning
    this matter name. Used when no dedicated channel is found.
    """
    keywords = _extract_keywords(matter_name)
    if not keywords:
        return []

    # Use the two most distinctive keywords as the search query
    query = " ".join(keywords[:2])
    try:
        resp = await slack_client.search_messages(
            query=query,
            count=limit,
            sort="timestamp",
            sort_dir="desc",
        )
        matches = resp.get("messages", {}).get("matches", [])
        return [
            {
                "ts":      m.get("ts", ""),
                "channel": m.get("channel", {}).get("name", ""),
                "user":    m.get("username", ""),
                "text":    m.get("text", ""),
            }
            for m in matches
        ]
    except Exception as e:
        logger.warning("_search_slack_for_matter: %s", e)
        return []
