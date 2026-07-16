"""
alfred/skills/klg_oral_argument_prep.py — Full oral argument preparation package.

Builds a complete oral argument prep kit: 60-second opener, 10 hardest questions
with answers, record citations, and the one concession to offer if pressed.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate, skill_read_file_text

logger = logging.getLogger(__name__)

_OA_PREP_PROMPT = """\
You are a KLG senior appellate attorney preparing for oral argument.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

WRITING RULES:
- Answers must be confident, direct, and under 3 sentences each
- Em dashes without spaces—like this
- No "furthermore", "therefore", "clearly", "it is well established"
- The opening statement must be memorizable — no jargon, no hedging
- Every record citation must include a page/volume reference if known

CRITICAL: Do NOT invent record facts, case citations, or judicial quotes.
Flag anything uncertain: "[VERIFY from record]" or "[VERIFY citation]".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRIEF EXCERPT / KEY ARGUMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{brief_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARGUMENT DETAILS AND INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a complete oral argument prep package:

## 60-Second Opening Statement

A three-part opener the advocate can memorize:
1. **The hook** (1 sentence): the single most compelling fact or legal principle
2. **The theory** (1–2 sentences): why the court should reverse/affirm
3. **The ask** (1 sentence): what relief we want and why the standard requires it

Total: 60 seconds when read at a moderate pace (~130 words).

## The 10 Hardest Questions

For each question the panel is most likely to ask:

**Q[N]: [The question, as the judge would actually ask it]**
- Why they ask it: (the underlying concern)
- Answer: (direct, confident, under 3 sentences)
- Pivot: how to redirect to your theory after answering
- Record support: [cite or "(verify from record)"]

Order by difficulty—hardest first.

## The Absolute Concession

The one point to concede immediately if pressed—the concession that builds credibility
without giving away the case. State it precisely as you would say it on the bench.

## Key Record Citations

10 specific record citations the advocate should have at fingertips:
| Item | What it shows | Record cite |
|------|---------------|-------------|

Flag any that need to be verified: "[VERIFY]"

## Moot Court Setup

3 questions the moot court panel should hammer hardest, and why.

---

DRAFT — attorney review required. Do not rely on unverified record citations.\
"""


class KLGOralArgumentPrep(Skill):
    name = "klg-oral-argument-prep"
    required_tools = ["web_search", "search_notion"]
    description = (
        "Build a complete oral argument prep package: 60-second opener, 10 hardest "
        "questions with answers, record citations, and the one concession to offer. "
        "Optionally upload a brief excerpt for deeper prep."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()

        brief_text = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    brief_text = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-oral-argument-prep: file extraction failed: %s", e)

        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        if not matter_text and not instruction and not brief_text:
            return SkillResult(
                summary="klg-oral-argument-prep: no case context provided.",
                output=(
                    "Provide the matter name and argument details:\n\n"
                    "`Alfred, run klg-oral-argument-prep on [Matter Name]: "
                    "[court, date, and key arguments to prep]`\n\n"
                    "Optionally upload the brief or key excerpts for deeper prep."
                ),
                next_action="Re-run with matter context and argument details.",
                success=False,
            )

        prompt = _OA_PREP_PROMPT.format(
            matter_summary=matter_text[:4000],
            brief_text=brief_text[:10000],
            instruction=instruction[:2000],
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Oral argument prep complete for {matter_label}. "
                "Opening statement, 10 hard questions, and record citations ready."
            ),
            output=f"**Oral Argument Prep — {matter_label}**\n\n{output_text}",
            next_action=(
                "Verify all record citations. Run a moot court with the hardest 3 questions. "
                "Memorize the 60-second opener before the argument."
            ),
            success=True,
        )
