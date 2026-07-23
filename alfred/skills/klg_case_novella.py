"""
alfred/skills/klg_case_novella.py — Compelling factual narrative for appellate briefs.

Drafts the "story" of the case: a persuasive, human-centered statement of facts
that primes the panel before they reach the legal arguments. This is distinct from
klg-brief-elevation (which elevates a full draft) — the Novella focuses entirely
on crafting the narrative architecture of the Statement of Facts.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate, skill_read_file_text

logger = logging.getLogger(__name__)

_NOVELLA_PROMPT = """\
You are a KLG senior appellate attorney drafting the factual narrative section
of an appellate brief. Your job is to write the Statement of Facts as a compelling
story that makes the panel want to rule for your client before they read a single
legal argument.

KLG WRITING RULES (non-negotiable):
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "it is well established," "as such"
- Active verbs. Lead with the most compelling fact, not the procedural posture.
- No throat-clearing. No doubled modifiers. No bold or italics for emphasis.
- Chronological narrative with purposeful selection—every fact must earn its place.
- CRITICAL: Do not invent record facts, quotes, or dates.
  Flag anything uncertain: "[VERIFY from record]"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE MATERIALS (uploaded documents or notes)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{source_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC INSTRUCTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce the following:

## NARRATIVE ARCHITECTURE BRIEF

Before drafting, identify:

**The protagonist:** Who is the most sympathetic party, and what did they want?
**The antagonist force:** What institutional or individual force worked against them?
**The pivotal moment:** The single factual event the whole appeal turns on.
**The emotional core:** The human cost of what happened.
**The legal hook:** The fact that, once seen, makes the legal violation undeniable.

---

## STATEMENT OF FACTS — DRAFT

Write a narrative statement of facts of approximately 800–1,200 words.

Structure:
1. **Opening sentence** — Start in the middle of the most compelling moment.
   Do not start with "On [date]" or "Plaintiff [Name] is a..."
2. **Background** — Provide just enough context for the narrative to land.
   Introduce the client as a human being, not a legal abstraction.
3. **The inciting event** — What happened, in specific detail. Record cites
   throughout: (RT 145:12–22), (AA at 23), (Exh. 7 at AA 44).
4. **Escalation** — How the situation developed. What the client did and
   what happened next. Keep the facts purposefully selected—every detail
   should make the panel more sympathetic or more outraged.
5. **The legal trigger** — The specific act or decision that gives rise to the
   appeal. Make it clear what was done and by whom.
6. **The consequence** — What the client lost. Be specific: job, reputation,
   livelihood, family. Concrete losses, not abstractions.
7. **The trial court** — What the trial court said and why it was wrong
   (without editorializing—let the facts speak). Keep to 1–2 sentences.

---

## RECORD CITATION CHECKLIST

List every record citation used above in a table:
| Fact | Citation | Verify? |
|------|----------|---------|
Flag any cite that needs to be confirmed from the actual record: [VERIFY]

---

## ALTERNATIVE OPENING SENTENCES (3 versions)

Offer three alternative first sentences using different rhetorical approaches:
1. **Scene-setter** (place the reader in the room)
2. **Irony** (the gap between what should have been and what happened)
3. **Consequence-first** (start with what was lost)

---

DRAFT — attorney review required. All record citations must be verified
before this narrative appears in a filed brief.\
"""


class KLGCaseNovella(Skill):
    name = "klg-case-novella"
    required_tools = ["search_notion"]
    description = (
        "Draft the Statement of Facts as a compelling narrative—the 'story' that primes "
        "the panel before they reach the legal arguments. Produces a 800–1,200 word "
        "narrative with record citations, narrative architecture analysis, and three "
        "alternative opening sentences."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        source_text = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    source_text = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-case-novella: file extraction failed: %s", e)

        if not matter_text and not source_text and not instruction:
            return SkillResult(
                summary="klg-case-novella: no case context provided.",
                output=(
                    "Provide the matter name or upload source materials:\n\n"
                    "`Alfred, run klg-case-novella on [Matter Name].`\n\n"
                    "Optionally attach key record excerpts, prior statements of facts, "
                    "or a summary of the key facts to work from."
                ),
                next_action="Re-run with matter context or uploaded source materials.",
                success=False,
            )

        prompt = _NOVELLA_PROMPT.format(
            matter_summary=matter_text[:4000],
            source_text=source_text[:12000] if source_text else "(No file uploaded — base narrative on Notion context above.)",
            instruction=instruction[:2000] or "(No specific instruction — draft full Statement of Facts narrative.)",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Case narrative drafted for {matter_label}. "
                "Statement of Facts, narrative architecture, and record citation checklist ready."
            ),
            output=f"**Case Novella — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Verify every [VERIFY from record] flag against the actual record before filing.\n"
                "2. Select your preferred opening sentence from the three alternatives.\n"
                "3. Route to Tim for narrative review before incorporating into the brief."
            ),
            success=True,
        )
