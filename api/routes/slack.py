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
    body_bytes = await request.body()

    # Verify the request came from Slack before doing anything else
    if settings.slack_signing_secret:
        _verify_slack_signature(request, body_bytes)

    import json
    payload = json.loads(body_bytes)

    # ── URL Verification (Slack setup challenge) ──────────────────────────────
    if payload.get("type") == "url_verification":
        return JSONResponse({"challenge": payload.get("challenge", "")})

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

        # Only process app_mention and direct-message events
        is_mention = event_type == "app_mention"
        is_direct_message = event_type == "message" and text.lower().startswith("alfred,")

        if not (is_mention or is_direct_message):
            return JSONResponse({"ok": True})

        # Strip the @mention prefix so Alfred gets clean input
        clean_text = _strip_mention(text)

        if not clean_text:
            return JSONResponse({"ok": True})

        # Get the user's Slack display name for logging
        user_id = event.get("user", "unknown")

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
    """
    from alfred.agent import AlfredAgent

    try:
        result = await AlfredAgent.run(message, deps=alfred_deps)
        response_text = result.output

        if slack_client:
            await slack_client.chat_postMessage(
                channel=channel,
                text=response_text,
                thread_ts=thread_ts,
            )
            logger.info("Slack ← Alfred: replied in thread %s", thread_ts)

    except Exception as e:
        logger.error("Slack Alfred reply error for user %s: %s", user_id, e, exc_info=True)
        if slack_client:
            try:
                await slack_client.chat_postMessage(
                    channel=channel,
                    text=(
                        "Alfred encountered an error processing your request. "
                        "Try again or open the web UI directly."
                    ),
                    thread_ts=thread_ts,
                )
            except Exception:
                pass


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
