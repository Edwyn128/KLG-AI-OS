"""
alfred/skills/klg_response_plan.py — Response brief strategy from appellant's opening brief.

Reads the opening brief (via uploaded file or pasted text), cross-references the matter's
Notion context and SharePoint documents, then produces a structured strategy memo:
argument map with counter-positions, record strategy, and research priorities.

CONFIDENTIALITY RULE: never echo client names or case facts into web searches.
"""
from __future__ import annotations

import logging
from pathlib import Path

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_RESPONSE_PLAN_PROMPT = """\
You are a KLG senior appellate attorney preparing a response brief strategy memo.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas \
bonds, First Amendment, public employee speech, civil rights, administrative law.

WRITING RULES (non-negotiable):
- Active verbs; no nominalizations or gerunds where a verb works better
- Em dashes without spaces—like this—not like this —
- No "furthermore", "therefore", "clearly", "it is axiomatic", "as such",
  "instant case", "aforementioned", "hereinabove", "it is well established"
- No doubled modifiers
- Lead with the conclusion; context follows
- Every draft must close with: DRAFT — attorney review required

CONFIDENTIALITY: This strategy memo is privileged work product.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RELEVANT DOCUMENTS (SharePoint)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sp_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APPELLANT'S OPENING BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{brief_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a response brief strategy memo with the following sections:

## Executive Summary

2–3 sentences. What is the opening brief's core theory, and what is our winning \
counter-theory?

## Argument Map

For each major argument in the opening brief, provide:

**Appellant's Argument [N]: [Title]**
- Their position: (1 sentence)
- Our counter: (1–2 sentences)
- Argument strength: 🔴 Strong / 🟡 Moderate / 🟢 Weak (with 1-sentence rationale)
- Record to pull: specific facts or passages from the record that undercut their position
- Research needed: the doctrinal issue to investigate before drafting our response

## Response Brief Structure

Proposed section order with a one-line description and suggested page allocation for \
each section. Total should not exceed the applicable court's page limit.

## Record Strategy

5–10 specific record items to locate and cite. For each: what we need, why it \
matters, and where to look (if known from the brief).

## Tone and Framing Notes

3–5 strategic notes: where to be aggressive, where to concede minor points to build \
credibility, and any procedural or preservation issues to flag.

## Research Priorities

3–5 doctrinal issues to research before drafting, in priority order. State each as \
an abstract legal question—no client facts.

---

DRAFT — attorney review required. Do not file without attorney sign-off.\
"""


class KLGResponsePlan(Skill):
    name = "klg-response-plan"
    description = (
        "Draft a response brief strategy memo from the appellant's opening brief—"
        "argument map with counter-positions, record strategy, and research priorities. "
        "Upload the opening brief first, then run this skill."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()

        # ── Brief text: file upload or pasted text ────────────────────────────
        brief_text = await _extract_brief_text(file_tokens, instruction)
        if not brief_text:
            return SkillResult(
                summary="klg-response-plan: no opening brief provided.",
                output=(
                    "To run a response plan, provide the opening brief by either:\n\n"
                    "1. **Upload the brief** (PDF, .docx, or .txt), then run:\n"
                    "   `Alfred, run klg-response-plan on [Matter Name]`\n\n"
                    "2. **Paste the brief text** as the instruction:\n"
                    "   `Alfred, run klg-response-plan on [Matter Name]: [brief text]`"
                ),
                next_action="Upload or paste the appellant's opening brief and re-run.",
                success=False,
            )

        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found for this matter.)"

        sp_text = await _fetch_sharepoint(ctx)

        prompt = _RESPONSE_PLAN_PROMPT.format(
            matter_summary=matter_text[:5000],
            sp_text=sp_text[:3000],
            brief_text=brief_text[:20000],
            instruction=instruction[:1000],
        )

        output_text = await _generate(prompt)

        return SkillResult(
            summary=(
                f"Response brief strategy complete for {matter_label}. "
                "Argument map and counter-positions ready for attorney review."
            ),
            output=(
                f"**Response Brief Strategy — {matter_label}**\n\n"
                f"{output_text}"
            ),
            next_action=(
                "Review the argument map and counter-positions. "
                "Locate the record items listed in Record Strategy. "
                "Address research priorities before drafting."
            ),
            success=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _extract_brief_text(file_tokens: list[str], fallback: str) -> str:
    if file_tokens:
        try:
            from alfred.file_store import consume_token, delete_file
            path = consume_token(file_tokens[0])
            if path:
                text = _read_file_text(path)
                delete_file(path)
                if text:
                    return text
        except Exception as e:
            logger.warning("klg-response-plan: file extraction failed: %s", e)
    return fallback


def _read_file_text(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".txt":
        return p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".doc", ".docx"):
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            texts: list[str] = []
            with zipfile.ZipFile(path) as z:
                with z.open("word/document.xml") as f:
                    tree = ET.parse(f)
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    for t in tree.findall(".//w:t", ns):
                        if t.text:
                            texts.append(t.text)
            return " ".join(texts)
        except Exception:
            pass
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


async def _fetch_sharepoint(ctx: SkillContext) -> str:
    deps = ctx.extra.get("deps")
    if not deps or not deps.sharepoint or not ctx.matter_name:
        return "(SharePoint not configured.)"
    try:
        results = await deps.sharepoint.search_files(ctx.matter_name, top=5)
        if not results:
            return f"(No SharePoint documents found for '{ctx.matter_name}'.)"
        lines = []
        for r in results:
            lines.append(
                f"  • {r.get('name', '')} — {r.get('lastModifiedDateTime', '')[:10]}\n"
                f"    {r.get('webUrl', '')}"
            )
        return "Documents found:\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("klg-response-plan: SharePoint search failed: %s", e)
        return "(SharePoint search failed — continuing without document list.)"


async def _generate(prompt: str) -> str:
    from pydantic_ai import Agent
    from alfred.model_factory import build_model
    from config import settings

    agent: Agent[None, str] = Agent(model=build_model(settings.alfred_model), output_type=str)
    result = await agent.run(prompt)
    return result.output
