"""
alfred/skills/klg_authority_map.py — Hierarchical authority map for a legal doctrine.

Takes a doctrine or legal issue and builds a structured authority map:
SCOTUS → 9th Circuit → Cal. Supreme Court, with tensions and open questions.

CONFIDENTIALITY RULE: search queries must be abstract doctrine—never client names or facts.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate

logger = logging.getLogger(__name__)

_AUTHORITY_MAP_PROMPT = """\
You are a KLG senior appellate attorney building an authority map for a constitutional
or statutory doctrine.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

CRITICAL: This is a legal research aid. You must NOT invent citations, case names,
holdings, or quotations. If you are uncertain whether a case exists or what it holds,
flag it explicitly: "[VERIFY: uncertain whether this citation is accurate]".
Every case you list must be real. Flag anything you are not fully confident about.

WRITING RULES:
- Active verbs; lead with the holding
- Em dashes without spaces—like this
- No "furthermore", "therefore", "clearly", "it is well established"
- No doubled modifiers

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOCTRINE / ISSUE TO MAP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Build a hierarchical authority map with the following sections:

## Doctrine Summary

One paragraph: what is this doctrine, what constitutional or statutory provision does
it interpret, and what is the core legal question it answers?

## SCOTUS Authority (chronological)

For each Supreme Court decision:
**[Case Name], [Year]** — [Citation if known, else "(citation to verify)"]
- Holding: (1–2 sentences, active voice)
- Key rule: the specific standard or test announced
- Impact on doctrine: did it expand, narrow, or clarify?

## 9th Circuit Interpretations

For each 9th Circuit case you are confident about:
**[Case Name], [Year]** — [Citation or "(citation to verify)"]
- Holding as applied in this circuit
- How it interprets or extends the SCOTUS rule

## California Court of Appeal / Cal. Supreme Court

For each California state court decision relevant to this doctrine:
**[Case Name], [Year]**
- Holding and relevance to the federal doctrine

## Circuit Split / Open Questions

Are there tensions between circuits? Is the doctrine unsettled in the 9th Circuit
or California? List each open question as a discrete research task.

## Brief Citation Outline

A ready-to-paste outline showing the authority hierarchy for use in a brief argument
section. Format: standard of review → governing rule (SCOTUS) → circuit application
→ factual analogy.

## Westlaw Pull List

5–10 specific searches or citations to verify before relying on this map in a brief.
Flag any case above marked "[VERIFY]" as priority.

---

DRAFT — attorney verification required before citing in any filing.\
"""


class KLGAuthorityMap(Skill):
    name = "klg-authority-map"
    required_tools = ["web_search", "search_notion"]
    description = (
        "Build a hierarchical authority map for a constitutional or statutory doctrine: "
        "SCOTUS → 9th Circuit → Cal. courts, with tensions and brief citation outline. "
        "Specify the doctrine in the instruction."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        instruction = ctx.user_instruction.strip()
        if not instruction:
            return SkillResult(
                summary="klg-authority-map: no doctrine specified.",
                output=(
                    "Specify the doctrine or legal issue to map:\n\n"
                    "`Alfred, run klg-authority-map on [Matter Name]: "
                    "[doctrine, e.g. 'Garcetti public employee speech retaliation']`"
                ),
                next_action="Re-run with the doctrine or legal issue stated in the instruction.",
                success=False,
            )

        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        prompt = _AUTHORITY_MAP_PROMPT.format(
            matter_summary=matter_text[:3000],
            instruction=instruction[:2000],
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Authority map complete for {matter_label} — {instruction[:80]}. "
                "Verify all citations before filing."
            ),
            output=f"**Authority Map — {matter_label}**\n\n{output_text}",
            next_action=(
                "Run the Westlaw Pull List before relying on this map. "
                "Verify every case marked [VERIFY] and confirm treatment history."
            ),
            success=True,
        )
