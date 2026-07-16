"""
alfred/skills/klg_prebill_audit.py — Pre-bill time-entry audit before finalization.

Reads a Clio-exported CSV of time entries and flags billing problems before
the bill goes to the client:

  • Block billing — multiple tasks lumped into one entry
  • Thin descriptions — entries too vague to survive a fee motion
  • Duplicate entries — same task billed twice
  • Intra-firm conferences — partner + associate both billing the same call
  • Clerical or administrative work — tasks that should not appear on a legal bill
  • Vague communications — "phone call," "email correspondence" with no substance

Usage:
  Upload the Clio time-entry CSV export, then:
  "Alfred, run klg-prebill-audit on [Matter Name]."

The skill reads the uploaded file, runs the LLM audit, and returns a flagged
entry list with recommended edits or deletions.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_FEE_CUT_DOCTRINE = """\
CALIFORNIA FEE-CUT DOCTRINE (embedded — do not invent additional authority):

1. Block billing: billing multiple tasks in a single entry without time
   allocated to each. Courts routinely apply percentage reductions (20–30%)
   to block-billed entries. (Hensley v. Eckerhart; Ketchum v. Moses.)

2. Insufficient description: entries must describe the work with enough
   specificity for the court to assess reasonableness. "Research" or
   "review file" without further detail routinely draws reductions.

3. Duplicative billing: when two timekeepers bill for the same meeting,
   call, or task, courts reduce or eliminate the lesser entry — particularly
   paralegal/associate entries for conferences the partner also bills.

4. Clerical tasks: filing, copying, calendaring, and administrative coordination
   are overhead, not compensable legal work. Billing these tasks invites
   across-the-board reductions.

5. Vague communications: "phone call re: case" or "email to client" without
   stating the substance fails the reasonable-scrutiny standard.

Flag — do not delete. Attorney decides what to keep, edit, or remove.
"""

_AUDIT_PROMPT = """\
You are a KLG senior appellate attorney conducting a pre-bill audit.

Your job: identify time entries in the attached CSV that create fee-cut risk
before this invoice reaches the client. You are not the billing attorney —
flag problems for review; do not unilaterally delete or revise entries.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEE-CUT DOCTRINE (California)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{fee_cut_doctrine}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER: {matter_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIME ENTRIES (CSV):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{csv_content}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTIONS:
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce the pre-bill audit report in this format:

## Summary
- Total entries reviewed: [N]
- Total hours: [X.X]
- Total amount: $[X]
- Flagged entries: [N] entries, $[X] at risk

## Flagged Entries

For each flagged entry:

| # | Date | Timekeeper | Hours | Amount | Description | Issue | Recommended Action |
|---|------|------------|-------|--------|-------------|-------|-------------------|

Issue categories: BLOCK-BILLING | THIN-DESCRIPTION | DUPLICATE | INTRA-FIRM-CONF | CLERICAL | VAGUE-COMMS

Recommended actions: SPLIT-ENTRY | EXPAND-DESCRIPTION | DELETE | REDUCE-TIME | COMBINE | VERIFY

## Risk Assessment

- High risk (likely reduced if challenged): [list entries]
- Medium risk (could be defended with context): [list entries]
- Low risk (fine as-is): [N entries — not listed individually]

## Recommended Edits

For each flagged entry, draft an improved description that would survive
judicial scrutiny. Example:
  Original: "Email re: case (0.5 hrs)"
  Improved: "Email to client re: opposition's supplemental authority on Garcetti
             and whether prior public-concern holding survives; advised client
             of our response strategy (0.5 hrs)"

## Totals at Risk

| Issue Type | Entries | Hours | Amount |
|------------|---------|-------|--------|
| Block billing | | | |
| Thin description | | | |
| Duplicate | | | |
| Intra-firm conference | | | |
| Clerical | | | |
| Vague communications | | | |
| **TOTAL AT RISK** | | | |

---
DRAFT — attorney review required. Do not send this bill until flagged entries
are resolved. Billing attorney has final authority on all edits.
"""


class KLGPrebillAudit(Skill):
    name = "klg-prebill-audit"
    required_tools = []
    description = (
        "Audit Clio time-entry CSV exports before finalization: flags block billing, "
        "thin descriptions, duplicates, intra-firm conferences, clerical work, and "
        "vague communications. Upload the CSV before running. "
        "Returns a flagged-entry report with recommended edits."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"

        csv_content = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    csv_content = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-prebill-audit: file extraction failed: %s", e)

        if not csv_content:
            return SkillResult(
                summary="klg-prebill-audit: no time-entry file provided.",
                output=(
                    "Upload the Clio time-entry CSV export first, then run the audit:\n\n"
                    "1. Export time entries from Clio → Reports → Time Entries (CSV)\n"
                    "2. Attach the CSV in Alfred\n"
                    "3. Run: `Alfred, run klg-prebill-audit on [Matter Name]`\n\n"
                    "The audit flags block billing, thin descriptions, duplicates, "
                    "intra-firm conferences, clerical work, and vague communications."
                ),
                next_action="Export CSV from Clio and re-run with the file attached.",
                success=False,
            )

        prompt = _AUDIT_PROMPT.format(
            fee_cut_doctrine=_FEE_CUT_DOCTRINE,
            matter_label=matter_label,
            csv_content=csv_content[:20000],
            instruction=instruction or "(none — run standard audit)",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=f"Pre-bill audit complete for {matter_label}. Flagged entries ready for attorney review.",
            output=f"**Pre-Bill Audit — {matter_label}**\n\n{output_text}",
            next_action=(
                "Review each flagged entry. Expand thin descriptions, split block-billed entries, "
                "and remove clerical items before finalizing the invoice."
            ),
            success=True,
        )
