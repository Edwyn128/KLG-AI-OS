"""
alfred/skills/klg_amicus_assessment.py — Evaluate whether a case warrants a KLG amicus brief.

Assesses the case's importance to KLG's practice areas, identifies KLG's unique angle,
maps likely coalition filers, and drafts proposed question/argument section titles.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate

logger = logging.getLogger(__name__)

_AMICUS_PROMPT = """\
You are a KLG senior appellate attorney evaluating a potential amicus brief opportunity.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

WRITING RULES:
- Active verbs; lead with the assessment
- Em dashes without spaces—like this
- No "furthermore", "therefore", "clearly", "it is well established"
- The recommendation must be concrete: Yes / Conditional / No

CONFIDENTIALITY: This assessment is privileged work product.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KLG PRACTICE CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CASE INFORMATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce an amicus assessment with the following sections:

## Case Snapshot

- Court and posture (what ruling is being reviewed, what stage)
- The legal question presented
- Expected decision timeline

## KLG Interest Assessment

Rate KLG's interest: 🔴 Low / 🟡 Moderate / 🟢 High

Explain in 3–5 sentences: How does this case affect KLG's practice areas? Does the
potential ruling create risk for KLG clients or open favorable doctrinal space?

## KLG's Unique Angle

What perspective can KLG bring that no other amicus filer will? KLG's value is its
practitioner-level experience with supersedeas, public employee First Amendment,
and civil rights at the appellate level. Identify the scholarly or practice angle
that is distinctly KLG's to argue.

If KLG has no unique angle, say so directly.

## Coalition Map

Who else is likely to file amicus in this case?
- Likely filers aligned with KLG's position (and their expected angle)
- Likely filers on the other side
- Coordination opportunity: is there a coalition brief KLG should join vs. lead?

## Proposed Question / Argument Titles

If KLG files, draft:
- The proposed question presented for the amicus brief (1 sentence)
- 2–4 proposed argument section titles

## Resource and Timeline Estimate

- Estimated pages (typical amicus: 20–25 pages)
- Estimated drafting time (weeks)
- Filing deadline (based on case schedule—flag if unknown: "[VERIFY from court docket]")
- Who at KLG should lead

## Recommendation

**File independently / Join coalition / Monitor only / Pass**

One-paragraph rationale. If "conditional": what condition must be met.

---

DRAFT — Tim sign-off required before any amicus commitment.\
"""


class KLGAmicusAssessment(Skill):
    name = "klg-amicus-assessment"
    required_tools = ["web_search", "search_notion"]
    description = (
        "Evaluate whether a case warrants a KLG amicus brief: importance assessment, "
        "KLG's unique angle, coalition map, proposed arguments, and a file/pass recommendation."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        instruction = ctx.user_instruction.strip()

        if not instruction:
            return SkillResult(
                summary="klg-amicus-assessment: no case information provided.",
                output=(
                    "Provide the case information:\n\n"
                    "`Alfred, run klg-amicus-assessment: "
                    "[case name, court, legal question, and why KLG might care]`"
                ),
                next_action="Re-run with case name, court, and legal question.",
                success=False,
            )

        matter_text = ctx.matter_summary or "(No specific matter context — assessing standalone amicus opportunity.)"
        matter_label = ctx.matter_name or "amicus opportunity"

        prompt = _AMICUS_PROMPT.format(
            matter_summary=matter_text[:3000],
            instruction=instruction[:3000],
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=f"Amicus assessment complete for {matter_label}. Recommendation and resource estimate ready for Tim's review.",
            output=f"**Amicus Assessment — {matter_label}**\n\n{output_text}",
            next_action=(
                "Tim to review the recommendation. If filing: confirm the deadline from "
                "the court docket, identify lead attorney, and open a matter page in Notion."
            ),
            success=True,
        )
