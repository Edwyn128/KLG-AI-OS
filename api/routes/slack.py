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
        history = await _fetch_conversation_history(
            slack_client=slack_client,
            channel=channel,
            thread_ts=thread_ts,
            event_ts=event_ts,
        )
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
        err_type = type(e).__name__
        err_msg = str(e)[:300]
        logger.error("Slack Alfred reply error for user %s: %s", user_id, e, exc_info=True)
        if slack_client:
            try:
                await slack_client.chat_postMessage(
                    channel=channel,
                    text=(
                        f"Alfred hit an error: `{err_type}: {err_msg}`\n"
                        "Try again or open the web UI directly."
                    ),
                    thread_ts=thread_ts,
                )
            except Exception:
                pass


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
            return []

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
