"""
alfred/skills — Individual KLG skill implementations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT SKILLS ARE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

In the KLG AI OS, a "skill" is a structured, named workflow that follows
the standard 5-step lifecycle:

  Step 1 — Locate the project page (find the matter in Notion)
  Step 2 — Read context (Layer 0 source data + Layer 1 project state)
  Step 3 — Do the work (draft, analyze, compose, synthesize)
  Step 4 — Update Layer 1 (write status/notes back to the project page)
  Step 5 — Tee up what's next (identify and surface the next action)

Every skill in this package follows this pattern. This standardization is
what makes Alfred a SINGLE assistant the team converses with — not a
collection of disconnected one-off scripts.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SKILL NAMING CONVENTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Skills are named with the prefix "klg-" followed by a hyphenated descriptor:
  klg-brief-elevation    — elevate a brief from draft to filing-ready
  klg-matter-intake      — onboard a new matter, clear conflicts, intake form
  klg-engagement-letter  — draft the engagement letter for a new matter

The skill name is logged to the project page on every execution (Step 4),
so the audit trail shows exactly which skill touched the page.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADDING A NEW SKILL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Create a new file: alfred/skills/klg_<name>.py
  2. Define a class that inherits from Skill (alfred/skills/base.py)
  3. Implement the `execute()` method following the 5-step lifecycle
  4. Register the skill in the SKILL_REGISTRY dict below
  5. The skill runner will automatically find it by name
"""

from alfred.skills.base import Skill, SkillResult
from alfred.skills.klg_matter_intake import KLGMatterIntake

# Registry of all available skills, keyed by name.
# Alfred's skill runner looks skills up here by name.
SKILL_REGISTRY: dict[str, Skill] = {
    KLGMatterIntake.name: KLGMatterIntake(),
}

__all__ = ["Skill", "SkillResult", "KLGMatterIntake", "SKILL_REGISTRY"]
