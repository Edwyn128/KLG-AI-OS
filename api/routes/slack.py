"""
api/routes/slack.py — Slack Events API webhook: receive messages and route to Alfred.

This endpoint lets team members talk to Alfred directly from Slack without
opening the web UI. Any message in the configured channel that mentions
the bot or starts with "Alfred," is forwarded to AlfredAgent and the
response is posted back to Slack as a reply.

SETUP (one-time in Slack app settings):
  1. Go to api.slack.com/apps → your app → Event Subscriptions
  2. Enable Events, set Request URL to: https://your-server/slack/events
  3. Subscribe to bot events: message.channels, app_mention
  4. Under Basic Information → App Credentials → copy the Signing Secret
     and set SLACK_SIGNING_SECRET in .env

SECURITY:
  Every Slack request is verified using HMAC-SHA256 with the signing secret.
  We reject any request that can't be verified — this prevents spoofed
  webhook calls from triggering Alfred queries.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["Slack"])

# Slack requires webhook URL verification during setup — it sends a
# challenge value and expects it echoed back immediately.
# Real event payloads have a different structure handled in receive_event().


@router.post("/events", summary="Receive Slack events and route to Alfred")
async def receive_event(request: Request) -> JSONResponse:
    """
    Slack Events API webhook handler.

    Handles two payload types:
      1. url_verification  — Slack's one-time challenge to confirm the URL is live
      2. event_callback    — An actual message or app_mention event

    Alfred responds to messages that:
      - @mention the bot  (event type: app_mention)
      - Start with "Alfred," in a direct message  (event type: message)
    """
    import json
    body_bytes = await request.body()
    payload = json.loads(body_bytes)

    # ── URL Verification (Slack setup challenge) ──────────────────────────────
    # Must respond before signature verification — Slack sends this once during
    # setup to confirm the endpoint is reachable. No auth risk: the response
    # only echoes back a value Slack itself just sent.
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge", "")})

    # Verify the request came from Slack before processing real events
    if settings.slack_signing_secret:
        _verify_slack_signature(request, body_bytes)

    # ── Real Event ────────────────────────────────────────────────────────────
    if payload.get("type") == "event_callback":
        event = payload.get("event", {})
        event_type = event.get("type", "")
        text = event.get("text", "").strip()
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts", "")
        bot_id = event.get("bot_id")

        # Never respond to messages from other bots (including ourselves) to
        # prevent infinite loops where Alfred responds to its own messages.
        if bot_id:
            return JSONResponse({"ok": True})

        channel_type = event.get("channel_type", "")

        # DMs (im): any message is addressed to Alfred — no prefix needed
        is_dm = event_type == "message" and channel_type == "im"
        # Channel @mention
        is_mention = event_type == "app_mention"
        # Channel message starting with "Alfred," (no @mention)
        is_channel_direct = event_type == "message" and text.lower().startswith("alfred,")

        if not (is_dm or is_mention or is_channel_direct):
            return JSONResponse({"ok": True})

        # Strip the @mention prefix so Alfred gets clean input
        # (DMs don't have a mention prefix — _strip_mention is a no-op on clean text)
        clean_text = _strip_mention(text)

        if not clean_text:
            return JSONResponse({"ok": True})

        # Get the user's Slack display name for logging
        user_id = event.get("user", "unknown")
        event_ts = event.get("ts", "")

        logger.info(
            "Slack → Alfred: user=%s channel=%s message=%s",
            user_id, channel, clean_text[:80],
        )

        # Fire-and-forget — respond to Slack immediately (within 3 seconds,
        # per Slack's requirement) and process Alfred's response asynchronously.
        import asyncio
        asyncio.create_task(
            _run_alfred_and_reply(
                message=clean_text,
                channel=channel,
                thread_ts=thread_ts,
                event_ts=event_ts,
                slack_client=request.app.state.slack_client,
                alfred_deps=request.app.state.alfred_deps,
                user_id=user_id,
                files=event.get("files", []),
            )
        )

    return JSONResponse({"ok": True})


async def _run_alfred_and_reply(
    message: str,
    channel: str,
    thread_ts: str,
    event_ts: str,
    slack_client,
    alfred_deps,
    user_id: str,
    files: list | None = None,
) -> None:
    """
    Run Alfred on the incoming Slack message and post the response as a reply.

    Runs in the background so the webhook endpoint can return 200 immediately
    (Slack requires a response within 3 seconds; Alfred can take 5–15 seconds).

    Posts the response in the same thread as the original message so it doesn't
    flood the channel with top-level replies.

    For channel @mentions (not DMs): if the channel name maps to an active matter,
    the original message is also logged to that matter's Notion page so the team
    has a record of Slack activity alongside case notes.
    """
    from alfred.agent import run_with_fallback

    try:
        # ── Connect mode: "@Alfred connect" → two-phase intro with Notion matter context
        if message.strip().lower() == "connect" or message.strip().lower().startswith("connect "):
            await _handle_connect_mode(
                slack_client=slack_client,
                alfred_deps=alfred_deps,
                channel=channel,
                user_id=user_id,
            )
            return

        history = await _fetch_conversation_history(
            slack_client=slack_client,
            channel=channel,
            thread_ts=thread_ts,
            event_ts=event_ts,
        )

        # Append any attached file content to the message so Alfred can act on it
        if files:
            file_context = await _extract_slack_file_text(files)
            if file_context:
                message = message + "\n\n" + file_context

        result = await run_with_fallback(message, message_history=history or None, deps=alfred_deps)
        response_text = result.output

        if slack_client:
            # DMs (channel starts with D): post directly, no thread_ts.
            # Threading in DMs hides replies behind a "1 reply" link.
            post_kwargs: dict = {"channel": channel, "text": response_text}
            if not channel.startswith("D"):
                post_kwargs["thread_ts"] = thread_ts
            await slack_client.chat_postMessage(**post_kwargs)
            logger.info("Slack ← Alfred: replied in %s", channel)

        # Auto-log @mentions in case channels to Notion.
        # Only runs for public/private channels (not DMs) when the channel name
        # maps to an active matter. Requires channels:read scope — degrades
        # gracefully (debug-level log) if the scope is missing or the channel
        # doesn't match any matter.
        if not channel.startswith("D") and slack_client:
            try:
                info_resp = await slack_client.conversations_info(channel=channel)
                channel_name = (info_resp.get("channel") or {}).get("name", "")
                if channel_name:
                    from agents.case_checkin import resolve_matter_for_channel
                    matter = await resolve_matter_for_channel(
                        channel_name, alfred_deps.project_pages
                    )
                    if matter and matter.get("id"):
                        snippet = message[:200].replace("\n", " ")
                        await alfred_deps.project_pages.log_skill_action(
                            page_id=matter["id"],
                            skill_name="slack-mention",
                            action_summary=f"@mention from {user_id}: {snippet}",
                        )
                        logger.info(
                            "Slack: Logged @mention from %s in #%s to matter '%s'",
                            user_id,
                            channel_name,
                            matter.get("Project name", matter["id"][:8]),
                        )
            except Exception as e:
                logger.debug("Slack: Could not log @mention to Notion: %s", e)

    except Exception as e:
        logger.error("Slack Alfred reply error for user %s: %s", user_id, e, exc_info=True)
        if slack_client:
            try:
                err_lower = str(e).lower()
                if any(p in err_lower for p in ("credit balance", "credits", "billing", "payment", "exhausted")):
                    user_msg = (
                        "Alfred's API credits are depleted — all models failed. "
                        "Please ask Tim to add credits at console.anthropic.com → Plans & Billing."
                    )
                elif any(p in err_lower for p in ("rate limit", "quota", "429")):
                    user_msg = "Alfred is temporarily rate-limited. Please try again in a moment."
                elif "timed out" in err_lower or "timeout" in err_lower:
                    user_msg = "Alfred timed out on this request. Try a shorter question or open the web UI."
                else:
                    user_msg = "Alfred encountered an unexpected error. Try again or open the web UI directly."
                await slack_client.chat_postMessage(
                    channel=channel,
                    text=user_msg,
                    thread_ts=thread_ts,
                )
            except Exception:
                pass


async def _handle_connect_mode(
    slack_client,
    alfred_deps,
    channel: str,
    user_id: str,
) -> None:
    """
    Handle "@Alfred connect": two-phase introduction matching KLG's executive assistant standard.

    Phase 1 — Post immediately to channel: "Just joined, reading history now..."
    Phase 2 — Post in thread off phase 1: rich matter-context intro + 3 proactive task offers
    Phase 3 — Post second thread reply: behavior preference note

    Alfred's key advantage over Claude.ai: full Notion access. The intro pulls
    the actual matter summary, status, stage, and deadline—not just channel history.
    """
    from alfred.agent import run_with_fallback

    channel_name = ""
    channel_history_text = ""
    matter_context = ""

    # ── Resolve channel name ──────────────────────────────────────────────────
    try:
        if not channel.startswith("D") and slack_client:
            info_resp = await slack_client.conversations_info(channel=channel)
            channel_name = (info_resp.get("channel") or {}).get("name", "")
    except Exception as e:
        logger.debug("connect-mode: could not resolve channel name: %s", e)

    # ── Read channel history (skip bots, skip the "connect" trigger) ──────────
    try:
        if slack_client:
            history_resp = await slack_client.conversations_history(channel=channel, limit=30)
            raw = list(reversed(history_resp.get("messages", [])))
            lines = []
            for msg in raw:
                if msg.get("bot_id"):
                    continue
                text = (msg.get("text") or "").strip()
                if text and text.lower() not in ("connect", "@alfred connect"):
                    lines.append(f"[{msg.get('user', 'team')}]: {text[:300]}")
            if lines:
                channel_history_text = "\n".join(lines[-20:])
    except Exception as e:
        logger.debug("connect-mode: could not fetch channel history: %s", e)

    # ── Resolve matter from Notion (Alfred's advantage over Claude.ai) ────────
    try:
        if channel_name and alfred_deps and alfred_deps.project_pages:
            from agents.case_checkin import resolve_matter_for_channel
            matter = await resolve_matter_for_channel(channel_name, alfred_deps.project_pages)
            if matter:
                m_name = matter.get("Project name") or matter.get("name") or ""
                m_status = matter.get("Status") or matter.get("status") or ""
                m_stage = matter.get("Case Stage") or matter.get("case_stage") or ""
                m_deadline = (
                    matter.get("Next Court Deadline") or matter.get("next_court_deadline") or ""
                )
                m_summary = matter.get("Summary") or matter.get("summary") or ""
                matter_context = (
                    f"Matter: {m_name}\n"
                    f"Status: {m_status}\n"
                    f"Stage: {m_stage}\n"
                    f"Next Court Deadline: {m_deadline}\n"
                    f"Summary: {m_summary[:600] if m_summary else '(no summary on file)'}"
                )
    except Exception as e:
        logger.debug("connect-mode: could not resolve matter: %s", e)

    # ── Phase 1: Immediate joining message ────────────────────────────────────
    join_ts = None
    join_text = (
        ":wave: Just joined. Reading up on this channel's history and Notion context now — "
        "I'll share what I found in :thread:"
    )
    if slack_client:
        try:
            resp = await slack_client.chat_postMessage(channel=channel, text=join_text)
            join_ts = resp.get("ts")
        except Exception as e:
            logger.error("connect-mode: could not post joining message: %s", e)
            return

    # ── Build intro prompt ────────────────────────────────────────────────────
    intro_parts = [
        "You are Alfred, KLG's AI executive assistant. You just joined a Slack channel.",
        "Write a concise introduction in Slack markdown (*bold*, _italic_) following this structure:",
        "",
        "Start with: 'I'm Alfred — KLG's AI assistant.'",
        "",
    ]
    if matter_context:
        intro_parts += [
            "Then write 2-3 sentences summarizing the matter's current state from the context below. "
            "Include the status, stage, and next deadline.",
            "",
            "Then write: 'Here are 3 things I can pick up:' followed by 3 numbered task offers "
            "specific to this matter's current stage. Examples by stage:",
            "  - Intake/Setup: conflict check, engagement letter, task seeding",
            "  - Brief Preparation: response plan, record navigator, authority map",
            "  - Cites/Review: cite check, style guide check, appendix audit",
            "  - Oral Argument: panel intelligence, Q&A prep, moot court script",
            "",
            f"MATTER CONTEXT FROM NOTION:\n{matter_context}",
        ]
    else:
        intro_parts += [
            "Then write: 'Here are 3 things I can pick up:' followed by 3 general KLG capabilities "
            "(brief drafting, research, deadline and task management).",
        ]
    if channel_history_text:
        intro_parts.append(f"\nRECENT CHANNEL HISTORY:\n{channel_history_text}")
    intro_parts.append("\nKeep the total under 250 words. Lead with substance — no preamble.")

    intro_prompt = "\n".join(intro_parts)

    # ── Phase 2: Rich intro in thread ─────────────────────────────────────────
    intro_text = (
        "I'm Alfred — KLG's AI assistant. I'm now connected to this channel.\n\n"
        "Here are 3 things I can pick up:\n"
        "1. Research and case analysis\n"
        "2. Brief drafting and review\n"
        "3. Deadline tracking and task management"
    )
    try:
        result = await run_with_fallback(intro_prompt, deps=alfred_deps)
        intro_text = result.output
    except Exception as e:
        logger.error("connect-mode: Alfred intro generation failed: %s", e)

    if slack_client:
        try:
            post_kwargs: dict = {"channel": channel, "text": intro_text}
            if join_ts and not channel.startswith("D"):
                post_kwargs["thread_ts"] = join_ts
            await slack_client.chat_postMessage(**post_kwargs)
        except Exception as e:
            logger.error("connect-mode: could not post intro: %s", e)

    # ── Phase 3: Behavior preference note in same thread ─────────────────────
    if slack_client and join_ts and not channel.startswith("D"):
        behavior_note = (
            "I can be as proactive or as quiet as you like. Mostly I stay in the background "
            "and chime in when I can clearly help. @mention me or say 'Alfred,' when you need something."
        )
        try:
            await slack_client.chat_postMessage(
                channel=channel,
                text=behavior_note,
                thread_ts=join_ts,
            )
        except Exception as e:
            logger.debug("connect-mode: could not post behavior note: %s", e)

    logger.info("Slack ← Alfred (connect): join + intro + behavior posted in #%s", channel_name or channel)


async def _fetch_conversation_history(
    slack_client,
    channel: str,
    thread_ts: str,
    event_ts: str,
) -> list:
    """
    Fetch prior Slack messages and return them as pydantic-ai message history.

    DMs: fetch recent channel history (last 20 messages).
    Threads: fetch thread replies if the current message is a reply in an
             existing thread (thread_ts differs from event_ts).
    Top-level channel messages: return [] — no prior context to thread over.

    Degrades gracefully to [] if the Slack client is unavailable or lacks scopes.
    """
    if not slack_client:
        return []

    from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart

    try:
        is_dm = channel.startswith("D")
        is_thread_reply = thread_ts and thread_ts != event_ts

        if is_dm:
            resp = await slack_client.conversations_history(channel=channel, limit=20)
            raw_messages = list(reversed(resp.get("messages", [])))
        elif is_thread_reply:
            resp = await slack_client.conversations_replies(
                channel=channel, ts=thread_ts, limit=20
            )
            raw_messages = resp.get("messages", [])
        else:
            # Top-level channel @mention — read recent channel history so Alfred
            # has the same conversational context Claude.ai shows in its responses.
            resp = await slack_client.conversations_history(channel=channel, limit=15)
            raw_messages = list(reversed(resp.get("messages", [])))

        history = []
        for msg in raw_messages:
            if msg.get("ts") == event_ts:
                continue  # Skip the current message — it's passed separately
            text = (msg.get("text") or "").strip()
            if not text:
                continue
            clean = _strip_mention(text)
            if not clean:
                continue
            if msg.get("bot_id"):
                history.append(ModelResponse(parts=[TextPart(content=clean)]))
            else:
                history.append(ModelRequest(parts=[UserPromptPart(content=clean)]))

        return history

    except Exception as e:
        logger.debug("Could not fetch Slack history (continuing without): %s", e)
        return []


async def _extract_slack_file_text(files: list) -> str:
    """
    Download and extract text from Slack file attachments.

    Uses the bot token to download private Slack files. Handles PDF, .txt,
    .md, and .docx. Binary files get a placeholder so Alfred knows they exist.
    Caps at 2 files and 15,000 chars per file to keep context manageable.
    """
    import httpx
    import tempfile
    import os

    from config import settings
    if not settings.slack_bot_token:
        return ""

    from alfred.skills.base import skill_read_file_text

    texts: list[str] = []
    for f in files[:2]:
        name = f.get("name", "file")
        url = f.get("url_private_download") or f.get("url_private", "")
        mimetype = f.get("mimetype", "")
        if not url:
            continue
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {settings.slack_bot_token}"},
                )
                resp.raise_for_status()

            ext = os.path.splitext(name)[1].lower() or ".bin"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(resp.content)
                tmp_path = tmp.name

            try:
                extracted = skill_read_file_text(tmp_path)
                if extracted:
                    texts.append(f"[Attached file: {name}]\n{extracted[:15000]}")
                else:
                    texts.append(
                        f"[Attached file: {name} ({mimetype}) — "
                        "content could not be extracted. Ask the user to upload via the Alfred web UI.]"
                    )
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        except Exception as e:
            logger.warning("Slack file download failed for %s: %s", name, e)
            texts.append(f"[Attached file: {name} — download failed.]")

    return "\n\n".join(texts)


def _verify_slack_signature(request: Request, body: bytes) -> None:
    """
    Verify an incoming Slack request using HMAC-SHA256.

    Raises HTTP 401 if the signature doesn't match or the timestamp is too old
    (> 5 minutes, which protects against replay attacks).

    Slack documentation: https://api.slack.com/authentication/verifying-requests-from-slack
    """
    ts = request.headers.get("X-Slack-Request-Timestamp", "")
    slack_sig = request.headers.get("X-Slack-Signature", "")

    # Reject requests older than 5 minutes to block replay attacks
    try:
        if abs(time.time() - float(ts)) > 300:
            raise HTTPException(status_code=401, detail="Slack timestamp too old")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp")

    # Compute expected signature
    sig_basestring = f"v0:{ts}:{body.decode('utf-8')}"
    expected = "v0=" + hmac.new(
        settings.slack_signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, slack_sig):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")


def _strip_mention(text: str) -> str:
    """
    Remove the @mention prefix from a Slack message so Alfred gets clean input.

    Slack encodes mentions as <@USERID>. We strip that and any leading
    punctuation/whitespace so Alfred gets "what's pending on Petersen?"
    rather than "<@U12345> what's pending on Petersen?".
    """
    import re
    # Remove <@USERID> patterns
    cleaned = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    # Remove a leading comma or colon if the user wrote "Alfred, ..."
    cleaned = re.sub(r"^[Aa]lfred[,:]?\s*", "", cleaned).strip()
    return cleaned
