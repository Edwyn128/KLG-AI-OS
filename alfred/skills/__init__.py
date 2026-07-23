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
  4. Import the class in this file and add it to SKILL_REGISTRY
"""

from alfred.skills.base import Skill, SkillResult, skill_generate, skill_read_file_text, skill_fetch_sharepoint
from alfred.skills.klg_case_assessment import KLGCaseAssessment
from alfred.skills.klg_case_novella import KLGCaseNovella
from alfred.skills.klg_record_digest import KLGRecordDigest
from alfred.skills.klg_opposition_separate_statement import KLGOppositionSeparateStatement
from alfred.skills.klg_dz_overlay import KLGDZOverlay
from alfred.skills.klg_notebooklm_handoff import KLGNotebookLMHandoff
from alfred.skills.klg_court_doc_renamer import KLGCourtDocRenamer
from alfred.skills.klg_authority_library import KLGAuthorityLibrary
from alfred.skills.klg_appendix_cites import KLGAppendixCites
from alfred.skills.klg_content_research import KLGContentResearch
from alfred.skills.klg_oral_argument_full import KLGOralArgumentFull
from alfred.skills.klg_matter_intake import KLGMatterIntake
from alfred.skills.klg_deep_research_prompts import KLGDeepResearchPrompts
from alfred.skills.klg_conflict_waiver import KLGConflictWaiver
from alfred.skills.klg_podcast_guest_prep import KLGPodcastGuestPrep
from alfred.skills.klg_style_guide_check import KLGStyleGuideCheck
from alfred.skills.klg_cite_check import KLGCiteCheck
from alfred.skills.klg_response_plan import KLGResponsePlan
from alfred.skills.klg_appendix_audit import KLGAppendixAudit
from alfred.skills.klg_brief_elevation import KLGBriefElevation
from alfred.skills.klg_authority_map import KLGAuthorityMap
from alfred.skills.klg_issue_framing import KLGIssueFraming
from alfred.skills.klg_standard_of_review import KLGStandardOfReview
from alfred.skills.klg_oral_argument_prep import KLGOralArgumentPrep
from alfred.skills.klg_amicus_assessment import KLGAmicusAssessment
from alfred.skills.klg_record_navigator import KLGRecordNavigator
from alfred.skills.klg_daily_triage import KLGDailyTriage
from alfred.skills.klg_prebill_audit import KLGPrebillAudit
from alfred.skills.klg_research_compilation import KLGResearchCompilation
from alfred.skills.klg_brief_assembly import KLGBriefAssembly

# Registry of all available skills, keyed by name.
# Alfred's run_skill tool looks skills up here by name.
SKILL_REGISTRY: dict[str, Skill] = {
    KLGCaseAssessment.name:          KLGCaseAssessment(),
    KLGMatterIntake.name:            KLGMatterIntake(),
    KLGDeepResearchPrompts.name:     KLGDeepResearchPrompts(),
    KLGConflictWaiver.name:          KLGConflictWaiver(),
    KLGPodcastGuestPrep.name:        KLGPodcastGuestPrep(),
    KLGStyleGuideCheck.name:         KLGStyleGuideCheck(),
    KLGCiteCheck.name:               KLGCiteCheck(),
    KLGResponsePlan.name:            KLGResponsePlan(),
    KLGAppendixAudit.name:           KLGAppendixAudit(),
    KLGBriefElevation.name:          KLGBriefElevation(),
    KLGAuthorityMap.name:            KLGAuthorityMap(),
    KLGIssueFraming.name:            KLGIssueFraming(),
    KLGStandardOfReview.name:        KLGStandardOfReview(),
    KLGOralArgumentPrep.name:        KLGOralArgumentPrep(),
    KLGAmicusAssessment.name:        KLGAmicusAssessment(),
    KLGRecordNavigator.name:         KLGRecordNavigator(),
    KLGDailyTriage.name:             KLGDailyTriage(),
    KLGPrebillAudit.name:            KLGPrebillAudit(),
    KLGResearchCompilation.name:     KLGResearchCompilation(),
    KLGBriefAssembly.name:           KLGBriefAssembly(),
    KLGCaseNovella.name:             KLGCaseNovella(),
    KLGRecordDigest.name:            KLGRecordDigest(),
    KLGOppositionSeparateStatement.name: KLGOppositionSeparateStatement(),
    KLGDZOverlay.name:               KLGDZOverlay(),
    KLGNotebookLMHandoff.name:       KLGNotebookLMHandoff(),
    KLGCourtDocRenamer.name:         KLGCourtDocRenamer(),
    KLGAuthorityLibrary.name:        KLGAuthorityLibrary(),
    KLGAppendixCites.name:           KLGAppendixCites(),
    KLGContentResearch.name:         KLGContentResearch(),
    KLGOralArgumentFull.name:        KLGOralArgumentFull(),
}

__all__ = [
    "Skill",
    "SkillResult",
    "SKILL_REGISTRY",
    "KLGCaseAssessment",
    "KLGMatterIntake",
    "KLGDeepResearchPrompts",
    "KLGConflictWaiver",
    "KLGPodcastGuestPrep",
    "KLGStyleGuideCheck",
    "KLGCiteCheck",
    "KLGResponsePlan",
    "KLGAppendixAudit",
    "KLGBriefElevation",
    "KLGAuthorityMap",
    "KLGIssueFraming",
    "KLGStandardOfReview",
    "KLGOralArgumentPrep",
    "KLGAmicusAssessment",
    "KLGRecordNavigator",
    "KLGDailyTriage",
    "KLGPrebillAudit",
    "KLGResearchCompilation",
    "KLGBriefAssembly",
    "KLGCaseNovella",
    "KLGRecordDigest",
    "KLGOppositionSeparateStatement",
    "KLGDZOverlay",
    "KLGNotebookLMHandoff",
    "KLGCourtDocRenamer",
    "KLGAuthorityLibrary",
    "KLGAppendixCites",
    "KLGContentResearch",
    "KLGOralArgumentFull",
]
