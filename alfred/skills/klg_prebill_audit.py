"""
alfred/skills/klg_prebill_audit.py — Pre-bill time-entry audit before finalization.

Two-phase workflow:
  Phase 1 — Mechanical detection: flag entries matching known cut patterns
  Phase 2 — Judgment layer: Claude culls false positives and drafts supplements

For the full .xlsx workbook (recommended for monthly billing QC), run the
standalone script:
    python alfred/skills/scripts/prebill_audit.py export.csv -o audit.xlsx --period "May 2026"

This Alfred skill does the same detection as an LLM analysis when a CSV is
uploaded, and returns a structured flagged-entry report with suggested supplements.

Usage:
  1. Export time entries from Clio → Reports → Time Entries (CSV)
  2. Attach the CSV in Alfred
  3. "Alfred, run klg-prebill-audit on [Matter Name]."

For full-period billing review (all matters, .xlsx output):
  "Alfred, run klg-prebill-audit: monthly review for [Month Year]."
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_FEE_CUT_DOCTRINE = """\
CALIFORNIA FEE-CUT DOCTRINE (internal training reference — verify all citations before filing):

FRAMEWORK: Lodestar = reasonable hours × reasonable rate. Fee applicant bears
the burden of documenting reasonable hours. Vague, padded, duplicative, or
clerical time fails that burden. (Ketchum v. Moses (2001) 24 Cal.4th 1122 [VERIFY];
PLCM Group, Inc. v. Drexler (2000) 22 Cal.4th 1084 [VERIFY])

1. LONG ENTRY, THIN DESCRIPTION (highest exposure)
   An entry of 2+ hours with a narrative too generic to test ("continue working on AOB,"
   "attention to appeal") cannot be evaluated for reasonableness. Courts reduce or
   strike. (Same authority as block billing — the defect is identical, magnified by hours.)
   Fix: itemize discrete tasks and what each produced — which section drafted, which
   issue researched, which authority located.

2. BLOCK BILLING (multiple tasks lumped in one entry)
   Prevents the court from assessing the reasonableness of any single task. Courts apply
   percentage haircuts (commonly 20–30%). (Bell v. Vista Unified School Dist. (2000)
   82 Cal.App.4th 672 [VERIFY]; Christian Research Institute v. Alnor (2008)
   165 Cal.App.4th 1315 [VERIFY])
   Fix: split into separate entries, one task each, with task-level time.

3. DUPLICATE / NEAR-DUPLICATE ENTRIES
   Identical or near-identical narratives read as the same work billed twice. Even when
   work is genuinely distinct, identical text invites the inference and the cut.
   Fix: differentiate narratives to show progression (Day 1: outline; Day 2: draft II.B).

4. INTRA-FIRM CONFERENCE (multiple billers on same meeting)
   Courts ask whether multiple billers were necessary. Some co-authorship is reasonable
   and defensible; it must be justified, not assumed.
   Fix: confirm second attendee was necessary; otherwise bill one timekeeper.

5. CLERICAL / SECRETARIAL WORK (overhead, not compensable at professional rates)
   Filing, formatting, bookmarking, uploading, calendaring, binder assembly,
   memoranda of costs, proofs of service. (Missouri v. Jenkins (1989) 491 U.S. 274 [VERIFY])
   Fix: write off, reclassify as overhead, or — if genuinely substantive — rewrite to show substance.

6. CONFERENCE / EMAIL WITHOUT STATED SUBJECT
   "Phone call re: case" or "email to client" fails the reasonableness test.
   Fix: add "re [subject]" — takes 5 seconds, defeats the cut.

7. BILLING JUDGMENT / LARGE SINGLE BLOCK (6+ hours in one entry)
   Courts scrutinize. Confirm genuine continuous work; exercise billing judgment.

SUPPLEMENTATION STANDARD: Specificity defeats vagueness cuts. But the cure is real
task detail, not more words. A longer entry that is still generic is no better.
Write what the work was and what it produced, in plain active voice.
"""

_AUDIT_PROMPT = """\
You are a KLG senior appellate attorney conducting a pre-bill audit.

Your job: Phase 1 (detect) + Phase 2 (judgment) in one pass.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEE-CUT DOCTRINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{fee_cut_doctrine}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER: {matter_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TIME ENTRIES (CSV):
{csv_content}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDITIONAL INSTRUCTIONS: {instruction}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PHASE 1 — FLAG EVERY ENTRY THAT MATCHES A CUT PATTERN:

Issue categories to detect:
  LONG-THIN     — ≥2h with <8-word or generic description
  BLOCK-BILLING — multiple distinct tasks in one entry (look for semicolons, action verb clusters)
  DUPLICATE     — same/near-identical narrative by same timekeeper within the period
  INTRA-CONF    — ≥2 timekeepers billing the same conference on the same day
  CLERICAL      — filing, formatting, uploading, calendaring, copying, bookmarking, etc.
  VAGUE-COMM    — conference/email entry with no "re [subject]"
  OUTLIER       — single entry ≥6h (billing judgment check)
  HYGIENE       — missing description, zero hours, off-increment duration

PHASE 2 — JUDGMENT LAYER:

For each flagged entry:
1. Determine severity: High (LONG-THIN, BLOCK-BILLING, CLERICAL, DUPLICATE) /
   Medium (INTRA-CONF, VAGUE-COMM, OUTLIER) / Low (HYGIENE)
2. Cull obvious false positives — note them as cleared rather than flagging
3. Draft a supplemented narrative drawn ONLY from what the work actually was
   (based on context/description). If underlying work is unknown, write
   "[TIMEKEEPER to supplement — describe tasks completed and outputs]"

OUTPUT FORMAT:

## Audit Summary
- Total entries reviewed: [N]
- Total hours: [X.X h]
- Total amount: $[X]
- Flagged entries: [N] entries / [X.X h] / $[X] at risk

## High Severity Flags

| # | Date | Timekeeper | Hours | Description | Issue | Suggested supplement |
|---|------|------------|-------|-------------|-------|---------------------|
[One row per flagged entry, sorted High → Medium → Low, then by hours desc]

## Medium Severity Flags

[Same table format]

## Summary by Issue Category

| Issue | Entries | Hours | Amount |
|-------|---------|-------|--------|
| Long entry, thin description | | | |
| Block billing | | | |
| Duplicate / near-duplicate | | | |
| Intra-firm conference | | | |
| Clerical / non-billable | | | |
| Conference/email without subject | | | |
| Outlier (billing judgment) | | | |
| **TOTAL AT RISK** | | | |

## Summary by Timekeeper

| Timekeeper | Flagged entries | Flagged hours |
|------------|-----------------|---------------|

## Firm-Level Notes (if applicable)
[e.g., if >40% of entries land on whole/half-hour values: flag as possible estimation]

## Recommended Next Steps
1. [Top 2–3 specific actions for the billing team]

---
DRAFT — attorney review required. Attorney decides what to keep, edit, or remove.
All flagged entries require billing-team judgment before Clio is updated.
For the full .xlsx workbook, run: python alfred/skills/scripts/prebill_audit.py export.csv -o audit.xlsx
"""


class KLGPrebillAudit(Skill):
    name = "klg-prebill-audit"
    required_tools = []
    description = (
        "Monthly pre-bill hardening audit. Upload a Clio time-entry CSV, then run. "
        "Detects block billing, thin descriptions, duplicates, intra-firm conferences, "
        "clerical work, and vague communications. Returns flagged-entry report with "
        "suggested supplements. Full .xlsx workbook available via the standalone script."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "all matters (period review)"

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
                    "Upload the Clio time-entry CSV export first, then run the audit.\n\n"
                    "**How to export from Clio:**\n"
                    "Reports → Time Entries → select billing period → Export CSV\n\n"
                    "**Then run:**\n"
                    "`Alfred, run klg-prebill-audit on [Matter Name].`\n\n"
                    "**Or for the full .xlsx workbook (monthly billing QC):**\n"
                    "```\n"
                    "python alfred/skills/scripts/prebill_audit.py export.csv \\\n"
                    "  -o May2026_audit.xlsx --period 'May 2026'\n"
                    "```\n\n"
                    "The script produces a color-coded .xlsx with a Flagged Entries sheet "
                    "(one row per flag with suggested supplement column) and a Summary sheet "
                    "(counts/hours/dollars by issue category and timekeeper)."
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
                "1. Review each High severity flag first — expand thin descriptions, "
                "split block-billed entries, write off clerical items.\n"
                "2. For the full .xlsx workbook with color-coding and resolution columns:\n"
                "   `python alfred/skills/scripts/prebill_audit.py export.csv -o audit.xlsx`\n"
                "3. Attorney must approve all edits before Clio is updated."
            ),
            success=True,
        )
