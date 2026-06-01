"""
Model dispatch: sends the routed query to Claude (primary) and optionally
ChatGPT (braiding). Notion context is injected here once the token is available.
"""

import os
import asyncio
from typing import Optional
import anthropic
import httpx

_anthropic = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

CLAUDE_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
BRAIDING_ENABLED = os.getenv("BRAIDING_ENABLED", "true").lower() == "true"


def _build_system_prompt(skill_text: str, notion_context: str = "") -> str:
    parts = [skill_text.strip()]
    if notion_context:
        parts.append(f"\n\n--- MATTER CONTEXT (from Notion) ---\n{notion_context}")
    return "\n".join(parts)


async def _call_claude(system: str, query: str) -> str:
    response = _anthropic.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": query}],
    )
    return response.content[0].text


async def _call_chatgpt(system: str, query: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return ""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": OPENAI_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": query},
                ],
                "max_tokens": 4096,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _fetch_notion_context(matter: str) -> str:
    """
    Pull matter context from Notion. Stub until NOTION_TOKEN is available.
    Replace this body with actual Notion API calls once the integration token exists.
    """
    notion_token = os.getenv("NOTION_TOKEN", "")
    if not notion_token or not matter:
        return ""

    # TODO: query Notion Projects DB for matter matching `matter`,
    # pull deadlines, task list, last Comms Log entry.
    # Return as a structured text block.
    return ""


async def dispatch(
    query: str,
    skill_name: str,
    skill_text: str,
    matter: Optional[str] = None,
    braid: bool = False,
) -> dict:
    # Pull Notion context if a matter was specified
    notion_context = await _fetch_notion_context(matter or "")
    system = _build_system_prompt(skill_text, notion_context)

    if braid and BRAIDING_ENABLED and os.getenv("OPENAI_API_KEY"):
        # Fire Claude and ChatGPT in parallel
        claude_task = asyncio.create_task(_call_claude(system, query))
        gpt_task = asyncio.create_task(_call_chatgpt(system, query))
        claude_response, gpt_response = await asyncio.gather(claude_task, gpt_task)
        return {
            "response": claude_response,
            "braided_response": gpt_response,
            "model": CLAUDE_MODEL,
        }

    response = await _call_claude(system, query)
    return {
        "response": response,
        "model": CLAUDE_MODEL,
    }
