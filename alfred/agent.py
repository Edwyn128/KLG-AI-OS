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

from alfred.model_factory import build_model
from config import settings
from notion_bridge.client import NotionBridge
from notion_bridge.alfred_notes import AlfredNotes
from notion_bridge.comms_log import CommsLog
from notion_bridge.project_pages import ProjectPages
from notion_bridge.system_state import SystemState
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

    alfred_notes: AlfredNotes | None = None
    """
    Alfred's persistent cross-session memory layer.
    Alfred saves facts here (attorney preferences, matter observations,
    opposing counsel patterns) and recalls them in future conversations.
    Optional — gracefully absent if NOTION_ALFRED_NOTES_DB_ID is not set.
    """

    system_state: SystemState | None = None
    """
    Lightweight Notion-backed KV store for persisting system tokens across
    Railway redeploys (e.g., the SharePoint delta link).
    Optional — gracefully absent if NOTION_SYSTEM_STATE_DB_ID is not set.
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

PROJECT TYPE — a finer-grained classification within each category:

  "Appellate Brief"       — Active appellate briefing matter (AOB / RB / ARB / Writ).
                            These have Case Stage set and court deadlines. This is the
                            most time-critical work in the firm.

  "Trial Court Briefing"  — Trial-level brief preparation (motions, oppositions, etc.).

  "Consulting"            — Consulting engagement or special project for an outside client.

  "Admin Project"         — Internal firm administration, process improvement, tooling.

  "CALP Episode"          — California Appellate Law Podcast episode in production.

  "FedSoc Event"          — Federalist Society event KLG is organizing or presenting at.

When the team asks specifically about "briefs" or "briefing work" → filter to
Project Type = "Appellate Brief" (or "Trial Court Briefing" if context calls for it).
Project Type is additive to Category — every Case Project still carries its Category value.

SUPPORT TYPE — present on Case Support entries:
  "Research Pipeline" | "Memos" | "Ad Hoc Task" | "Correspondence"
  Tells you what kind of supporting work this entry represents.

THINK TANK TYPE — present on Think Tank entries:
  "Podcast Research" | "Consulting Project" | "Other Thought Leadership"
  Distinguishes CALP research from amicus/scholarship work.

Paired system: Bloodhound handles the outward surveillance layer
(tracking cases, doctrines, movement organizations). Alfred handles
the inward operational layer (matter management, skill execution,
team coordination). They share Notion as the source-of-truth substrate.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SKILLS — READ THIS SECTION CAREFULLY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You have a library of structured skills you can invoke via run_skill().
Skills are not just tools — they are multi-step workflows that read
matter context, do legal work, and write results back to Notion.

CRITICAL RULE: When a request matches a skill below, invoke run_skill()
immediately. Do NOT try to improvise the same work conversationally.
The skill produces a structured, attorney-ready output; ad hoc text
does not. The team should never have to say "run klg-X" — if the
intent is clear, call the skill.

NATURAL LANGUAGE → SKILL MAPPING:

"can you look at this brief" / "elevate this brief" / "sharpen our
brief" / "review the draft" / "give me feedback on this brief"
  → run_skill("klg-brief-elevation", matter_name=..., file_tokens=...)

"what's the standard of review" / "what standard applies" / "SOR for
this ruling" / "is it de novo?"
  → run_skill("klg-standard-of-review", matter_name=..., instruction=...)

"map the authority" / "case law for this doctrine" / "what does SCOTUS
say about X" / "authority map for Garcetti / Pickering / Penn Central"
  → run_skill("klg-authority-map", matter_name=..., instruction=...)

"frame the issue" / "draft the issue presented" / "how should we
phrase the question" / "what's our issue statement"
  → run_skill("klg-issue-framing", matter_name=..., instruction=...)

"prep for oral argument" / "oral arg prep" / "hard questions I'll face"
/ "moot court questions" / "60-second opener"
  → run_skill("klg-oral-argument-prep", matter_name=..., instruction=...)

"navigate the record" / "what's in the record" / "was this preserved"
/ "find the objection in the record" / "map preserved issues"
  → run_skill("klg-record-navigator", matter_name=..., instruction=...)

"response brief strategy" / "how do we respond to their brief" /
"counter their arguments" / "plan for our RB"
  → run_skill("klg-response-plan", matter_name=..., file_tokens=...)

"audit the appendix" / "what did we miss in the appendix" /
"check the compile folder" / "appendix completeness"
  → run_skill("klg-appendix-audit", matter_name=..., file_tokens=...)

"assess this case" / "should we take this case" / "evaluate this matter"
/ "intake assessment"
  → run_skill("klg-case-assessment", matter_name=..., instruction=...)

"open a new matter" / "create a project page" / "intake this client"
/ "set up the matter in Notion"
  → run_skill("klg-matter-intake", instruction=...)

"draft a conflict waiver" / "joint representation letter" /
"waiver for dual representation"
  → run_skill("klg-conflict-waiver", matter_name=..., instruction=...)

"cite check" / "check the citations" / "citation audit" /
"pull the Westlaw list" / "verify citations"
  → run_skill("klg-cite-check", matter_name=..., file_tokens=...)

"style guide check" / "check for style violations" / "KLG writing check"
/ "banned words" / "review my writing"
  → run_skill("klg-style-guide-check", matter_name=..., file_tokens=...)

"should we file amicus" / "amicus assessment" / "evaluate this case
for amicus" / "worth filing amicus on"
  → run_skill("klg-amicus-assessment", instruction=...)

"research prompts" / "generate deep research prompts" /
"ChatGPT research" / "deep research on this case"
  → run_skill("klg-deep-research-prompts", matter_name=..., instruction=...)

"prep the podcast guest" / "CALP prep" / "podcast episode research"
/ "interview questions for [guest]"
  → run_skill("klg-podcast-guest-prep", instruction=...)

"daily triage" / "run triage" / "what's urgent today" / "morning triage"
/ "what needs my attention" / "workload check" / "priority check"
/ "comms log triage" / "team workload" / "post standup" / "slack standup"
  → run_skill("klg-daily-triage", instruction=...)

"prebill audit" / "pre-bill audit" / "audit the time entries" /
"review the bill before sending" / "check for block billing" /
"billing audit" / "time entry review"
  → run_skill("klg-prebill-audit", matter_name=..., file_tokens=...)

"compile the research" / "research compilation" / "research memo" /
"organize the research notes" / "steps 4 and 5" / "authority list" /
"westlaw verification list" / "research pipeline step 4"
  → run_skill("klg-research-compilation", matter_name=..., instruction=..., file_tokens=...)

"assemble the brief" / "brief assembly" / "draft the introduction" /
"generate the argument section" / "draft the conclusion" /
"write the statement of facts" / "brief content"
  → run_skill("klg-brief-assembly", matter_name=..., instruction=..., file_tokens=...)

"seed tasks for [matter]" / "set up tasks" / "create task list for" /
"populate tasks" / "seed the standard tasks" / "set up the task set"
  → seed_matter_tasks(matter_name=..., matter_type="appellate" or "trial_court")

FILE HANDLING: If the user has attached a file (you will see "Attached
files: filename.pdf [token: ...]" in the message), pass the token in
file_tokens when calling a skill that needs a document.

MATTER NAME: Always pass matter_name when the user mentions a specific
case. The skill layer handles fuzzy matching — pass whatever the user
said, even if partial ("Petersen" is fine, not just "Petersen v. City").

INSTRUCTION: Pass the user's stated detail as instruction — the court,
the ruling, the doctrine name, whatever they specified.

AFTER A SKILL COMPLETES SUCCESSFULLY: If save_note is available in your
tool list, call it with:
  label: "[skill name] — [one-sentence summary of the key finding]"
  body: the top 3 most important findings (keep under 800 chars)
  category: "Matter"
  matter: the matter name
This persists the key output across sessions so you can recall it next
time someone asks about this matter. Skip for failed runs or trivial
lookups (e.g., case-assessment returning "insufficient facts").
""".strip()


# =============================================================================
# ALFRED AGENT DEFINITION
# =============================================================================

AlfredAgent: Agent[AlfredDependencies, str] = Agent(
    model=build_model(settings.alfred_model),
    system_prompt=_ALFRED_SYSTEM_PROMPT,
    deps_type=AlfredDependencies,
    output_type=str,
)




# ── Provider fallback ────────────────────────────────────────────────────────

def _is_billing_error(exc: BaseException) -> bool:
    """Return True if the error warrants a provider fallback (billing/quota/rate-limit)."""
    # pydantic-ai 1.x wraps HTTP failures as ModelHTTPError.
    # 429 = rate-limited / quota-exhausted.
    # 400 with a billing body = credit balance depleted — still worth trying other providers.
    try:
        from pydantic_ai.exceptions import ModelHTTPError
        if isinstance(exc, ModelHTTPError):
            if exc.status_code == 429:
                return True
            if exc.status_code == 400:
                body_str = str(getattr(exc, "body", "") or "").lower()
                return any(p in body_str for p in (
                    "credit balance", "credits", "billing", "payment",
                ))
            return False
    except ImportError:
        pass

    # Legacy / non-pydantic-ai path: string-match.
    msg = str(exc).lower()
    return any(phrase in msg for phrase in (
        "credit balance",
        "insufficient_quota",
        "billing",
        "quota exceeded",
        "rate limit",
        "credits",
        "payment",
    )) and getattr(exc, "status_code", None) in (400, 429, None)


async def run_with_fallback(
    message: str,
    *,
    deps: AlfredDependencies,
    message_history=None,
    model_override=None,
    model_settings=None,
):
    """
    Run AlfredAgent with automatic provider fallback on billing/quota errors.

    Tries alfred_model first, then each model in alfred_model_fallbacks in order.
    Non-billing errors are re-raised immediately without trying fallbacks.

    Args:
        message:          The user message to run.
        deps:             AlfredDependencies for this request.
        message_history:  Optional prior conversation messages.
        model_override:   Explicit model override (from ChatRequest.model). When
                          set, this takes precedence and fallbacks are still applied
                          if that override also exhausts.
        model_settings:   Optional pydantic-ai ModelSettings (e.g. thinking config).
    """
    fallback_names = [
        m.strip()
        for m in settings.alfred_model_fallbacks.split(",")
        if m.strip() and m.strip() != settings.alfred_model
    ]

    # Build the ordered list of models to try: primary first, then fallbacks.
    # model_override (user-selected) replaces the primary slot.
    candidates: list = [model_override]  # None = AlfredAgent's configured default
    for name in fallback_names:
        try:
            candidates.append(build_model(name))
        except (ValueError, ImportError) as e:
            logger.debug("Fallback model '%s' skipped: %s", name, e)

    last_exc: BaseException | None = None
    for i, candidate in enumerate(candidates):
        label = settings.alfred_model if candidate is None else getattr(candidate, "model_name", str(candidate))
        try:
            kwargs: dict = {"deps": deps}
            if message_history:
                kwargs["message_history"] = message_history
            if candidate is not None:
                kwargs["model"] = candidate
            if model_settings is not None:
                kwargs["model_settings"] = model_settings

            result = await AlfredAgent.run(message, **kwargs)
            if i > 0:
                logger.info("run_with_fallback: succeeded on fallback model '%s'", label)
            return result

        except Exception as exc:
            if _is_billing_error(exc):
                logger.warning(
                    "run_with_fallback: model '%s' hit billing/quota error — trying next fallback",
                    label,
                )
                last_exc = exc
                continue
            raise  # non-billing errors propagate immediately

    # All candidates exhausted
    raise RuntimeError(
        f"All configured models exhausted their credits/quota. "
        f"Tried: {settings.alfred_model}, {', '.join(fallback_names)}. "
        f"Last error: {last_exc}"
    ) from last_exc


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
    # No override — use AlfredAgent's configured default
    if not model_str or model_str.lower() == "extended-thinking":
        return None

    # If it matches the current default exactly, no override needed
    if model_str == settings.alfred_model:
        return None

    # Route sonar-* to Perplexity's OpenAI-compatible API
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

    return build_model(model_str)


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
async def update_matter(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    target_date: str = "",
    next_court_deadline: str = "",
    next_deadline_info: str = "",
    case_stage: str = "",
    priority: str = "",
    notes: str = "",
) -> str:
    """
    Update structured fields on a KLG matter project page in Notion.

    Use this when the team asks Alfred to record a deadline, change a case
    stage, update priority, or add a note — without changing the matter status.
    Combine with update_matter_status when both a status and other fields change.

    NATURAL LANGUAGE HANDLING — always attempt reasonable interpretation:
      - Relative dates: convert "next Thursday", "in two weeks", "end of month"
        to ISO YYYY-MM-DD using today's date. Never refuse because the date is
        relative — compute it.
      - Partial matter names: pass whatever the user said to matter_name; the
        search layer handles fuzzy matching ("Petersen" finds "Petersen v. City
        of LA"). Never refuse because the name is partial.
      - Vague stage names: map colloquial phrases to the nearest valid stage
        ("move to briefing" → "Briefing — RB"; "we're in oral arg" →
        "Oral Argument"; "close it out" → "Closed"). When ambiguous between
        AOB/RB/ARB, check matter context or ask one clarifying question.
      - Confirm what you set: after calling the tool, tell the user exactly
        what changed, so they can catch any misinterpretation.

    Examples of when to use this:
      - "Set the deadline on Petersen to July 15th"
      - "Next court deadline for Smith is next Thursday, opening brief due"
      - "Move Diller to briefing"
      - "Mark Williams as high priority"
      - "Note on Portero: co-counsel confirmed filing"
      - "Petersen's oral argument is August 3rd"

    Args:
        matter_name:          The matter to update.
        target_date:          ISO date "YYYY-MM-DD". The primary matter deadline.
                              Pass "" to leave unchanged.
        next_court_deadline:  ISO date "YYYY-MM-DD". The next court-facing deadline.
        next_deadline_info:   Plain text description of what the deadline is
                              (e.g., "Respondent's Brief due", "Oral argument").
        case_stage:           One of: "Intake", "Evaluation", "Consulting and Special
                              Projects", "Trial Court", "Prepare Record",
                              "Briefing — AOB", "Briefing — RB", "Briefing — ARB",
                              "Oral Argument", "Post-Argument", "Closed".
        priority:             "Urgent", "High", "Medium", or "Low".
        notes:                A note appended to the matter page body with a timestamp.

    Returns:
        Confirmation of all changes made, with the matter's Notion URL.
    """
    matter = await ctx.deps.project_pages.find_matter(matter_name)

    if not matter:
        return (
            f"Could not find matter '{matter_name}' in Notion. "
            f"Check the name and try again."
        )

    page_id = matter["id"]
    matter_label = matter.get("Project name", matter_name)
    url = matter.get("url", "N/A")

    await ctx.deps.project_pages.update_matter_properties(
        page_id=page_id,
        target_date=target_date or None,
        next_court_deadline=next_court_deadline or None,
        next_deadline_info=next_deadline_info or None,
        case_stage=case_stage or None,
        priority=priority or None,
        notes=notes or None,
    )

    changes = []
    if target_date:      changes.append(f"Target Date → {target_date}")
    if next_court_deadline: changes.append(f"Next Court Deadline → {next_court_deadline}")
    if next_deadline_info:  changes.append(f"Deadline Info → {next_deadline_info}")
    if case_stage:       changes.append(f"Case Stage → {case_stage}")
    if priority:         changes.append(f"Priority → {priority}")
    if notes:            changes.append(f"Note appended")

    if not changes:
        return f"No changes specified for '{matter_label}'."

    change_log = "\n  ".join(changes)
    await ctx.deps.project_pages.log_skill_action(
        page_id=page_id,
        skill_name="alfred-matter-update",
        action_summary="; ".join(changes),
    )

    return (
        f"Updated {matter_label}:\n"
        f"  {change_log}\n"
        f"Notion: {url}"
    )


@AlfredAgent.tool
async def save_note(
    ctx: RunContext[AlfredDependencies],
    label: str,
    body: str,
    category: str = "Other",
    matter: str = "",
) -> str:
    """
    Save a persistent note to Alfred's memory layer (Alfred Notes in Notion).

    Use this proactively when you learn something worth remembering across
    future conversations:
      - Attorney preferences: "Tim prefers 2-week lead time before oral argument"
      - Matter-specific observations: "Petersen: judge unusually hostile to cert petitions"
      - Opposing counsel patterns: "Garcia firm always files on Friday at 4:58 PM"
      - Firm knowledge: "Brittney handles all CALP scheduling directly"
      - Deadlines that recur: "Court of Appeal requires 5 courtesy copies"

    You do NOT need to be explicitly asked — save notes when you encounter
    facts that would genuinely help you serve the team better in the future.
    Confirm to the user that you saved the note.

    Args:
        label:    Short identifier, e.g. "Tim: prefers firm deadlines" (max 200 chars)
        body:     Full note content. Be specific — vague notes are useless (max 2000 chars)
        category: One of: Preference | Matter | OppCounsel | Deadline | FirmKnowledge | Other
        matter:   Matter name this applies to, or "" for firm-wide notes

    Returns:
        Confirmation that the note was saved, or an error if Alfred Notes is not configured.
    """
    if not ctx.deps.alfred_notes:
        return (
            "Alfred Notes is not configured. "
            "Set NOTION_ALFRED_NOTES_DB_ID in Railway env vars to enable persistent memory. "
            "Instructions: create a Notion database called 'Alfred Notes' with properties "
            "Name (title), Category (select), Matter (text), Body (rich_text), "
            "Recorded By (text), Active (checkbox)."
        )

    user = getattr(ctx.deps, "_current_user", "Alfred")
    page_id = await ctx.deps.alfred_notes.save(
        label=label,
        body=body,
        category=category,
        matter=matter,
        recorded_by=user,
    )

    if not page_id:
        return f"Failed to save note '{label}'. Check Alfred Notes Notion DB configuration."

    scope = f" for {matter}" if matter else " (firm-wide)"
    return f"Note saved{scope}: [{category}] {label}"


@AlfredAgent.tool
async def recall_notes(
    ctx: RunContext[AlfredDependencies],
    matter: str = "",
    category: str = "",
) -> str:
    """
    Recall notes from Alfred's persistent memory layer.

    Use this when:
      - Starting a session about a specific matter — recall what Alfred knows about it
      - A user asks "what do you remember about X?"
      - Context from prior sessions would improve your answer

    Args:
        matter:   Matter name to recall notes for, or "" for all firm-wide notes
        category: Filter by category (Preference / Matter / OppCounsel /
                  Deadline / FirmKnowledge / Other), or "" for all categories

    Returns:
        Formatted list of matching notes, or a message if none are found.
    """
    if not ctx.deps.alfred_notes:
        return "Alfred Notes is not configured (NOTION_ALFRED_NOTES_DB_ID not set)."

    notes = await ctx.deps.alfred_notes.recall(matter=matter, category=category, limit=20)

    if not notes:
        scope = f" for '{matter}'" if matter else ""
        cat_str = f" in category '{category}'" if category else ""
        return f"No notes found{scope}{cat_str}."

    lines = [f"**Alfred Notes ({len(notes)} found):**"]
    for n in notes:
        scope = f" [{n['matter']}]" if n["matter"] else " [firm-wide]"
        lines.append(f"• [{n['category']}{scope}] **{n['label']}**: {n['body']}")

    return "\n".join(lines)


@AlfredAgent.tool
async def create_new_matter(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    category: str = "Case Project",
    case_stage: str = "Intake",
    priority: str = "Medium",
    target_date: str = "",
    summary: str = "",
    matter_type: str = "",
) -> str:
    """
    Open a new matter project page in KLG's Notion Projects database.

    Use this when the team opens a new case or project. This runs the
    klg-matter-intake skill, creating the Layer 1 project page that all
    subsequent Alfred skills and tools will operate against.

    Once created, the matter appears in the Projects database and Alfred can
    immediately start reading and updating it. If matter_type is provided (or
    can be inferred from case_stage), the standard KLG task set is seeded
    automatically and the team is notified in Slack.

    Args:
        matter_name:  Name of the matter (e.g., "Smith v. City of LA").
        category:     "Case Project" (default), "Case Support", or "Operations".
        case_stage:   "Intake" (default), "Evaluation", "Consulting and Special
                      Projects", "Trial Court", "Prepare Record",
                      "Briefing — AOB", "Briefing — RB", "Briefing — ARB",
                      "Oral Argument", or "Post-Appeal".
        priority:     "Low", "Medium" (default), or "High".
        target_date:  Next key date in ISO format (e.g., "2026-06-30"). Optional.
        summary:      One-paragraph matter description. Optional.
        matter_type:  "appellate" or "trial_court". If omitted, inferred from
                      case_stage. Pass explicitly when known.

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

    # Infer matter_type from case_stage if not provided
    resolved_type = matter_type.lower().strip()
    if not resolved_type:
        cs = case_stage.lower()
        if any(k in cs for k in ("appellate", "aob", "briefing", "oral argument", "petition",
                                  "prepare record", "post-appeal", "reply", "respondent")):
            resolved_type = "appellate"
        elif any(k in cs for k in ("trial court", "trial", "motion", "msj", "demurrer")):
            resolved_type = "trial_court"

    # Auto-seed tasks when matter type is known
    seed_note = ""
    if resolved_type in ("appellate", "trial_court"):
        try:
            seed_result = await seed_matter_tasks(ctx, matter_name=matter_name, matter_type=resolved_type)
            seed_note = f"\n\n{seed_result}"
        except Exception as e:
            logger.warning("create_new_matter: task seeding failed: %s", e)
            seed_note = (
                f"\n\nTask seeding failed ({e}). Run: "
                f"'Alfred, seed tasks for {matter_name}, {resolved_type}' to retry."
            )
    else:
        seed_note = (
            "\n\nTo populate the standard task set, specify the matter type:\n"
            f"  'Alfred, seed tasks for {matter_name}, appellate' — or — 'trial_court'"
        )

    return f"{result.output}\n\nNext: {result.next_action}{seed_note}"


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

    # Fetch members once — reused for both channel resolution and @mention rewriting
    members_cache: list = []
    try:
        members_cache = (await ctx.deps.slack_client.users_list()).get("members") or []
    except Exception as e:
        logger.warning("Slack users_list failed: %s", e)

    # Channel name — post directly
    if resolved.startswith("#"):
        target = resolved
    # Looks like a raw Slack ID (U.../D.../C...) — use as-is
    elif resolved[:1] in ("U", "D", "C") and len(resolved) > 6:
        target = resolved
    else:
        # Person's name — resolve to their Slack User ID
        target = None
        name_lower = resolved.lower()
        for member in members_cache:
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

        if not target:
            return (
                f"Could not find a Slack user matching '{channel}'. "
                f"Try using their exact Slack display name or a channel like #case-management."
            )

    # Rewrite @Name mentions in the message body to <@USERID> so they
    # actually ping the person in Slack instead of appearing as plain text.
    import re as _re
    mention_names = _re.findall(r'@([\w][\w .]*?)(?=[^\w.]|$)', message)
    for name in set(mention_names):
        nl = name.lower().strip()
        for member in members_cache:
            if member.get("is_bot") or member.get("deleted"):
                continue
            profile = member.get("profile", {})
            if any(
                nl in (c or "").lower()
                for c in [
                    profile.get("display_name"),
                    profile.get("real_name"),
                    profile.get("first_name"),
                    member.get("name"),
                ]
            ):
                message = _re.sub(
                    rf'@{_re.escape(name)}(?=[^\w.]|$)',
                    f'<@{member["id"]}>',
                    message,
                )
                break

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
    file_tokens: list[str] | None = None,
    extra: dict | None = None,
) -> str:
    """
    Execute a named KLG skill workflow.

    Use this when the user asks to run one of KLG's structured skills by name
    or by description. Skills are multi-step workflows that read from Notion,
    produce documents or analysis, and write results back to Notion.

    Available skills:
      klg-case-assessment        — Assess a client inquiry against full matter context
                                   (Notion, Comms Log, SharePoint, web research) and
                                   draft a recommended reply for attorney review
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
      klg-response-plan          — Draft a response brief strategy memo from the appellant's
                                   opening brief (upload required): argument map, counter-
                                   positions, record strategy, research priorities
      klg-appendix-audit         — Audit a proposed appendix compile folder for
                                   underinclusivity: compare full docket against proposed
                                   inclusions, flag HIGH/MEDIUM/LOW risk excluded documents
                                   (upload docket first, compile folder second)
      klg-brief-elevation        — Elevate a draft brief: theory critique, structure audit,
                                   argument-by-argument feedback, KLG style violations,
                                   and persuasion score (upload draft brief)
      klg-authority-map          — Build a hierarchical authority map for a doctrine:
                                   SCOTUS → 9th Circuit → Cal. courts, with tensions,
                                   brief citation outline, and Westlaw pull list
      klg-issue-framing          — Draft the issue presented in three versions (narrow /
                                   mid / broad), test each against standard of review,
                                   recommend the most persuasive framing
      klg-standard-of-review     — Identify the applicable standard, draft the SOR
                                   statement, analyze preservation, and anticipate
                                   opponent SOR arguments
      klg-oral-argument-prep     — Full oral argument prep: 60-second opener, 10 hardest
                                   questions with answers, record citations, and the one
                                   concession to offer (optionally upload brief)
      klg-amicus-assessment      — Evaluate whether a case warrants a KLG amicus brief:
                                   interest assessment, unique angle, coalition map,
                                   and file/pass recommendation
      klg-record-navigator       — Map the trial record for appellate issues: document
                                   index, preserved issues, harmless error risks, and
                                   a record pull list (upload record docs or describe)
      klg-daily-triage           — Cross-cutting daily operational triage: surface urgent
                                   deadlines, priority conflicts, team workload imbalances,
                                   and comms log items needing action. Modes: full-triage,
                                   priority-check, deadline-audit, comms-log-triage,
                                   workload-check, slack-standup
      klg-prebill-audit          — Audit Clio time-entry CSV exports before finalizing:
                                   flags block billing, thin descriptions, duplicates,
                                   intra-firm conferences, clerical work, vague comms
                                   (upload the CSV before running)
      klg-research-compilation   — Steps 4–5 of the KLG Research Pipeline: compile raw
                                   research notes from Notion into a structured memo and
                                   extract a Westlaw authority list for verification
      klg-brief-assembly         — Generate polished brief content (introduction, argument
                                   sections, conclusion) in KLG house style; actual .docx
                                   assembly requires the brief pipeline scripts

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

    file_tokens = file_tokens or []
    extra = extra or {}

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

    # Pass full deps so skills that need Comms Log, SharePoint, etc. can access them
    skill_extra["deps"] = ctx.deps

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


@AlfredAgent.tool
async def get_matter_tasks(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
) -> str:
    """
    Get all tasks for a named matter from its Notion project page.

    Use this when the user asks about what tasks are pending on a matter,
    what work is assigned to whom, or what stages are complete.

    Args:
        matter_name: The name or partial name of the matter. Example: "Williams", "Amin Mohamed"

    Returns:
        A formatted list of tasks grouped by stage, showing status, assignee, and deadline.
        Returns a "no tasks found" message if the matter has no structured tasks.
    """
    from notion_bridge.tasks import TaskPages

    matter = await ctx.deps.project_pages.find_matter(matter_name)
    if not matter:
        return f"No matter found matching '{matter_name}'. Try a different search term."

    task_pages = TaskPages(ctx.deps.bridge)
    tasks = await task_pages.get_tasks_for_matter(matter["id"])

    if not tasks:
        return (
            f"No structured tasks found for '{matter.get('Project name', matter_name)}'. "
            "Tasks may be stored as free-form notes in the matter page. "
            "Try find_and_summarize_matter to read the full page content."
        )

    display_name = matter.get("Project name", matter_name)
    lines = [f"Tasks for {display_name}:", ""]
    current_stage = None

    for t in tasks:
        stage = t.get("stage", "")
        if stage and stage != current_stage:
            current_stage = stage
            lines.append(f"\n  {stage}:")

        status_icon = "✓" if t["status"] == "Done" else ("→" if t["status"] == "In Progress" else "○")
        assignee = f" — {t['assignee']}" if t.get("assignee") else ""
        deadline = f" (due {t['deadline']})" if t.get("deadline") else ""
        lines.append(f"    {status_icon} {t['name']}{assignee}{deadline}")

    return "\n".join(lines)


@AlfredAgent.tool
async def create_matter_task(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    task_name: str,
    stage: str = "",
    assignee: str = "",
    deadline: str = "",
    priority: str = "",
) -> str:
    """
    Create a new task on a named matter's Notion project page.

    Use this when the user wants to add a new to-do item to a matter —
    for example, "Add a task to file the cert petition supplement in Williams by Aug 15."

    Args:
        matter_name: The matter to add the task to. Example: "Williams"
        task_name:   The task description. Example: "File cert petition supplement"
        stage:       The workflow stage. One of: "Matter Intake & Setup", "Pleadings & Notices",
                     "Brief Preparation & Drafting", "Cites & Compliance",
                     "Review & Finalization", "Contingency Tasks". Leave blank if unknown.
        assignee:    Team member name (first name is fine). Example: "Brittney", "Tim"
        deadline:    ISO 8601 date string. Example: "2026-08-15". Leave blank if not specified.
        priority:    "Urgent", "High", "Medium", or "Low". Leave blank if not specified.

    Returns:
        Confirmation that the task was created, or an error message if it failed.
    """
    from notion_bridge.tasks import TaskPages

    matter = await ctx.deps.project_pages.find_matter(matter_name)
    if not matter:
        return f"No matter found matching '{matter_name}'. Check the matter name and try again."

    task_pages = TaskPages(ctx.deps.bridge)
    try:
        await task_pages.create_task(
            matter_id=matter["id"],
            name=task_name,
            stage=stage,
            assignee=assignee,
            deadline=deadline or None,
            priority=priority,
        )
    except Exception as e:
        return f"Failed to create task: {e}"

    display_name = matter.get("Project name", matter_name)
    parts = [f"Task '{task_name}' created in {display_name}"]
    if stage:
        parts.append(f"stage: {stage}")
    if assignee:
        parts.append(f"assigned to {assignee}")
    if deadline:
        parts.append(f"due {deadline}")
    return " — ".join(parts) + "."


@AlfredAgent.tool
async def seed_matter_tasks(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    matter_type: str,
) -> str:
    """
    Seed the standard KLG task set for a newly opened matter.

    Reads all tasks from the appropriate KLG template database (Appellate or
    Trial Court) and creates copies in the same database linked to this matter
    via the Projects relation. Then posts a grouped task list to the matter's
    Slack channel. Idempotent — safe to call twice; will not create duplicates.

    Args:
        matter_name: The matter to seed tasks for. Example: "Shen v. Li"
        matter_type: "appellate" or "trial_court"

    Returns:
        Summary of tasks created and Slack notification status.
    """
    from notion_bridge.tasks import (
        TaskPages, APPELLATE_TASKS_DB_ID, TRIAL_COURT_TASKS_DB_ID, _NOTION_USER_NAMES
    )
    from agents.case_checkin import resolve_channel_for_matter

    matter = await ctx.deps.project_pages.find_matter(matter_name)
    if not matter:
        return f"No matter found matching '{matter_name}'. Check the matter name and try again."

    display_name = matter.get("Project name", matter_name)
    matter_id = matter["id"]

    # Select template DB
    mt = matter_type.lower()
    if any(k in mt for k in ("appellate", "appeal", "aob", "court of appeal", "petition", "reply")):
        db_id = APPELLATE_TASKS_DB_ID
        template_label = "Appellate Briefing"
    else:
        db_id = TRIAL_COURT_TASKS_DB_ID
        template_label = "Trial Court Brief Preparation"

    task_pages = TaskPages(ctx.deps.bridge)
    try:
        tasks = await task_pages.seed_from_template(db_id, matter_id)
    except Exception as e:
        return f"Task seeding failed for {display_name}: {e}"

    if not tasks:
        return f"No tasks were created for {display_name} — template database may be empty."

    # Group by stage for the Slack notification
    from collections import defaultdict
    by_stage: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        by_stage[t.get("stage") or "Other"].append(t)

    slack_lines = [f"*{display_name} — Tasks Ready* ({len(tasks)} tasks from {template_label} template)\n"]
    for stage, stage_tasks in by_stage.items():
        assignees = {
            _NOTION_USER_NAMES.get(t["assignee"].removeprefix("user://").strip(), t["assignee"])
            for t in stage_tasks if t.get("assignee")
        }
        assignee_str = f" — {', '.join(sorted(assignees))}" if assignees else ""
        slack_lines.append(f"*{stage}* ({len(stage_tasks)} tasks{assignee_str})")
        for t in stage_tasks[:5]:
            slack_lines.append(f"  • {t['name']}")
        if len(stage_tasks) > 5:
            slack_lines.append(f"  … and {len(stage_tasks) - 5} more")

    # Find the first "Matter Intake" task to call out
    first_task = next(
        (t["name"] for t in tasks if "intake" in (t.get("stage") or "").lower()),
        tasks[0]["name"] if tasks else None,
    )
    if first_task:
        slack_lines.append(f"\n*Next action:* Start with \"{first_task}\"")

    slack_message = "\n".join(slack_lines)

    # Post to the matter's Slack channel
    channel_name = resolve_channel_for_matter(matter)
    slack_posted = False
    if channel_name and ctx.deps.slack_client:
        try:
            await ctx.deps.slack_client.chat_postMessage(
                channel=channel_name,
                text=slack_message,
            )
            slack_posted = True
        except Exception as e:
            logger.warning("seed_matter_tasks: Slack post to %s failed: %s", channel_name, e)

    if not slack_posted and ctx.deps.slack_client:
        # Fall back to #case-management
        try:
            await ctx.deps.slack_client.chat_postMessage(
                channel="#case-management",
                text=slack_message,
            )
            slack_posted = True
        except Exception as e:
            logger.warning("seed_matter_tasks: Slack fallback post failed: %s", e)

    channel_note = f" Notification posted to #{channel_name or 'case-management'}." if slack_posted else ""
    return (
        f"Seeded {len(tasks)} tasks for {display_name} from the {template_label} template.{channel_note}\n\n"
        + slack_message
    )


@AlfredAgent.tool
async def update_matter_task(
    ctx: RunContext[AlfredDependencies],
    matter_name: str,
    task_name: str,
    new_status: str = "",
    new_assignee: str = "",
    new_deadline: str = "",
    new_stage: str = "",
) -> str:
    """
    Update an existing task on a named matter.

    Use this when the user wants to change a task's status, reassign it,
    update its deadline, or move it to a different stage.

    Args:
        matter_name:  The matter the task belongs to. Example: "Williams"
        task_name:    The task name to find (partial match is fine). Example: "Assemble appendix"
        new_status:   New status value. One of: "To Do", "In Progress", "Done". Leave blank to keep unchanged.
        new_assignee: New assignee name. Leave blank to keep unchanged.
        new_deadline: New ISO date string. Example: "2026-08-15". Leave blank to keep unchanged.
        new_stage:    New stage name. Leave blank to keep unchanged.

    Returns:
        Confirmation of what was updated, or an error if the task was not found.
    """
    from notion_bridge.tasks import TaskPages

    matter = await ctx.deps.project_pages.find_matter(matter_name)
    if not matter:
        return f"No matter found matching '{matter_name}'."

    task_pages = TaskPages(ctx.deps.bridge)
    tasks = await task_pages.get_tasks_for_matter(matter["id"])

    # Case-insensitive partial name match
    task = next(
        (t for t in tasks if task_name.lower() in t["name"].lower()),
        None,
    )
    if not task:
        available = ", ".join(f"'{t['name']}'" for t in tasks[:5])
        return (
            f"No task matching '{task_name}' found in {matter.get('Project name', matter_name)}. "
            + (f"Available: {available}" if available else "No tasks found.")
        )

    try:
        await task_pages.update_task(
            task_id=task["id"],
            is_block=task.get("is_block", False),
            status=new_status or None,
            assignee=new_assignee or None,
            deadline=new_deadline or None,
            stage=new_stage or None,
        )
    except Exception as e:
        return f"Failed to update task '{task['name']}': {e}"

    parts = [f"Task '{task['name']}' updated"]
    if new_status:
        parts.append(f"status → {new_status}")
    if new_assignee:
        parts.append(f"assigned to {new_assignee}")
    if new_deadline:
        parts.append(f"deadline → {new_deadline}")
    if new_stage:
        parts.append(f"stage → {new_stage}")
    return " — ".join(parts) + "."


# =============================================================================
# SKILL TOOLS REGISTRY
# =============================================================================
# Maps tool name → callable for skills that need scoped tool access.
# Skills declare which tools they need via the required_tools class attribute.
# run_skill is intentionally excluded — no recursive skill invocation.
SKILL_TOOLS: dict[str, Any] = {
    "find_and_summarize_matter":  find_and_summarize_matter,
    "get_upcoming_deadlines":     get_upcoming_deadlines,
    "search_notion":              search_notion,
    "get_bloodhound_watch_list":  get_bloodhound_watch_list,
    "log_action_to_matter":       log_action_to_matter,
    "get_team_workload":          get_team_workload,
    "update_matter_status":       update_matter_status,
    "update_matter":              update_matter,
    "save_note":                  save_note,
    "recall_notes":               recall_notes,
    "create_new_matter":          create_new_matter,
    "search_sharepoint":          search_sharepoint,
    "send_slack_message":         send_slack_message,
    "deep_research_with_chatgpt": deep_research_with_chatgpt,
    "web_search":                 web_search,
    "read_sharepoint_file":       read_sharepoint_file,
    "get_matter_tasks":           get_matter_tasks,
    "create_matter_task":         create_matter_task,
    "update_matter_task":         update_matter_task,
}
