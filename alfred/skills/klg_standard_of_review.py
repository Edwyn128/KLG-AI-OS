"""
alfred/skills/klg_standard_of_review.py — Identify and argue the standard of review.

Identifies the applicable standard, drafts the standard of review statement,
flags preservation issues, and anticipates opponent SOR arguments.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate

logger = logging.getLogger(__name__)

_SOR_PROMPT = """\
You are a KLG senior appellate attorney drafting the standard of review section.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

CRITICAL: Do NOT invent citations. If uncertain about a specific case holding
standard of review, flag it: "[VERIFY]". Every cited case must be real.

WRITING RULES:
- Active verbs; lead with the standard
- Em dashes without spaces—like this
- No "furthermore", "therefore", "clearly", "it is well established"
- Draft the statement as if ready to drop into a brief

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULING BEING CHALLENGED AND COURT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a standard of review analysis with the following sections:

## Ruling Classification

Classify the trial court ruling: fact-finding / legal conclusion / mixed question /
discretionary ruling / constitutional question. Explain why. This determines the standard.

## Applicable Standard

State the standard of review that applies, with the governing authority:
- The standard (e.g., de novo, clear error, abuse of discretion)
- The leading case establishing it in this circuit / Cal. courts [VERIFY any citation]
- Whether the standard is deferential or plenary—and why that matters here

## Draft Standard of Review Statement

A ready-to-use paragraph for the brief. Active voice, specific to this ruling type.

## Preservation Analysis

Did the issue appear to be preserved? What objection or motion would have been needed?
Flag any risk of invited error, forfeiture, or plain error review.

## Favorable Standard Arguments

If there is any argument for a MORE favorable (less deferential) standard, state it.
Example: a ruling characterized as discretionary may actually present a pure legal question.

## Opponent's Standard Arguments

What standard will the opposing party argue for? Why? How to preempt it.

## Harmless Error / Prejudice

If the court applies the wrong standard, what is the harmless error argument the opponent
will make? What facts demonstrate prejudice?

---

DRAFT — attorney verification required before filing.\
"""


class KLGStandardOfReview(Skill):
    name = "klg-standard-of-review"
    required_tools = ["web_search", "search_notion"]
    description = (
        "Identify the applicable standard of review, draft the SOR statement, "
        "analyze preservation, and anticipate opponent SOR arguments. "
        "Specify the ruling being challenged and the court in the instruction."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        if not instruction and not matter_text:
            return SkillResult(
                summary="klg-standard-of-review: no ruling specified.",
                output=(
                    "Specify the ruling being challenged and the court:\n\n"
                    "`Alfred, run klg-standard-of-review on [Matter Name]: "
                    "[describe the trial court ruling and the appellate court]`"
                ),
                next_action="Re-run with the ruling type and court specified.",
                success=False,
            )

        prompt = _SOR_PROMPT.format(
            matter_summary=matter_text[:4000],
            instruction=instruction[:2000],
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=f"Standard of review analysis complete for {matter_label}.",
            output=f"**Standard of Review — {matter_label}**\n\n{output_text}",
            next_action=(
                "Verify all cited cases before dropping the statement into the brief. "
                "Confirm preservation with the trial court record."
            ),
            success=True,
        )
