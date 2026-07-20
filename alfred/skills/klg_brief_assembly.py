"""
alfred/skills/klg_brief_assembly.py — Brief assembly content generation for KLG.

Two modes:
  CONTENT GENERATION — Alfred generates polished brief content (introduction,
  argument sections, conclusion, statement of facts) in KLG house style.
  This is the primary mode in Alfred Chat.

  ASSEMBLY GUIDANCE — Alfred explains the Word XML assembly process using
  the standalone script at alfred/skills/scripts/assemble_brief.py.
  Actual .docx packaging requires the script + pandoc in Alfred Code or Cowork.

CRITICAL: Before treating any uploaded document as a fresh-build target,
determine whether this is a REVISION (targeted edits to existing work) or a
FRESH BUILD (assemble from template). A revision requires surgical edits only.
A fresh build uses the full assembly workflow.

KLG Custom Word Styles (for assembly script):
  P1Pleading1  — Top-level headings (centered, small caps, Century Schoolbook 13pt)
                 Pandoc Heading1 → P1Pleading1
  P2Pleading2  — Lettered argument subsections (A. B. C.) — auto-numbered via style
                 Pandoc Heading2 → P2Pleading2 (do NOT include numId=0 — kills numbering)
  P3Pleading3  — Numbered subsections (1. 2. 3.) — auto-numbered via style
                 Pandoc Heading3 (in Argument) → P3Pleading3
  BodyText     — Standard body paragraphs
                 Pandoc FirstParagraph → BodyText
  Italic BodyText — Narrative subheadings in Statement of Case
                 Pandoc Heading3 (in Statement of Case) → Italic BodyText + keepNext
  Quote        — Block quotes (1440 twips indent each side — NO quotation marks)
                 Pandoc BlockText → Quote

Brief structure boundaries (for assemble_brief.py --boundaries):
  Petition: intro_heading, petition_start, memo_pagebreak, cert_pagebreak
  Opening/Reply/Respondent: intro_heading, cert_pagebreak

Post-assembly checklist (attorney does in Word):
  1. Update TOC: right-click → Update Field → Update Entire Table
  2. Update TOA: same
  3. Update Certificate of Word Count (after TOC refresh)
  4. Search for [RECORD CITE NEEDED] and [VERIFY] placeholders
  5. Verify P2/P3 numbering renders correctly (A. B. C. / 1. 2. 3.)
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_KLG_STYLE_RULES = """\
KLG HOUSE STYLE — California Appellate Briefs (non-negotiable):

TYPOGRAPHY AND PUNCTUATION:
  - Em dashes without spaces—like this (never spaced out — like this)
  - Oxford comma in all series
  - No exclamation points anywhere in the brief
  - Numerals: spell out one through nine; figures for 10+
    (exception: always figures for %, $, record citations, rule numbers)
  - Italics for case names and for emphasis in brief text
  - Bold acceptable only for dates. Never bold for textual emphasis.

PROHIBITED LANGUAGE (never use these — courts notice):
  - "instant case" / "case at bar" → use the case name or "this case"
  - "furthermore" / "moreover" → restructure the sentence
  - "therefore" / "thus" / "hence" → restructure or use a period
  - "clearly" / "obviously" / "plainly" → cut the word
  - "it is axiomatic" / "it is well established" / "it is beyond dispute"
  - "as such" → "accordingly" or restructure
  - "hereinabove" / "hereinbelow" / "aforementioned" → use specific references
  - Doubled modifiers: "clearly and unambiguously," "fully and completely"
  - Throat-clearing: "It is important to note that..." → cut the setup

ARGUMENT STRUCTURE (CREAC):
  - Conclusion (up front) → Rule → Explanation → Application → Conclusion
  - Lead each argument section with a point heading that is a full declaratory sentence
  - Point headings: ALL CAPS in California appellate briefs (CRC rule 8.204(a)(1)(B))
  - Every factual assertion in the argument must cite to the record: (RT 245:3–7) or (CT 12)
  - Block quotes: indented, NO surrounding quotation marks (indentation signals the quote)
    Citation after a block quote goes on its own line with no first-line indent

CITATIONS (California style):
  - Cases: *Party v. Party* (Year) Vol Cal.5th Page, Pinpoint.
    E.g.: *Garcetti v. Ceballos* (2006) 547 U.S. 410, 421.
  - Statutes: Full cite first use; short form thereafter (§ 1983)
  - Record: RT = Reporter's Transcript; CT = Clerk's Transcript; AA = Appellant's Appendix
  - Rules of Court short form: after first full cite, just "rule 8.108(e)(2)"
    (not "Cal. Rules of Court, rule...")
  - NEVER fabricate citations, page numbers, volume numbers, or holdings
    Flag uncertain cites: [VERIFY CITATION]
    Flag record cites not confirmed from source: [RECORD CITE NEEDED — not found in source]

PARTY DESIGNATIONS:
  - Refer to client by appellate designation (appellant, respondent), not trial designations
    (plaintiff, defendant) unless quoting a trial court document
"""

_BRIEF_STRUCTURES = {
    "petition": """\
WRIT PETITION STRUCTURE (preserve all back matter exactly as templated):
  [FRONT MATTER — preserve] Cover, Cert of Interested Entities, TOC, TOA
  [INTRODUCTION — replace body, preserve heading] BodyText paragraphs only
  [FORMAL PETITION — preserve entirely] I. Parties/Jurisdiction, II. Background,
    III. Irreparable Harm, IV. Stay Request, V. Authenticity/Prayer, Verification
  [MEMORANDUM — replace body, preserve page break + heading]
    Statement of the Case | Standard of Review | Argument | Conclusion
  [BACK MATTER — preserve] Certificate of Word Count, Signature, Attachment
""",
    "opening": """\
OPENING BRIEF STRUCTURE:
  [FRONT MATTER — preserve] Cover, Cert, TOC, TOA
  [BODY — replace] Introduction | Statement of the Case | Standard of Review
                   Argument (A. B. C. with subsections) | Conclusion
  [BACK MATTER — preserve] Certificate of Word Count, Proof of Service
""",
    "reply": """\
REPLY BRIEF STRUCTURE (no Statement of Case or SOR unless respondent misstated):
  [FRONT MATTER — preserve]
  [BODY — replace] Introduction | Argument (responding to RB arguments) | Conclusion
  [BACK MATTER — preserve]
""",
    "respondent": """\
RESPONDENT'S BRIEF STRUCTURE:
  [FRONT MATTER — preserve]
  [BODY — replace] Introduction | Statement of the Case (respondent's framing)
                   Standard of Review | Argument | Conclusion
  [BACK MATTER — preserve]
""",
}

_CONTENT_PROMPT = """\
You are a KLG senior appellate attorney generating brief content for {matter_label}.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REVISION VS. FRESH BUILD CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{revision_note}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KLG HOUSE STYLE (non-negotiable):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{style_rules}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DRAFT OR OUTLINE PROVIDED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{draft_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRIEF TYPE: {brief_type}
{brief_structure}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

INSTRUCTION: {instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Generate the requested sections. For each section:

POINT HEADINGS:
  Top-level: ALL CAPS DECLARATORY SENTENCE (P1Pleading1 style)
  Lettered subsections: Bold declaratory sentence — auto-numbered A. B. C.
    (do not write "A." manually — the Word style provides the letter)
  Numbered subsections: Bold declaratory sentence — auto-numbered 1. 2. 3.
    (do not write "1." manually)
  In Statement of Case: *Italic narrative subheading for each factual section.*

ARGUMENT TEXT (CREAC per section):
  - Lead with the conclusion
  - State the rule (with citation)
  - Explain with controlling authority (with explanatory parentheticals)
  - Apply to the facts — every factual assertion needs a record cite
    If record cite is not confirmed: [RECORD CITE NEEDED — verify from RT/CT]
  - Conclude with the specific relief requested

CITATIONS:
  - Use California citation style
  - Every citation that needs Westlaw verification: [VERIFY CITATION]
  - NEVER fabricate page numbers, volume numbers, or holdings

ASSEMBLY GUIDANCE (append at end of output):
---
**Assembly Notes for Word:**
This content is ready for the brief pipeline after attorney review.

For targeted edits to an existing .docx: use Track Changes in Word.

For a fresh build using the assembly script:
  1. Save this output as `memo.md` (or `intro.md` + `memo.md` for petition)
  2. Unpack the template: `python unpack.py template.docx unpacked/`
  3. Run assembly:
     ```
     python alfred/skills/scripts/assemble_brief.py \\
       --template unpacked/ \\
       --content-body memo.md \\
       --brief-type {brief_type_lower} \\
       --output-dir assembled/ \\
       --original-docx template.docx \\
       --boundaries "intro_heading:NNNN,cert_pagebreak:NNNN"
     ```
     (Find boundary line numbers by grepping the unpacked document.xml)
  4. Repack: `python pack.py assembled/ output.docx --original template.docx`
  5. Fix standalone: `python fix_docx_standalone.py output.docx`
  6. Open in Word → Update TOC, TOA, and Certificate of Word Count fields
  7. Search for [RECORD CITE NEEDED] and [VERIFY CITATION] placeholders

Post-assembly attorney checklist:
  ☐ Record citations verified (all [RECORD CITE NEEDED] resolved)
  ☐ Case citations verified in Westlaw (all [VERIFY CITATION] resolved)
  ☐ TOC updated in Word
  ☐ TOA updated in Word
  ☐ Certificate of Word Count updated
  ☐ P2/P3 heading numbering renders correctly (A. B. C. / 1. 2. 3.)
  ☐ Block quotes indented, no quotation marks
  ☐ Style Guide Check run (klg-style-guide-check)
  ☐ Cite Check run (klg-cite-check)
---

DRAFT — attorney review required before filing. All [VERIFY] flags must be
resolved. KLG house style confirmed by senior attorney before submission.
"""


def _detect_brief_type(instruction: str) -> str:
    text = instruction.lower()
    if any(k in text for k in ("writ", "supersedeas", "mandate", "prohibition", "certiorari", "petition")):
        return "petition"
    if any(k in text for k in ("reply brief", "reply")):
        return "reply"
    if any(k in text for k in ("respondent", "respondent's", "respondents'")):
        return "respondent"
    return "opening"


class KLGBriefAssembly(Skill):
    name = "klg-brief-assembly"
    required_tools = ["search_notion", "search_sharepoint"]
    description = (
        "Generate polished brief content (introduction, argument sections, conclusion, "
        "statement of facts) in KLG house style with all prohibited phrases and style "
        "rules enforced. Returns section text with record cite placeholders. "
        "Includes assembly guidance for assemble_brief.py (requires pandoc + Alfred Code/Cowork). "
        "Handles all brief types: petition, opening, reply, respondent."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_summary = ctx.matter_summary or "(No Notion project page found.)"
        brief_type = _detect_brief_type(instruction)

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
                    "Specify which sections to generate and the brief type:\n\n"
                    "`Alfred, run klg-brief-assembly on [Matter Name]: "
                    "[instruction — e.g., 'generate Introduction and Statement of Facts "
                    "for appellant's opening brief']`\n\n"
                    "Optionally upload a draft or outline.\n\n"
                    "**Sections Alfred can generate:**\n"
                    "- Introduction\n"
                    "- Statement of the Case / Facts\n"
                    "- Standard of Review\n"
                    "- Argument sections (by issue — specify the legal question)\n"
                    "- Conclusion / Prayer for Relief\n"
                    "- Cover page metadata\n\n"
                    "**Brief types:** petition (writ supersedeas/mandate), opening, reply, respondent\n\n"
                    "**For .docx assembly after generating content:**\n"
                    "Use `alfred/skills/scripts/assemble_brief.py` with pandoc in Alfred Code/Cowork."
                ),
                next_action="Re-run with a specific section instruction and brief type.",
                success=False,
            )

        # Revision vs. fresh build check
        is_revision = draft_text and any(k in instruction.lower() for k in (
            "fix", "edit", "change", "update", "revise", "correct", "add citations",
            "targeted", "only change",
        ))
        revision_note = (
            "REVISION MODE DETECTED: The uploaded document contains existing edits. "
            "Make ONLY the specific changes requested — do not rebuild or regenerate "
            "content that wasn't asked for. Surgical edits only."
        ) if is_revision else (
            "FRESH GENERATION: Generate the requested sections from scratch using "
            "the matter context, any uploaded draft/outline, and KLG style rules."
        )

        # Pull from SharePoint/Notion if no draft provided
        fetch_note = ""
        if not draft_text:
            fetch_note = (
                f"BEFORE WRITING: Use search_sharepoint and search_notion to check "
                f"if a draft, outline, or prior brief exists for {matter_label}. "
                "Incorporate what you find as the starting point.\n\n"
            )

        brief_structure = _BRIEF_STRUCTURES.get(brief_type, _BRIEF_STRUCTURES["opening"])

        prompt = fetch_note + _CONTENT_PROMPT.format(
            matter_label=matter_label,
            revision_note=revision_note,
            matter_summary=matter_summary[:2000],
            style_rules=_KLG_STYLE_RULES,
            draft_text=draft_text[:12000] if draft_text else "(No draft — generate from instruction and matter context.)",
            brief_type=brief_type.upper(),
            brief_type_lower=brief_type,
            brief_structure=brief_structure,
            instruction=instruction or "Generate Introduction and Statement of Facts.",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Brief content ({brief_type}) generated for {matter_label}. "
                "Attorney review and [VERIFY] resolution required before filing."
            ),
            output=f"**Brief Assembly — {matter_label} ({brief_type.title()})**\n\n{output_text}",
            next_action=(
                "1. Resolve all [RECORD CITE NEEDED] flags — confirm from RT/CT.\n"
                "2. Resolve all [VERIFY CITATION] flags — confirm in Westlaw.\n"
                "3. Run klg-style-guide-check and klg-cite-check before filing.\n"
                "4. For .docx assembly: use assemble_brief.py in Alfred Code/Cowork "
                "(requires pandoc; see assembly notes at end of output)."
            ),
            success=True,
        )
