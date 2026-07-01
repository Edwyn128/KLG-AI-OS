"""
alfred/skills/klg_record_navigator.py — Map the trial record for appellate issues.

Takes uploaded record documents or a description of the case and produces an index
of key documents, preserved issues, harmless error risks, and supporting facts.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_generate, skill_read_file_text

logger = logging.getLogger(__name__)

_RECORD_NAV_PROMPT = """\
You are a KLG senior appellate attorney navigating the trial record to identify
preserved appellate issues and build the factual foundation for the brief.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

CRITICAL: Do NOT invent record facts, testimony, or rulings. If you are working from
a description rather than the actual record, flag every factual assertion that
needs verification: "[VERIFY from record]". Never fabricate a transcript page number.

WRITING RULES:
- Active verbs; lead with the finding
- Em dashes without spaces—like this
- No "furthermore", "therefore", "clearly", "it is well established"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RECORD DOCUMENTS / CASE DESCRIPTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{record_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a record navigation report with the following sections:

## Record Inventory

List key documents in the record by category:
- Pleadings and operative documents
- Trial court orders and rulings
- Trial transcripts (key hearings)
- Evidence / exhibits admitted
- Post-trial motions and rulings

For each: document name, approximate date, and why it matters on appeal.

## Preserved Appellate Issues

For each issue likely to be raised on appeal:

**Issue [N]: [Title]**
- What the issue is (1 sentence)
- How it was raised below: the motion, objection, or request that preserved it
- The court's ruling: [VERIFY from record if not confirmed]
- Preservation status: 🟢 Clearly preserved / 🟡 Arguably preserved / 🔴 Preservation risk
- If preservation risk: what argument keeps the issue alive (plain error? constitutional?)

## Facts That Support Our Narrative

5–10 specific record facts that favor the appellant/respondent (as applicable).
For each: what the fact shows and where in the record to find it (or "[VERIFY]").

## Harmless Error / Prejudice Risks

For each preserved issue: what harmless error argument will the opponent make,
and what facts in the record demonstrate prejudice?

## Record Gaps

What is missing from the record that should be there? Flag anything that should
have been admitted, objected to, or requested below that was not.

## Record Pull List

10 specific things to locate and cite before drafting the brief:
| Item | Why needed | Where to look |
|------|------------|---------------|

---

DRAFT — attorney review required. Verify all record citations before filing.\
"""


class KLGRecordNavigator(Skill):
    name = "klg-record-navigator"
    description = (
        "Map the trial record for appellate issues: document index, preserved issues, "
        "supporting facts, harmless error risks, and a record pull list. "
        "Upload record documents or describe the case in the instruction."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()

        record_text = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    record_text = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-record-navigator: file extraction failed: %s", e)

        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        prompt = _RECORD_NAV_PROMPT.format(
            matter_summary=matter_text[:3000],
            record_text=(record_text or instruction)[:15000],
            instruction=instruction[:1500] if record_text else "",
        )

        output_text = await skill_generate(prompt)

        return SkillResult(
            summary=f"Record navigation complete for {matter_label}. Preserved issues and record pull list ready.",
            output=f"**Record Navigator — {matter_label}**\n\n{output_text}",
            next_action=(
                "Work through the Record Pull List before drafting. "
                "Confirm preservation status for any issue marked 🟡 or 🔴."
            ),
            success=True,
        )
