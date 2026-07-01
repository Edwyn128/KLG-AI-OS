"""
alfred/skills/klg_issue_framing.py — Frame the issue presented for maximum persuasive impact.

Drafts three versions of the issue (narrow / mid / broad), tests each against the
favorable facts, and recommends the version that best primes the panel.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate

logger = logging.getLogger(__name__)

_ISSUE_FRAMING_PROMPT = """\
You are a KLG senior appellate attorney drafting the issue presented for an appellate brief.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

WRITING RULES (non-negotiable):
- The issue presented must imply the answer you want
- Active verbs; no passive construction in the issue statement
- Em dashes without spaces—like this
- No "furthermore", "therefore", "clearly", "it is axiomatic", "as such"
- Lead with the conclusion; context follows

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CASE FACTS AND LEGAL QUESTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce an issue framing analysis with the following sections:

## Core Legal Question

In one sentence: the abstract legal question this appeal will answer. No client facts.

## Version 1 — Narrow Framing

Draft the issue presented at the narrowest possible scope (fact-bound, specific to
this case). Then assess:
- Does it imply the answer we want? (Yes / Partly / No)
- Risk: does narrowness let the court duck the issue?
- Best for: (what circumstances favor this version)

## Version 2 — Mid Framing (Recommended Starting Point)

Draft the issue at moderate scope — specific enough to be grounded, broad enough to
have doctrinal significance. Same assessment as above.

## Version 3 — Broad Framing

Draft the issue at the broadest defensible scope. Same assessment as above.

## Standard of Review Alignment

For each version: does it signal the correct standard of review? Which version best
positions us on standard of review?

## Recommendation

Which version to use, and why. If none is fully satisfactory, draft a fourth version
that synthesizes the best elements.

## Opponent's Issue Framing

Draft the version the opposing party is likely to use. What does that framing do
to the standard of review and the court's likely approach?

---

DRAFT — attorney review required.\
"""


class KLGIssueFraming(Skill):
    name = "klg-issue-framing"
    description = (
        "Frame the issue presented at the optimal level of specificity: drafts three "
        "versions (narrow / mid / broad), tests each against the standard of review, "
        "and recommends the most persuasive framing."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        if not instruction and not matter_text:
            return SkillResult(
                summary="klg-issue-framing: no case facts provided.",
                output=(
                    "Provide the case facts and legal question:\n\n"
                    "`Alfred, run klg-issue-framing on [Matter Name]: "
                    "[describe the ruling being challenged and the key facts]`"
                ),
                next_action="Re-run with case facts and the ruling being challenged.",
                success=False,
            )

        prompt = _ISSUE_FRAMING_PROMPT.format(
            matter_summary=matter_text[:4000],
            instruction=instruction[:3000],
        )

        output_text = await skill_generate(prompt)

        return SkillResult(
            summary=f"Issue framing complete for {matter_label}. Three versions drafted with recommendation.",
            output=f"**Issue Framing — {matter_label}**\n\n{output_text}",
            next_action=(
                "Select a version or combine elements, then align the standard of review "
                "argument with the chosen framing before drafting."
            ),
            success=True,
        )
