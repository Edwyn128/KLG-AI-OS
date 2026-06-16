"""
alfred/skills/klg_podcast_guest_prep.py — CALP podcast guest discovery and interview prep.

Two modes:
  Phase 0 (discovery): Finds potential podcast guests by topic or landscape scan.
  Prep mode: Builds a full interview package for a confirmed guest — profile,
             architecture, style-calibrated questions, optional NotebookLM prompts,
             and a recording-day briefing packet — delivered as a Notion page.

Hosts: Tim Kowal and Jeff Lewis.
Target audience: California trial and appellate attorneys.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_DISCOVERY_PROMPT = """You are a podcast booking researcher for CALP (California Appellate Law Podcast).
Hosts: Tim Kowal and Jeff Lewis, California appellate attorneys.
Target audience: California trial and appellate attorneys.
Focus: California appellate practice, constitutional law, civil procedure, first amendment,
public employee rights, property rights.

{task}

For each candidate, provide:
1. Full name and current affiliation/position
2. Why they'd make a compelling guest (specific expertise, recent work, distinctive perspective)
3. 2–3 suggested episode angles
4. Estimated audience appeal (practitioner relevance)
5. How to reach them (LinkedIn, law school faculty page, firm website — public info only)

Format as a numbered shortlist. Be specific — "leading scholar on California public employee
speech rights" is useful; "interesting attorney" is not.
"""

_PREP_PROMPT = """You are preparing Tim Kowal and Jeff Lewis for a CALP interview.

GUEST PROFILE:
{guest_info}

RESEARCH GATHERED:
{research}

STYLE CALIBRATION:
{style_notes}

Produce a complete interview prep package in the following structure:

## GUEST PROFILE
[2–3 paragraph bio synthesizing background, expertise, recent work, notable positions]

## WHY THIS MATTERS TO CALP LISTENERS
[1 paragraph — specific relevance to California trial and appellate practitioners]

## INTERVIEW ARCHITECTURE
[3–4 proposed segments with time estimates, from opening context to deeper analysis to practitioner takeaways]

## OPENING QUESTIONS (warm-up, 2–3)
[Questions that let the guest introduce their perspective naturally]

## CORE QUESTIONS (substantive, 6–8)
[The questions that will produce the most valuable content for practitioners.
Calibrated to the guest's style — see style notes.]

## DEEP-DIVE QUESTIONS (if time allows, 3–4)
[More technical or nuanced questions for guests who are comfortable going deep]

## PRACTITIONER TAKEAWAYS
[3–5 bullet points: what a California trial or appellate attorney should take away from this episode]

## POTENTIAL LANDMINES
[Issues to handle carefully — pending cases, controversial positions, anything that
could create friction. Not a reason to avoid topics, but worth flagging for the hosts.]

## RECORDING DAY BRIEFING (2-minute read)
[Ultra-condensed briefing card: who they are, why today, 3 key things to draw out,
1 thing to watch for. Written for a host who hasn't had time to read anything else.]
"""

_STYLE_NOTES = {
    "academic": (
        "This guest is an academic. Questions should be conceptual and theoretical. "
        "Allow time for nuanced answers. Avoid interrupting complex explanations. "
        "Ask about 'tensions' and 'frameworks' rather than 'wins and losses'."
    ),
    "practitioner": (
        "This guest is a practicing attorney. Questions should be practical and case-grounded. "
        "Ask about specific decisions they've made, strategies that worked or failed, "
        "and advice for other practitioners. Concrete over theoretical."
    ),
    "judge": (
        "This guest is a judge (or former judge). Questions should be respectful of "
        "judicial independence and avoid asking about pending matters. Focus on "
        "appellate craft, brief writing, oral argument, and systemic observations. "
        "Avoid asking them to critique specific decisions."
    ),
    "default": (
        "Calibrate questions to the guest's background. Mix conceptual and practical angles. "
        "Lead with accessible questions that establish context for listeners."
    ),
}


class KLGPodcastGuestPrep(Skill):
    name = "klg-podcast-guest-prep"
    description = (
        "Discovers CALP podcast guests by topic (Phase 0) or builds a full interview "
        "prep package for a confirmed guest, delivered as a Notion page."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        extra = ctx.extra or {}
        mode = extra.get("mode", "prep")  # "discovery" or "prep"

        if mode == "discovery":
            return await self._run_discovery(ctx, extra)
        return await self._run_prep(ctx, extra)

    # ── Phase 0: Guest Discovery ───────────────────────────────────────────────

    async def _run_discovery(self, ctx: SkillContext, extra: dict) -> SkillResult:
        topic = extra.get("topic", "California appellate practice")
        scan_type = extra.get("scan_type", "topic")  # "topic" or "landscape"

        if scan_type == "landscape":
            task = (
                "Do a landscape scan of the California appellate law space. "
                "Identify 8–10 compelling potential guests across different backgrounds "
                "(academics, practitioners, judges, advocates) who would resonate with "
                "California trial and appellate attorneys. Focus on people with recent, "
                "distinctive, or underrepresented perspectives."
            )
        else:
            task = (
                f"Find 5–8 compelling podcast guests who specialize in or have done "
                f"notable work on: {topic}\n"
                "Focus on practitioners, scholars, or advocates with distinctive perspectives "
                "that would resonate with California trial and appellate attorneys."
            )

        result_text = await self._generate(
            _DISCOVERY_PROMPT.format(task=task)
        )

        return SkillResult(
            summary=f"Guest discovery complete. Topic: {topic}. Mode: {scan_type}.",
            output=(
                f"**CALP Guest Discovery — {topic}**\n\n"
                f"{result_text}\n\n"
                "---\n"
                "To build a full interview prep package for any of these guests, "
                "say: 'Alfred, run klg-podcast-guest-prep for [Guest Name]'"
            ),
            next_action=(
                "Review the shortlist and select a guest. "
                "Then run klg-podcast-guest-prep in prep mode with the guest's name."
            ),
            success=True,
        )

    # ── Prep Mode: Full Interview Package ────────────────────────────────────

    async def _run_prep(self, ctx: SkillContext, extra: dict) -> SkillResult:
        guest_name = extra.get("guest_name", "")
        guest_affiliation = extra.get("guest_affiliation", "")
        guest_style = extra.get("guest_style", "default")

        if not guest_name:
            return SkillResult(
                summary="klg-podcast-guest-prep: guest name required.",
                output=(
                    "To prepare for an interview, I need:\n\n"
                    "- **Guest name** (required)\n"
                    "- **Affiliation** (law firm, law school, court, etc.)\n"
                    "- **Style** (optional): 'academic', 'practitioner', or 'judge'\n\n"
                    "Example: 'Alfred, run klg-podcast-guest-prep for Jane Smith, "
                    "UCLA Law professor, academic style'"
                ),
                next_action="Provide the guest name and affiliation.",
                success=False,
            )

        # Gather research from Notion (check if we already have notes on this guest)
        research = await self._gather_research(ctx, guest_name)
        style_notes = _STYLE_NOTES.get(guest_style.lower(), _STYLE_NOTES["default"])

        guest_info = f"Name: {guest_name}"
        if guest_affiliation:
            guest_info += f"\nAffiliation: {guest_affiliation}"
        if extra.get("episode_angle"):
            guest_info += f"\nProposed episode angle: {extra['episode_angle']}"

        result_text = await self._generate(
            _PREP_PROMPT.format(
                guest_info=guest_info,
                research=research or "No prior research in Notion. Generate from public information.",
                style_notes=style_notes,
            )
        )

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        notion_title = f"CALP Interview Prep — {guest_name} — {today}"
        notion_url = await self._create_notion_page(ctx, notion_title, result_text)

        return SkillResult(
            summary=(
                f"Interview prep package created for {guest_name}. "
                f"Notion page: {notion_url}"
            ),
            output=(
                f"**CALP Interview Prep — {guest_name}**\n\n"
                f"{result_text}\n\n"
                f"---\nNotion page: {notion_url}"
            ),
            next_action=(
                f"Review the prep package at {notion_url}. "
                "Share with Tim and Jeff at least 48 hours before recording."
            ),
            success=True,
        )

    async def _generate(self, prompt: str) -> str:
        from config import settings
        from pydantic_ai import Agent
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        model = AnthropicModel(
            settings.alfred_model,
            provider=AnthropicProvider(api_key=settings.anthropic_api_key),
        )
        agent: Agent[None, str] = Agent(model=model, output_type=str)
        result = await agent.run(prompt)
        return result.output

    async def _gather_research(self, ctx: SkillContext, guest_name: str) -> str:
        """Search Notion for any existing research on this guest."""
        try:
            # SkillContext doesn't directly carry the bridge, but we can instantiate
            from notion_bridge.client import NotionBridge
            bridge = NotionBridge()
            results = await bridge.search(guest_name)
            if not results:
                return ""
            snippets = []
            for r in results[:3]:
                title = r.get("title") or r.get("Project name", "")
                snippet = r.get("snippet", "")
                if title:
                    snippets.append(f"Notion page: {title}\n{snippet}")
            return "\n\n".join(snippets) if snippets else ""
        except Exception as e:
            logger.debug("klg-podcast-guest-prep: Notion research lookup failed: %s", e)
            return ""

    async def _create_notion_page(self, ctx: SkillContext, title: str, content: str) -> str:
        """Create the interview prep page in Notion."""
        try:
            from notion_bridge.client import NotionBridge
            from config import settings

            bridge = NotionBridge()
            db_id = settings.notion_projects_db_id
            if not db_id:
                return "(Notion not configured)"

            blocks = _text_to_blocks(content)
            properties: dict[str, Any] = {
                "Name": {"title": [{"text": {"content": title}}]},
            }

            page = await bridge.create_page(
                database_id=db_id,
                properties=properties,
                children=blocks[:100],
            )
            page_id = page.get("id", "")
            if page_id:
                return f"https://www.notion.so/{page_id.replace('-', '')}"
            return "(created — URL unavailable)"
        except Exception as e:
            logger.error("klg-podcast-guest-prep: Notion create failed: %s", e)
            return f"(Notion error: {e})"


def _text_to_blocks(text: str) -> list[dict]:
    blocks = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            continue
        if s.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                           "heading_2": {"rich_text": [{"type": "text", "text": {"content": s[3:2000]}}]}})
        elif s.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3",
                           "heading_3": {"rich_text": [{"type": "text", "text": {"content": s[4:2000]}}]}})
        elif s.startswith("- ") or s.startswith("* "):
            blocks.append({"object": "block", "type": "bulleted_list_item",
                           "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": s[2:2000]}}]}})
        elif s == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [{"type": "text", "text": {"content": s[:2000]}}]}})
    return blocks
