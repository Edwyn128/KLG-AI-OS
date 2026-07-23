"""
alfred/skills/klg_appendix_cites.py — Appendix citation formatter for California appellate briefs.

California appellate practice requires record citations to reference the Appellant's Appendix
(AA) or Joint Appendix (JA) page numbers: "Smith v. Jones (2024) 100 Cal.App.5th 1234.
(AA at 45–67.)" This skill extracts all record citations from a brief and adds the
correct AA/JA page references, or flags where page numbers need to be supplied.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_APPENDIX_CITES_PROMPT = """\
You are a KLG appellate attorney formatting appendix citations in a California appellate brief.

CALIFORNIA APPENDIX CITATION RULES:
- Record documents must cite the Appellant's Appendix (AA) or Joint Appendix (JA) page
- Format: (AA at [page].) or (AA at [page range].) — note the period inside the parenthesis
- When citing a range: (AA at 45–67.) — use en dash (–), not hyphen
- For voluminous records with multiple volumes: (2 AA at 45.) — volume number first
- Clerk's transcript: (CT at [page].) or (1 CT at [page].)
- Reporter's transcript: (RT at [page]:[line]–[page]:[line].) or (RT [date] at [page]:[line].)
- Deposition transcripts: ([Name] Dep. [Vol.] at [page]:[line].)

KLG WRITING RULES:
- Em dashes without spaces—like this
- Parentheticals: period goes INSIDE the closing parenthesis for California courts
- CRITICAL: Do not invent page numbers. Flag missing pages: [AA PAGE NEEDED]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRIEF TEXT (with record citations to format)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{brief_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
APPENDIX INDEX (if available — maps documents to AA pages)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{appendix_index}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce:

## APPENDIX CITATION AUDIT — {matter_label}

---

### PART 1: CITATION INVENTORY

List every record citation found in the brief:

| # | Original citation | Document type | AA/JA page known? | Formatted cite |
|---|-------------------|---------------|-------------------|----------------|
| 1 | | CT / RT / Exh / Decl | ✅ / ❌ [AA PAGE NEEDED] | |

**Total record citations found:** [N]
**Citations needing AA page numbers:** [N]

---

### PART 2: FORMATTED CITATION LIST

For each citation where the AA page IS known (from the index or context):
```
ORIGINAL:  [original citation text]
FORMATTED: [formatted with AA page reference]
```

For each citation where the AA page is NOT known:
```
ORIGINAL:  [original citation text]
FLAG:      [AA PAGE NEEDED] — Document: [description], approximate location in record
```

---

### PART 3: AA PAGE ASSIGNMENT WORKSHEET

Table for the attorney to fill in the missing page numbers:

| Document | Description | Expected location | AA pages (to fill in) |
|----------|-------------|-------------------|----------------------|

---

### PART 4: CITATION FORMAT ISSUES

Flag any citations with formatting problems regardless of AA pages:
- Wrong dash type (hyphen instead of en dash)
- Period outside parenthesis instead of inside
- Incomplete volume references
- Non-standard abbreviations

| Issue | Citation | Correct format |
|-------|----------|----------------|

---

DRAFT — All [AA PAGE NEEDED] flags must be resolved by cross-referencing the
compiled appendix before filing.\
"""


class KLGAppendixCites(Skill):
    name = "klg-appendix-cites"
    description = (
        "Extract and format all record citations in a brief with Appellant's Appendix (AA) "
        "page references in California appellate format. Identifies citations missing AA pages "
        "and generates an assignment worksheet. "
        "Attach the brief (required) and optionally the appendix index."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or ""

        brief_text = ""
        appendix_index = ""

        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                for i, token in enumerate(file_tokens[:2]):
                    path = consume_token(token)
                    if path:
                        text = skill_read_file_text(path)
                        delete_file(path)
                        if i == 0:
                            brief_text = text
                        else:
                            appendix_index = text
            except Exception as e:
                logger.warning("klg-appendix-cites: file extraction failed: %s", e)

        if not brief_text:
            return SkillResult(
                summary="klg-appendix-cites: no brief provided.",
                output=(
                    "Attach the brief to format appendix citations:\n\n"
                    "`Alfred, run klg-appendix-cites on [Matter Name].`\n\n"
                    "**File 1 (required):** The brief with record citations to format\n"
                    "**File 2 (optional):** The appendix index (maps documents to AA pages)\n\n"
                    "Without the appendix index, citations will be flagged [AA PAGE NEEDED] "
                    "for manual completion."
                ),
                next_action="Upload the brief (and optionally the appendix index) and re-run.",
                success=False,
            )

        prompt = _APPENDIX_CITES_PROMPT.format(
            matter_summary=matter_text[:2000] if matter_text else "(No Notion context.)",
            brief_text=brief_text[:16000],
            appendix_index=appendix_index[:6000] if appendix_index else "(No appendix index uploaded — flag all unknown pages.)",
            instruction=instruction or "(No specific instructions — format all record citations.)",
            matter_label=matter_label,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Appendix citation audit complete for {matter_label}. "
                "Formatted citations, [AA PAGE NEEDED] flags, and assignment worksheet ready."
            ),
            output=f"**Appendix Citation Audit — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Fill in the AA Page Assignment Worksheet with actual appendix page numbers.\n"
                "2. Apply formatted citations to the brief.\n"
                "3. Run klg-cite-check after all citations are finalized.\n"
                "4. Verify the period-inside-parenthesis format before filing."
            ),
            success=True,
        )
