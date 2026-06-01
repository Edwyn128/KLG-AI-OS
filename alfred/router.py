"""
Query classification and skill selection.

MVP: keyword-based routing. Each entry maps signal terms to a skill file.
Upgrade path: replace classify() with a Claude call for smarter classification.
"""

import os
import re
from pathlib import Path

SKILLS_DIR = Path(os.getenv("SKILLS_DIR", "./skills"))

# Maps query type label → skill filename (without .md) + signal keywords
SKILL_MAP = [
    {
        "query_type": "response_plan",
        "skill": "klg-response-plan",
        "signals": [
            "response plan", "opposition", "respond to", "reply brief",
            "anti-slapp", "motion to dismiss", "demurrer", "answer",
        ],
    },
    {
        "query_type": "case_assessment",
        "skill": "case-assessment",
        "signals": [
            "case assessment", "evaluate", "potential client", "intake",
            "worth taking", "merit", "viability",
        ],
    },
    {
        "query_type": "brief_elevation",
        "skill": "brief-elevation",
        "signals": [
            "brief elevation", "polish", "sharpen", "improve brief",
            "make this better", "elevate",
        ],
    },
    {
        "query_type": "oral_argument",
        "skill": "oral-argument",
        "signals": [
            "oral argument", "moot", "panel questions", "bench",
            "argument prep",
        ],
    },
]

DEFAULT_SKILL = "klg-response-plan"
DEFAULT_QUERY_TYPE = "general"


def load_skill(skill_name: str) -> str:
    """Load skill text from skills/ directory. Returns empty string if not found."""
    path = SKILLS_DIR / f"{skill_name}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    # Fallback: try repo root skills/ if CWD differs
    fallback = Path(__file__).parent.parent / "skills" / f"{skill_name}.md"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8")
    return ""


def classify(query: str) -> dict:
    """Classify query against SKILL_MAP. Returns first match or default."""
    q = query.lower()
    for entry in SKILL_MAP:
        for signal in entry["signals"]:
            if signal in q:
                return {"query_type": entry["query_type"], "skill": entry["skill"]}
    return {"query_type": DEFAULT_QUERY_TYPE, "skill": DEFAULT_SKILL}


def route_query(query: str, skill_override: str | None = None) -> dict:
    """
    Main routing function. Returns skill name, skill text, and query type.
    skill_override bypasses classification when the caller specifies a skill directly.
    """
    if skill_override:
        classification = {"query_type": "manual_override", "skill": skill_override}
    else:
        classification = classify(query)

    skill_text = load_skill(classification["skill"])

    # If skill file is missing or is a stub, fall back gracefully
    if not skill_text or "STUB" in skill_text:
        skill_text = _stub_fallback(classification["skill"])

    return {
        "skill": classification["skill"],
        "query_type": classification["query_type"],
        "skill_text": skill_text,
    }


def _stub_fallback(skill_name: str) -> str:
    return (
        f"You are Alfred, the AI executive assistant for Kowal Law Group (KLG), "
        f"a California civil rights litigation firm. The skill '{skill_name}' has not "
        f"been fully configured yet. Answer the user's question as helpfully as you can "
        f"using your general legal knowledge, and note that the KLG-specific skill "
        f"instructions for this query type are still being developed."
    )
