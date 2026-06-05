"""
bloodhound — The outward-facing KLG research and surveillance engine.

Bloodhound tracks the legal landscape: cases, doctrines, movement organizations,
and thought leaders. It feeds intelligence to Alfred so that KLG always knows
what's happening in areas the firm cares about.

Named for the bloodhound: follows scent, relentless, single-minded. Two syllables,
no baggage, functionally accurate.

Modules:
  signals.py       — Signal tier definitions and the WatchSignal data model.
  feed_ingestor.py — RSS + CourtListener feed parsing; creates Watch List entries.
  agent.py         — Pydantic AI agent for signal triage and analysis.
"""

from bloodhound.signals import WatchSignal, SignalTier
from bloodhound.agent import BloodhoundTriageAgent, TriageDecision

__all__ = ["WatchSignal", "SignalTier", "BloodhoundTriageAgent", "TriageDecision"]
