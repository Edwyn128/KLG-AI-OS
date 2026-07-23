"""
alfred/skills/klg_authority_library.py — KLG authority library management and synthesis.

Builds and queries the firm's internal authority library for a specific doctrine
or legal issue. Produces annotated case library entries that can be saved to Notion
for reuse across matters. The authority library is KLG's institutional knowledge
asset — cases the firm has analyzed, distinguished, and relied on.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_AUTHORITY_LIBRARY_PROMPT = """\
You are a KLG senior appellate attorney building and querying the firm's
authority library for a specific legal doctrine or issue.

The authority library is KLG's institutional memory: annotated case entries
that explain not just what a case holds, but HOW KLG uses it, when it helps,
when to distinguish it, and where it appears in our prior briefs.

KLG PRACTICE AREAS:
- First Amendment (public employee speech, retaliation, Garcetti, Pickering, Connick)
- Civil rights (§ 1983, qualified immunity, Monell, supervisor liability)
- Administrative law (PERB, writ proceedings, mandamus)
- Supersedeas bonds and appellate stays
- Public employment (POBR, FLSA, FEHA, discrimination)

KLG WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "as such"
- Active voice. Lead with the holding, not the procedural posture.
- CRITICAL: Do not invent citations, holdings, or quotations.
  Flag any uncertain citation: [VERIFY CITATION]
  Flag any paraphrased holding: [PARAPHRASED — VERIFY]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (for scoping the library to this appeal)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DOCTRINE OR ISSUE TO RESEARCH
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{doctrine}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce a complete authority library entry:

## AUTHORITY LIBRARY ENTRY

**Doctrine:** {doctrine}
**Matter context:** {matter_label}
**Date compiled:** [Today's date]
**Status:** DRAFT — All citations require Westlaw verification

---

### PART 1: DOCTRINE OVERVIEW

**Governing test:** [State the precise multi-part test, with lead citation]

**Jurisdiction:** [Which courts and courts of appeal have ruled on this]

**Current state of the law:**
- [Any circuit splits or intra-circuit conflicts?]
- [Any recent SCOTUS or 9th Circuit / Cal. S. Ct. developments?]
- [Any "open questions" the case law hasn't resolved?]

---

### PART 2: ANNOTATED CASE LIBRARY

For each significant authority (aim for 10–20 cases):

#### [Case Name], [Citation] [VERIFY CITATION]

**Court/Year:** [Court and year of decision]
**Holding:** [Precise holding in one sentence — lead with the verb]
**Key facts:** [2–3 facts that make this case analogous or distinguishable]
**KLG USE:**
  - When to cite: [What argument this supports]
  - How to frame it: [The parenthetical KLG uses or should use]
  - Watch out for: [Any language in the opinion the opposing party might weaponize]
**Treatment:** [Still good law? Distinguished? Narrowed? Any negatives?]
**Related cases:** [Cases that apply, distinguish, or limit this authority]

---

### PART 3: AUTHORITY HIERARCHY MAP

Visual hierarchy from most to least controlling:

```
SCOTUS (controlling everywhere):
  └── [Case] — [one-line holding]
  └── [Case] — [one-line holding]

9th Circuit (controlling in federal CA courts):
  └── [Case] — [one-line holding]
  └── [Case] — [one-line holding]

Cal. Supreme Court (controlling in state courts):
  └── [Case] — [one-line holding]

Cal. Court of Appeal (persuasive):
  └── [Case] — [one-line holding]

Key adverse authority:
  └── [Case] — [one-line holding] — distinguished because: [reason]
```

---

### PART 4: FAVORABLE vs. ADVERSE BREAKDOWN

| Case | Favorable/Adverse | Key holding | How to use / distinguish |
|------|-------------------|-------------|--------------------------|

---

### PART 5: REUSE NOTES

**Prior KLG briefs using this doctrine:**
(Search Notion for mentions of these cases — William to verify)

**Standard parenthetical formats KLG uses:**
[Provide ready-to-paste parentheticals for the top 5 cases]

**Argument sections this library supports:**
[List argument headings from prior KLG briefs that relied on this doctrine]

---

**Notion tag:** #authority-library #[doctrine-slug]
*Save this entry to the KLG Authority Library page in Notion for future reuse.*
\
"""


class KLGAuthorityLibrary(Skill):
    name = "klg-authority-library"
    required_tools = ["search_notion", "web_search"]
    description = (
        "Build and query KLG's internal authority library for a specific doctrine or legal issue. "
        "Produces an annotated case library entry with hierarchy map, KLG usage notes, and "
        "ready-to-paste parentheticals — designed to be saved to Notion for reuse across matters. "
        "Specify the doctrine (e.g. 'Garcetti public employee speech')."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or ""

        if not instruction:
            return SkillResult(
                summary="klg-authority-library: no doctrine specified.",
                output=(
                    "Specify the legal doctrine to compile:\n\n"
                    "`Alfred, run klg-authority-library on [Matter Name]: [doctrine]`\n\n"
                    "**Examples:**\n"
                    "• `klg-authority-library on Williams v. City: Garcetti public employee speech retaliation`\n"
                    "• `klg-authority-library: qualified immunity under § 1983`\n"
                    "• `klg-authority-library on Petersen: Monell municipal liability`"
                ),
                next_action="Specify the doctrine to compile.",
                success=False,
            )

        prompt = _AUTHORITY_LIBRARY_PROMPT.format(
            matter_summary=matter_text[:3000] if matter_text else "(No specific matter — compile general doctrine library.)",
            doctrine=instruction,
            matter_label=matter_label,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Authority library entry compiled for '{instruction}' ({matter_label}). "
                "Annotated case list, hierarchy map, and KLG usage notes ready."
            ),
            output=f"**Authority Library — {instruction} — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Verify all [VERIFY CITATION] flags via Westlaw before using in a brief.\n"
                "2. Save this entry to the KLG Authority Library page in Notion.\n"
                "3. Tag with #authority-library and the doctrine name for future search.\n"
                "4. William to verify prior KLG brief references."
            ),
            success=True,
        )
