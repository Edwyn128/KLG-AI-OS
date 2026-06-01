"""
bloodhound/signals.py — Signal tier definitions and the WatchSignal data model.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE THREE-TIER SIGNAL HIERARCHY
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Not all signals are equally important. Bloodhound uses a three-tier system
to prioritize which detected cases deserve the most attention:

  TIER 1 — Highest signal. KLG's core practice areas.
    Sources: Movement-org press releases (PLF, IJ, NCLA, FIRE, Cato amicus),
             CourtListener RECAP keyword alerts.
    Why: These are pre-filtered by organizations that share KLG's orientation.
         Every filing announced by PLF is directly relevant. The leverage point
         is the org press-release layer — these orgs do the filtering for us.

  TIER 2 — Medium signal. Adjacent doctrine worth monitoring.
    Sources: 9th Circuit and Cal. Ct. App. opinion feeds,
             Legal commentary blogs (Volokh, How Appealing, SCOTUSblog,
             At The Lectern, Reason, City Journal).
    Why: Broad appellate landscape — not every case is relevant to KLG,
         but this layer catches circuit splits and emerging doctrine.

  TIER 3 — Lower signal. Ambient legal landscape.
    Sources: PACER/Bloomberg dockets, Westlaw practice-area alerts, X lists.
    Why: Useful background noise — worth a quick scan but not worth deep
         triage time. Most Tier 3 items get skipped after review.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIGNAL FLOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Feed Ingestor → WatchSignal (raw detected item)
  →  Triage (Bloodhound agent decides: add to Watch List? what tier?)
  →  WatchList.add_case() (if worth tracking)
  →  Alfred (queries Watch List when asked about a doctrine)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SignalTier(str, Enum):
    """
    Signal importance tier for Bloodhound Watch List entries.

    Using an Enum instead of raw strings means:
      - Typos are caught at import time ("Tier1" instead of "1")
      - All valid tiers are listed in one place
      - The Notion Watch List and the Python code use the same values
    """

    TIER_1 = "1"
    """
    Highest priority. Core KLG practice area. Issues KLG has litigated or that
    are central to the firm's constitutional theory. These entries stay on the
    Watch List permanently — they are seeded from closed-case post-mortems and
    never auto-closed. Example: supersedeas exception doctrine, First Amendment
    overbreadth, public employee speech rights.
    """

    TIER_2 = "2"
    """
    Medium priority. Adjacent doctrine worth ongoing monitoring. Not a current
    KLG matter area but close enough that a circuit split or SCOTUS grant
    would matter to the firm's strategy. Example: qualified immunity trends,
    California CEQA procedure, administrative law chevron aftermath.
    """

    TIER_3 = "3"
    """
    Ambient. Broad legal landscape. Useful context during weekly triage but
    not worth deep analysis. Most Tier 3 items are reviewed and skipped.
    Example: general federal appellate docket news, broad First Amendment
    news not specific to KLG practice areas.
    """


@dataclass
class WatchSignal:
    """
    A single signal detected by Bloodhound's feed ingestor.

    This is the intermediate representation between "we found something in
    a feed" and "we added it to the Notion Watch List." Every detected item
    becomes a WatchSignal; only items that survive triage become Watch List entries.

    WHY A SEPARATE CLASS FROM THE WATCH LIST ROW?
        The Watch List row is the *decided* result (Tim or AI has triaged it and
        assigned a tier). A WatchSignal is the *raw detection* — it might be
        irrelevant, a duplicate of something already on the list, or not specific
        enough to warrant tracking. Having a distinct class makes the pipeline
        stages explicit.

    Attributes:
        title:          The case name, article headline, or filing title as
                        detected in the source feed.
        source_url:     The URL where this signal was found (RSS entry link,
                        CourtListener docket URL, etc.).
        source_name:    Human-readable source name (e.g., "PLF Press Releases",
                        "9th Circuit Opinions Feed", "CourtListener RECAP").
        detected_at:    When Bloodhound found this signal.
        content:        The full text of the RSS entry or relevant excerpt.
                        This is what the triage agent reads to decide tier.
        suggested_tier: Bloodhound's initial tier suggestion (before human review).
                        Can be overridden during triage.
        issue_keywords: Keywords extracted from the content that suggest which
                        KLG issue areas this signal touches.
        court:          Detected court name, if identifiable from the content.
        docket_no:      Detected docket number, if identifiable.
        is_duplicate:   True if this signal matches an existing Watch List entry.
                        Duplicates are logged but not added as new rows.
        extra:          Any additional metadata the specific feed source provides.
    """

    title: str
    source_url: str
    source_name: str
    detected_at: datetime = field(default_factory=datetime.utcnow)
    content: str = ""
    suggested_tier: SignalTier = SignalTier.TIER_3
    issue_keywords: list[str] = field(default_factory=list)
    court: str = ""
    docket_no: str = ""
    is_duplicate: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_triage_prompt(self) -> str:
        """
        Format this signal as a text block for the triage agent to evaluate.

        The triage agent reads this and decides:
          - Is this worth adding to the Watch List? (yes/no)
          - What tier? (1, 2, or 3)
          - What issue areas does it touch?
          - What is the KLG nexus? (why does this matter to the firm specifically?)

        Returns:
            A formatted string prompt ready to include in an AI message.
        """
        return (
            f"SIGNAL FROM: {self.source_name}\n"
            f"DETECTED:    {self.detected_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"TITLE:       {self.title}\n"
            f"URL:         {self.source_url}\n"
            f"COURT:       {self.court or 'Not detected'}\n"
            f"DOCKET:      {self.docket_no or 'Not detected'}\n"
            f"KEYWORDS:    {', '.join(self.issue_keywords) or 'None extracted'}\n"
            f"\nCONTENT:\n{self.content[:2000]}"  # Cap at 2k chars to stay in token budget
            f"{'...[truncated]' if len(self.content) > 2000 else ''}"
        )


# =============================================================================
# FEED SOURCE REGISTRY
# =============================================================================
#
# This registry defines all the RSS/Atom feeds that Bloodhound monitors.
# To add a new source, add a new entry to this list.
#
# Structure: (source_name, feed_url, default_tier)
#   source_name:   Human-readable name shown in Watch List "Source" field
#   feed_url:      RSS/Atom URL to poll
#   default_tier:  Initial tier suggestion for items from this source
#                  (can be overridden by triage)
#
FEED_SOURCES: list[tuple[str, str, SignalTier]] = [
    # ── Tier 1 Sources — Movement Organizations ───────────────────────────────
    # These orgs share KLG's constitutional orientation. Everything they announce
    # is potentially relevant. Start at Tier 1; triage may downgrade to Tier 2.
    (
        "Pacific Legal Foundation (PLF)",
        "https://pacificlegal.org/feed/",
        SignalTier.TIER_1,
    ),
    (
        "Institute for Justice (IJ)",
        "https://ij.org/feed/",
        SignalTier.TIER_1,
    ),
    (
        "FIRE (Foundation for Individual Rights and Expression)",
        "https://www.thefire.org/news/rss.xml",
        SignalTier.TIER_1,
    ),
    (
        "NCLA (New Civil Liberties Alliance)",
        "https://nclalegal.org/feed/",
        SignalTier.TIER_1,
    ),

    # ── Tier 2 Sources — Legal Commentary ─────────────────────────────────────
    # Broad appellate coverage. Not everything is relevant to KLG but the
    # commentary layer helps identify emerging doctrine worth monitoring.
    (
        "The Volokh Conspiracy",
        "https://reason.com/volokh/feed/",
        SignalTier.TIER_2,
    ),
    (
        "SCOTUSblog",
        "https://www.scotusblog.com/feed/",
        SignalTier.TIER_2,
    ),
    (
        "How Appealing",
        "https://howappealing.abovethelaw.com/atom.xml",
        SignalTier.TIER_2,
    ),

    # ── Tier 2 Sources — Court Opinion Feeds ──────────────────────────────────
    # Direct from the courts. High volume — most items are irrelevant —
    # but the Bloodhound triage agent filters for KLG-relevant issue areas.
    (
        "9th Circuit Recent Opinions",
        "https://www.ca9.uscourts.gov/rss/opinions.php",
        SignalTier.TIER_2,
    ),
    # Cal. Ct. App. does not publish a reliable RSS feed as of 2026.
    # CourtListener covers California appellate opinions instead.
]
