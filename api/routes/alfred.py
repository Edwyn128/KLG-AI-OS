"""
api/routes/alfred.py — FastAPI routes for Alfred (inward executive assistant).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENDPOINTS IN THIS FILE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  POST /alfred/chat
      Send a message to Alfred and get a response.
      This is the primary endpoint — the web UI calls this.
      Alfred decides which tools to use (Notion search, Watch List query, etc.)

  GET  /alfred/matters
      List all active matters from Notion.
      Used by the web UI dashboard to populate the matter list.

  GET  /alfred/deadlines
      Get matters with upcoming deadlines (next 7 days by default).
      Used by the dashboard's "Upcoming" panel.

  POST /alfred/agents/deadline-watch
      Manually trigger the daily deadline-watch agent.
      Useful for testing without waiting for the cron schedule.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# APIRouter groups all Alfred routes under the /alfred prefix.
# The router is registered in main.py with app.include_router().
router = APIRouter(prefix="/alfred", tags=["Alfred"])


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================
# Pydantic models define what the API accepts and returns.
# FastAPI validates incoming requests against these models automatically —
# if a required field is missing, FastAPI returns a 422 with a clear error.


class ChatRequest(BaseModel):
    """
    Request body for POST /alfred/chat.

    Example JSON:
        {
            "message": "Alfred, what's pending on Petersen this week?",
            "user": "Tim"
        }
    """

    message: str = Field(
        ...,
        description="The message to send to Alfred.",
        min_length=1,
        max_length=4000,
        examples=["Alfred, what's pending on Petersen?"],
    )
    user: str = Field(
        default="Team",
        description="The name of the team member sending the message. Used for logging.",
        examples=["Tim", "Edwyn", "Brittney", "Ted"],
    )
    model: str = Field(
        default="",
        description=(
            "Model to use for this request. Empty string = Claude default. "
            "Supported: 'claude-sonnet-4-6', 'claude-opus-4-8', "
            "'gpt-4o', 'gpt-4o-mini', 'gemini-2.0-flash', 'gemini-1.5-pro', "
            "'sonar-pro', 'sonar-reasoning-pro'."
        ),
    )
    history: list[Any] = Field(
        default_factory=list,
        description=(
            "Serialized conversation history returned by the previous response. "
            "Pass it back unchanged to give Alfred context from earlier in the session. "
            "Send an empty list (or omit) to start a fresh conversation."
        ),
    )


class ChatResponse(BaseModel):
    """
    Response body for POST /alfred/chat.

    Example JSON:
        {
            "response": "Petersen has a filing deadline in 4 days...",
            "user": "Tim",
            "tools_used": ["find_and_summarize_matter"],
            "history": [...]
        }
    """

    response: str = Field(description="Alfred's response to the message.")
    user: str = Field(description="The team member who sent the message.")
    tools_used: list[str] = Field(
        default_factory=list,
        description="List of tool names Alfred called while processing this message.",
    )
    history: list[Any] = Field(
        default_factory=list,
        description=(
            "Updated conversation history. Store this client-side and send it "
            "back as ChatRequest.history on the next message to maintain context."
        ),
    )


# =============================================================================
# DEPENDENCY: Alfred Dependencies
# =============================================================================
# These dependency functions extract the initialized objects from FastAPI's
# app.state (where main.py stores them at startup) and provide them to
# route handlers. Using Depends() keeps the route handlers clean — they
# don't need to know where the NotionBridge or ProjectPages came from.


def get_alfred_deps(request: Request):
    """
    FastAPI dependency that returns Alfred's dependencies from app state.

    The NotionBridge, ProjectPages, and WatchList objects are created once
    in main.py's lifespan() and stored on app.state. This function retrieves
    them so route handlers can use them without creating new connections.

    Usage in a route:
        @router.post("/chat")
        async def chat(req: ChatRequest, deps=Depends(get_alfred_deps)):
            result = await AlfredAgent.run(req.message, deps=deps)
    """
    return request.app.state.alfred_deps


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/chat", response_model=ChatResponse, summary="Send a message to Alfred")
async def chat_with_alfred(
    request: ChatRequest,
    alfred_deps=Depends(get_alfred_deps),
) -> ChatResponse:
    """
    Send a message to Alfred and receive a response.

    Alfred (Claude + tools) reads the message, decides which Notion queries
    to run, and returns a direct, professional answer.

    This is the core endpoint — everything else in the web UI is built
    on top of this.

    Examples of messages Alfred handles well:
      - "What's pending on Petersen?" → reads matter project page
      - "What deadlines do we have this week?" → queries Projects DB
      - "What did Bloodhound find on supersedeas issues?" → queries Watch List
      - "Log that I filed the brief in Smith" → writes to project page

    Rate limiting: Not yet implemented. Future versions should add
    rate limiting per user to prevent accidental runaway usage.
    """
    from alfred.agent import AlfredAgent, resolve_alfred_model, resolve_thinking_settings

    logger.info(
        "Alfred chat from '%s' [model=%s]: %s",
        request.user, request.model or "default", request.message[:100],
    )

    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        model_override = resolve_alfred_model(request.model)
        thinking_settings = resolve_thinking_settings(request.model)

        message_history = []
        if request.history:
            try:
                message_history = ModelMessagesTypeAdapter.validate_python(request.history)
            except Exception:
                message_history = []

        result = await AlfredAgent.run(
            request.message,
            deps=alfred_deps,
            model=model_override,
            model_settings=thinking_settings,
            message_history=message_history,
        )

        tools_used = _extract_tools_used(result)

        new_history: list[Any] = []
        try:
            new_history = ModelMessagesTypeAdapter.dump_python(
                result.all_messages(), mode="json"
            )
        except Exception:
            pass

        chat_response = ChatResponse(
            response=result.output,
            user=request.user,
            tools_used=tools_used,
            history=new_history,
        )

        if alfred_deps.comms_log:
            try:
                from config import settings as _settings
                await alfred_deps.comms_log.log_interaction(
                    user=request.user,
                    agent="alfred",
                    message=request.message,
                    response=result.output,
                    tools_used=tools_used,
                    model=request.model or _settings.alfred_model,
                )
            except Exception:
                pass

        return chat_response

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Alfred chat error for user '%s': %s", request.user, e, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Alfred encountered an error processing your request. "
                   f"Check the server logs for details. Error type: {type(e).__name__}",
        )


@router.post("/chat/stream", summary="Stream Alfred's response token by token")
async def chat_with_alfred_stream(
    request: ChatRequest,
    alfred_deps=Depends(get_alfred_deps),
) -> StreamingResponse:
    """
    Server-Sent Events (SSE) endpoint for Alfred.

    Streams Alfred's response as it is generated so the first words appear
    in ~0.5 seconds rather than waiting for the full response. Tool calls
    (Notion queries, etc.) still execute before text begins streaming — the
    typing indicator covers that gap on the frontend.

    Each SSE message is a JSON object on a `data:` line:
      {"delta": "..."} — incremental text chunk
      {"done": true, "tools_used": [...]} — stream finished
      {"error": "..."} — an error occurred

    The frontend reads these with a fetch + ReadableStream (not EventSource,
    since EventSource does not support POST or Authorization headers).
    """
    from alfred.agent import AlfredAgent, resolve_alfred_model, resolve_thinking_settings
    from config import settings as _settings

    logger.info(
        "Alfred stream from '%s' [model=%s]: %s",
        request.user, request.model or "default", request.message[:100],
    )

    from pydantic_ai.messages import ModelMessagesTypeAdapter

    try:
        model_override = resolve_alfred_model(request.model)
        thinking_settings = resolve_thinking_settings(request.model)
    except ValueError as e:
        async def _err():
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(
            _err(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    message_history = []
    if request.history:
        try:
            message_history = ModelMessagesTypeAdapter.validate_python(request.history)
        except Exception:
            message_history = []

    async def generate():
        # Send a ping immediately so Railway's proxy knows this is SSE
        # and won't buffer the response waiting for the connection to close.
        # The frontend ignores lines that don't start with "data:".
        yield ": ping\n\n"

        full_response = ""
        tools_used: list[str] = []
        try:
            # Drive the run with agent.iter() and stream text from EVERY model
            # response — not run_stream(), which locks in the FIRST text part
            # as the final output. With run_stream, a response like
            # "On it — pulling the matter page now." + tool call ends the run
            # after the narration: the tool still executes (so the UI shows a
            # tool badge) but the model is never called again and the actual
            # answer never exists. iter() lets the graph continue through tool
            # calls, so narration streams, tools run, and the post-tool answer
            # streams after it.
            from pydantic_ai.messages import (
                PartDeltaEvent,
                PartStartEvent,
                TextPart,
                TextPartDelta,
            )

            async with AlfredAgent.iter(
                request.message,
                deps=alfred_deps,
                model=model_override,
                model_settings=thinking_settings,
                message_history=message_history,
            ) as agent_run:
                pending_separator = False
                async for node in agent_run:
                    if not AlfredAgent.is_model_request_node(node):
                        continue
                    node_streamed_text = False
                    async with node.stream(agent_run.ctx) as node_stream:
                        async for event in node_stream:
                            # Thinking parts and tool-call parts are skipped;
                            # only visible answer text reaches the client.
                            if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
                                delta = event.part.content
                            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                                delta = event.delta.content_delta
                            else:
                                continue
                            if not delta:
                                continue
                            if pending_separator:
                                pending_separator = False
                                full_response += "\n\n"
                                yield f"data: {json.dumps({'delta': chr(10) * 2})}\n\n"
                            node_streamed_text = True
                            full_response += delta
                            yield f"data: {json.dumps({'delta': delta})}\n\n"
                    # Separate this node's narration from the next response's
                    # text so "pulling it now" and the answer don't run together.
                    if node_streamed_text:
                        pending_separator = True

                result = agent_run.result
                tools_used = _extract_tools_used(result)

            new_history: list = []
            try:
                new_history = ModelMessagesTypeAdapter.dump_python(
                    result.all_messages(), mode="json"
                )
            except Exception:
                pass

            if alfred_deps.comms_log:
                try:
                    await alfred_deps.comms_log.log_interaction(
                        user=request.user,
                        agent="alfred",
                        message=request.message,
                        response=full_response,
                        tools_used=tools_used,
                        model=request.model or _settings.alfred_model,
                    )
                except Exception:
                    pass

            yield f"data: {json.dumps({'done': True, 'tools_used': tools_used, 'history': new_history})}\n\n"

        except Exception as e:
            logger.error("Alfred stream error for '%s': %s", request.user, e, exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


_ACTIVITY_ALLOWED = {"tim", "stu"}


@router.get("/activity", summary="Get recent agent chat activity for the Activity Log tab")
async def get_activity(
    request: Request,
    days: int = 14,
    alfred_deps=Depends(get_alfred_deps),
) -> dict[str, Any]:
    """
    Return recent Alfred/Bloodhound chat interactions for the Activity Log tab.

    Only chat entries — who talked to which agent, what tools ran, which
    model answered. Emails, huddle imports, and other Comms Log rows are
    excluded at the Notion query level (the log tracks what Alfred does and
    which user did it with him, not the firm's full comms stream).

    Query parameters:
      days: Look-back window (default 14, max 60).
    """
    import base64
    from fastapi import HTTPException
    auth = request.headers.get("Authorization", "")
    username = ""
    if auth.startswith("Basic "):
        try:
            username = base64.b64decode(auth[6:]).decode().split(":", 1)[0].lower()
        except Exception:
            pass
    if username not in _ACTIVITY_ALLOWED:
        raise HTTPException(status_code=403, detail="Access restricted.")

    days = min(max(days, 1), 60)

    if not alfred_deps.comms_log:
        return {"count": 0, "entries": [], "days": days}

    try:
        raw = await alfred_deps.comms_log.get_chat_activity(days=days)
    except Exception as e:
        logger.error("get_activity error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    entries = []
    for item in raw[:100]:
        name = item.get("Name") or ""
        notes = item.get("Notes") or ""

        # Parse Notes: "Tools: find_matter, ... | Model: claude-sonnet-4-6 | Agent: alfred"
        tools: list[str] = []
        model = ""
        agent = "alfred"
        for part in notes.split("|"):
            part = part.strip()
            if part.startswith("Tools:"):
                raw_tools = part[6:].strip()
                tools = [
                    t.strip() for t in raw_tools.split(",")
                    if t.strip() and t.strip().lower() != "none"
                ]
            elif part.startswith("Model:"):
                model = part[6:].strip()
            elif part.startswith("Agent:"):
                agent = part[6:].strip()

        # Extract user from "Alfred chat — Tim" → "Tim"
        user = name.split("—")[-1].strip() if "—" in name else ""

        entries.append({
            "id": item.get("id", ""),
            "type": "chat",
            "name": name,
            "created_time": item.get("created_time", ""),
            "user": user,
            "agent": agent,
            "message": (item.get("Email Text") or "")[:300],
            "response_summary": (item.get("Summary") or "")[:300],
            "tools": tools,
            "model": model,
        })

    return {"count": len(entries), "entries": entries, "days": days}


@router.get("/matters", summary="List active matters by category")
async def list_active_matters(
    category: str = "Case Project",
    alfred_deps=Depends(get_alfred_deps),
) -> dict[str, Any]:
    """
    Return active matters from the Notion Projects database.

    Query parameters:
      category: Filter by project category. Default "Case Project" (actual
                client matters). Other valid values: "Case Support",
                "Operations", "Think Tank". Pass "all" to return everything.

    The KLG Projects database contains four distinct categories:
      - Case Project  — active client legal matters
      - Case Support  — research, briefs, support tasks for cases
      - Operations    — firm admin, potential clients, networking, biz dev
      - Think Tank    — CALP podcast, amicus practice, scholarship
    """
    try:
        cat = None if category.lower() == "all" else category
        matters = await alfred_deps.project_pages.get_all_active_matters(category=cat)
        return {"count": len(matters), "category": category, "matters": matters}
    except Exception as e:
        logger.error("list_active_matters error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deadlines", summary="Get matters with upcoming deadlines")
async def get_upcoming_deadlines(
    days: int = 7,
    category: str = "Case Project",
    alfred_deps=Depends(get_alfred_deps),
) -> dict[str, Any]:
    """
    Return matters with deadlines in the next N days.

    Query parameters:
      days: How many days ahead to look (default 7, max 90).

    Used by the web UI's "Upcoming Deadlines" panel.
    """
    days = min(days, 90)
    try:
        cat = None if category.lower() == "all" else category
        matters = await alfred_deps.project_pages.get_matters_with_upcoming_deadlines(
            days=days, category=cat
        )
        return {"days_ahead": days, "category": category, "count": len(matters), "matters": matters}
    except Exception as e:
        logger.error("get_upcoming_deadlines error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/agents/huddle-import",
    summary="Manually trigger the Slack huddle → Notion import",
)
async def trigger_huddle_import(request: Request) -> dict[str, Any]:
    """
    Manually trigger the Slack huddle canvas importer.

    Searches Slack for new huddle summary canvases, checks for duplicates in
    Notion, and creates Comms Log entries for any new huddles found. Posts a
    summary to #klg-systems-development when complete.

    Returns the import result: how many were imported, skipped, and any errors.

    Required Slack scopes: search:read, files:read
    """
    from agents.huddle_import import run_huddle_import

    alfred_deps = request.app.state.alfred_deps
    slack_client = getattr(request.app.state, "slack_client", None)

    try:
        result = await run_huddle_import(
            bridge=alfred_deps.bridge,
            slack_client=slack_client,
        )
        return {
            "status": "success",
            "imported": result["imported"],
            "imported_count": len(result["imported"]),
            "skipped": result["skipped"],
            "errors": result["errors"],
            "diag": result.get("diag", {}),
        }
    except Exception as e:
        logger.error("trigger_huddle_import error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/agents/case-checkin",
    summary="Manually trigger the case check-in agent",
)
async def trigger_case_checkin(request: Request) -> dict[str, str]:
    """
    Manually trigger the case check-in agent.

    Posts a check-in message to each active matter's Slack channel immediately,
    without waiting for the Monday or Thursday schedule. Useful for testing
    channel resolution and Slack connectivity.

    Returns how many matters were posted and how many were skipped.
    """
    from agents.case_checkin import run_case_checkin

    alfred_deps = request.app.state.alfred_deps
    slack_client = getattr(request.app.state, "slack_client", None)

    try:
        await run_case_checkin(
            project_pages=alfred_deps.project_pages,
            slack_client=slack_client,
        )
        return {"status": "success", "detail": "Check-in run complete. See server logs for per-matter results."}
    except Exception as e:
        logger.error("trigger_case_checkin error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/agents/deadline-watch",
    summary="Manually trigger the daily deadline-watch agent",
)
async def trigger_deadline_watch(request: Request) -> dict[str, str]:
    """
    Manually trigger the daily deadline-watch agent.

    Useful for testing the agent output without waiting for the 8 AM cron,
    or for running an on-demand briefing during the day.

    Returns the Slack message text that was sent (or would have been sent
    if Slack is not configured).
    """
    from agents.deadline_watch import run_deadline_watch

    alfred_deps = request.app.state.alfred_deps
    slack_client = getattr(request.app.state, "slack_client", None)

    try:
        message = await run_deadline_watch(
            project_pages=alfred_deps.project_pages,
            slack_client=slack_client,
        )
        return {"status": "success", "message": message}
    except Exception as e:
        logger.error("trigger_deadline_watch error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/agents/weekly-agenda",
    summary="Manually trigger the Monday weekly agenda agent",
)
async def trigger_weekly_agenda(request: Request) -> dict[str, str]:
    """Trigger the weekly agenda — posts all active matters grouped by priority to #case-management."""
    from agents.scheduler import _run_weekly_agenda

    alfred_deps = request.app.state.alfred_deps
    slack_client = getattr(request.app.state, "slack_client", None)

    try:
        await _run_weekly_agenda(
            project_pages=alfred_deps.project_pages,
            slack_client=slack_client,
        )
        return {"status": "success", "detail": "Weekly agenda posted. See #case-management."}
    except Exception as e:
        logger.error("trigger_weekly_agenda error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/agents/hygiene-scan",
    summary="Manually trigger the weekly project hygiene scan",
)
async def trigger_hygiene_scan(request: Request) -> dict[str, str]:
    """Trigger the hygiene scan — surfaces stale matters, missing dates, and owner gaps."""
    from agents.scheduler import _run_hygiene_scan

    alfred_deps = request.app.state.alfred_deps
    slack_client = getattr(request.app.state, "slack_client", None)

    try:
        await _run_hygiene_scan(
            project_pages=alfred_deps.project_pages,
            slack_client=slack_client,
        )
        return {"status": "success", "detail": "Hygiene scan complete. See #case-management."}
    except Exception as e:
        logger.error("trigger_hygiene_scan error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _extract_tools_used(result: Any) -> list[str]:
    """
    Extract the names of tools Alfred called from a Pydantic AI result.

    Pydantic AI stores all messages (including tool call messages) in
    result.all_messages(). We scan those for tool call entries and return
    the unique tool names.

    This powers the "tools_used" field in ChatResponse, which the web UI
    shows to give transparency about what Alfred did behind the scenes.

    Args:
        result: The return value of AlfredAgent.run().

    Returns:
        Deduplicated list of tool names in the order they were called.
    """
    tools: list[str] = []
    seen: set[str] = set()

    try:
        for msg in result.all_messages():
            # Pydantic AI messages have a 'parts' attribute in some versions,
            # or a 'content' attribute. The structure varies slightly across
            # pydantic-ai versions — we handle both to stay resilient.
            parts = getattr(msg, "parts", None) or []
            for part in parts:
                tool_name = getattr(part, "tool_name", None)
                if tool_name and tool_name not in seen:
                    tools.append(tool_name)
                    seen.add(tool_name)
    except Exception:
        # Tool extraction is non-critical — if it fails, return empty list
        pass

    return tools
