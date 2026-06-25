"""
alfred/skills/klg_case_assessment.py — Client inquiry assessment and draft response.

Receives a client email or question, reads the matter's full Notion context
and Comms Log history, optionally pulls relevant SharePoint documents and
live legal research, then drafts a recommended reply for attorney review.

This is Tim's primary daily workflow: client emails in, Alfred assesses and
drafts, Tim reviews and sends.

CONFIDENTIALITY RULE: never echo client names or case facts into web searches.
Only search for the legal doctrine or procedural question in the abstract.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_ASSESSMENT_PROMPT = """\
You are a KLG legal assistant preparing a case assessment and draft client \
response for attorney review.

KLG is a California appellate specialty firm. Primary practice areas: \
supersedeas bonds, First Amendment, public employee speech, civil rights, \
administrative law.

WRITING RULES (non-negotiable):
- Active verbs; no nominalizations or gerunds where a verb works better
- Em dashes without spaces—like this—not like this —
- No "furthermore", "therefore", "clearly", "it is axiomatic", "as such",
  "instant case", "aforementioned", "hereinabove", "it is well established"
- No doubled modifiers ("clearly and unambiguously")
- Lead with the conclusion; context follows
- Every draft must close with: DRAFT — attorney review required

CONFIDENTIALITY: This assessment is privileged work product.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRIOR COMMUNICATIONS FOR THIS MATTER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{comms_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RELEVANT DOCUMENTS (SharePoint)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sp_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LEGAL RESEARCH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{web_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLIENT INQUIRY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{inquiry}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce the following two sections:

## Assessment

2–3 paragraphs. What legal or procedural question does this inquiry raise? \
How does it relate to the matter's current posture and pending deadlines? \
What is the recommended attorney position?

## Recommended Response

Draft a response the attorney can review and send. Requirements:
- Professionally direct; no unnecessary preamble
- Address the client's question substantively
- Set accurate expectations about process, timing, or outcome
- Do not overcommit or state positions the attorney hasn't confirmed
- 150–250 words

---

DRAFT — attorney review required. Do not send without attorney sign-off.\
"""

_SEARCH_QUERY_PROMPT = """\
A client has sent the following inquiry to a California appellate law firm:

{inquiry}

Extract a concise legal research query (10 words or fewer) suitable for \
a web search. Focus only on the legal doctrine or procedural question—\
no client names, no case names, no identifying facts. \
Return only the query string, nothing else.\
"""


class KLGCaseAssessment(Skill):
    name = "klg-case-assessment"
    description = (
        "Assess a client inquiry against full matter context—Notion project page, "
        "Comms Log history, SharePoint documents, and live legal research—then draft "
        "a recommended reply for attorney review."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        inquiry = ctx.user_instruction.strip()
        if not inquiry:
            return SkillResult(
                summary="klg-case-assessment: no inquiry provided.",
                output=(
                    "Paste the client's email or question as the instruction, then run "
                    "klg-case-assessment again. Example:\n\n"
                    "  run klg-case-assessment on [Matter Name]: [client's question]"
                ),
                next_action="Re-run with the client inquiry as the instruction.",
                success=False,
            )

        deps = ctx.extra.get("deps")

        # ── Step 1: Comms Log history ─────────────────────────────────────────
        comms_text = await _fetch_comms(deps, ctx.matter_id)

        # ── Step 2: SharePoint documents ──────────────────────────────────────
        sp_text = await _fetch_sharepoint(deps, ctx.matter_name)

        # ── Step 3: Web search (doctrinal query only) ─────────────────────────
        web_text = await _fetch_web_research(inquiry)

        # ── Step 4: Matter context ────────────────────────────────────────────
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found for this matter.)"

        # ── Step 5: Generate assessment + draft ──────────────────────────────
        prompt = _ASSESSMENT_PROMPT.format(
            matter_summary=matter_text[:6000],
            comms_text=comms_text[:4000],
            sp_text=sp_text[:3000],
            web_text=web_text[:3000],
            inquiry=inquiry[:2000],
        )

        output_text = await _generate(prompt)

        return SkillResult(
            summary=(
                f"Case assessment complete for {matter_label}. "
                "Draft response ready for attorney review."
            ),
            output=(
                f"**Case Assessment — {matter_label}**\n\n"
                f"{output_text}"
            ),
            next_action=(
                "Review the assessment and draft response. Edit as needed and send. "
                "Mark the Comms Log entry as Done once sent."
            ),
            success=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_comms(deps, matter_id: str) -> str:
    if not deps or not deps.comms_log or not matter_id:
        return "(Comms Log not available — NOTION_COMMS_LOG_DB_ID may not be configured.)"
    try:
        entries = await deps.comms_log.get_for_matter(matter_id)
        if not entries:
            return "(No prior communications on file for this matter.)"
        lines = []
        for e in entries[:10]:
            date = e.get("Comm Date") or e.get("Created") or ""
            name = e.get("Name") or e.get("From") or ""
            body = e.get("Email Text") or e.get("Summary") or ""
            action = e.get("Actions") or ""
            lines.append(
                f"[{date}] {name} | Status: {action}\n{body[:500]}"
            )
        return "\n\n---\n\n".join(lines)
    except Exception as e:
        logger.warning("klg-case-assessment: comms log fetch failed: %s", e)
        return "(Comms Log fetch failed — continuing without communication history.)"


async def _fetch_sharepoint(deps, matter_name: str) -> str:
    if not deps or not deps.sharepoint or not matter_name:
        return "(SharePoint not configured.)"
    try:
        results = await deps.sharepoint.search_files(matter_name, top=5)
        if not results:
            return f"(No SharePoint documents found for '{matter_name}'.)"
        lines = []
        for r in results:
            lines.append(
                f"  • {r.get('name', '')} — {r.get('lastModifiedDateTime', '')[:10]}\n"
                f"    {r.get('webUrl', '')}"
            )
        return "Documents found:\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("klg-case-assessment: SharePoint search failed: %s", e)
        return "(SharePoint search failed — continuing without document list.)"


async def _fetch_web_research(inquiry: str) -> str:
    from config import settings
    if not settings.tavily_api_key:
        return "(Web search not configured — set TAVILY_API_KEY to enable live legal research.)"

    # Extract a doctrinal search query—never use client facts or names
    try:
        search_query = await _generate(_SEARCH_QUERY_PROMPT.format(inquiry=inquiry[:1000]))
        search_query = search_query.strip().strip('"').strip("'")[:120]
    except Exception:
        return "(Could not extract search query.)"

    if not search_query:
        return "(No search query extracted.)"

    try:
        import httpx
        payload = {
            "api_key": settings.tavily_api_key,
            "query": search_query,
            "search_depth": "basic",
            "max_results": 4,
            "include_answer": True,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post("https://api.tavily.com/search", json=payload)
            resp.raise_for_status()
            data = resp.json()

        lines = [f"Query: {search_query}\n"]
        if answer := data.get("answer"):
            lines.append(f"Summary: {answer}\n")
        for r in data.get("results", []):
            lines.append(
                f"  • {r['title']}\n"
                f"    {r['url']}\n"
                f"    {r.get('content', '')[:300]}\n"
            )
        return "\n".join(lines)

    except Exception as e:
        logger.warning("klg-case-assessment: Tavily search failed: %s", e)
        return "(Web search failed — continuing without live legal research.)"


async def _generate(prompt: str) -> str:
    from pydantic_ai import Agent
    from alfred.model_factory import build_model
    from config import settings

    agent: Agent[None, str] = Agent(model=build_model(settings.alfred_model), output_type=str)
    result = await agent.run(prompt)
    return result.output
