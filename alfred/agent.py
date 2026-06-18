"""
alfred/agent.py — Alfred: KLG's firm-wide executive assistant AI agent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT THIS FILE IS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This is the core of Alfred — the Pydantic AI agent that powers the inward-
facing half of the KLG AI OS. It defines:

  1. SYSTEM PROMPT — Alfred's identity, role, firm context, and rules of behavior.
     This is what tells Claude who it is when it runs as Alfred.

  2. DEPENDENCIES — The runtime objects Alfred needs: the Notion bridge, the
     Watch List, and optionally a Slack client. Injected at runtime so tests
     can mock them.

  3. TOOLS — The functions Alfred can call during a conversation. Each tool
     is a Python function decorated with @alfred.tool. Alfred (Claude) decides
     which tools to call based on the user's message, automatically, without
     explicit routing logic.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW PYDANTIC AI AGENTS WORK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. You call `await alfred.run("What's pending on Petersen?", deps=deps)`
  2. Pydantic AI sends the message + system prompt to Claude via the Anthropic API
  3. Claude decides which tools to call (e.g., search_notion, get_matter_summary)
  4. Pydantic AI executes those tools, passing `ctx.deps` so they have access
     to the Notion bridge
  5. Tool results are sent back to Claude as additional context
  6. Claude formulates a final answer and returns it
  7. The whole exchange is in `result.data` (a string) and `result.all_messages()`

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    from alfred.agent import AlfredAgent, AlfredDependencies
    from notion_bridge import NotionBridge
    from notion_bridge.project_pages import ProjectPages
    from notion_bridge.watch_list import WatchList

    bridge = NotionBridge()
    deps = AlfredDependencies(
        bridge=bridge,
        project_pages=ProjectPages(bridge),
        watch_list=WatchList(bridge),
    )

    result = await AlfredAgent.run(
        "Alfred, what's pending on Petersen this week?",
        deps=deps,
    )
    print(result.data)  # Alfred's answer as a string
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from config import settings
from notion_bridge.client import NotionBridge
from notion_bridge.comms_log import CommsLog
from notion_bridge.project_pages import ProjectPages
from notion_bridge.watch_list import WatchList
from sharepoint_bridge.client import SharePointBridge

logger = logging.getLogger(__name__)


# =============================================================================
# DEPENDENCIES (Dependency Injection Container)
# =============================================================================
#
# AlfredDependencies is a dataclass that holds the runtime objects Alfred's
# tools need. Pydantic AI passes this object to every tool call via `ctx.deps`.
#
# WHY DEPENDENCY INJECTION INSTEAD OF MODULE-LEVEL SINGLETONS?
#   If Alfred's tools just imported `notion_bridge` directly at module level,
#   tests would have to patch at the module level — messy and fragile. With
#   dependency injection, a test passes a mock AlfredDependencies with a mock
#   bridge, and the tools use that mock automatically. No patching needed.
#
@dataclass
class AlfredDependencies:
    """
    Runtime dependencies for Alfred's tools.

    These objects are created once (at FastAPI startup) and passed to every
    Alfred.run() call. They represent Alfred's "hands" — the interfaces to
    the systems Alfred can read and write.
    """

    bridge: NotionBridge
    """
    The raw Notion API client. Used by tools that need generic search
    or operations not covered by ProjectPages/WatchList.
    """

    project_pages: ProjectPages
    """
    High-level interface to KLG's matter project pages (Layer 1).
    The most frequently used dependency — almost every Alfred query
    about a matter goes through this.
    """

    watch_list: WatchList
    """
    Interface to Bloodhound's Watch List database. Alfred queries this
    when Tim asks about what Bloodhound has found on a doctrine or issue.
    """

    sharepoint: SharePointBridge | None = None
    """
    SharePoint document library client. Allows Alfred to search and surface
    KLG's filed briefs, exhibits, and correspondence stored in SharePoint.
    Optional — gracefully absent if SharePoint credentials are not configured.
    """

    comms_log: CommsLog | None = None
    """
    Interface to the KLG Comms Log database. Alfred logs every chat
    interaction here so Tim can see what the team has been asking.
    Optional — gracefully absent if NOTION_COMMS_LOG_DB_ID is not set.
    """

    slack_client: Any | None = None
    """
    Slack AsyncWebClient for posting messages to channels and DMs.
    Optional — gracefully absent if SLACK_BOT_TOKEN is not configured.
    """

    conversation_history: list[dict] = field(default_factory=list)
    """
    Optional conversation history for multi-turn sessions.
    Not used by individual tool calls, but available for the API layer
    to persist and replay conversation context across requests.
    """


# =============================================================================
# SYSTEM PROMPT
# =============================================================================
#
# The system prompt is Alfred's identity and operating rules. It runs before
# every conversation and frames how Claude behaves when it's playing Alfred.
#
# WRITING GOOD SYSTEM PROMPTS:
#   - Be specific about the persona and context (who Alfred is, where it operates)
#   - Define the mental model the AI should use (executive-and-dictaphone)
#   - Enumerate constraints clearly (what Alfred should and shouldn't do)
#   - Include firm-specific context that Claude wouldn't otherwise know
#
_ALFRED_SYSTEM_PROMPT = """
You are Alfred, the KLG AI Operating System's inward-facing executive assistant.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHO YOU ARE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are named for Alfred Pennyworth — brilliant, devoted, unflappable.
You run the household and the technology. You know where everything is.
You are the indispensable support to the KLG team.

You serve Tim Kowal (managing attorney), Edwyn (systems partner),
Brittney (paralegal), and Ted (associate). Anyone on the team can
talk to you; you serve the firm, not just one person.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT YOU DO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You are the layer through which the KLG team operates. The team tells
you what they need; you interact with Notion, Slack, and firm databases
on their behalf. Nobody on the team should be pointing and clicking through
software — that is your job.

Your primary workspace is Notion. All active matters have a project page
in Notion. When someone asks about a matter, you find its project page,
read the current state, and give a direct answer — you do not guess.

Bloodhound (your outward-facing counterpart) tracks legal landscape signals.
When you are asked about a doctrine or opposing organization, you can query
the Watch List to surface what Bloodhound has found.

You can also send messages to Slack channels and team members. Use the
send_slack_message tool when the team asks you to notify someone, post
an update to a channel, or ping a colleague about a matter.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW YOU COMMUNICATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Direct and professional. No corporate fluff, no throat-clearing.
- Lead with the answer. Context and caveats come after.
- If you use a tool and find nothing, say so clearly and suggest the
  next step. Do not fabricate matter state.
- When a skill runs (an action that modifies Notion), confirm what
  changed and what comes next. The team wants to know the matter
  moved forward.
- You speak as one trusted colleague to another — not as a chatbot
  announcing its capabilities.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW YOU REASON
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before answering anything non-trivial, think it through. Break the
request into what the user actually needs, decide which tools will get
you there, and plan the sequence before calling them. When tool results
come back, weigh them against the question—if they only partially
answer it, dig further instead of presenting partial findings as if
they were complete.

Reason like a colleague, not a script. Connect facts across matters and
tools: if a deadline lands while the owner is out, say so; if two
matters share an issue Bloodhound is tracking, surface the link. State
the implication, not just the data.

If a request is ambiguous, make the most reasonable reading, act on it,
and note the assumption in one line. Do not interrogate the user with
clarifying questions for routine asks—reserve questions for genuinely
consequential forks (destructive changes, conflicting instructions).

After acting, sanity-check your own answer: does it actually resolve
what was asked? Did you verify rather than assume? If you are not
confident, say what you are unsure about rather than papering over it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SEARCH STRATEGY — READ THIS BEFORE EVERY NOTION LOOKUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Never stop at one search attempt. If the first search returns nothing
useful, you are required to try at least two more approaches before
telling the user you couldn't find it.

NAMES: When searching for a person, the page title almost certainly
uses their full name, not their title. Drop honorifics. "Judge Altman"
→ search "Altman", then "Roy Altman". "Professor Smith" → "Smith".

PHRASES: Long queries compete against themselves. "Judge Altman
Federalist Society event" may rank FedSoc pages above Altman. Break
it: search "Altman" first, then "FedSoc" separately, then combine.

CONTENT VS TITLE: A page titled "FedSoc Event — July" may be exactly
what the user wants even though the name isn't in the title. The
search results include content previews — read them before concluding
a page is irrelevant.

RELATED CONCEPTS: If searching for the person fails, search for the
organization, event type, or date. "Federalist Society", "FedSoc",
the month, the court — any anchor that might appear on the page.

MINIMUM SEARCH PROTOCOL for any person or event query:
  1. Full query as stated
  2. Last name only (or most distinctive single word)
  3. Organization or event type if still nothing
  Only report "not found" after all three attempts return nothing.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTRAINTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Never invent matter state. If you can't find a page, say so.
- Never skip the Notion lookup when asked about a specific matter.
  "I believe Petersen is..." is not acceptable — search first.
- PROACTIVE LOOKUP: When a question mentions a named person, judge,
  case, event, or topic the team may have researched, search Notion
  for it BEFORE you respond — do not offer it as an option after the
  fact. "Do you want me to check Notion?" is not acceptable when you
  could have already checked. Alfred's value is in having already
  looked, not in asking permission to look.
- FINISH THE WORK IN THIS TURN: Never end your response by announcing
  what you are about to do. "Let me find that in Notion" or "I'll pull
  the matter now" is not an answer — it is a stall. You cannot do
  anything after your response ends; there is no background process
  that continues your work. Call the tools NOW, then respond with what
  you found or changed. The only acceptable future-tense ending is a
  question the user must answer before you can safely proceed.
- Prefer to confirm before making structural changes to a project page.
  Routine updates (adding a log note, updating status) can proceed;
  major structural changes (deleting content, restructuring milestones)
  should be confirmed first.
- Client information and matter details are confidential. Do not
  reference matter specifics in any output that leaves the firm's systems.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIRM CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

KLG (Kowal Law Group) is a California appellate litigation firm.
Practice areas: First Amendment, public employee rights, property rights,
constitutional litigation. The firm considers itself half law firm,
half think tank — it produces scholarship, podcast content (CALP), and
has an active amicus practice alongside client matters.

NOTION PROJECT CATEGORIES — the Projects database contains four distinct types.
Always apply the correct mental model when answering:

  "Case Project"  — Active client legal matters with court deadlines. These
                    are the firm's primary work. When someone asks "what are
                    our matters?" or "what cases do we have?", this is what
                    they mean. Examples: Petersen appeal, Sakauye briefing.

  "Case Support"  — Research memos, brief drafts, and support tasks that are
                    tied to a specific Case Project but tracked separately.
                    These often have their own deadlines tied to the parent case.

  "Operations"    — Firm administration, business development, potential client
                    intake, networking, and internal process work. When someone
                    asks about "potential clients" or "pipeline", look here.
                    These are NOT active legal matters.

  "Think Tank"    — CALP podcast episodes, amicus briefs in preparation,
                    and academic scholarship. Separate from client work.

When a user asks about "matters" or "cases" → filter to Case Project.
When a user asks about "potential clients" or "intake" → filter to Operations.
When a user asks about "everything" or "all projects" → include all categories
but group and label them clearly so the distinction is visible.

Paired system: Bloodhound handles the outward surveillance layer
(tracking cases, doctrines, movement organizations). Alfred handles
the inward operational layer (matter management, skill execution,
team coordination). They share Notion as the source-of-truth substrate.
""".strip()


# =============================================================================
# ALFRED AGENT DEFINITION
# =============================================================================

AlfredAgent: Agent[AlfredDependencies, str] = Agent(
    model=AnthropicModel(
        settings.alfred_model,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    ),
    system_prompt=_ALFRED_SYSTEM_PROMPT,
    deps_type=AlfredDependencies,
    output_type=str,
    # Allow the stalled-promise validator below to force up to two
    # continuations before giving up and returning the text as-is.
    output_retries=2,
)


# ── Stalled-promise guard ─────────────────────────────────────────────────────
#
# A plain-text model response ENDS a pydantic-ai run. When the model answers
# "Let me find that in Notion…" instead of calling a tool, that promise becomes
# Alfred's final message and the work never happens — the exact "he says he'll
# look and then stops" failure. This validator detects promise-only responses
# and raises ModelRetry, which sends the run back to the model so it actually
# executes the tools it announced.

_PROMISE_RE = re.compile(
    r"\b(?:"
    r"let me (?!know\b)"                      # "let me check/find/pull…" but not "let me know"
    r"|i(?:'|’)?ll (?:search|check|look|find|pull|grab|get|fetch|query|dig|update|create|add|start|go)"
    r"|i (?:will|am going to|can go)\s"
    r"|i(?:'|’)?m (?:going to|now going|about to)"
    r"|one (?:moment|second|sec)\b"
    r"|give me a (?:moment|minute|second|sec)"
    r"|hold on\b|stand by\b|bear with me"
    r"|(?:searching|checking|looking|pulling|querying) (?:notion|now|for|into)"
    r")",
    re.IGNORECASE,
)

# A genuine answer that merely closes with "let me know if…" is long; a stalled
# promise ("Sure — let me pull up the Petersen page.") is short. The length
# gate keeps completed answers from being retried.
_PROMISE_MAX_LEN = 400


def _looks_like_stalled_promise(text: str) -> bool:
    """True when a final response announces work instead of containing it."""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > _PROMISE_MAX_LEN:
        return False
    if stripped.endswith("?"):
        return False  # a question back to the user is a legitimate turn end
    return bool(_PROMISE_RE.search(stripped))


@AlfredAgent.output_validator
async def _no_stalled_promises(
    ctx: RunContext[AlfredDependencies], output: str
) -> str:
    # Streaming validates partial chunks too ("Let me" may be the start of a
    # fine sentence) — only judge the complete final text.
    if ctx.partial_output:
        return output
    if _looks_like_stalled_promise(output):
        logger.info(
            "Alfred: stalled-promise response detected — forcing continuation. "
            "Response was: %r", output[:120],
        )
        raise ModelRetry(
            "You announced work instead of doing it. Your turn is the ONLY "
            "chance to act — nothing runs after your response ends. Call the "
            "tools you need right now (search Notion, read the page, make the "
            "update), then reply with the actual findings or the result of "
            "the change. Do not describe what you are about to do."
        )
    return output


def resolve_alfred_model(model_str: str):
    """
    Map a model-identifier string from ChatRequest.model to a Pydantic AI
    Model instance suitable for passing as the ``model=`` override in
    AlfredAgent.run() / AlfredAgent.run_stream().

    Returns None when the caller wants the agent's configured default (Claude),
    so the caller can always pass ``model=resolve_alfred_model(req.model)``
    without any extra branching — None is the no-op value.

    Supported identifiers:
      ""                  → None (use agent default)
      "claude-*"          → AnthropicModel override (specific Claude tier)
      "extended-thinking" → None (use default Claude; pair with resolve_thinking_settings)
      "gpt-*"             → OpenAIModel (requires OPENAI_API_KEY)
      "gemini-*"          → GeminiModel (requires GOOGLE_API_KEY)
      "sonar-*"           → Perplexity via OpenAI-compatible API (requires PERPLEXITY_API_KEY)

    Raises ValueError if the requested model's API key is not configured.
    """
    if not model_str or model_str.lower().startswith("claude"):
        if model_str and model_str != settings.alfred_model:
            return AnthropicModel(
                model_str,
                provider=AnthropicProvider(api_key=settings.anthropic_api_key),
            )
        return None  # Use AlfredAgent's configured default

    # Extended thinking uses the default Claude model — just signals thinking mode.
    if model_str.lower() == "extended-thinking":
        return None

    if model_str.lower().startswith("gpt"):
        if not settings.openai_api_key:
            raise ValueError(
                "OpenAI API key not configured. Set OPENAI_API_KEY in Railway "
                "env vars to enable GPT models."
            )
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIModel(
            model_str,
            provider=OpenAIProvider(api_key=settings.openai_api_key),
        )

    if model_str.lower().startswith("gemini"):
        if not settings.google_api_key:
            raise ValueError(
                "Google API key not configured. Set GOOGLE_API_KEY in Railway "
                "env vars to enable Gemini models."
            )
        from pydantic_ai.models.gemini import GeminiModel
        from pydantic_ai.providers.google import GoogleProvider
        return GeminiModel(
            model_str,
            provider=GoogleProvider(api_key=settings.google_api_key),
        )

    if model_str.lower().startswith("sonar"):
        if not settings.perplexity_api_key:
            raise ValueError(
                "Perplexity API key not configured. Set PERPLEXITY_API_KEY in Railway "
                "env vars to enable Perplexity Sonar models."
            )
        from pydantic_ai.models.openai import OpenAIModel
        from pydantic_ai.providers.openai import OpenAIProvider
        return OpenAIModel(
            model_str,
            provider=OpenAIProvider(
                api_key=settings.perplexity_api_key,
                base_url="https://api.perplexity.ai",
            ),
        )

    logger.warning("Unknown model identifier '%s' — falling back to Claude default.", model_str)
    return None


def resolve_thinking_settings(model_str: str):
    """
    Return ModelSettings controlling how deeply the model reasons on this request.

    Alfred reasons by default. Every Claude request runs with adaptive thinking:
    the model decides per request whether and how much to deliberate before
    answering, the same mechanism Claude Code uses. Multi-step questions get
    genuine internal reasoning (planning tool calls, weighing results, catching
    gaps); trivial ones stay fast. Thinking tokens never reach the user — both
    routes surface only the final answer, and pydantic-ai's stream_text()
    filters thinking deltas on the SSE path.

    Mapping:
      "" or "claude-*"     → adaptive thinking, model-default effort
                             (on pre-4.6 Claude models pydantic-ai translates
                             this to a budget_tokens config automatically)
      "extended-thinking"  → deep-reasoning mode: adaptive thinking at the
                             highest supported effort, larger output ceiling,
                             for hard analytical work
      "gpt-*" / "gemini-*" / "sonar-*" → None (those providers manage their
                             own reasoning; an unsupported reasoning flag
                             would 400 on non-reasoning models like gpt-4o)
    """
    from pydantic_ai.settings import ModelSettings

    s = (model_str or "").strip().lower()

    if s == "extended-thinking":
        # 'xhigh' maps to output_config effort xhigh where supported, else 'max'.
        # max_tokens must leave headroom for thinking + answer.
        return ModelSettings(thinking="xhigh", max_tokens=32000)

    if not s or s.startswith("claude"):
        # thinking=True → {'type': 'adaptive'} on 4.6+ models. Effort is left
        # at the model default so simple lookups stay cheap and fast.
        return ModelSettings(thinking=True, max_tokens=16000)

    return None


# =============================================================================
# ALFRED'S TOOLS
# =============================================================================
#
# Tools are functions decorated with @AlfredAgent.tool. Claude (Alfred) will
# automatically decide which tools to call based on the user's message.
# The function signature and docstring are what Claude uses to understand
# what each tool does — WRITE THEM CAREFULLY.
#
# IMPORTANT: Tool docstrings are part of the AI's context. They should
# explain what the tool does in plain English, what arguments mean, and
# what the return value looks like. Claude reads these to decide whether
# to call the tool.


@AlfredAgent.tool
async def find_and_summarize_matter(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
) -> str:
    """
    Find a KLG matter project page by name and return its full current state.

    Use this when the user asks about a specific matter (e.g., "What's the
    status on Petersen?", "What's pending on the Smith matter?", "Tell me
    about Sakauye."). This is your primary tool for matter-related questions.

    The summary includes:
      - Current status (In progress, Review needed, Blocked, etc.)
      - Priority level
      - Target date / next court deadline
      - Summary property
      - Full page body content (case notes, current theory, open questions)

    Args:
        matter_name: The name or partial name of the matter to look up.
                     Example: "Petersen", "Smith v. City", "Sakauye"

    Returns:
        A formatted text summary of the matter's current state, ready to
        read aloud or present to the user. Returns a clear "not found"
        message if no matching matter exists.
    """
    matter = await ctx.deps.project_pages.find_matter(matter_name)

    if not matter:
        return (
            f"I searched Notion for '{matter_name}' and found no matching matter. "
            f"The matter may use a different name in Notion, or it may not have "
            f"a project page yet. Try a different search term, or let me know "
            f"if you want me to create a new project page."
        )

    summary = await ctx.deps.project_pages.get_matter_summary(matter["id"])
    return summary


@AlfredAgent.tool
async def get_upcoming_deadlines(
    ctx: RunContext[AlfredDependencies],
    days_ahead: int = 7,
) -> str:
    """
    Get all KLG matters with deadlines in the next N days.

    Use this when the user asks about upcoming deadlines, what's due soon,
    what needs attention this week, or for a morning briefing on pressing matters.

    Args:
        days_ahead: How many days ahead to look. Default is 7 (one week).
                    Use 14 for a two-week horizon, 30 for the full month ahead.

    Returns:
        A formatted list of matters with upcoming deadlines, sorted soonest first.
        Each entry shows the matter name, deadline date, status, and priority.
        Returns "No matters with deadlines in the next N days" if none found.
    """
    matters = await ctx.deps.project_pages.get_matters_with_upcoming_deadlines(days_ahead)

    if not matters:
        return f"No matters with deadlines in the next {days_ahead} days."

    lines = [f"Matters with deadlines in the next {days_ahead} days ({len(matters)} total):\n"]
    for m in matters:
        name = m.get("Project name", "Unknown matter")
        deadline = m.get("date:Target Date:start", m.get("Target Date", "No date"))
        status = m.get("Status", "Unknown")
        priority = m.get("Priority", "")
        url = m.get("url", "")
        lines.append(
            f"  • {name}\n"
            f"    Deadline: {deadline} | Status: {status} | Priority: {priority}\n"
            f"    Notion: {url}\n"
        )

    return "\n".join(lines)


@AlfredAgent.tool
async def search_notion(
    ctx: RunContext[AlfredDependencies],
    query: str,
) -> str:
    """
    Full-text search across all Notion pages the integration can access.

    Use this for general knowledge questions about the firm's Notion workspace —
    finding documents, research memos, skills documentation, anything that isn't
    specifically a matter project page. For matter-specific questions, prefer
    find_and_summarize_matter() instead (it gives richer matter context).

    Examples of when to use this:
      - "Find the supersedeas memo"
      - "Where is the brief postmortem methodology?"
      - "What did we document about the Diller matter?"

    Args:
        query: The search term. Can be a case name, document title, concept,
               or any keyword likely to appear in the relevant Notion page.

    Returns:
        A list of matching pages with their titles and Notion URLs.
        Returns "No results found" if nothing matches.
    """
    # Words that carry no search signal — don't bother searching these alone.
    _STOP = {
        "when", "what", "where", "which", "with", "that", "this", "have",
        "from", "about", "event", "judge", "society", "the", "and", "for",
        "will", "been", "does", "their", "there", "then", "than", "some",
    }

    seen_ids: set[str] = set()
    results: list[dict] = []

    def _add(rows: list[dict]) -> None:
        for r in rows:
            pid = r.get("id", "")
            if pid not in seen_ids:
                results.append(r)
                seen_ids.add(pid)

    # Round 1 — full query
    _add(await ctx.deps.bridge.search(query))

    # Round 2 — if nothing found, try each significant keyword individually.
    # This catches hyphenated titles ("Roy-Altman"), partial-name pages, and
    # cases where a multi-word query deprioritises the most distinctive term.
    if not results:
        keywords = [
            w for w in re.split(r"\W+", query)
            if len(w) >= 4 and w.lower() not in _STOP
        ]
        for kw in keywords:
            _add(await ctx.deps.bridge.search(kw))

    if not results:
        return (
            f"No Notion pages found for '{query}' or its keywords. "
            f"The page may not be connected to the KLG AI OS integration — "
            f"open the page in Notion, click '...' → Connections, and add the integration."
        )

    # Enrich top results with a content snippet so Alfred can judge relevance
    # without opening every page. Cap at 5 and fetch concurrently to avoid
    # sequential Notion API calls stacking up (each ~300ms → 12× = 3.6s+).
    import asyncio as _aio
    top = results[:5]

    async def _snip(r: dict) -> str:
        pid = r.get("id", "")
        if not pid:
            return ""
        try:
            return await ctx.deps.bridge.get_page_snippet(pid)
        except Exception:
            return ""

    snippets = await _aio.gather(*[_snip(r) for r in top])

    lines = [f"Notion search results for '{query}' ({len(results)} found):\n"]
    for r, snippet in zip(top, snippets):
        title = r.get("Project name") or r.get("title") or "(Untitled)"
        url   = r.get("url", "")
        edited = r.get("last_edited_time", "")[:10]
        snippet_line = f"\n    Preview: {snippet}" if snippet else ""
        lines.append(f"  • {title}\n    {url}\n    Last edited: {edited}{snippet_line}")

    if len(results) > 5:
        lines.append(f"\n  ... and {len(results) - 5} more results.")

    return "\n".join(lines)


@AlfredAgent.tool
async def get_bloodhound_watch_list(
    ctx: RunContext[AlfredDependencies],
    tier: str | None = None,
    issue_keyword: str | None = None,
) -> str:
    """
    Query Bloodhound's Watch List for cases being actively tracked.

    Use this when the user asks what Bloodhound has found on a doctrine,
    an issue area, or a specific type of case. Also useful for "what is
    Bloodhound tracking right now?" status questions.

    Examples of when to use this:
      - "Alfred, what did Bloodhound flag this week?"
      - "What's Bloodhound tracking on supersedeas issues?"
      - "Are we watching any PLF cases?"

    Args:
        tier: Optional tier filter. "1" for highest-priority KLG core issues,
              "2" for adjacent doctrine, "3" for ambient monitoring.
              If None, returns all tiers.
        issue_keyword: Optional keyword to filter by issue area name.
                       Example: "First Amendment", "supersedeas"
                       Currently does client-side filtering (Notion's
                       multi_select filter requires exact matches).

    Returns:
        A formatted list of Watch List entries with case name, court, tier,
        status, and KLG nexus note. Returns "Watch List is empty" if nothing
        is being tracked.
    """
    cases = await ctx.deps.watch_list.get_active_cases(tier=tier)

    if not cases:
        tier_str = f" (Tier {tier})" if tier else ""
        return f"Bloodhound's Watch List{tier_str} is currently empty."

    # Client-side keyword filter if requested
    if issue_keyword:
        keyword_lower = issue_keyword.lower()
        cases = [
            c for c in cases
            if any(
                keyword_lower in area.lower()
                for area in (c.get("Issue Area") or [])
            )
        ]
        if not cases:
            return f"No Watch List cases found matching issue keyword '{issue_keyword}'."

    tier_str = f" (Tier {tier} only)" if tier else ""
    lines = [f"Bloodhound Watch List{tier_str} — {len(cases)} active cases:\n"]

    for case in cases:
        name = case.get("Case Name", "Unknown")
        court = case.get("Court", "N/A")
        case_tier = case.get("Tier", "?")
        status = case.get("Status", "Watching")
        issues = ", ".join(case.get("Issue Area") or []) or "N/A"
        nexus = case.get("KLG Nexus Note", "")
        url = case.get("url", "")

        entry = (
            f"  • {name} ({court}) — Tier {case_tier}, {status}\n"
            f"    Issues: {issues}\n"
        )
        if nexus:
            entry += f"    KLG Nexus: {nexus}\n"
        entry += f"    Notion: {url}"
        lines.append(entry)

    return "\n".join(lines)


@AlfredAgent.tool
async def log_action_to_matter(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    skill_name: str,
    action_description: str,
) -> str:
    """
    Write a timestamped action note to a matter's project page.

    Use this when completing work on a matter — after drafting a document,
    after a filing, after a Bloodhound triage session tied to a specific matter.
    This keeps the matter's project page current without the team having to
    manually update it.

    Args:
        matter_name:        The name of the matter to log to.
        skill_name:         The name of the skill or action that was executed.
                            Use the formal skill name (e.g., "klg-brief-elevation")
                            or a descriptive label (e.g., "Alfred manual action").
        action_description: A one-to-two sentence description of what was done.
                            Be specific: "Drafted respondent's brief cover page
                            and uploaded to SharePoint folder." not "Worked on brief."

    Returns:
        Confirmation that the note was logged, with the matter's Notion URL.
    """
    matter = await ctx.deps.project_pages.find_matter(matter_name)

    if not matter:
        return (
            f"Could not find matter '{matter_name}' in Notion to log the action. "
            f"Check the matter name and try again."
        )

    await ctx.deps.project_pages.log_skill_action(
        page_id=matter["id"],
        skill_name=skill_name,
        action_summary=action_description,
    )

    return (
        f"Logged to {matter.get('Project name', matter_name)}:\n"
        f"  {action_description}\n"
        f"  Notion: {matter.get('url', 'N/A')}"
    )


@AlfredAgent.tool
async def get_team_workload(
    ctx: RunContext[AlfredDependencies],
    person_name: str,
) -> str:
    """
    Get all active matters assigned to a specific team member.

    Use this when someone asks what a colleague has on their plate, who owns
    a matter, or what's blocking forward progress because of another person's
    pending work.

    Examples of when to use this:
      - "Alfred, what's on Brittney's plate?"
      - "What matters does Ted own right now?"
      - "What's blocking me that Brittney is handling?"

    Args:
        person_name: Name or partial name of the team member. Case-insensitive.
                     Examples: "Brittney", "Tim", "Ted", "Edwyn"

    Returns:
        A formatted list of active matters assigned to that person — status,
        priority, and deadline for each. Returns a clear message if none found.
    """
    matters = await ctx.deps.project_pages.get_all_active_matters()

    name_lower = person_name.lower()
    assigned = [
        m for m in matters
        if any(
            name_lower in owner.lower()
            for owner in (m.get("Owner") or [])
        )
    ]

    if not assigned:
        return (
            f"No active matters found assigned to '{person_name}'. "
            f"They may have no active matters, or the Owner field in Notion "
            f"uses a different name."
        )

    lines = [f"Active matters assigned to {person_name} ({len(assigned)} total):\n"]
    for m in assigned:
        name = m.get("Project name", "Unknown matter")
        status = m.get("Status", "Unknown")
        priority = m.get("Priority", "")
        deadline = m.get("date:Target Date:start", m.get("Target Date", "None set"))
        url = m.get("url", "")
        lines.append(
            f"  • {name}\n"
            f"    Status: {status} | Priority: {priority} | Deadline: {deadline}\n"
            f"    Notion: {url}\n"
        )

    return "\n".join(lines)


@AlfredAgent.tool
async def update_matter_status(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    new_status: str,
) -> str:
    """
    Update the status of a KLG matter project page.

    Use this when the team instructs Alfred to move a matter forward or change
    its stage — e.g., "mark Petersen as done", "move Smith to Paused", "Diller
    is now In progress".

    Valid status values: "Planning", "In progress", "Paused",
                         "Backlog", "Done", "Canceled"

    Args:
        matter_name: The name of the matter to update.
        new_status:  The new status. Must match one of the valid values exactly.

    Returns:
        Confirmation of the change, showing old and new status, with Notion URL.
    """
    matter = await ctx.deps.project_pages.find_matter(matter_name)

    if not matter:
        return (
            f"Could not find matter '{matter_name}' in Notion. "
            f"Check the name and try again."
        )

    old_status = matter.get("Status", "Unknown")
    await ctx.deps.project_pages.update_matter_status(matter["id"], new_status)
    await ctx.deps.project_pages.log_skill_action(
        page_id=matter["id"],
        skill_name="alfred-status-update",
        action_summary=f"Status changed from '{old_status}' to '{new_status}'.",
    )

    return (
        f"{matter.get('Project name', matter_name)}: "
        f"'{old_status}' → '{new_status}'.\n"
        f"Notion: {matter.get('url', 'N/A')}"
    )


@AlfredAgent.tool
async def create_new_matter(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    category: str = "Case Project",
    case_stage: str = "Intake",
    priority: str = "Medium",
    target_date: str = "",
    summary: str = "",
) -> str:
    """
    Open a new matter project page in KLG's Notion Projects database.

    Use this when the team opens a new case or project. This runs the
    klg-matter-intake skill, creating the Layer 1 project page that all
    subsequent Alfred skills and tools will operate against.

    Once created, the matter appears in the Projects database and Alfred can
    immediately start reading and updating it.

    Args:
        matter_name: Name of the matter (e.g., "Smith v. City of LA").
        category:    "Case Project" (default), "Case Support", or "Operations".
        case_stage:  "Intake" (default), "Evaluation", "Consulting and Special
                     Projects", "Trial Court", "Prepare Record",
                     "Briefing — AOB", "Briefing — RB", "Briefing — ARB",
                     "Oral Argument", or "Post-Appeal".
        priority:    "Low", "Medium" (default), or "High".
        target_date: Next key date in ISO format (e.g., "2026-06-30"). Optional.
        summary:     One-paragraph matter description. Optional.

    Returns:
        Confirmation with the new matter's Notion URL and next steps.
    """
    from alfred.skills.klg_matter_intake import KLGMatterIntake
    from alfred.skills.base import SkillContext

    skill = KLGMatterIntake()
    skill_ctx = SkillContext(
        matter_id="",
        matter_name=matter_name,
        matter_summary="",
        matter_props={},
        user_instruction=summary,
        extra={
            "matter_name": matter_name,
            "category": category,
            "case_stage": case_stage,
            "priority": priority,
            "target_date": target_date,
            "summary": summary,
        },
    )

    result = await skill.run(skill_ctx, ctx.deps.project_pages)

    if not result.success:
        return f"Intake failed: {result.summary}"

    return f"{result.output}\n\nNext: {result.next_action}"


@AlfredAgent.tool
async def search_sharepoint(
    ctx: RunContext[AlfredDependencies],
    query: str,
    folder_path: str = "",
) -> str:
    """
    Search KLG's SharePoint document library for briefs, exhibits, and files.

    Use this when the user asks about filed documents, correspondence, or
    anything stored in SharePoint — not in Notion. Examples:
      - "Find the respondent's brief in Petersen"
      - "What's in the Sakauye exhibits folder?"
      - "Find the last brief Tim filed on supersedeas issues"

    Args:
        query:       Search terms — matter name, document type, keywords.
                     Examples: "Petersen respondent brief", "Sakauye exhibits 2026"
        folder_path: Optional subfolder to restrict search, e.g. "/Matters/Petersen".
                     Leave empty to search all of SharePoint.

    Returns:
        A list of matching files with names, paths, dates, and direct links.
        Returns a clear "SharePoint not configured" message if credentials are absent.
    """
    if not ctx.deps.sharepoint:
        return (
            "SharePoint is not configured. Set SHAREPOINT_TENANT_ID, "
            "SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET, and "
            "SHAREPOINT_SITE_URL in .env to enable document search."
        )

    if folder_path:
        items = await ctx.deps.sharepoint.list_folder(folder_path)
        if not items:
            return f"No files found in SharePoint folder '{folder_path}'."

        lines = [f"SharePoint folder '{folder_path}' ({len(items)} items):\n"]
        for item in items:
            icon = "📁" if item["type"] == "folder" else "📄"
            modified = item.get("lastModifiedDateTime", "")[:10]
            lines.append(f"  {icon} {item['name']}  (modified {modified})\n    {item['webUrl']}")
        return "\n".join(lines)

    results = await ctx.deps.sharepoint.search_files(query)
    if not results:
        return f"No SharePoint files found matching '{query}'."

    lines = [f"SharePoint search results for '{query}' ({len(results)} files):\n"]
    for r in results:
        name = r.get("name", "Unknown")
        url = r.get("webUrl", "")
        modified = r.get("lastModifiedDateTime", "")[:10]
        parent = r.get("parentPath", "").split("root:")[-1] or "/"
        lines.append(
            f"  📄 {name}\n"
            f"    Path: {parent}\n"
            f"    Modified: {modified}\n"
            f"    Link: {url}\n"
        )

    return "\n".join(lines)


@AlfredAgent.tool
async def send_slack_message(
    ctx: RunContext[AlfredDependencies],
    channel: str,
    message: str,
) -> str:
    """
    Post a message to a Slack channel or send a direct message to a team member.

    Use this when the team asks Alfred to notify someone, post an update to a
    channel, or ping a colleague. Examples:
      - "Alfred, let Brittney know the Petersen brief is ready for review"
      - "Post to #case-management that Smith has a deadline on Friday"
      - "DM Tim that the Bloodhound scan found something on supersedeas"

    Args:
        channel: The Slack channel name (e.g. "#case-management", "#alfred")
                 or a team member's name (e.g. "Tim", "Brittney"). Channel names
                 should include the # prefix. For DMs, use the person's first name
                 and Alfred will resolve it to their Slack handle if possible.
        message: The message text to send.

    Returns:
        Confirmation that the message was sent, or an error description.
    """
    if not ctx.deps.slack_client:
        return (
            "Slack is not configured on this deployment. "
            "Set SLACK_BOT_TOKEN in Railway env vars to enable Slack messaging."
        )

    resolved = channel.strip().lstrip("@")

    # Channel name — post directly
    if resolved.startswith("#"):
        target = resolved
    # Looks like a raw Slack ID (U.../D.../C...) — use as-is
    elif resolved[:1] in ("U", "D", "C") and len(resolved) > 6:
        target = resolved
    else:
        # Person's name — resolve to their Slack User ID via users.list
        target = None
        try:
            resp = await ctx.deps.slack_client.users_list()
            name_lower = resolved.lower()
            for member in (resp.get("members") or []):
                if member.get("is_bot") or member.get("deleted"):
                    continue
                profile = member.get("profile", {})
                candidates = [
                    profile.get("display_name", ""),
                    profile.get("real_name", ""),
                    profile.get("first_name", ""),
                    member.get("name", ""),
                ]
                if any(name_lower in c.lower() for c in candidates if c):
                    target = member["id"]
                    break
        except Exception as e:
            logger.warning("Slack user lookup failed: %s", e)

        if not target:
            return (
                f"Could not find a Slack user matching '{channel}'. "
                f"Try using their exact Slack display name or a channel like #case-management."
            )

    try:
        response = await ctx.deps.slack_client.chat_postMessage(
            channel=target,
            text=message,
        )
        if response.get("ok"):
            logger.info("Alfred → Slack: sent to %s", target)
            return f"Message sent to {channel}."
        else:
            error = response.get("error", "unknown error")
            return f"Slack returned an error: {error}."
    except Exception as e:
        logger.error("send_slack_message error: %s", e)
        return f"Failed to send Slack message: {type(e).__name__}: {e}"


@AlfredAgent.tool
async def deep_research_with_chatgpt(
    ctx: RunContext[AlfredDependencies],
    research_question: str,
    context_summary: str = "",
) -> str:
    """
    Hand off a complex legal research question to ChatGPT for a long-form memo.

    Use this when Tim asks for a deep-dive research memo that would benefit
    from ChatGPT's extended reasoning or when the question requires synthesizing
    many sources into a 2,000–4,000 word analysis. Examples:
      - "Write a memo on current circuit splits on the Pickering balance test"
      - "Research how other states have applied Garcetti to academic freedom"
      - "Analyze the trend in SCOTUS cert grants on First Amendment public employee cases"

    Alfred handles day-to-day matter queries; this tool escalates to ChatGPT
    for research tasks that benefit from its o1/o3 reasoning models.

    Args:
        research_question: The full research question or memo prompt.
        context_summary:   Optional KLG case context to include (e.g., the matter
                           summary from Notion so ChatGPT understands the stakes).

    Returns:
        ChatGPT's research memo as a string. Note: this output should be reviewed
        by an attorney before relying on it — citations must be verified independently.
    """
    if not settings.openai_api_key:
        return (
            "OpenAI integration is not configured. "
            "Set OPENAI_API_KEY in .env to enable ChatGPT deep research."
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    system_prompt = (
        "You are a senior legal research attorney at Kowal Law Group (KLG), "
        "a California appellate firm specializing in First Amendment, public employee "
        "rights, property rights, and constitutional litigation. "
        "Produce thorough, well-organized legal research memos. "
        "Cite cases accurately — do not invent citations. "
        "Flag any areas where you are uncertain about current state of the law."
    )

    user_message = research_question
    if context_summary:
        user_message = (
            f"Case context from our matter files:\n{context_summary}\n\n"
            f"Research question:\n{research_question}"
        )

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            max_tokens=4000,
            temperature=0.2,
        )

        memo = response.choices[0].message.content or ""
        logger.info(
            "ChatGPT deep research completed: %d tokens used",
            response.usage.total_tokens if response.usage else 0,
        )

        return (
            f"ChatGPT Research Memo\n"
            f"{'='*60}\n"
            f"Question: {research_question[:200]}\n"
            f"{'='*60}\n\n"
            f"{memo}\n\n"
            f"[Attorney review required — verify all citations before relying on this memo.]"
        )

    except Exception as e:
        logger.error("ChatGPT deep research error: %s", e)
        return f"ChatGPT research failed: {type(e).__name__}: {e}"


@AlfredAgent.tool
async def web_search(
    ctx: RunContext[AlfredDependencies],
    query: str,
    search_depth: str = "basic",
) -> str:
    """
    Search the web for current information not found in Notion or SharePoint.

    Use this when the user asks about:
      - Recent case decisions, legal news, or appellate docket developments
      - Public information about opposing parties, judges, or organizations
      - Any question requiring up-to-date external information
      - Current events relevant to a matter or doctrine KLG tracks

    Do NOT use for matter state, project status, or anything in Notion — use
    find_and_summarize_matter or search_notion for internal firm knowledge.

    Args:
        query:        The search query. Be specific — include case names,
                      court names, or statute numbers when relevant.
        search_depth: "basic" (fast, most queries) or "advanced" (slower,
                      deeper results for complex legal research). Default: "basic".

    Returns:
        Web results with titles, URLs, and content summaries. Includes a
        synthesized answer when Tavily can generate one.
    """
    if not settings.tavily_api_key:
        return (
            "Web search is not configured. "
            "Set TAVILY_API_KEY in Railway env vars to enable Alfred's web search. "
            "Get a free key (1,000 searches/month) at https://app.tavily.com"
        )

    import httpx as _httpx

    payload = {
        "api_key": settings.tavily_api_key,
        "query": query,
        "search_depth": search_depth,
        "max_results": 5,
        "include_answer": True,
    }

    async with _httpx.AsyncClient(timeout=20.0) as client:
        try:
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except _httpx.HTTPStatusError as e:
            logger.error("web_search Tavily error: %s", e)
            return f"Web search failed: {e}"
        except Exception as e:
            logger.error("web_search error: %s", e)
            return f"Web search error: {type(e).__name__}: {e}"

    lines = [f"Web search results for: {query}\n"]

    if answer := data.get("answer"):
        lines.append(f"Summary: {answer}\n")

    results = data.get("results", [])
    if not results:
        return f"No web results found for '{query}'."

    for r in results:
        title = r.get("title", "")
        url = r.get("url", "")
        snippet = r.get("content", "")[:300]
        lines.append(f"  • {title}\n    {url}\n    {snippet}\n")

    return "\n".join(lines)


@AlfredAgent.tool
async def read_sharepoint_file(
    ctx: RunContext[AlfredDependencies],
    drive_id: str,
    item_id: str,
    file_name: str = "",
) -> str:
    """
    Read and return the text content of a SharePoint document.

    Use this AFTER search_sharepoint() has returned a file — call this with
    the driveId and driveItemId from the search result to read the actual
    document text. Works for .docx and .txt files. PDFs return a download link.

    Typical pattern:
      1. search_sharepoint("Petersen respondent brief") → returns file list with driveId + driveItemId
      2. read_sharepoint_file(drive_id=..., item_id=..., file_name="brief.docx") → returns text

    Args:
        drive_id:  driveId from a search_sharepoint() result.
        item_id:   driveItemId from a search_sharepoint() result.
        file_name: Filename for display and format detection (e.g. "brief.docx").

    Returns:
        Extracted document text (up to 15,000 characters), or a download link
        for formats that can't be extracted (PDF).
    """
    if not ctx.deps.sharepoint:
        return (
            "SharePoint is not configured. Set SHAREPOINT_TENANT_ID, "
            "SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET, and "
            "SHAREPOINT_SITE_URL in .env to enable document reading."
        )

    content = await ctx.deps.sharepoint.get_file_content(drive_id, item_id, file_name)

    if not content:
        return f"No content returned for file '{file_name}' (driveId={drive_id}, itemId={item_id})."

    label = f"Content of '{file_name}'" if file_name else "Document content"
    return f"{label}:\n\n{content}"


@AlfredAgent.tool
async def run_skill(
    ctx: RunContext[AlfredDependencies],
    skill_name: str,
    instruction: str = "",
    matter_name: str = "",
    file_tokens: list[str] = [],
    extra: dict = {},
) -> str:
    """
    Execute a named KLG skill workflow.

    Use this when the user asks to run one of KLG's structured skills by name
    or by description. Skills are multi-step workflows that read from Notion,
    produce documents or analysis, and write results back to Notion.

    Available skills:
      klg-matter-intake          — Open a new matter project page in Notion
      klg-deep-research-prompts  — Generate tiered ChatGPT Deep Research prompts
                                   from case materials; deliver to Notion research page
      klg-conflict-waiver        — Draft a joint-representation conflict waiver letter
      klg-podcast-guest-prep     — Discover CALP podcast guests (mode=discovery) or
                                   build a full interview prep package (mode=prep)
      klg-style-guide-check      — Review a brief against the KLG Style Guide;
                                   returns conformance report (requires uploaded brief)
      klg-cite-check             — Phase A: citation format audit + Westlaw pull list;
                                   Phase B: verify citations against Westlaw source text

    Args:
        skill_name:   The skill to run (exactly as listed above).
        instruction:  The user's specific instruction for this skill run.
        matter_name:  The matter name to look up in Notion (if the skill needs matter context).
        file_tokens:  Token(s) for files the user uploaded. Obtain these from the
                      "Attached files" note in the message, if present.
        extra:        Additional skill-specific parameters (e.g., phase="B" for klg-cite-check,
                      mode="discovery" for klg-podcast-guest-prep, jurisdiction="California").

    Returns:
        The skill's output as a string, including any Notion page URLs and next steps.
    """
    from alfred.skills import SKILL_REGISTRY
    from alfred.skills.base import SkillContext

    skill = SKILL_REGISTRY.get(skill_name)
    if skill is None:
        available = ", ".join(sorted(SKILL_REGISTRY.keys()))
        return (
            f"Unknown skill '{skill_name}'. Available skills: {available}\n\n"
            "Check the skill name and try again."
        )

    # Resolve matter context from Notion if matter_name provided
    matter_id = ""
    matter_summary = ""
    matter_props: dict = {}

    if matter_name:
        try:
            matter = await ctx.deps.project_pages.find_matter(matter_name)
            if matter:
                matter_id = matter.get("id", "")
                matter_summary = await ctx.deps.project_pages.get_matter_summary(matter_id)
                matter_props = matter
            else:
                logger.info("run_skill: matter '%s' not found in Notion", matter_name)
        except Exception as e:
            logger.warning("run_skill: matter lookup failed for '%s': %s", matter_name, e)

    # Merge file_tokens into extra so skills can access them
    skill_extra = dict(extra)
    if file_tokens:
        skill_extra["file_tokens"] = file_tokens
    if not matter_name and not matter_id:
        skill_extra.setdefault("matter_name", "")

    skill_ctx = SkillContext(
        matter_id=matter_id,
        matter_name=matter_name or skill_extra.get("matter_name", ""),
        matter_summary=matter_summary,
        matter_props=matter_props,
        user_instruction=instruction,
        extra=skill_extra,
    )

    if skill.long_running:
        # Long-running skills return a job ID immediately; the caller polls
        # GET /alfred/jobs/{job_id}. Not yet implemented for non-long-running skills.
        return (
            f"'{skill_name}' is a long-running skill. "
            "Background job execution is available in Phase 3. "
            "For now, this skill must be run directly via POST /alfred/agents/run-skill."
        )

    try:
        result = await skill.run(skill_ctx, ctx.deps.project_pages)
    except Exception as e:
        logger.error("run_skill: '%s' raised an exception: %s", skill_name, e, exc_info=True)
        return f"Skill '{skill_name}' encountered an error: {type(e).__name__}: {e}"

    if result.file_attachments:
        logger.info(
            "run_skill: '%s' produced %d file attachment(s)",
            skill_name, len(result.file_attachments),
        )

    return result.output
