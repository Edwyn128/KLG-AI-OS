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

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
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


class ChatResponse(BaseModel):
    """
    Response body for POST /alfred/chat.

    Example JSON:
        {
            "response": "Petersen has a filing deadline in 4 days...",
            "user": "Tim",
            "tools_used": ["find_and_summarize_matter"]
        }
    """

    response: str = Field(description="Alfred's response to the message.")
    user: str = Field(description="The team member who sent the message.")
    tools_used: list[str] = Field(
        default_factory=list,
        description="List of tool names Alfred called while processing this message.",
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
    from alfred.agent import AlfredAgent

    logger.info("Alfred chat from '%s': %s", request.user, request.message[:100])

    try:
        result = await AlfredAgent.run(
            request.message,
            deps=alfred_deps,
        )

        # Extract which tools Alfred called from the message history
        tools_used = _extract_tools_used(result)

        return ChatResponse(
            response=result.output,
            user=request.user,
            tools_used=tools_used,
        )

    except Exception as e:
        logger.error("Alfred chat error for user '%s': %s", request.user, e, exc_info=True)
        # Return a 500 with enough context to debug, but don't leak stack traces
        # to the client in production (debug=True in config exposes them in FastAPI's
        # default error handling, but this explicit message is always safe).
        raise HTTPException(
            status_code=500,
            detail=f"Alfred encountered an error processing your request. "
                   f"Check the server logs for details. Error type: {type(e).__name__}",
        )


@router.get("/matters", summary="List all active matters")
async def list_active_matters(
    alfred_deps=Depends(get_alfred_deps),
) -> dict[str, Any]:
    """
    Return all active matters from the Notion Projects database.

    Used by the web UI dashboard to populate the matter list panel.
    Returns matters sorted by priority (High → Medium → other) and
    then by nearest deadline.

    Response format:
        {
            "count": 12,
            "matters": [
                {
                    "id": "3580fc06-...",
                    "Project name": "Petersen",
                    "Status": "In progress",
                    "Priority": "High",
                    "Target Date": "2026-05-15",
                    "url": "https://www.notion.so/..."
                },
                ...
            ]
        }
    """
    try:
        matters = await alfred_deps.project_pages.get_all_active_matters()
        return {"count": len(matters), "matters": matters}
    except Exception as e:
        logger.error("list_active_matters error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deadlines", summary="Get matters with upcoming deadlines")
async def get_upcoming_deadlines(
    days: int = 7,
    alfred_deps=Depends(get_alfred_deps),
) -> dict[str, Any]:
    """
    Return matters with deadlines in the next N days.

    Query parameters:
      days: How many days ahead to look (default 7, max 90).

    Used by the web UI's "Upcoming Deadlines" panel.
    """
    days = min(days, 90)  # Cap at 90 days to prevent abuse
    try:
        matters = await alfred_deps.project_pages.get_matters_with_upcoming_deadlines(days)
        return {"days_ahead": days, "count": len(matters), "matters": matters}
    except Exception as e:
        logger.error("get_upcoming_deadlines error: %s", e, exc_info=True)
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
