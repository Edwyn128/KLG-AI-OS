"""
bloodhound/agent.py — Bloodhound's signal triage agent (Pydantic AI).

This agent evaluates raw external legal signals (WatchSignal) and decides:
1. Is it relevant to KLG's specific constitutional/appellate focus?
2. What tier (1, 2, or 3) should it be assigned?
3. What is the KLG Strategic Nexus (why we are watching it)?
4. What are the metadata tags (court, docket number, issue area)?
"""

from __future__ import annotations

import logging
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from alfred.model_factory import build_model
from config import settings
from bloodhound.signals import WatchSignal

logger = logging.getLogger(__name__)

# =============================================================================
# TRIAGE DECISION SCHEMA
# =============================================================================

class TriageDecision(BaseModel):
    """
    Structured output returned by the Bloodhound triage agent.
    Maps directly to the properties in Notion's Bloodhound Watch List.
    """
    is_relevant: bool = Field(
        ...,
        description="True if the case matches KLG's strategic litigation focus and is worth adding to the Watch List."
    )
    reasoning: str = Field(
        ...,
        description="A 1-2 sentence explanation of why this case is relevant or why it is skipped."
    )
    case_name: str = Field(
        ...,
        description="Clean, official case title/caption (e.g. 'Smith v. City of Los Angeles')."
    )
    court: str = Field(
        ...,
        description="Standardized court name. MUST match one of KLG's options exactly: '9th Cir.', 'SCOTUS', 'Cal. Ct. App.', 'Cal. S. Ct.', 'N.D. Cal.', 'C.D. Cal.', 'E.D. Cal.', 'S.D. Cal.', or empty string if it doesn't match any."
    )
    docket_no: str = Field(
        default="",
        description="Court docket/case number (e.g. '23-55612' or 'G061234')."
    )
    suggested_tier: str = Field(
        ...,
        description="Suggested importance tier: '1' (highest priority core KLG issue), '2' (adjacent doctrine/active tracking), '3' (ambient monitoring/passive)."
    )
    issue_areas: list[str] = Field(
        ...,
        description="List of issue tags. Each MUST match KLG's options: 'First Amendment', 'Free Speech', 'Public Employee Speech', 'Property Rights', 'Takings', 'Regulatory Taking', 'Supersedeas Exceptions', 'Appellate Procedure'."
    )
    procedural_posture: str = Field(
        default="Briefing",
        description="Standardized stage of the case: 'Briefing', 'Argued', 'Decided', or 'Cert. pending'."
    )
    klg_nexus_note: str = Field(
        default="",
        description="A detailed explanation of the strategic significance to KLG (e.g., impact on appellate precedent, podcast guest potential, amicus briefs)."
    )


# =============================================================================
# SYSTEM PROMPT
# =============================================================================

_BLOODHOUND_SYSTEM_PROMPT = """
You are Bloodhound, the outward-facing legal research and surveillance engine for Kowal Law Group (KLG).
Your role is to evaluate incoming legal signals (new filings, opinions, legal commentary, press releases) and decide which cases are worth tracking on KLG's Notion Watch List.

KLG is a premium California appellate litigation firm. The firm operates half as a law firm and half as a think tank, producing scholarship, podcasts (CALP), and amicus briefs.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
KLG STRATEGIC PRACTICE CRITERIA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evaluate signals based on their fit with KLG's key areas:

1. FIRST AMENDMENT & PUBLIC EMPLOYEE RIGHTS (Core Tier 1/2)
   - Free speech rights of government workers, public teachers, and whistleblowers.
   - Circuit splits or major appellate rulings regarding public employee retaliation, Garcetti v. Ceballos exceptions, and Pickering balancing.
   - Retaliation against citizens exercising free speech/petition rights.

2. PROPERTY RIGHTS & TAKINGS (Core Tier 1/2)
   - Eminent domain, regulatory takings, zoning overreach, and property rights disputes.
   - California land use law (CEQA, Coastal Commission, housing mandates) and constitutional takings clause issues (Nollan/Dolan/Koontz).

3. APPELLATE PROCEDURE & LITIGATION MOATS (Core Tier 1/2)
   - Supersedeas bonds, stays pending appeal, preliminary injunction appellate standards.
   - Writs of supersedeas, preservation of issues for appeal, and California-specific appellate jurisdiction splits.

4. AMBENT APPELLATE LANDSCAPE (Tier 3)
   - Significant 9th Circuit or California Supreme Court constitutional issues that do not directly fit the above but are broad thought-leadership opportunities (e.g., podcast topics, major administrative law shifts post-Chevron).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TIER ASSIGNMENT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Tier 1 (Highest): Directly matches KLG's core active or recently litigated issues (especially public employee speech retaliation, California supersedeas exceptions, or regulatory takings). Essential watch items.
- Tier 2 (Medium): Doctrines adjacent to KLG's core practice where an appellate split or high court ruling impacts KLG's strategy.
- Tier 3 (Ambient): Broadly interesting constitutional or California appellate developments suitable for CALP podcast guest bookings or general firm awareness.
- Skip (Not Relevant): Commercial disputes, criminal law (unless major 4th/5th Amendment issue), family law, personal injury, tax, patent law, or minor procedural decisions.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
METADATA STANDARDIZATION GUIDELINES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Court: MUST be one of KLG's options:
  * "9th Cir." (9th Circuit Court of Appeals)
  * "SCOTUS" (U.S. Supreme Court)
  * "Cal. Ct. App." (California Courts of Appeal)
  * "Cal. S. Ct." (California Supreme Court)
  * "N.D. Cal." / "C.D. Cal." / "E.D. Cal." / "S.D. Cal." (Federal District Courts in CA)
  * If a case is from another state court or circuit, map it to the closest or return an empty string.
- Issue Areas: Choose only from these KLG tags:
  * "First Amendment", "Free Speech", "Public Employee Speech", "Property Rights", "Takings", "Regulatory Taking", "Supersedeas Exceptions", "Appellate Procedure".
- Procedural Posture: Must be 'Briefing', 'Argued', 'Decided', or 'Cert. pending'.
- Case Name: Format cleanly, e.g. "Smith v. City of Los Angeles" instead of "JOHN SMITH, Plaintiff-Appellant, v. THE CITY OF LOS ANGELES, a municipal entity...".
""".strip()


# =============================================================================
# BLOODHOUND AGENT DEFINITION
# =============================================================================

BloodhoundTriageAgent: Agent[None, TriageDecision] = Agent(
    model=build_model(settings.bloodhound_model),
    system_prompt=_BLOODHOUND_SYSTEM_PROMPT,
    output_type=TriageDecision,
)
"""
The Bloodhound triage agent.
Takes a raw feed signal string (or WatchSignal) and returns a structured TriageDecision.

Usage:
    result = await BloodhoundTriageAgent.run("Raw text from RSS feed...")
    triage = result.data  # TriageDecision object
"""
