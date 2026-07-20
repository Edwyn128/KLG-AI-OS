"""
alfred/skills/klg_research_compilation.py — Steps 4–5 of the KLG Research Pipeline.

Two-phase workflow adapted from the full Claude.ai klg-research-compilation skill:

  Phase A — Compilation + Authority Extraction:
    Read completed Deep Research memos from Notion (or uploaded files),
    compile into a single research memo, perform convergence analysis,
    and generate a Westlaw Find & Print authority list.

  Phase B — Finalization (optional, after Westlaw run):
    Upload the Westlaw .doc file, cross-reference for hallucinations,
    and produce the final verified research package.

  Post-Pipeline Review:
    High-leverage findings, case memo options, client memo decision,
    recursive research opportunities.

KLG Research Pipeline steps:
  1. klg-issue-framing       — define the precise legal question
  2. klg-deep-research-prompts — generate tiered research prompts
  3. [William runs prompts in Westlaw/Fastcase/Deep Research]
  4. THIS SKILL (Phase A)   — compile + extract authorities
  5. [William runs Comet/Westlaw Find & Print]
  6. THIS SKILL (Phase B)   — finalize research package

Westlaw authority list format (non-negotiable):
  - Reporter volume, reporter name, start page ONLY — no case names, no years
  - One authority per line, no blank lines, deduplicated
  - Batches of ≤100 items if total exceeds 100
  - Example: "75 Cal.App.5th 1234" / "42 U.S.C. § 1983"
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_COMPILATION_PROMPT = """\
You are a KLG senior appellate attorney compiling legal research for {matter_label}.

EFFICIENCY RULE: Single-pass reading. Read each memo ONCE. During that pass,
extract (a) key conclusions, (b) every citation, (c) red flags. Do not re-read.
Build the compiled document as you read. Target: Phase A in 10–15 minutes.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEFORE READING MEMOS — USE YOUR TOOLS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{fetch_instructions}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESEARCH MEMOS / NOTES:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{research_content}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC FOCUS: {instruction}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "it is well established," "as such"
- Active verbs. Lead with the holding, not the procedural posture.
- CRITICAL: never fabricate citations, holdings, or quotations
  If a citation looks suspicious (unusual reporter, non-standard format):
  mark it ⚠ [VERIFY CITATION] — do not drop it, do not trust it.
  If a holding is paraphrased from notes: mark [PARAPHRASED — VERIFY]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PHASE A OUTPUT — PRODUCE ALL THREE SECTIONS:

## 1. COMPILED RESEARCH MEMORANDUM

Header:
  COMPILED LEGAL RESEARCH MEMORANDUM
  Case: {matter_label}
  Status: DRAFT — AI ASSISTED — Citations require Westlaw verification
  Pipeline Stage: Step 4 of 5 — Compilation

### Issue Presented
[One sentence, precisely stated]

### Short Answer
[2–4 sentences — bottom line up front]

### Governing Legal Standard
[Controlling test(s) with citations]

### Issue-by-Issue Analysis
For each legal issue:

#### Issue [N]: [Title]
**Governing rule:** [rule statement with lead citation]
**Key favorable authority:** [citation — parenthetical]
**Key adverse authority:** [citation — parenthetical, if any]
**Analysis:** [synthesized discussion, ≤3 paragraphs]
**Strength:** Strong / Moderate / Weak — [one-sentence explanation]
**Research gaps:** [what still needs verification]

### Favorable Authorities (Ranked)
| Rank | Citation | What it establishes | Why it helps |
|------|----------|---------------------|--------------|
[Top 10, ranked by strength]

### Adverse Authorities and Responses
| Citation | Holding | Our response/distinction |
|----------|---------|--------------------------|

---

## 2. CONVERGENCE ANALYSIS

Authorities cited in multiple memos are higher-confidence signals.

### High-Confidence (cited in 3+ memos)
| Authority | Full Citation | Cited in Memos | Issue |
|-----------|--------------|----------------|-------|

### Moderate-Confidence (cited in 2 memos)
| Authority | Full Citation | Cited in Memos | Issue |
|-----------|--------------|----------------|-------|

### Single-Source (cited in 1 memo — verify carefully)
| Authority | Full Citation | Source Memo | Issue | Flag |
|-----------|--------------|-------------|-------|------|

### Potential Hallucinations
| Citation | Reason Flagged | Source | Priority |
|----------|---------------|--------|----------|
[Any citation that looks suspicious — non-standard reporter, unusual format,
 year that seems off, holding inconsistent with known doctrine]

---

## 3. WESTLAW AUTHORITY LIST

Format: reporter volume + reporter abbreviation + start page ONLY.
No case names. No years. No parentheticals. One per line. Deduplicated.
Statutes: code name + section number.

**Total authorities: [N]**
**Status: DRAFT — AI ASSISTED — Pending Westlaw verification**

{batch_instruction}

```
[LIST EVERY AUTHORITY HERE, one per line]
[Example:]
75 Cal.App.5th 1234
547 U.S. 410
Cal. Gov. Code § 3304
42 U.S.C. § 1983
```

[If >100 authorities, split into labeled batches of ≤100:]
```
BATCH 1 OF [N] (items 1–100):
[authorities]
```
```
BATCH 2 OF [N] (items 101–[M]):
[authorities]
```

---

## 4. POST-PIPELINE OPTIONS

Present these questions for the attorney to answer (respond with letter choices,
e.g. "1a, 2b, 3b, 4c"):

1. HIGH-LEVERAGE FINDINGS — Identify the 3–5 most strategically valuable
   authorities or legal theories from this research. Add to case memo?
   a. Yes — add to evolving case memo  b. No — keep separate

2. COMPILED MEMO — Delivery preference?
   a. Add to existing case memo as new section  b. Keep as standalone document

3. CLIENT MEMO — Want a client-facing version?
   a. No — internal only  b. Yes — create client-ready version now
   c. Yes — but let me revise internal memo first

4. ADDITIONAL RESEARCH — Are there gaps worth a second round?
   a. Yes — generate new research prompts  b. No — sufficient

---

DRAFT — attorney review required. All [VERIFY CITATION] flags must be
resolved in Westlaw before any authority appears in a filed brief.
Pipeline Stage 5 (Westlaw verification) follows.
"""

_PHASE_B_PROMPT = """\
You are a KLG senior appellate attorney finalizing a research package after Westlaw verification.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER: {matter_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

WESTLAW RESULTS (extracted text from downloaded .doc):
{westlaw_content}

PHASE A COMPILATION (from prior run):
{prior_compilation}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PHASE B TASKS:

1. WESTLAW RESULTS SUMMARY
   - How many authorities were successfully retrieved?
   - Which were not found / rejected / out-of-plan?
   Report:
     Authorities requested: [N]
     Successfully retrieved: [N]
     Not found / rejected: [list]
     Out of plan (excluded): [list]

2. CROSS-REFERENCE vs. HALLUCINATION FLAGS
   Compare retrieved authorities against the ⚠ [VERIFY CITATION] flags
   from Phase A. Which flagged citations were confirmed real? Which were
   not found (likely hallucinated)? Update confidence ratings.

3. VERIFIED AUTHORITY LIST
   Produce the final authority list with verification status:
   | Citation | Status | Notes |
   |----------|--------|-------|
   | [cite] | ✅ Confirmed | |
   | [cite] | ❌ Not found — hallucination risk | Remove from brief |
   | [cite] | ⚠ Out-of-plan | Verify via law library |

4. UPDATED RESEARCH SUMMARY
   Revise the compiled memo's executive summary to reflect:
   - [N] authorities confirmed via Westlaw
   - [N] removed (not found / likely hallucinated)
   - Final strength assessment for each issue

5. POST-PIPELINE REVIEW (present once, all questions together)
   [Same options as Phase A Post-Pipeline Options — attorney answers with letters]

WRITING RULES: Same as Phase A. No fabricated holdings. Active voice. Em dashes—like this.

DRAFT — attorney review required before final filing.
"""


class KLGResearchCompilation(Skill):
    name = "klg-research-compilation"
    required_tools = ["search_notion"]
    description = (
        "Steps 4–5 of the KLG Research Pipeline: compile Deep Research memos from Notion "
        "into a structured legal research memo, perform convergence analysis, and generate "
        "a Westlaw Find & Print authority list (batches of ≤100). "
        "Phase B finalizes after Westlaw download. Run after Steps 1–3 are complete."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_summary = ctx.matter_summary or "(No Notion project page found.)"

        # Determine phase from instruction
        is_phase_b = any(k in instruction.lower() for k in (
            "westlaw authorities", "westlaw downloaded", "finalize", "phase b",
            "authorities are downloaded", "downloaded the westlaw",
        ))

        # Read any uploaded file
        file_content = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    file_content = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-research-compilation: file extraction failed: %s", e)

        if is_phase_b:
            if not file_content:
                return SkillResult(
                    summary="klg-research-compilation (Phase B): no Westlaw file provided.",
                    output=(
                        "To finalize the research package, upload the Westlaw Find & Print "
                        ".doc file downloaded after the authority verification run.\n\n"
                        "Then say: 'Alfred, the Westlaw authorities are downloaded. "
                        "Finalize the research package for [Matter Name].'"
                    ),
                    next_action="Upload the Westlaw .doc file and re-run.",
                    success=False,
                )

            prompt = _PHASE_B_PROMPT.format(
                matter_label=matter_label,
                westlaw_content=file_content[:15000],
                prior_compilation=matter_summary[:3000],
            )

            output_text = await self.generate(prompt, ctx)
            return SkillResult(
                summary=f"Research package finalized for {matter_label}. Westlaw verification complete.",
                output=f"**Research Compilation — Phase B Finalization — {matter_label}**\n\n{output_text}",
                next_action=(
                    "1. Verify all ❌ Not found authorities are removed from brief drafts.\n"
                    "2. Save final research package to SharePoint: [Matter Folder]/KLG Research/\n"
                    "3. Notify Tim in matter Slack channel that pipeline is complete."
                ),
                success=True,
            )

        # Phase A: Compilation
        if not file_content and not matter_summary:
            return SkillResult(
                summary="klg-research-compilation: no research content found.",
                output=(
                    "No research notes found for this matter.\n\n"
                    "**To run research compilation:**\n"
                    "1. Complete Steps 1–3 first:\n"
                    "   klg-issue-framing → klg-deep-research-prompts → run in Westlaw/Deep Research\n"
                    "2. Paste research memo results into the matter's Notion page, OR\n"
                    "   upload a research notes file when invoking this skill\n"
                    "3. Re-run: `Alfred, run klg-research-compilation on [Matter Name]`"
                ),
                next_action="Complete Steps 1–3 of the research pipeline first.",
                success=False,
            )

        fetch_instructions = (
            f"Call search_notion with query 'research notes {matter_label}' to retrieve "
            "any additional research memos stored in Notion for this matter. "
            "Combine whatever you find with the notes already provided below."
        ) if not file_content else "(File uploaded — use the research content below.)"

        batch_instruction = (
            "If the total authority count exceeds 100, split into batches of ≤100 items each, "
            "labeled 'BATCH 1 OF N (items 1–100):' and so on. "
            "Westlaw Find & Print accepts a maximum of 100 authorities per batch."
        )

        research_content = file_content[:15000] if file_content else (
            f"[No file uploaded — retrieve from Notion using search_notion for '{matter_label}']"
        )

        prompt = _COMPILATION_PROMPT.format(
            matter_label=matter_label,
            fetch_instructions=fetch_instructions,
            matter_summary=matter_summary[:2000],
            research_content=research_content,
            instruction=instruction or "(none — compile all available research)",
            batch_instruction=batch_instruction,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Research compilation complete for {matter_label}. "
                "Memo, convergence table, and Westlaw authority list ready."
            ),
            output=f"**Research Compilation — Phase A — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Copy the Westlaw Authority List (Section 3) and run it through "
                "Westlaw Find & Print (batches of ≤100). Settings: Full text, Word (.doc), "
                "single merged file.\n"
                "2. Upload the Westlaw .doc and say: 'Alfred, the Westlaw authorities are "
                "downloaded. Finalize the research package for [Matter Name].'\n"
                "3. Verify every [VERIFY CITATION] flag before using any authority in a brief."
            ),
            success=True,
        )
