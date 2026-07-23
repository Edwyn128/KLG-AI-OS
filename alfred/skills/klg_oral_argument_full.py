"""
alfred/skills/klg_oral_argument_full.py — Full oral argument package with panel research.

An enhanced upgrade of klg-oral-argument-prep. Adds:
  - Panel/judge research (recent opinions, known positions on key issues)
  - Argument time budget (how to allocate 10–20 minutes)
  - Two-sided moot court script (adversarial Q&A with model answers)
  - Rebuttal strategy
  - Panic protocol (what to do if the first question derails you)

Use this for high-stakes arguments where preparation depth matters.
For quick prep, use klg-oral-argument-prep instead.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult, skill_read_file_text

logger = logging.getLogger(__name__)

_FULL_OA_PROMPT = """\
You are a KLG senior appellate attorney leading comprehensive oral argument preparation
for a high-stakes appeal.

KLG is a California appellate specialty firm. Primary practice areas: supersedeas
bonds, First Amendment, public employee speech, civil rights, administrative law.

KLG WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "it is well established," "as such"
- Answers must be confident, direct, and under 3 sentences
- The opening statement must be memorizable — no jargon, no hedging
- CRITICAL: Do NOT invent record facts, citations, or judicial quotes.
  Flag everything uncertain: "[VERIFY from record]" or "[VERIFY citation]"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRIEF EXCERPT / KEY ARGUMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{brief_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ARGUMENT DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Use your web_search tool to research the assigned panel and their recent opinions
on the relevant legal issues before producing the prep package.

Produce a complete oral argument prep package:

---

## PART 1: PANEL INTELLIGENCE REPORT

For each judge on the assigned panel (search for their recent opinions):

### Judge [Name]
**Appointed by:** [President/Governor, year]
**Known positions:**
- [Key issue 1]: [Their documented position, with case cite if known] [VERIFY]
- [Key issue 2]: [Their documented position] [VERIFY]
**Hot-bench style:** [Do they ask early? Late? Are they aggressive or passive?] [VERIFY]
**Most dangerous question from this judge:** [Their likely hardest question]
**Most favorable signal from this judge:** [Any prior ruling that supports our position]

---

## PART 2: ARGUMENT TIME BUDGET

*For a [N]-minute argument (specify total time):*

| Segment | Minutes | Content |
|---------|---------|---------|
| Opening (uninterrupted if possible) | 1.5–2 min | Thesis + three pillars |
| Issue 1: [Name] | [N] min | Core argument + anticipated Q&A |
| Issue 2: [Name] | [N] min | Core argument + anticipated Q&A |
| Issue 3: [Name] | [N] min | Core argument + anticipated Q&A |
| Reserve for rebuttal | 2–3 min | [What to save for rebuttal] |

**Time signals:** Warn me at 5 min remaining — shift to closing if still in Issue 2 or later.
**The one point that must land:** [If you only make one argument, make this one.]

---

## PART 3: 60-SECOND OPENING STATEMENT

Three versions to choose from:

**VERSION A — Fact-first (lead with the injustice):**
[~130 words, memorizable, three-part structure]

**VERSION B — Legal-first (lead with the controlling standard):**
[~130 words, memorizable, three-part structure]

**VERSION C — Consequence-first (lead with what's at stake):**
[~130 words, memorizable, three-part structure]

*Tim's recommendation: [Which version is strongest for this panel, and why.]*

---

## PART 4: THE 15 HARDEST QUESTIONS

Questions ordered from hardest to least hard:

**Q[N]: [The question, as the judge would actually ask it]**
- Why they ask it: [The underlying concern or hostile inference]
- Answer: [Direct, confident, ≤3 sentences]
- Pivot: [How to redirect to your strongest ground after answering]
- Record support: [Specific cite, or "(verify from record)"]
- Danger level: 🔴 / 🟡 / 🟢

---

## PART 5: TWO-SIDED MOOT COURT SCRIPT

A complete adversarial Q&A script:

### ROUND 1: Opposing counsel's best 5 questions
*[Play as opposing counsel — ask the hardest possible questions from their perspective]*

**OPPOSING COUNSEL Q1:** [Question from the opposing party's view]
→ **OUR ANSWER:** [Tim's answer]

[Continue for 5 exchanges]

### ROUND 2: Skeptical panel questions
*[Play as a skeptical judge who doesn't want to rule for us]*

**JUDGE Q1:** [Question designed to find the limits of our position]
→ **OUR ANSWER:** [Tim's answer]

[Continue for 5 exchanges]

---

## PART 6: THE ABSOLUTE CONCESSION

The one point to concede immediately if pressed—the concession that builds
credibility without giving away the case.

**Concede:** [State it precisely as you would say it on the bench]
**Why this works:** [How giving this up actually helps the bigger argument]
**After conceding, pivot to:** [The argument that survives the concession]

---

## PART 7: REBUTTAL STRATEGY

**Save for rebuttal:**
1. [Point 1 — why this should be reserved, not deployed in main argument]
2. [Point 2]

**The 90-second rebuttal outline:**
[Exactly what to say in rebuttal if opposing counsel makes their best arguments]

**What to do if opposing counsel says [X]:** [Pre-planned rebuttal line]

---

## PART 8: KEY RECORD CITATIONS (Quick-Reference)

15 specific citations the advocate should have at fingertips:

| # | What it shows | Record cite | Ready to use? |
|---|--------------|-------------|---------------|
Flag any that need verification: [VERIFY]

---

## PART 9: PANIC PROTOCOL

If the first question immediately derails you:

**Scenario A — The panel signals they want to rule against you on Issue 1:**
→ [What to do: pivot to, concede, or reframe]

**Scenario B — You get interrupted before finishing the opening:**
→ [How to handle the interruption and still land the thesis]

**Scenario C — A factual question exposes a record gap:**
→ ["We will provide the court with a citation in our post-argument submission."]

**Scenario D — The panel is completely hostile:**
→ [Focus on: preserve the record, get the absolute best argument on tape]

---

## PART 10: MOOT COURT SETUP

**Three questions the moot panel should hammer hardest:**
1. [Question — because this is the one Tim is least comfortable with]
2. [Question — because the panel might not be familiar with the record]
3. [Question — because it attacks the foundational premise of Issue 1]

**Scoring criteria for moot:**
- Did the opening land in ≤90 seconds?
- Was every 🔴 question answered in ≤3 sentences?
- Did the advocate pivot off every answer toward our thesis?
- Did the absolute concession feel strategic, not defensive?

---

DRAFT — attorney review required. Verify all record citations and judicial profile
information before argument.\
"""


class KLGOralArgumentFull(Skill):
    name = "klg-oral-argument-full"
    required_tools = ["web_search", "search_notion"]
    long_running = True
    description = (
        "Full oral argument preparation package with panel research. Includes judge intelligence "
        "profiles (recent opinions, known positions), argument time budget, three opening statement "
        "versions, 15 hardest Q&As, two-sided moot court script, rebuttal strategy, and panic "
        "protocol. Use for high-stakes arguments. Optionally attach a brief excerpt for deeper prep."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        file_tokens: list[str] = ctx.extra.get("file_tokens", [])
        instruction = ctx.user_instruction.strip()

        brief_text = ""
        if file_tokens:
            try:
                from alfred.file_store import consume_token, delete_file
                path = consume_token(file_tokens[0])
                if path:
                    brief_text = skill_read_file_text(path)
                    delete_file(path)
            except Exception as e:
                logger.warning("klg-oral-argument-full: file extraction failed: %s", e)

        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        if not matter_text and not instruction and not brief_text:
            return SkillResult(
                summary="klg-oral-argument-full: no case context provided.",
                output=(
                    "Provide the matter name and argument details:\n\n"
                    "`Alfred, run klg-oral-argument-full on [Matter Name]: "
                    "[court, judges if known, argument date, key issues, time allotted]`\n\n"
                    "Optionally upload the brief or key argument sections for deeper prep.\n\n"
                    "**Example:**\n"
                    "`klg-oral-argument-full on Williams v. Allstate: 9th Circuit, "
                    "Judges Smith/Jones/Brown, argument Sept 15, First Amendment retaliation "
                    "and qualified immunity, 15 minutes`"
                ),
                next_action="Re-run with matter context and argument details.",
                success=False,
            )

        prompt = _FULL_OA_PROMPT.format(
            matter_summary=matter_text[:4000],
            brief_text=brief_text[:10000] if brief_text else "(No brief uploaded.)",
            instruction=instruction[:3000] or "(No specific details provided — prepare comprehensive package.)",
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Full oral argument prep complete for {matter_label}. "
                "Panel research, time budget, 15 Q&As, moot court script, and panic protocol ready."
            ),
            output=f"**Full Oral Argument Package — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Verify all panel intelligence facts — judge profiles change with new opinions.\n"
                "2. Verify all record citations flagged [VERIFY from record].\n"
                "3. Select one opening statement version and memorize it.\n"
                "4. Schedule moot court at least 48 hours before the argument.\n"
                "5. Bring the Quick-Reference table (Part 8) to the podium."
            ),
            success=True,
        )
