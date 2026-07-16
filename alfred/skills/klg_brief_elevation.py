"""
alfred/skills/klg_brief_elevation.py — Elevate a draft brief to KLG standard.

Reads the draft brief (uploaded file or pasted text), cross-references the matter's
Notion context, and produces a structured elevation report: theory critique, structure
audit, argument-by-argument feedback, KLG style violations, and persuasion notes.

CONFIDENTIALITY RULE: never echo client names or case facts into web searches.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate, skill_read_file_text

logger = logging.getLogger(__name__)

_ELEVATION_PROMPT = """\
You are a KLG senior appellate attorney performing a brief elevation review.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

WRITING RULES (non-negotiable):
- Active verbs; no nominalizations or gerunds where a verb works better
- Em dashes without spaces—like this
- No "furthermore", "therefore", "clearly", "it is axiomatic", "as such",
  "instant case", "aforementioned", "hereinabove", "it is well established"
- No doubled modifiers ("clearly and unambiguously")
- Lead with the conclusion; context follows
- Every draft must close with: DRAFT — attorney review required

CONFIDENTIALITY: This elevation report is privileged work product.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DRAFT BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{brief_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a brief elevation report with the following sections:

## Theory of the Appeal

State in one sentence what the brief's current theory is. Then state in one sentence
what the theory SHOULD be—the framing that most compels reversal given these facts and
this court. If they match, say so. If not, explain the gap and how to close it.

## Issue Presented

Quote the current issue presented verbatim. Rate it: 🟢 Sharp / 🟡 Improvable / 🔴 Needs rewrite.
If improvable or needs rewrite, draft a better version.

## Structure Audit

Walk through each section heading in the brief. For each:
- **Section**: [heading]
- **Assessment**: Does it do its job? Does it lead with the conclusion?
- **Fix**: One concrete suggestion, or "No change needed."

## Argument-by-Argument Feedback

For each major argument:

**Argument [N]: [Title]**
- Strength: 🔴 Weak / 🟡 Solid / 🟢 Strong
- What works: (1 sentence)
- What to sharpen: (1–2 sentences with specific suggestion)
- Record support: Is it adequately grounded in the record? What's missing?

## KLG Style Violations

List every sentence or phrase that violates KLG's writing rules. For each:
| Violation | Original | Suggested fix |
|-----------|----------|---------------|

If no violations: "No KLG style violations found."

## Standard of Review

Is the standard of review stated correctly and applied throughout? If not, what needs to change?

## Persuasion Audit

Rate the brief's overall persuasive impact: 🔴 1–3 / 🟡 4–6 / 🟢 7–10, with a one-paragraph
explanation. What is the single highest-leverage change to make before filing?

---

DRAFT — attorney review required. Do not file without attorney sign-off.\
"""


class KLGBriefElevation(Skill):
    name = "klg-brief-elevation"
    required_tools = ["search_notion"]
    description = (
        "Elevate a draft brief to KLG standard: theory critique, structure audit, "
        "argument-by-argument feedback, KLG style violations, and persuasion score. "
        "Upload the draft brief first, then run this skill."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()

        brief_text = await _extract_brief_text(file_tokens, instruction)
        if not brief_text:
            return SkillResult(
                summary="klg-brief-elevation: no draft brief provided.",
                output=(
                    "To run a brief elevation, provide the draft brief by either:\n\n"
                    "1. **Upload the brief** (.pdf, .docx, or .txt), then run:\n"
                    "   `Alfred, run klg-brief-elevation on [Matter Name]`\n\n"
                    "2. **Paste the brief text** as the instruction:\n"
                    "   `Alfred, run klg-brief-elevation on [Matter Name]: [brief text]`"
                ),
                next_action="Upload or paste the draft brief and re-run.",
                success=False,
            )

        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found for this matter.)"

        prompt = _ELEVATION_PROMPT.format(
            matter_summary=matter_text[:4000],
            brief_text=brief_text[:25000],
            instruction=instruction[:1000],
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Brief elevation complete for {matter_label}. "
                "Theory critique, structure audit, and style violations ready for attorney review."
            ),
            output=f"**Brief Elevation Report — {matter_label}**\n\n{output_text}",
            next_action=(
                "Review the theory gap and persuasion audit first — those are the "
                "highest-leverage changes. Address style violations before final review."
            ),
            success=True,
        )


async def _extract_brief_text(file_tokens: list[str], fallback: str) -> str:
    if file_tokens:
        try:
            from alfred.file_store import consume_token, delete_file
            path = consume_token(file_tokens[0])
            if path:
                text = skill_read_file_text(path)
                delete_file(path)
                if text:
                    return text
        except Exception as e:
            logger.warning("klg-brief-elevation: file extraction failed: %s", e)
    return fallback
