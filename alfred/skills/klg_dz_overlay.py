"""
alfred/skills/klg_dz_overlay.py — Danger Zone risk overlay for a matter.

Runs a structured risk assessment on a matter's appellate posture: identifies
the facts, record gaps, standard-of-review hurdles, and adverse authority that
pose the greatest danger to the client's position. Produces a prioritized risk
matrix so the team can address vulnerabilities before briefing begins.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_DZ_PROMPT = """\
You are a KLG senior appellate attorney running a pre-briefing "Danger Zone" analysis.
Your job is to be the devil's advocate—identify every vulnerability in the client's
position before the opposing party does. This is not a brief; it is a risk map.

KLG WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "as such"
- Direct, clinical language. Rate risk severity objectively.
- CRITICAL: Do not invent case citations or record facts.
  If uncertain about a case cite, flag: [VERIFY CITATION]
  If uncertain about a record fact, flag: [VERIFY FROM RECORD]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOCUMENTS OR BRIEF EXCERPTS (if uploaded)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{doc_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a full Danger Zone analysis:

## DANGER ZONE ANALYSIS — {matter_label}
**Status:** DRAFT — Requires attorney review

---

### OVERALL RISK RATING: [🔴 HIGH / 🟡 MODERATE / 🟢 LOW]

**One-sentence bottom line:** [The single greatest threat to this appeal, stated plainly.]

---

### ZONE 1: STANDARD OF REVIEW DANGERS 🎯

The standard of review is the litigation moat—or the trap. Identify:

| Issue | Standard | Why it's dangerous | Severity |
|-------|----------|-------------------|----------|
| [issue] | [de novo / abuse of discretion / substantial evidence] | [why this standard hurts us] | 🔴/🟡/🟢 |

**Most dangerous standard:** [Identify the one that poses the greatest risk and why.]

---

### ZONE 2: RECORD GAPS AND PRESERVATION PROBLEMS 📋

| Problem | Issue affected | Likely opposing argument | Mitigation |
|---------|---------------|--------------------------|------------|

**Invited error risk:** [Any acts by trial counsel that could estop our arguments?]
**Forfeiture risk:** [Any arguments not properly preserved below?]

---

### ZONE 3: ADVERSE AUTHORITY ⚖️

Strongest cases and statutes working against us:

| Authority | What it says | Why it's dangerous | Our best response |
|-----------|-------------|-------------------|-------------------|
[flag any uncertain citation: [VERIFY CITATION]]

**The single most dangerous case:** [Name it. Explain in 2 sentences why it threatens the appeal.]

---

### ZONE 4: BAD RECORD FACTS 💣

Facts in the record that the opposing party will weaponize:

| Fact | Source | Why it's damaging | Our response / mitigation |
|------|--------|------------------|--------------------------|
[flag any uncertain record cite: [VERIFY FROM RECORD]]

**The most dangerous fact:** [The one fact the opposing party will put in the first sentence of their brief.]

---

### ZONE 5: STRUCTURAL ARGUMENT WEAKNESSES 🏗️

Argument-by-argument vulnerability assessment:

| Argument | Structural weakness | Risk level | Recommended fix |
|----------|--------------------|-----------|--------------  |

---

### ZONE 6: PANEL AND JUDICIAL RISK 🔭

(Based on available information about the court and judge/panel):
- Court temperament on this issue: [conservative/liberal/mixed/unknown]
- Recent decisions in this area: [any unfavorable recent opinions? [VERIFY]]
- Procedural posture risk: [any procedural issues that could derail the appeal?]

---

### PRIORITY ACTION LIST

Before briefing begins, address these items in order:

| Priority | Danger | Action required | Who | Deadline |
|----------|--------|----------------|-----|----------|
| 🔴 1 | | | | |
| 🔴 2 | | | | |
| 🟡 3 | | | | |
| 🟡 4 | | | | |
| 🟢 5 | | | | |

---

DRAFT — Tim to review before the briefing strategy meeting.\
"""


class KLGDZOverlay(Skill):
    name = "klg-dz-overlay"
    required_tools = ["search_notion", "web_search"]
    description = (
        "Run a pre-briefing Danger Zone risk analysis on a matter: identify standard-of-review "
        "traps, record gaps, preservation problems, adverse authority, and bad facts — ranked "
        "by severity. Produces a prioritized action list before briefing begins. "
        "Optionally attach a brief draft or record excerpt for deeper analysis."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        doc_text = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    doc_text = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-dz-overlay: file extraction failed: %s", e)

        if not matter_text and not doc_text:
            return SkillResult(
                summary="klg-dz-overlay: no matter context available.",
                output=(
                    "Provide the matter name to run the Danger Zone analysis:\n\n"
                    "`Alfred, run klg-dz-overlay on [Matter Name].`\n\n"
                    "Optionally attach a brief draft or record excerpt for deeper analysis."
                ),
                next_action="Re-run with the matter name or uploaded materials.",
                success=False,
            )

        prompt = _DZ_PROMPT.format(
            matter_summary=matter_text[:4000],
            doc_text=doc_text[:10000] if doc_text else "(No document uploaded — base analysis on Notion context.)",
            instruction=instruction or "(No specific focus — run full Danger Zone analysis.)",
            matter_label=matter_label,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Danger Zone analysis complete for {matter_label}. "
                "Risk matrix, adverse authority, bad facts, and priority action list ready."
            ),
            output=f"**Danger Zone Analysis — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Discuss the Priority Action List with Tim before drafting begins.\n"
                "2. Verify all [VERIFY CITATION] flags via Westlaw before briefing.\n"
                "3. Address all 🔴 items before any brief section is drafted."
            ),
            success=True,
        )
