"""
alfred/skills/klg_brief_assembly.py — Brief assembly content generation for KLG.

Generates polished content for each section of a KLG appellate brief:
cover page metadata, table of contents/authorities stubs, introduction,
argument sections, and conclusion — all in KLG house style.

IMPORTANT — SCRIPT DEPENDENCY:
Actual .docx assembly requires the brief pipeline scripts:
  • unpack.py   — extracts Word XML from an existing shell .docx
  • pack.py     — repackages XML changes back into .docx
  • assemble_brief.py — orchestrates the full build

These scripts run in the Alfred Code or Cowork environment, NOT in the
Alfred web chat. This skill generates the CONTENT (text for each section).
A second step assembles it into .docx using the scripts.

Usage:
  "Alfred, run klg-brief-assembly on [Matter Name]: [instruction]"

  Instruction examples:
    "generate the introduction and Statement of Facts for appellant's opening brief"
    "draft Argument Section II on the Garcetti issue"
    "produce the conclusion and signature block"

  Optionally upload a draft or outline for Alfred to build from.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_KLG_STYLE_RULES = """\
KLG HOUSE STYLE — California Appellate Briefs:

Typography and punctuation:
  - Em dashes without spaces—like this (never spaced out — like this)
  - Oxford comma required in all series
  - No exclamation points anywhere in the brief
  - Numerals: spell out one through nine; use figures for 10 and above
    (exception: always use figures for percentages, dollar amounts, record citations)

Prohibited language (never use these):
  - "instant case" / "case at bar" → use the case name or "this case"
  - "furthermore" / "moreover" → restructure the sentence
  - "therefore" / "thus" / "hence" → restructure or use a period
  - "clearly" / "obviously" / "plainly" → cut the word; if it's clear, it shows
  - "it is axiomatic" / "it is well established" / "it is beyond dispute"
  - "as such" → "accordingly" or restructure
  - "hereinabove" / "hereinbelow" / "aforementioned" → use specific references
  - Doubled modifiers: "clearly and unambiguously," "fully and completely"
  - Throat-clearing openers: "It is important to note that..." → cut the setup

Argument structure:
  - CREAC: Conclusion (up front) → Rule → Explanation → Application → Conclusion
  - Lead each argument section with a point heading that is a full declaratory sentence
  - Point headings are ALL CAPS in California appellate briefs (CRC rule 8.204(a)(1)(B))
  - Every factual assertion in the argument must cite to the record: (RT 245:3–7) or (CT 12)

Citations (California style):
  - Cases: Name v. Name (Year) Vol Reporter Page, Pinpoint. — e.g., Garcetti v. Ceballos (2006) 547 U.S. 410, 421.
  - Statutes: Full cite on first use; short form thereafter (§ 1983)
  - Record: RT = Reporter's Transcript; CT = Clerk's Transcript; AA = Appellant's Appendix
  - NEVER fabricate citations. Flag any uncertain cite: [VERIFY CITATION]

Do NOT add bold or italics for rhetorical emphasis. Case names are italicized.
No footnotes unless the court requires them.
"""

_ASSEMBLY_PROMPT = """\
You are a KLG senior appellate attorney generating brief content for {matter_label}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DRAFT / OUTLINE PROVIDED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{draft_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KLG HOUSE STYLE (non-negotiable)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{style_rules}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCTION:
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Generate the requested brief content. For each section:

1. COVER PAGE METADATA (if requested):
   - Case name and appellate case number: [VERIFY from record]
   - Court name and division
   - Party designations (Appellant / Respondent / Cross-Appellant)
   - Attorney of record: Timothy R. Kowal, SBN [VERIFY]
   - Firm: Kowal Law Group, APC
   - Filing date: [leave blank — attorney fills in]

2. POINT HEADINGS (if generating argument sections):
   - ALL CAPS, full declaratory sentence
   - Subheadings: Mixed Case, full declaratory sentence
   - Every heading must tell a complete story on its own (the TOC should be an argument outline)

3. ARGUMENT TEXT:
   - Lead with the conclusion
   - State the rule (with citation)
   - Explain the rule with the controlling authority
   - Apply to the facts (with record citations in brackets: [VERIFY RT ___:_])
   - Conclude with the requested relief
   - Every factual assertion → [VERIFY — record cite needed]

4. CITATIONS:
   - Use California citation style
   - Flag every citation that needs Westlaw verification: [VERIFY CITATION]
   - Never fabricate page numbers, volume numbers, or holdings

5. CONCLUSION / PRAYER FOR RELIEF (if requested):
   - State the precise relief sought
   - California format: "For the foregoing reasons, [Appellant/Respondent] respectfully
     requests that this Court [relief]."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ASSEMBLY NOTE (for attorney):

This content is ready for the brief pipeline once reviewed:
  1. Review and verify all [VERIFY] flags
  2. Copy polished sections into the Word shell (.docx)
     OR use the brief scripts in Alfred Code/Cowork:
       python unpack.py brief_shell.docx
       [paste content into extracted XML]
       python pack.py brief_shell.docx
       python /mnt/skills/user/klg-shared-scripts/fix_docx_standalone.py output.docx
  3. Run klg-cite-check before filing

DRAFT — attorney review required before filing. All [VERIFY] flags must be
resolved. KLG house style confirmed by senior attorney.\
"""


class KLGBriefAssembly(Skill):
    name = "klg-brief-assembly"
    required_tools = ["search_notion", "search_sharepoint"]
    description = (
        "Generate polished brief content (introduction, argument sections, conclusion) "
        "in KLG house style. Returns section text ready for attorney review and Word assembly. "
        "Actual .docx packaging requires the brief pipeline scripts (Alfred Code/Cowork)."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_summary = ctx.matter_summary or "(No Notion project page found.)"

        draft_text = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    draft_text = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-brief-assembly: file extraction failed: %s", e)

        if not instruction and not draft_text and not matter_summary:
            return SkillResult(
                summary="klg-brief-assembly: no instruction or content provided.",
                output=(
                    "Specify which sections to generate:\n\n"
                    "`Alfred, run klg-brief-assembly on [Matter Name]: "
                    "[instruction — e.g., 'generate Introduction and Statement of Facts']`\n\n"
                    "Optionally upload a draft or outline for Alfred to build from.\n\n"
                    "Sections Alfred can generate:\n"
                    "- Cover page metadata\n"
                    "- Introduction\n"
                    "- Statement of the Case / Facts\n"
                    "- Standard of Review\n"
                    "- Argument sections (by issue)\n"
                    "- Conclusion / Prayer for Relief\n"
                    "- Signature block"
                ),
                next_action="Re-run with a specific section instruction.",
                success=False,
            )

        # If no draft provided and the scoped agent has search_sharepoint,
        # prime it to look for existing brief content
        fetch_note = ""
        if not draft_text:
            fetch_note = (
                "BEFORE WRITING: Use search_sharepoint to check if a draft brief "
                f"or outline exists for {matter_label}. Use search_notion to pull any "
                "research notes or prior analysis for this matter. Incorporate what you find.\n\n"
            )

        prompt = fetch_note + _ASSEMBLY_PROMPT.format(
            matter_label=matter_label,
            matter_summary=matter_summary[:3000],
            draft_text=draft_text[:12000] if draft_text else "(No draft provided — generate from matter context and instruction.)",
            style_rules=_KLG_STYLE_RULES,
            instruction=instruction or "Generate the Introduction and Statement of Facts.",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=f"Brief content generated for {matter_label}. Attorney review and [VERIFY] resolution required before filing.",
            output=f"**Brief Assembly — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Resolve all [VERIFY] flags — record cites and citations must be confirmed.\n"
                "2. Copy into Word shell, OR use the brief scripts in Alfred Code/Cowork "
                "(unpack.py → pack.py → fix_docx_standalone.py).\n"
                "3. Run klg-cite-check on the assembled brief before filing."
            ),
            success=True,
        )
