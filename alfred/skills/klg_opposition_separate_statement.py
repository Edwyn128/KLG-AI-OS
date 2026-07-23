"""
alfred/skills/klg_opposition_separate_statement.py — California MSJ separate statement response.

California Rule of Court 3.1350 requires the opposing party to respond to the moving party's
Separate Statement of Undisputed Material Facts in an MSJ. Each numbered fact must be admitted,
denied, or objected to, with supporting evidence cited for any denial.

This skill drafts the full opposition separate statement from the moving party's filing.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_OSS_PROMPT = """\
You are a KLG appellate attorney drafting an opposition to a Separate Statement
of Undisputed Material Facts for a California summary judgment motion.

CALIFORNIA LAW REQUIREMENTS (California Rules of Court, rule 3.1350):
- Each numbered fact from the moving party must be addressed individually.
- Response format for each fact: Disputed / Undisputed / Objection
- For Disputed: state why disputed AND cite supporting evidence from the record
  (declaration paragraph, deposition page/line, exhibit number)
- For Undisputed: simply write "Undisputed."
- For Objection: state the evidentiary basis (foundation, hearsay, relevance, etc.)
  followed by the response on the merits (Disputed or Undisputed)
- Additional facts: after addressing all moving party facts, may add "Additional
  Material Facts" that raise triable issues

KLG WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "as such"
- Active voice. Be concise—the form is functional, not persuasive prose.
- Every denial must cite specific record evidence. No evidence = cannot deny.
- CRITICAL: Do not invent record facts, citations, or deposition testimony.
  Flag any gap: "[NEED RECORD CITE — attorney to supply]"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MOVING PARTY'S SEPARATE STATEMENT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{moving_statement}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUR EVIDENCE AND ADDITIONAL FACTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{our_evidence}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce:

## PLAINTIFF/DEFENDANT'S OPPOSITION TO SEPARATE STATEMENT
## OF UNDISPUTED MATERIAL FACTS

Case: {matter_label}
Status: DRAFT — Evidence citations require attorney verification

---

### RESPONSES TO MOVING PARTY'S FACTS

For each numbered fact, use this format exactly:

**Moving Party's Fact No. [N]:**
[Quote the moving party's fact verbatim]

**Supporting Evidence (Moving Party):**
[Quote or summarize their cited evidence]

**Response:** [DISPUTED / UNDISPUTED / OBJECTION AND DISPUTED / OBJECTION AND UNDISPUTED]

**Opposing Party's Evidence (if Disputed):**
[Cite specific record evidence: "Declaration of [Name], ¶[N]" / "Deposition of [Name] [page]:[line]–[line]" / "Exhibit [N] at [page]"]

**Explanation of Dispute (if Disputed, optional, ≤2 sentences):**
[Why the evidence creates a triable issue of fact]

---

[Repeat for every numbered fact]

---

### PLAINTIFF/DEFENDANT'S ADDITIONAL MATERIAL FACTS
(Facts that raise genuine issues of triable fact not addressed above)

**Additional Fact No. [N]:**
[State the additional fact]

**Supporting Evidence:**
[Specific record citation — [NEED RECORD CITE — attorney to supply] if unknown]

---

### COUNSEL'S CHECKLIST BEFORE FILING

- [ ] Every "Disputed" response has a specific record cite (no naked denials)
- [ ] Every "[NEED RECORD CITE]" flag has been resolved
- [ ] All declaration paragraph numbers verified against actual declarations
- [ ] All deposition page/line cites verified against transcript
- [ ] Additional Material Facts section reviewed for completeness
- [ ] Format conforms to CRC 3.1350 and local court rules

---

DRAFT — attorney review and record-cite verification required before filing.\
"""


class KLGOppositionSeparateStatement(Skill):
    name = "klg-opposition-separate-statement"
    description = (
        "Draft the opposition to a moving party's Separate Statement of Undisputed Material Facts "
        "for a California MSJ. Produces admitted/denied responses in CRC 3.1350 format with "
        "record citations and Additional Material Facts section. Attach the moving party's "
        "separate statement and your supporting evidence summary."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        moving_statement = ""
        our_evidence = ""
        files_read = []

        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                for i, token in enumerate(file_tokens[:2]):
                    path = consume_token(token)
                    if path:
                        text = skill_read_file_text(path)
                        delete_file(path)
                        if i == 0:
                            moving_statement = text
                        else:
                            our_evidence = text
                        files_read.append(i + 1)
            except Exception as e:
                logger.warning("klg-opposition-separate-statement: file extraction failed: %s", e)

        if not moving_statement:
            return SkillResult(
                summary="klg-opposition-separate-statement: no moving party statement provided.",
                output=(
                    "Attach the moving party's Separate Statement to draft the opposition:\n\n"
                    "`Alfred, run klg-opposition-separate-statement on [Matter Name].`\n\n"
                    "**File 1 (required):** Moving party's Separate Statement of Undisputed Material Facts\n"
                    "**File 2 (optional):** Your evidence summary, declaration outlines, or depo highlights\n\n"
                    "Also describe any specific disputed facts to prioritize:\n"
                    "'Focus on Facts 3, 7, and 12 — those are our strongest disputes.'"
                ),
                next_action="Upload the moving party's Separate Statement and re-run.",
                success=False,
            )

        prompt = _OSS_PROMPT.format(
            matter_summary=matter_text[:2000],
            moving_statement=moving_statement[:14000],
            our_evidence=our_evidence[:6000] if our_evidence else "(No supporting evidence file uploaded — flag all denials as [NEED RECORD CITE].)",
            instruction=instruction or "(No specific instructions — draft full opposition to all facts.)",
            matter_label=matter_label,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Opposition separate statement drafted for {matter_label}. "
                "All moving-party facts addressed; record cites flagged for verification."
            ),
            output=f"**Opposition to Separate Statement — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Resolve every [NEED RECORD CITE] flag before filing.\n"
                "2. Verify all declaration paragraph numbers against the actual declarations.\n"
                "3. Check local court rules for any format requirements beyond CRC 3.1350.\n"
                "4. Route to Tim for substantive review of the dispute positions."
            ),
            success=True,
        )
