"""
alfred/task_rubric.py — Hard-coded task rubric for KLG brief-writing matters.

Transcribed verbatim from William's decision table, August 5, 2026.
Source document: docs/plans/_rubric_extracted.txt

Two project templates:
  APPELLATE_TASKS      — Appellate Briefing
  TRIAL_COURT_TASKS    — Trial Court Brief Preparation

Usage:
    from alfred.task_rubric import resolve_tasks_for_matter
    tasks, flags = resolve_tasks_for_matter("appellate", answers)

Condition keys (applies_when values that are not "always"/"contingent"/"confirm"):
  filed_original_noa           — appellate, appearance_type == "filed_original"
  substituting_in              — appellate, appearance_type == "substituting_in"
  associating_in               — appellate, appearance_type == "associating_in"
  is_appellant_side            — appellate, klg_side in {appellant, petitioner}
  is_respondent_side           — appellate, klg_side in {respondent, plaintiff, defendant}
  is_appellant_side_and_coa_opened — is_appellant_side AND coa_case_opened_and_numbered
  is_ninth_circuit             — answers.get("is_ninth_circuit", False)
  not_already_counsel_of_record — trial court, not klg_already_counsel_of_record
  drafter_not_tim              — drafting_attorney is not Tim (handled specially below)

applies_when sentinel values:
  "always"     — create for every project of this type
  "contingent" — never created at setup; see CONTINGENCY_TRIGGERS
  "confirm"    — ambiguous per rubric; always skipped and always flagged

Owner sentinel:
  "__drafting_attorney__" — resolved from answers["drafting_attorney"] at runtime
                            (Trial Court: "Notify Brittney to Begin Cites & Formatting")
"""
from __future__ import annotations

from typing import Any


# =============================================================================
# APPELLATE BRIEFING — PROJECT TASKS
# Source: William's decision table, August 5, 2026
# Sections: Matter Intake & Setup → Pleadings & Notices →
#           Brief Preparation & Drafting → Cites & Compliance →
#           Review & Finalize → Contingency Tasks (As Needed)
# =============================================================================

APPELLATE_TASKS: list[dict[str, Any]] = [

    # ── Matter Intake & Setup ─────────────────────────────────────────────────
    {
        "task":          "New Matter Intake and Retainer",
        "stage":         "Matter Intake & Setup",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Setup",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Set up the shared workspace",
        "stage":         "Matter Intake & Setup",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Setup",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Create Case Memo and Populate Clearbrief Database",
        "stage":         "Matter Intake & Setup",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Setup",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Populate custom fields in the project",
        "stage":         "Matter Intake & Setup",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Setup",
        "default_owner": "William",
        "applies_when":  "always",
    },
    {
        "task":          "Template Header/Setup Review",
        "stage":         "Matter Intake & Setup",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Setup",
        "default_owner": "Tim Kowal",
        "applies_when":  "always",
    },

    # ── Pleadings & Notices ───────────────────────────────────────────────────
    {
        "task":          "Notice of Appeal",
        "stage":         "Pleadings & Notices",
        "priority":      "High",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "filed_original_noa",
    },
    {
        "task":          "File Designation of Record in Superior Court & Post RT Deposit",
        "stage":         "Pleadings & Notices",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "filed_original_noa",
    },
    {
        "task":          "File Substitution in the Case",
        "stage":         "Pleadings & Notices",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "substituting_in",
    },
    {
        "task":          "Calendar all filing deadlines and important dates.",
        "stage":         "Pleadings & Notices",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "File Notice of Association in Court of Appeal",
        "stage":         "Pleadings & Notices",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "associating_in",
    },
    {
        "task":          "File Civil Case Information Statement",
        "stage":         "Pleadings & Notices",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "is_appellant_side_and_coa_opened",
    },

    # ── Brief Preparation & Drafting ──────────────────────────────────────────
    {
        "task":          "Obtain & Process Opposing Filings",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Obtain and Process Reporter's/Clerk's Transcripts",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "2 hours",
        "labels":        "",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Create Response Plan",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Drafting",
        "default_owner": "Brittney",
        "applies_when":  "is_respondent_side",
    },
    {
        "task":          "Create brief shell",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Drafting",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Brief Drafting",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Drafting",
        "default_owner": None,  # Always resolved from intake — never guess
        "applies_when":  "always",
    },
    {
        "task":          "Assemble Documents for the Appendix",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "2 hours",
        "labels":        "Drafting",
        "default_owner": "Brittney",
        "applies_when":  "is_appellant_side",
    },

    # ── Cites & Compliance ────────────────────────────────────────────────────
    {
        "task":          "Notify Paralegal to Begin Cites & Formatting",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Citations",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Brief: Cites and Formatting",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "2 hours",
        "labels":        "Citations",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Cite checking",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "2 hours",
        "labels":        "",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Ninth Circuit Brief Technical Review",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "",
        "default_owner": "Brittney",
        "applies_when":  "is_ninth_circuit",
    },

    # ── Review & Finalize ─────────────────────────────────────────────────────
    {
        "task":          "Brief: Second Drafter Review",
        "stage":         "Review & Finalize",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Review",
        "default_owner": "Tim Kowal",  # Resolved in resolve_tasks_for_matter
        "applies_when":  "drafter_not_tim",
    },
    {
        "task":          "Get briefing extension",
        "stage":         "Review & Finalize",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "contingent",
    },
    {
        "task":          "Finalize and File the Document with the Court",
        "stage":         "Review & Finalize",
        "priority":      "High",
        "duration":      "1 hour",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },

    # ── Contingency Tasks (As Needed) ─────────────────────────────────────────
    {
        "task":          "Request Extension (if needed)",
        "stage":         "Contingency",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Drafting",
        "default_owner": "Brittney",
        "applies_when":  "contingent",
    },
    {
        "task":          "Motion Edits (Any Other Business Edits)",
        "stage":         "Contingency",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Drafting",
        "default_owner": "Brittney",
        "applies_when":  "contingent",
    },
    {
        "task":          "Emergency Motion or Filing (if needed)",
        "stage":         "Contingency",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "contingent",
    },
]


# =============================================================================
# TRIAL COURT BRIEF PREPARATION — PROJECT TASKS
# Source: William's decision table, August 5, 2026
# Sections: Matter Setup → Pleadings & Notices →
#           Brief Preparation & Drafting → Cites & Compliance →
#           Review & Finalization → Contingency Tasks (As Needed)
# =============================================================================

TRIAL_COURT_TASKS: list[dict[str, Any]] = [

    # ── Matter Setup ──────────────────────────────────────────────────────────
    {
        "task":          "New Matter Intake and Retainer",
        "stage":         "Matter Setup",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Setup",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Set up the shared workspace",
        "stage":         "Matter Setup",
        "priority":      "Medium",
        "duration":      "1 hour",
        "labels":        "Setup",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Create Case Memo and Populate Clearbrief Database",
        "stage":         "Matter Setup",
        "priority":      "High",
        "duration":      "3 hours",
        "labels":        "Setup",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Populate custom fields in the project",
        "stage":         "Matter Setup",
        "priority":      "Medium",
        "duration":      "1 hour",
        "labels":        "Setup",
        "default_owner": "William",
        "applies_when":  "always",
    },
    {
        "task":          "Template Header/Setup Review",
        "stage":         "Matter Setup",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Setup",
        "default_owner": "Tim Kowal",
        "applies_when":  "always",
    },

    # ── Pleadings & Notices ───────────────────────────────────────────────────
    {
        "task":          "Calendar all filing deadlines and important dates.",
        "stage":         "Pleadings & Notices",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Court Deadline",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "File Notice of Association",
        "stage":         "Pleadings & Notices",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "not_already_counsel_of_record",
    },

    # ── Brief Preparation & Drafting ──────────────────────────────────────────
    {
        "task":          "Identify documents or exhibits needed",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "4 hours",
        "labels":        "Drafting",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Create brief shell",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "High",
        "duration":      "30 min",
        "labels":        "Drafting",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Brief Drafting",
        "stage":         "Brief Preparation & Drafting",
        "priority":      "Medium",
        "duration":      "8 hours",
        "labels":        "Drafting",
        "default_owner": None,  # Always resolved from intake — never guess
        "applies_when":  "always",
    },

    # ── Cites & Compliance ────────────────────────────────────────────────────
    {
        "task":          "Notify Brittney to Begin Cites & Formatting",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Citations",
        "default_owner": "__drafting_attorney__",  # Owned by whichever attorney drafted
        "applies_when":  "always",
    },
    {
        "task":          "Brief: Cites and Formatting",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "4 hours",
        "labels":        "Citations",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },
    {
        "task":          "Cite checking",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "2 hours",
        "labels":        "Citations",
        "default_owner": "Tim Kowal",
        "applies_when":  "always",
    },
    {
        "task":          "Ninth Circuit Brief Technical Compliance Checklist",
        "stage":         "Cites & Compliance",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Citations",
        "default_owner": "Brittney",
        "applies_when":  "confirm",  # Ambiguous — likely doesn't belong on state trial court
    },

    # ── Review & Finalization ─────────────────────────────────────────────────
    {
        "task":          "Brief: Second Drafter Review",
        "stage":         "Review & Finalization",
        "priority":      "Medium",
        "duration":      "2 hours",
        "labels":        "Review",
        "default_owner": "Tim Kowal",  # Resolved in resolve_tasks_for_matter
        "applies_when":  "drafter_not_tim",
    },
    {
        "task":          "Get briefing extension",
        "stage":         "Review & Finalization",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Court Deadline",
        "default_owner": "Brittney",
        "applies_when":  "contingent",
    },
    {
        "task":          "Finalize and File the Document with the Court",
        "stage":         "Review & Finalization",
        "priority":      "Medium",
        "duration":      "1 hour",
        "labels":        "Filing",
        "default_owner": "Brittney",
        "applies_when":  "always",
    },

    # ── Contingency Tasks (As Needed) ─────────────────────────────────────────
    {
        "task":          "Motion Edits (if needed)",
        "stage":         "Contingency",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Drafting",
        "default_owner": "William",
        "applies_when":  "contingent",
    },
    {
        "task":          "Request Extension (if needed)",
        "stage":         "Contingency",
        "priority":      "Medium",
        "duration":      "30 min",
        "labels":        "Court Deadline",
        "default_owner": "Brittney",
        "applies_when":  "contingent",
    },
]


# =============================================================================
# CONTINGENCY TASK TRIGGERS
# Transcribed verbatim from William's rubric, August 5, 2026.
# Reference these when asked to add a contingent task later in a matter.
# =============================================================================

CONTINGENCY_TRIGGERS: dict[str, str] = {
    "Request Extension (if needed) / Get briefing extension": (
        "Trigger: the drafting attorney determines more time is needed before an upcoming "
        "filing deadline. These two tasks appear in different stages of the two templates "
        "but cover the same event — confirm with Tim and Brittney whether both are actually "
        "needed or one is a leftover duplicate."
    ),
    "Motion Edits (Any Other Business Edits) / Motion Edits (if needed)": (
        "Trigger: an ancillary motion, unrelated to the core brief, needs drafting or "
        "editing during the matter's pendency."
    ),
    "Emergency Motion or Filing (if needed)": (
        "Trigger: an unplanned, urgent filing becomes necessary outside the normal "
        "briefing schedule."
    ),
}


# =============================================================================
# CONDITION EVALUATOR
# =============================================================================

def _evaluate_condition(condition: str, answers: dict) -> bool:
    """
    Evaluate a rubric condition key against intake-questionnaire answers.

    Returns True if the task applies to this matter, False if it is genuinely
    N/A. A False result is not a gap — it means the condition was answered and
    the answer was "no".
    """
    appearance = (answers.get("appearance_type") or "").strip().lower()
    side = (answers.get("klg_side") or "").strip().lower()

    if condition == "filed_original_noa":
        return appearance == "filed_original"
    if condition == "substituting_in":
        return appearance == "substituting_in"
    if condition == "associating_in":
        return appearance == "associating_in"
    if condition == "is_appellant_side":
        return side in {"appellant", "petitioner"}
    if condition == "is_respondent_side":
        return side in {"respondent", "plaintiff", "defendant"}
    if condition == "is_appellant_side_and_coa_opened":
        return (
            side in {"appellant", "petitioner"}
            and bool(answers.get("coa_case_opened_and_numbered", False))
        )
    if condition == "is_ninth_circuit":
        return bool(answers.get("is_ninth_circuit", False))
    if condition == "not_already_counsel_of_record":
        return not bool(answers.get("klg_already_counsel_of_record", False))
    if condition == "drafter_not_tim":
        drafter = (answers.get("drafting_attorney") or "").strip().lower()
        return drafter not in {"tim", "tim kowal"}
    return False


# =============================================================================
# PUBLIC API
# =============================================================================

def resolve_tasks_for_matter(
    project_type: str,
    answers: dict,
) -> tuple[list[dict], list[str]]:
    """
    Apply the rubric to a set of intake-questionnaire answers.

    Contingent tasks are never included. Ambiguous ("confirm") tasks are never
    included but always surface as flags. Condition-false tasks are silently
    skipped (they are genuinely N/A, not gaps).

    Returns:
        tasks  — resolved task dicts ready to create in Notion
        flags  — items requiring human attention (owner gaps, skipped-confirm
                 tasks, Tim-is-drafter notices, William UUID gap)
    """
    table = APPELLATE_TASKS if project_type == "appellate" else TRIAL_COURT_TASKS
    resolved: list[dict] = []
    flags: list[str] = []

    for t in table:
        aw = t["applies_when"]

        if aw == "contingent":
            continue  # Never created at setup — see CONTINGENCY_TRIGGERS

        if aw == "confirm":
            flags.append(
                f"Skipped '{t['task']}' — ambiguous per rubric, needs a human decision "
                f"before it can be added to this matter."
            )
            continue

        if aw != "always" and not _evaluate_condition(aw, answers):
            continue  # Condition false — correctly N/A

        owner = t["default_owner"]

        # Brief Drafting: always resolved from intake, never guessed
        if t["task"] == "Brief Drafting":
            owner = answers.get("drafting_attorney") or None
            if not owner:
                flags.append(
                    "Brief Drafting has no owner — drafting_attorney was not provided "
                    "at intake. Assign it manually before work begins."
                )

        # Brief: Second Drafter Review: N/A when Tim is the drafter
        elif t["task"] == "Brief: Second Drafter Review":
            if answers.get("drafting_attorney", "").strip().lower() in {"tim", "tim kowal"}:
                flags.append(
                    "Brief: Second Drafter Review skipped — Tim is the drafter. "
                    "No fallback reviewer is defined in the rubric; confirm with Tim "
                    "if a second review is still wanted in this matter."
                )
                continue
            owner = "Tim Kowal"

        # "Notify Brittney to Begin Cites & Formatting" (Trial Court): owned by drafter
        elif owner == "__drafting_attorney__":
            owner = answers.get("drafting_attorney") or None
            if not owner:
                flags.append(
                    f"'{t['task']}' has no owner — drafting_attorney was not provided "
                    f"at intake. Assign it manually."
                )

        resolved.append({**t, "default_owner": owner})

    # William's Notion UUID is not yet configured — flag his tasks
    if any(t.get("default_owner") == "William" for t in resolved):
        flags.append(
            "'Populate custom fields in the project' is assigned to William — "
            "his Notion UUID is not yet configured in this codebase. "
            "The task will be created without an Assignee; assign it to William manually in Notion."
        )

    return resolved, flags
