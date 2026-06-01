"""
alfred — The inward-facing KLG executive assistant.

Alfred is Layer 2 of the KLG AI OS. The team talks to Alfred; Alfred
talks to Notion, Slack, and SharePoint on the team's behalf.

Named for Alfred Pennyworth: brilliant, devoted, runs the household and the
technology, knows where everything is, indispensable support to the lead.

Modules:
  agent.py       — Pydantic AI agent definition with all of Alfred's tools.
  skill_runner.py — Executes the 5-step skill lifecycle against a matter.
  skills/        — Individual skill implementations (brief, intake, etc.)
"""

from alfred.agent import AlfredAgent, AlfredDependencies

__all__ = ["AlfredAgent", "AlfredDependencies"]
