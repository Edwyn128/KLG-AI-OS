"""
alfred/skills/klg_court_doc_renamer.py — KLG document naming convention generator.

Applies the KLG file naming convention to a list of court documents.
Standard format: YYYY-MM-DD_[MatterShort]_[DocType]_[Descriptor]_[Version].[ext]

This is a pure generation skill — no AI model call needed. The skill generates
a rename mapping from the user's document list and naming rules.
"""
from __future__ import annotations

import logging
import re

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_RENAMER_PROMPT = """\
You are a KLG legal assistant applying the firm's document naming convention to a list of court documents.

KLG DOCUMENT NAMING CONVENTION:
Format: YYYY-MM-DD_[MatterShort]_[DocType]_[Descriptor]_[Version].[ext]

MATTER SHORT: 1–3 word abbreviation of the matter name
  Smith v. CDCR → Smith-CDCR
  Williams v. Allstate Insurance → Williams-Allstate
  Petersen v. City of Los Angeles → Petersen-City

DOC TYPES (use exact abbreviations):
  AOB         — Appellant's Opening Brief
  RB          — Respondent's Brief
  Reply       — Appellant's Reply Brief
  Petition    — Petition for Review / Certiorari
  Answer      — Answer to Petition
  Motion      — Any trial court motion
  Opp         — Opposition to motion
  Reply-Mtn   — Reply in support of motion
  Order       — Court order
  Transcript  — Reporter's transcript
  CT          — Clerk's transcript
  AA          — Appendix / Appellant's Appendix
  RA          — Respondent's Appendix
  JA          — Joint Appendix
  Decl        — Declaration
  Ex          — Exhibit
  Stip        — Stipulation
  Notice      — Notice of filing, appeal, etc.
  Judgment    — Judgment / Final order
  SOF         — Separate Statement of Facts
  Complaint   — Initial complaint
  Answer-Cmp  — Answer to complaint

DESCRIPTOR: 1–4 word description of the specific document
  "Draft", "Final", "Filed", "Redlined", "Sections-I-III"

VERSION: v1, v2, v3 (omit on final filed versions)

DATE RULES:
  - Use the filing date, deposition date, or order date if known
  - If no date known, use the current date for drafts
  - Format: YYYY-MM-DD

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER: {matter_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MATTER SHORT FORM: {matter_short}

DOCUMENTS TO RENAME:
{doc_list}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce:

## DOCUMENT RENAME MAPPING — {matter_label}

For each document, produce:

| # | Original Name | Proposed KLG Name | Notes |
|---|---------------|-------------------|-------|

After the table, flag any documents where:
- The date is unknown (use [DATE] as placeholder)
- The doc type is ambiguous (offer two options)
- The descriptor needs attorney input

### RENAME SCRIPT (for SharePoint/Windows use)

Produce a list of rename commands in plain text:
```
OLD: [original filename]
NEW: [KLG filename]

OLD: [original filename]
NEW: [KLG filename]
```

### NAMING NOTES

- [Any patterns noticed in the document set]
- [Any conflicts or near-duplicates that need resolution]
- [Recommendations for folder organization]
\
"""


class KLGCourtDocRenamer(Skill):
    name = "klg-court-doc-renamer"
    description = (
        "Apply the KLG document naming convention to a list of court documents. "
        "Produces a rename mapping table and plain-text rename script. "
        "Paste or upload a list of document names, or describe the documents to rename."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"

        doc_list = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    doc_list = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-court-doc-renamer: file extraction failed: %s", e)

        if not doc_list and instruction:
            doc_list = instruction
            instruction = ""

        if not doc_list:
            return SkillResult(
                summary="klg-court-doc-renamer: no document list provided.",
                output=(
                    "Provide the document names to rename:\n\n"
                    "`Alfred, run klg-court-doc-renamer on [Matter Name]: [list documents]`\n\n"
                    "Or upload a text file containing the list of current document names.\n\n"
                    "**KLG naming format:**\n"
                    "`YYYY-MM-DD_[MatterShort]_[DocType]_[Descriptor]_[Version].[ext]`\n\n"
                    "**Example:**\n"
                    "`2024-11-15_Smith-CDCR_AOB_Final.docx`"
                ),
                next_action="Provide a list of document names to rename.",
                success=False,
            )

        matter_short = ""
        if ctx.matter_name:
            parts = re.sub(r"\bv\b\.?", "v", ctx.matter_name, flags=re.IGNORECASE).split()
            short_parts = [p for p in parts if p.lower() not in ("v", "v.", "the", "of", "in", "re")]
            matter_short = "-".join(short_parts[:2]) if short_parts else ctx.matter_name[:20]

        prompt = _RENAMER_PROMPT.format(
            matter_label=matter_label,
            matter_short=matter_short or "[MATTER-SHORT]",
            doc_list=doc_list[:8000],
            instruction=instruction or "(No specific instructions.)",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Document rename mapping generated for {matter_label}. "
                "KLG-format names and rename script ready."
            ),
            output=f"**Document Renamer — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Review any [DATE] placeholders and fill in actual dates.\n"
                "2. Apply the rename script to SharePoint documents.\n"
                "3. Update Notion document links if any were previously stored."
            ),
            success=True,
        )
