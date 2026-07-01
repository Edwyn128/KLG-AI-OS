"""
alfred/skills/klg_appendix_audit.py — Appendix underinclusivity audit.

Given the full docket (all documents in the record) and a proposed compile
folder list (documents proposed for inclusion), identifies items NOT proposed
and flags any that look important.

Tim's use case: appellate record compilation — catch the documents that got
left out before the appendix is lodged.

CONFIDENTIALITY RULE: never echo client names or case facts into web searches.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate, skill_read_file_text

logger = logging.getLogger(__name__)

_AUDIT_PROMPT = """\
You are a KLG senior appellate attorney auditing a proposed appendix for underinclusivity.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

WRITING RULES (non-negotiable):
- Active verbs; no nominalizations or gerunds where a verb works better
- Em dashes without spaces—like this—not like this —
- No "furthermore", "therefore", "clearly", "it is axiomatic", "as such",
  "instant case", "aforementioned", "hereinabove", "it is well established"
- No doubled modifiers
- Lead with the conclusion; context follows
- Every draft must close with: DRAFT — attorney review required

CONFIDENTIALITY: This audit is privileged work product.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FULL DOCKET (all documents in the record)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{docket_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PROPOSED COMPILE FOLDER (documents proposed for appendix inclusion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{compile_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Your job is to audit the proposed appendix for UNDERINCLUSIVITY—documents that
exist in the record but are not proposed for inclusion.

Produce a structured audit report with the following sections:

## Audit Summary

2–3 sentences. How complete is the proposed compile folder relative to the
full docket? What is the most significant omission risk?

## Excluded Documents — Flag for Review

For each document in the docket that is NOT in the proposed compile folder,
evaluate its importance and provide:

| # | Document | Why It May Matter | Risk Level |
|---|----------|-------------------|------------|

Risk levels:
- 🔴 HIGH — likely needed; omission may prejudice the record
- 🟡 MEDIUM — potentially relevant; attorney should make a conscious decision
- 🟢 LOW — probably safe to exclude (duplicative, procedural, irrelevant)

Sort by risk level (HIGH first).

## Inclusion Gaps by Category

Group the high- and medium-risk excluded documents by category:
- Pleadings and operative documents
- Orders and judgments
- Evidence / exhibits
- Expert materials
- Deposition excerpts
- Discovery motions and rulings
- Other

For each category: how many excluded documents, and what is the net risk?

## Recommended Additions

List only the HIGH-risk excluded documents with a one-sentence rationale for
each. These are the documents the attorney should consider adding before lodging.

## Documents Confirmed Included

Brief confirmation: list the count of proposed documents and note any
categories well-represented in the compile folder.

---

DRAFT — attorney review required. Do not lodge without attorney sign-off.\
"""


class KLGAppendixAudit(Skill):
    name = "klg-appendix-audit"
    description = (
        "Audit a proposed appendix compile folder for underinclusivity: "
        "compare the full docket against proposed inclusions and flag documents "
        "that were left out but may be important. Upload or paste both lists."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()

        # ── Extract document lists from uploaded files or instruction text ─────
        # Convention: if two files are uploaded, first = docket, second = compile.
        # If one file is uploaded, it's the docket; compile comes from instruction text.
        # If no files, both lists must be pasted inline in the instruction.
        docket_text, compile_text = await _extract_document_lists(
            file_tokens, instruction
        )

        if not docket_text:
            return SkillResult(
                summary="klg-appendix-audit: no docket provided.",
                output=(
                    "To run an appendix audit, provide the full docket and the proposed "
                    "compile folder. Two options:\n\n"
                    "1. **Upload two files** (docket first, compile folder second), then run:\n"
                    "   `Alfred, run klg-appendix-audit on [Matter Name]`\n\n"
                    "2. **Paste both lists** as the instruction:\n"
                    "   `Alfred, run klg-appendix-audit on [Matter Name]:\n"
                    "   DOCKET: [list]\n"
                    "   COMPILE: [list]`\n\n"
                    "3. **Upload the docket** and paste the compile folder list "
                    "inline in the instruction."
                ),
                next_action="Provide the full docket and proposed compile folder, then re-run.",
                success=False,
            )

        if not compile_text:
            return SkillResult(
                summary="klg-appendix-audit: docket provided but no compile folder list.",
                output=(
                    "Docket received. To complete the audit, also provide the proposed "
                    "compile folder:\n\n"
                    "- Upload the compile folder list as a second file, OR\n"
                    "- Include it in the instruction after `COMPILE:`"
                ),
                next_action="Provide the proposed compile folder list and re-run.",
                success=False,
            )

        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found for this matter.)"

        prompt = _AUDIT_PROMPT.format(
            matter_summary=matter_text[:3000],
            docket_text=docket_text[:15000],
            compile_text=compile_text[:10000],
            instruction=instruction[:1000],
        )

        output_text = await skill_generate(prompt)

        return SkillResult(
            summary=(
                f"Appendix underinclusivity audit complete for {matter_label}. "
                "Excluded documents flagged for attorney review."
            ),
            output=(
                f"**Appendix Audit — {matter_label}**\n\n"
                f"{output_text}"
            ),
            next_action=(
                "Review the HIGH-risk excluded documents and decide which to add. "
                "Update the compile folder accordingly before lodging."
            ),
            success=True,
        )


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

async def _extract_document_lists(
    file_tokens: list[str], instruction: str
) -> tuple[str, str]:
    """Return (docket_text, compile_text) from uploaded files + instruction."""
    texts: list[str] = []

    for token in file_tokens[:2]:
        try:
            from alfred.file_store import consume_token, delete_file
            path = consume_token(token)
            if path:
                text = skill_read_file_text(path)
                delete_file(path)
                if text:
                    texts.append(text)
        except Exception as e:
            logger.warning("klg-appendix-audit: file extraction failed: %s", e)

    if len(texts) >= 2:
        return texts[0], texts[1]

    if len(texts) == 1:
        compile_from_instruction = _parse_section(instruction, "COMPILE")
        return texts[0], compile_from_instruction

    # No files — parse both from inline instruction text
    docket_from_instruction = _parse_section(instruction, "DOCKET")
    compile_from_instruction = _parse_section(instruction, "COMPILE")
    return docket_from_instruction, compile_from_instruction


def _parse_section(text: str, label: str) -> str:
    """Extract text after LABEL: up to the next section label or end of string."""
    import re
    pattern = rf"{label}\s*:?\s*\n(.*?)(?=\n[A-Z]{{3,}}\s*:|\Z)"
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # If no sections found and this is the only label, return everything after it
    idx = text.upper().find(f"{label.upper()}:")
    if idx >= 0:
        return text[idx + len(label) + 1:].strip()
    return ""


