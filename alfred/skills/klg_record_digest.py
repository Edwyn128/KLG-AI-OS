"""
alfred/skills/klg_record_digest.py — Issue-organized trial record digest.

Unlike klg-record-navigator (which maps preservation and objections), this skill
creates a working reference document organized by legal issue rather than
chronologically. Designed for briefing: when you need to find every piece of
record support for Issue III, this digest tells you exactly where to look.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_RECORD_DIGEST_PROMPT = """\
You are a KLG appellate attorney digesting a trial record for briefing purposes.
Your task is to reorganize the record from its chronological raw form into an
issue-organized reference tool that lets the brief-writer find every piece of
supporting evidence for any legal issue in seconds.

KLG WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "as such"
- Active verbs. Precise record citations throughout.
- Every factual claim must have a record cite: (RT 145:12–22) or (AA at 23).
- CRITICAL: Do not invent record facts, testimony, or quotes.
  Flag any paraphrase as [PARAPHRASED] — exact quotes require record verification.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECORD MATERIALS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{record_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ISSUES TO ORGANIZE AROUND
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce the following:

## RECORD DIGEST — {matter_label}

**Status:** DRAFT — Record citations require verification against original transcript

---

### PART 1: RECORD INVENTORY

Quick-reference table of all record materials available:

| Document | Type | Pages/Volume | Key Contents |
|----------|------|-------------|--------------|

---

### PART 2: ISSUE-ORGANIZED DIGEST

For each legal issue on appeal (identify from matter context or instruction):

#### ISSUE [N]: [Issue Title]

**Legal standard:** [The test the court applies — one sentence]

**Favorable record evidence:**
| Evidence | Source | Citation | Strength |
|----------|--------|----------|----------|

**Adverse record evidence (and our response):**
| Evidence | Source | Citation | How to distinguish |
|----------|--------|----------|--------------------|

**Preserved objections / rulings:**
| Ruling | Citation | Preservation status |
|--------|----------|---------------------|

**Key witness testimony:**
- [Witness name]: [Summary of relevant testimony] (RT [pages])

**Key exhibits:**
- [Exhibit ID]: [Description] (AA at [pages])

---

### PART 3: RECORD GAPS AND FLAGS

Issues that need additional record development before briefing:

| Gap | Issue affected | What's needed | Priority |
|-----|----------------|---------------|----------|

### PART 4: QUICK-FIND INDEX

Alphabetical index of key parties, dates, and record references:

| Entry | Type | Record cites |
|-------|------|-------------|

---

DRAFT — attorney verification required before relying on record citations in filings.\
"""


class KLGRecordDigest(Skill):
    name = "klg-record-digest"
    description = (
        "Create an issue-organized trial record digest for briefing. Reorganizes the raw "
        "chronological record into a reference tool keyed to legal issues—so the brief-writer "
        "can immediately locate all record support for any argument. Attach record excerpts, "
        "transcripts, or an index of the appendix."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        record_text = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                for token in file_tokens[:3]:
                    path = consume_token(token)
                    if path:
                        chunk = skill_read_file_text(path)
                        delete_file(path)
                        if chunk:
                            record_text += f"\n\n---\n\n{chunk}"
            except Exception as e:
                logger.warning("klg-record-digest: file extraction failed: %s", e)

        if not record_text and not matter_text:
            return SkillResult(
                summary="klg-record-digest: no record materials provided.",
                output=(
                    "Attach record materials to create a digest:\n\n"
                    "`Alfred, run klg-record-digest on [Matter Name].`\n\n"
                    "Attach any of:\n"
                    "• Trial transcripts or excerpts\n"
                    "• Appendix index or compile list\n"
                    "• Prior record summaries\n"
                    "• Clerk's transcript index\n\n"
                    "Also specify the legal issues to organize around, e.g.:\n"
                    "'Issues: First Amendment retaliation, Monell liability, qualified immunity'"
                ),
                next_action="Upload record materials and specify the issues to organize around.",
                success=False,
            )

        prompt = _RECORD_DIGEST_PROMPT.format(
            matter_summary=matter_text[:3000],
            record_text=record_text[:16000] if record_text else "(No file uploaded — base digest on matter context.)",
            instruction=instruction or "(No specific issues provided — identify issues from matter context.)",
            matter_label=matter_label,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Record digest complete for {matter_label}. "
                "Issue-organized reference with record citations, gaps, and quick-find index."
            ),
            output=f"**Record Digest — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Verify all record citations against original transcripts.\n"
                "2. Address each gap identified in Part 3 before drafting begins.\n"
                "3. Share with the briefing team as the canonical record reference."
            ),
            success=True,
        )
