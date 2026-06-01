"""
bloodhound/feed_ingestor.py — RSS + CourtListener feed parsing for Bloodhound.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This module fetches and parses external signal sources for Bloodhound.
It turns raw RSS entries and CourtListener API responses into WatchSignal
objects, which the triage agent then evaluates to decide what's worth tracking.

SIGNAL PIPELINE:
  FeedIngestor.run_daily_scan()
    → fetch_all_feeds()        [RSS parsing — fast, returns many signals]
    → fetch_courtlistener()    [CourtListener REST API — targeted keyword search]
    → deduplicate()            [mark signals already on the Watch List]
    → return list[WatchSignal] [passed to triage agent for tier assignment]

CADENCES (from the Bloodhound architecture doc):
  Daily lightweight scan  — ~5 minutes, no triage commitment.
                            Fetches feeds, skips already-seen items.
                            Most days yield nothing new.
  Weekly deep review      — ~30 minutes, structured triage.
                            All new signals triaged; tier assignments made;
                            existing Watch List entries get status updates.

This module handles both cadences — the daily scan fetches, the weekly
review uses the same fetch results but feeds them through deeper triage.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SEEN ITEMS CACHE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

We keep a simple in-memory set of seen feed entry URLs to avoid reporting
the same RSS item on every daily scan. On restart, the cache is empty and
we may briefly re-report items from the last day or two — this is acceptable.

For production resilience, this could be persisted to a file or a Notion page.
That is a future improvement. The current design is simple and correct for the
daily scan cadence where the app runs continuously.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from bloodhound.signals import FEED_SOURCES, SignalTier, WatchSignal
from config import settings

logger = logging.getLogger(__name__)

# Keywords that suggest a signal is relevant to KLG's practice areas.
# These are used to pre-filter Tier 2/3 feeds before sending to the triage agent.
# A signal matching at least one keyword gets flagged for triage; others are skipped.
# Keep this list updated as the firm's practice areas evolve.
KLG_RELEVANCE_KEYWORDS: list[str] = [
    # Constitutional rights
    "first amendment", "free speech", "free exercise", "establishment clause",
    "second amendment", "fourth amendment", "fifth amendment", "fourteenth amendment",
    # Public law / government
    "public employee", "government employee", "civil servant", "whistleblower",
    "qualified immunity", "section 1983", "monell",
    # Property rights
    "takings", "eminent domain", "land use", "zoning", "regulatory taking",
    "property rights", "CEQA",
    # Appellate procedure
    "supersedeas", "preliminary injunction", "stay", "cert petition",
    "en banc", "circuit split", "SCOTUS",
    # California courts
    "california court of appeal", "california supreme court", "ninth circuit",
    "9th circuit", "cal. app.", "cal. ct. app.",
    # Movement organizations KLG tracks
    "pacific legal", "institute for justice", "FIRE", "NCLA", "cato",
    "federalist society",
]


class FeedIngestor:
    """
    Fetches and parses external signal sources for Bloodhound.

    Instantiate once and reuse — the httpx.AsyncClient maintains a connection
    pool, so creating one per scan would be wasteful.

    Args:
        watch_list_urls: Set of URLs already on the Watch List.
                         Used to mark signals as duplicates before returning.
                         Call WatchList.get_active_cases() and extract URLs
                         to build this set before running a scan.
    """

    def __init__(self, known_urls: set[str] | None = None) -> None:
        """
        Args:
            known_urls: URLs already on the Watch List. Signals with matching
                        source_url will be marked is_duplicate=True.
                        Pass an empty set if you want all signals regardless.
        """
        self._known_urls: set[str] = known_urls or set()
        self._seen_this_run: set[str] = set()  # URLs fetched in this scan
        # Shared async HTTP client — reused across all feed fetches in one scan
        self._http = httpx.AsyncClient(
            timeout=30.0,  # 30-second timeout per feed fetch
            follow_redirects=True,
            headers={
                "User-Agent": "KLG-Bloodhound/1.0 (legal research surveillance; contact edwyn@kowallawgroup.com)"
            },
        )

    async def close(self) -> None:
        """Release the HTTP client connection pool. Call when done scanning."""
        await self._http.aclose()

    async def run_daily_scan(self) -> list[WatchSignal]:
        """
        Run a daily lightweight signal scan across all configured feed sources.

        This is the primary entry point for the daily cron job. It:
          1. Fetches all RSS/Atom feeds in FEED_SOURCES
          2. Fetches CourtListener alerts for KLG keyword list
          3. Deduplicates against known Watch List URLs
          4. Filters Tier 2/3 items by KLG keyword relevance
          5. Returns only new, potentially relevant signals

        The daily scan is intentionally lightweight — it fetches feeds fast
        and returns raw signals without running them through the triage agent.
        Triage happens separately (weekly deep review) to control AI API costs.

        Returns:
            List of new WatchSignal objects detected since last scan.
            Empty list means nothing new today — a normal, expected result.
        """
        logger.info("Bloodhound daily scan starting...")
        all_signals: list[WatchSignal] = []

        # Fetch all configured RSS feeds
        rss_signals = await self.fetch_all_feeds()
        all_signals.extend(rss_signals)

        # Fetch CourtListener keyword alerts
        court_signals = await self.fetch_courtlistener_alerts()
        all_signals.extend(court_signals)

        # Mark duplicates
        for sig in all_signals:
            if sig.source_url in self._known_urls:
                sig.is_duplicate = True

        # Filter out duplicates for the return value
        new_signals = [s for s in all_signals if not s.is_duplicate]

        logger.info(
            "Bloodhound daily scan complete: %d total signals fetched, "
            "%d new (non-duplicate).",
            len(all_signals),
            len(new_signals),
        )
        return new_signals

    async def fetch_all_feeds(self) -> list[WatchSignal]:
        """
        Fetch and parse all RSS/Atom feeds in the FEED_SOURCES registry.

        Fetches all feeds concurrently using asyncio.gather() to minimize
        total scan time. A slow or unresponsive feed does not block the others.

        Returns:
            List of WatchSignal objects from all feed entries, filtered by
            KLG keyword relevance for Tier 2/3 sources.
        """
        import asyncio

        tasks = [
            self._fetch_single_feed(name, url, default_tier)
            for name, url, default_tier in FEED_SOURCES
        ]

        # gather() runs all tasks concurrently; return_exceptions=True means
        # a failed feed fetch returns an Exception object instead of crashing
        # the whole scan — one bad feed should not kill the daily run.
        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals: list[WatchSignal] = []
        for i, result in enumerate(results):
            source_name = FEED_SOURCES[i][0]
            if isinstance(result, Exception):
                logger.warning(
                    "Feed fetch failed for '%s': %s", source_name, result
                )
                continue
            signals.extend(result)

        return signals

    async def _fetch_single_feed(
        self,
        source_name: str,
        feed_url: str,
        default_tier: SignalTier,
    ) -> list[WatchSignal]:
        """
        Fetch and parse a single RSS/Atom feed.

        Uses feedparser (which handles both RSS 1.0/2.0 and Atom formats)
        to parse the feed after fetching the raw content with httpx.

        WHY httpx + feedparser instead of feedparser alone?
            feedparser has its own HTTP fetching, but it's synchronous —
            it would block the event loop. We use httpx (async) to fetch,
            then pass the content string to feedparser (which can parse
            pre-fetched content without making its own HTTP request).

        Args:
            source_name:  Human-readable name for logging and Watch List "Source" field.
            feed_url:     RSS/Atom URL to fetch.
            default_tier: Starting tier for signals from this source.

        Returns:
            List of WatchSignal objects parsed from the feed entries.
        """
        try:
            response = await self._http.get(feed_url)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("Could not fetch feed '%s' (%s): %s", source_name, feed_url, e)
            return []

        # feedparser.parse() accepts either a URL string or raw content.
        # We pass the raw text content so feedparser doesn't make another HTTP call.
        feed = feedparser.parse(response.text)

        signals: list[WatchSignal] = []
        for entry in feed.entries:
            url = entry.get("link", "")

            # Skip entries we've already processed in this scan session
            if url in self._seen_this_run:
                continue
            self._seen_this_run.add(url)

            title = entry.get("title", "Untitled")
            content = (
                entry.get("summary", "")
                or entry.get("content", [{}])[0].get("value", "")
                or ""
            )

            # For Tier 1 sources (movement orgs), include everything — they
            # are pre-filtered by being KLG-relevant organizations.
            # For Tier 2/3 sources (broad feeds), require keyword match.
            if default_tier != SignalTier.TIER_1:
                if not self._has_klg_keywords(title + " " + content):
                    continue  # Skip irrelevant entries from broad feeds

            # Extract detected court and docket info (best-effort)
            court = self._extract_court(title + " " + content)
            keywords_found = self._extract_keywords(title + " " + content)

            # Parse the publication date — feedparser normalizes this to a
            # time.struct_time, which we convert to datetime
            published_raw = entry.get("published_parsed")
            if published_raw:
                try:
                    detected_at = datetime(*published_raw[:6], tzinfo=timezone.utc)
                except (TypeError, ValueError):
                    detected_at = datetime.now(timezone.utc)
            else:
                detected_at = datetime.now(timezone.utc)

            signal = WatchSignal(
                title=title,
                source_url=url,
                source_name=source_name,
                detected_at=detected_at,
                content=content,
                suggested_tier=default_tier,
                issue_keywords=keywords_found,
                court=court,
            )
            signals.append(signal)

        logger.debug(
            "Feed '%s': %d entries fetched, %d signals extracted.",
            source_name,
            len(feed.entries),
            len(signals),
        )
        return signals

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def fetch_courtlistener_alerts(self) -> list[WatchSignal]:
        """
        Fetch new case alerts from CourtListener's REST API.

        CourtListener (courtlistener.com) provides free access to PACER data
        for federal courts via a REST API. We use it to search for cases
        matching KLG-relevant keywords — catching filings that aren't announced
        by the movement org press release layer.

        CourtListener API docs: https://www.courtlistener.com/api/rest/v4/

        RATE LIMITS: CourtListener allows 5,000 requests/day for free accounts.
        The daily scan hits this endpoint once, returning up to 20 recent results.
        This is well within limits.

        Returns:
            List of WatchSignal objects from CourtListener results.
            Empty list if the API is unavailable or returns no new results.
        """
        # Search for recent opinions mentioning core KLG keywords
        # We search for the most specific and high-value terms first
        search_queries = [
            "supersedeas California",
            "First Amendment public employee speech",
            "regulatory taking California",
        ]

        signals: list[WatchSignal] = []

        for query in search_queries:
            try:
                response = await self._http.get(
                    "https://www.courtlistener.com/api/rest/v4/search/",
                    params={
                        "q": query,
                        "type": "o",           # opinions only (not dockets/filings)
                        "order_by": "score desc",
                        "filed_after": self._days_ago(7),  # last 7 days only
                        "court": "ca9,cacd,cand,casd,caed",  # 9th Circuit + CA districts
                    },
                    headers={
                        # CourtListener prefers authenticated requests but allows
                        # anonymous for low-volume use. Add your token here if you
                        # create a free account at courtlistener.com.
                        # "Authorization": f"Token {settings.courtlistener_token}",
                    },
                )
                response.raise_for_status()
                data = response.json()

                for result in data.get("results", [])[:5]:  # Max 5 per query
                    url = result.get("absolute_url", "")
                    if url:
                        url = f"https://www.courtlistener.com{url}"

                    signal = WatchSignal(
                        title=result.get("caseName", result.get("case_name", "Unknown Case")),
                        source_url=url,
                        source_name="CourtListener RECAP",
                        content=result.get("snippet", "")
                                or result.get("text", "")[:500],
                        suggested_tier=SignalTier.TIER_1,  # Targeted keyword search → start at Tier 1
                        court=result.get("court", ""),
                        docket_no=result.get("docket_number", ""),
                        issue_keywords=self._extract_keywords(
                            result.get("caseName", "") + " " + result.get("snippet", "")
                        ),
                    )
                    signals.append(signal)

            except httpx.HTTPError as e:
                logger.warning(
                    "CourtListener fetch failed for query '%s': %s", query, e
                )

        logger.info("CourtListener scan returned %d signals.", len(signals))
        return signals

    # ─────────────────────────────────────────────────────────────────────────
    # HELPER METHODS
    # ─────────────────────────────────────────────────────────────────────────

    def _has_klg_keywords(self, text: str) -> bool:
        """
        Return True if the text contains at least one KLG-relevant keyword.

        Used to filter Tier 2/3 feed entries — if a 9th Circuit opinion doesn't
        mention any of our practice area keywords, it's almost certainly not
        relevant to KLG and we skip it.

        Args:
            text: The concatenated title + content of a feed entry.

        Returns:
            True if any KLG_RELEVANCE_KEYWORDS keyword appears in the text
            (case-insensitive). False if none match.
        """
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in KLG_RELEVANCE_KEYWORDS)

    def _extract_keywords(self, text: str) -> list[str]:
        """
        Extract all KLG-relevant keywords found in the text.

        Returns a deduplicated list of keywords from KLG_RELEVANCE_KEYWORDS
        that appear in the text. Used to populate WatchSignal.issue_keywords,
        which helps the triage agent quickly understand what practice areas
        a signal touches without reading the full content.

        Args:
            text: The text to search.

        Returns:
            List of matched keywords (strings), deduplicated, preserving order
            of first occurrence.
        """
        text_lower = text.lower()
        found: list[str] = []
        seen: set[str] = set()
        for keyword in KLG_RELEVANCE_KEYWORDS:
            if keyword in text_lower and keyword not in seen:
                found.append(keyword)
                seen.add(keyword)
        return found

    def _extract_court(self, text: str) -> str:
        """
        Best-effort extraction of a court name from text.

        Looks for common court name patterns in the text. Returns the first
        match found, or empty string if no court is detected.

        This is intentionally simple — the triage agent can do better analysis
        of the full content. This is just to pre-populate the court field for
        the WatchSignal before triage.

        Args:
            text: The feed entry title + content.

        Returns:
            Detected court name string, or empty string.
        """
        court_patterns = {
            "9th Cir.": ["ninth circuit", "9th circuit", "9th cir."],
            "SCOTUS": ["supreme court of the united states", "scotus"],
            "Cal. Ct. App.": [
                "california court of appeal",
                "cal. ct. app.",
                "cal.app.",
            ],
            "Cal. S. Ct.": [
                "california supreme court",
                "cal. s. ct.",
            ],
            "N.D. Cal.": ["northern district of california", "n.d. cal."],
            "C.D. Cal.": ["central district of california", "c.d. cal."],
            "E.D. Cal.": ["eastern district of california", "e.d. cal."],
            "S.D. Cal.": ["southern district of california", "s.d. cal."],
        }

        text_lower = text.lower()
        for court_name, patterns in court_patterns.items():
            if any(p in text_lower for p in patterns):
                return court_name

        return ""

    def _days_ago(self, n: int) -> str:
        """
        Return an ISO 8601 date string N days ago from today.

        Used in CourtListener API queries to limit results to recent filings.
        Example: _days_ago(7) → "2026-05-04" (if today is 2026-05-11)
        """
        from datetime import date, timedelta
        return (date.today() - timedelta(days=n)).isoformat()
