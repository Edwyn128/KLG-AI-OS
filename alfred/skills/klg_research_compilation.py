"""
alfred/skills/klg_research_compilation.py — Steps 4–5 of the KLG Research Pipeline.

Reads raw research notes from Notion, compiles them into a structured legal
research memo, and extracts a formatted authority list for Westlaw verification.

KLG Research Pipeline:
  Step 1 — Issue framing           (klg-issue-framing)
  Step 2 — Deep research prompts   (klg-deep-research-prompts)
  Step 3 — Research execution      (researcher runs prompts in Westlaw/Fastcase/web)
  Step 4 — Research compilation  ← THIS SKILL: organize and synthesize notes
  Step 5 — Authority extraction  ← THIS SKILL: extract citation list for Westlaw

Usage:
  "Alfred, run klg-research-compilation on [Matter Name]: [any specific focus]"

  Alfred reads the matter's Notion research page, compiles the memo,
  and writes a summary back to Notion. The authority list is returned
  for the research attorney to verify in Westlaw.

NOTE: .docx / PDF assembly from compiled memo requires the brief pipeline
scripts (pack.py / assemble_brief.py). Run those in the Alfred Code or
Cowork environment after reviewing the memo Alfred produces here.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_COMPILATION_PROMPT = """\
You are a KLG senior appellate attorney compiling legal research for {matter_label}.

You have retrieved the matter's research notes from Notion. Your job:
1. Organize the raw notes into a structured legal research memo
2. Extract a clean authority list for Westlaw verification

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESEARCH NOTES (from Notion research page)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{research_notes}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC FOCUS / INSTRUCTIONS:
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "it is well established," "as such"
- Active verbs. Lead with the holding, not the court's procedural history
- CRITICAL: never fabricate case citations, holdings, or quotations
  If a citation seems incomplete or uncertain, flag it: [VERIFY CITATION]
  If a holding is paraphrased from notes, flag it: [PARAPHRASED — VERIFY]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STEP 4 — LEGAL RESEARCH MEMO

## Issue Presented
[One sentence, precisely stated]

## Short Answer
[2–4 sentences — bottom line up front]

## Governing Legal Standard
[The controlling test(s) with citations]

## Analysis by Sub-Issue

For each sub-issue or legal question in the research:

### [Sub-Issue Title]
**Controlling authority:** [cite]
**Holding:** [what the court held]
**Application to our facts:** [how this authority helps or hurts]
**Distinguishing factors:** [if adverse, how we distinguish]

## Favorable Authorities (Ranked)
List the 10 strongest authorities for our position:
| Rank | Citation | Holding | Why it helps |
|------|----------|---------|--------------|

## Adverse Authorities and Responses
List all adverse authorities found. For each:
| Citation | Holding | Our response / distinction |
|----------|---------|--------------------------|

## Research Gaps
What questions remain unanswered that need additional research?

---

STEP 5 — WESTLAW AUTHORITY EXTRACTION LIST

Extract every case, statute, regulation, and secondary source cited in the
notes into this format for Westlaw verification:

### Cases
| Citation (as found in notes) | Verified? | Notes |
|------------------------------|-----------|-------|
[List all — include string cites that may need updating]

### Statutes and Regulations
| Citation | Section | Notes |
|----------|---------|-------|

### Secondary Sources
| Source | Author | Year | Notes |
|--------|--------|------|-------|

FLAG: Any citation that looks incomplete, appears to be a paraphrase,
or could not be verified from the notes should be marked [VERIFY BEFORE CITING].

---
DRAFT — attorney review required. Verify all citations in Westlaw before
incorporating into a brief or motion.
"""


class KLGResearchCompilation(Skill):
    name = "klg-research-compilation"
    required_tools = ["search_notion"]
    description = (
        "Steps 4–5 of the KLG Research Pipeline: reads raw research notes from Notion, "
        "compiles them into a structured legal research memo, and extracts a formatted "
        "Westlaw authority list. Run after the research attorney has completed Steps 1–3."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_summary = ctx.matter_summary or "(No Notion project page found.)"

        # Try to read research notes from an uploaded file first
        research_notes = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    research_notes = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-research-compilation: file extraction failed: %s", e)

        # If no file, the scoped agent will fetch from Notion using search_notion
        if not research_notes:
            research_notes = (
                "[No file uploaded — the scoped agent should call search_notion to "
                f"retrieve research notes for {matter_label} from the matter's Notion page. "
                "Search for 'research notes' or 'legal research' in the matter context.]"
            )

        if not matter_summary and not research_notes and not instruction:
            return SkillResult(
                summary="klg-research-compilation: no research content found.",
                output=(
                    "No research notes found for this matter.\n\n"
                    "To run research compilation:\n"
                    "1. Complete Steps 1–3 of the KLG Research Pipeline first\n"
                    "   (klg-issue-framing → klg-deep-research-prompts → run in Westlaw)\n"
                    "2. Paste research notes into the matter's Notion page, OR\n"
                    "   upload a research notes file when invoking this skill\n"
                    "3. Re-run: `Alfred, run klg-research-compilation on [Matter Name]`"
                ),
                next_action="Complete Steps 1–3 of the research pipeline first.",
                success=False,
            )

        # Build prompt — the scoped agent (with search_notion tool) will fetch
        # additional Notion content if needed before synthesizing the memo
        fetch_instruction = (
            "BEFORE WRITING THE MEMO:\n"
            "Call search_notion with a query like 'research notes [matter name]' to retrieve "
            "any additional research content stored in Notion for this matter. "
            "Combine that with any notes already provided below.\n\n"
        ) if not file_tokens else ""

        prompt = fetch_instruction + _COMPILATION_PROMPT.format(
            matter_label=matter_label,
            matter_summary=matter_summary[:3000],
            research_notes=research_notes[:15000],
            instruction=instruction or "(none — compile all available research)",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Research compilation complete for {matter_label}. "
                "Memo and Westlaw authority list ready for attorney review."
            ),
            output=f"**Research Compilation — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Verify every citation marked [VERIFY CITATION] in Westlaw before using.\n"
                "2. To assemble into a .docx memo, use the brief pipeline scripts in the "
                "Alfred Code or Cowork environment: pack.py / assemble_brief.py.\n"
                "3. Run klg-brief-elevation after drafting to apply KLG style standards."
            ),
            success=True,
        )
