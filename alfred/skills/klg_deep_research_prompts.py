"""
alfred/skills/klg_deep_research_prompts.py — Step 1 of the KLG Research Pipeline.

Generates 3–12 tiered deep research prompts from case materials and delivers
them to a Notion research page. The human then runs Comet (or another tool)
to execute the prompts against ChatGPT Deep Research and paste results back.

Pipeline position:
  klg-case-assessment → [klg-deep-research-prompts] → (Comet) → klg-research-compilation
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """You are a senior appellate research attorney at Kowal Law Group (KLG).
Based on the case context below, generate deep research prompts for ChatGPT Deep Research.

CASE CONTEXT:
{context}

JURISDICTION: {jurisdiction}
KEY ISSUES: {key_issues}

Generate {tier_description} research prompts in three tiers:

TIER 1 — CORE (run always, 2–4 prompts):
These are the must-run prompts. Each should be a standalone, self-contained deep research question
that would produce a 2,000–5,000 word memo answering a central legal issue in the case.
Format each as: "Research [specific legal question]... Analyze [specific application]... Provide [specific output]..."

TIER 2 — IMPORTANT (run if time allows, 2–4 prompts):
Important but not critical. Supporting doctrines, procedural issues, or factual background.

TIER 3 — OPTIONAL (background, 1–4 prompts):
Useful context. Secondary issues, comparative law, policy background.

For each prompt:
- Be specific enough that ChatGPT Deep Research can produce a substantive memo without follow-up
- Include the jurisdiction (California appellate, unless otherwise noted)
- Reference the specific procedural posture where relevant
- End with: "Provide citations to case law, statutes, and secondary sources."

Output format:
## TIER 1 — CORE
### Prompt 1: [title]
[full prompt text]

### Prompt 2: [title]
[full prompt text]

## TIER 2 — IMPORTANT
[same format]

## TIER 3 — OPTIONAL
[same format]

## RESEARCH MAP
Brief explanation (3–5 sentences) of how these prompts work together and the recommended run order.
"""


class KLGDeepResearchPrompts(Skill):
    name = "klg-deep-research-prompts"
    description = (
        "Generates 3–12 tiered ChatGPT Deep Research prompts from case materials "
        "and delivers them to a Notion research page for Comet execution."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        from config import settings
        from pydantic_ai import Agent
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        matter_name = ctx.matter_name or ctx.extra.get("matter_name", "Matter")
        jurisdiction = ctx.extra.get("jurisdiction", "California")
        key_issues = ctx.extra.get("key_issues", "")
        tiers = ctx.extra.get("tiers", ["Core", "Important", "Optional"])

        tier_description = _describe_tiers(tiers)

        # Use the matter summary as primary context; supplement with user instruction
        context = ctx.matter_summary or ctx.user_instruction or "No case context provided."
        if ctx.user_instruction and ctx.matter_summary:
            context = f"{ctx.matter_summary}\n\nAdditional instruction: {ctx.user_instruction}"

        # Generate prompts with Claude
        model = AnthropicModel(
            settings.alfred_model,
            provider=AnthropicProvider(api_key=settings.anthropic_api_key),
        )
        agent: Agent[None, str] = Agent(model=model, output_type=str)

        prompt = _PROMPT_TEMPLATE.format(
            context=context[:8000],
            jurisdiction=jurisdiction,
            key_issues=key_issues or "See case context above",
            tier_description=tier_description,
        )

        gen_result = await agent.run(prompt)
        prompts_text = gen_result.output

        # Build the Notion page content
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        notion_title = f"Deep Research Prompts — {matter_name} — {today}"
        page_content = _build_notion_content(
            matter_name=matter_name,
            jurisdiction=jurisdiction,
            tiers=tiers,
            prompts_text=prompts_text,
            today=today,
        )

        # Create Notion research page
        notion_url = await _create_notion_page(
            ctx=ctx,
            title=notion_title,
            content=page_content,
        )

        next_steps = (
            f"Research prompts created at: {notion_url}\n\n"
            "Next steps:\n"
            "1. Review the prompts and select which tiers to run\n"
            "2. Open the Notion page and copy prompts to ChatGPT Deep Research (or run via Comet)\n"
            "3. Paste completed memos back into the Notion page under each prompt's heading\n"
            "4. When all selected prompts are complete, run klg-research-compilation to "
            "compile the memos into a single research memorandum"
        )

        return SkillResult(
            summary=(
                f"Generated deep research prompts for {matter_name}. "
                f"Tiers selected: {', '.join(tiers)}. Notion page: {notion_url}"
            ),
            output=(
                f"**Deep Research Prompts — {matter_name}**\n\n"
                f"{prompts_text}\n\n"
                f"---\n{next_steps}"
            ),
            next_action=next_steps,
            success=True,
        )


def _describe_tiers(tiers: list[str]) -> str:
    count_map = {"Core": "2–4", "Important": "2–4", "Optional": "1–4"}
    parts = [f"{count_map.get(t, '2–4')} {t}" for t in tiers]
    total = f"{2 * len(tiers)}–{4 * len(tiers)}"
    return f"{total} total"


def _build_notion_content(
    matter_name: str,
    jurisdiction: str,
    tiers: list[str],
    prompts_text: str,
    today: str,
) -> str:
    header = (
        f"# Deep Research Prompts — {matter_name}\n\n"
        f"**Date:** {today}  \n"
        f"**Jurisdiction:** {jurisdiction}  \n"
        f"**Tiers selected:** {', '.join(tiers)}\n\n"
        "---\n\n"
        "## How to Use This Page\n\n"
        "1. Copy each prompt below into ChatGPT Deep Research (or run via Comet)\n"
        "2. Paste the completed memo under the heading **Results — [Prompt Title]** "
        "directly below the prompt\n"
        "3. When all selected prompts have results, run `klg-research-compilation` "
        "to compile them into a single research memorandum\n\n"
        "---\n\n"
    )
    return header + prompts_text


async def _create_notion_page(ctx: SkillContext, title: str, content: str) -> str:
    """Create a research page in Notion. Returns the page URL."""
    from config import settings

    if not ctx.matter_id:
        logger.warning("klg-deep-research-prompts: no matter_id — cannot link page to matter")

    try:
        # Build blocks from markdown content
        blocks = _markdown_to_blocks(content)

        properties: dict[str, Any] = {
            "Name": {"title": [{"text": {"content": title}}]},
        }

        # Link to matter project page if available
        if ctx.matter_id:
            properties["Projects"] = {"relation": [{"id": ctx.matter_id}]}

        from notion_bridge.client import NotionBridge
        from config import settings as _settings

        bridge = NotionBridge()
        db_id = _settings.notion_projects_db_id

        if not db_id:
            return "(Notion DB not configured — prompts returned in chat only)"

        page = await bridge.create_page(
            database_id=db_id,
            properties=properties,
            children=blocks[:100],
        )
        page_id = page.get("id", "")
        if page_id:
            clean_id = page_id.replace("-", "")
            return f"https://www.notion.so/{clean_id}"
        return "(page created but URL unavailable)"

    except Exception as e:
        logger.error("klg-deep-research-prompts: Notion create failed: %s", e)
        return f"(Notion error: {e} — prompts returned in chat only)"


def _markdown_to_blocks(text: str) -> list[dict]:
    """Convert simple markdown to Notion API block objects."""
    blocks = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            blocks.append(_heading(stripped[4:], 3))
        elif stripped.startswith("## "):
            blocks.append(_heading(stripped[3:], 2))
        elif stripped.startswith("# "):
            blocks.append(_heading(stripped[2:], 1))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append(_bullet(stripped[2:]))
        elif stripped.startswith("1. ") or (len(stripped) > 3 and stripped[0].isdigit() and stripped[1] == "."):
            content = stripped.split(". ", 1)[-1]
            blocks.append(_bullet(content))
        elif stripped == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        else:
            blocks.append(_paragraph(stripped))
    return blocks


def _heading(text: str, level: int = 2) -> dict:
    t = {1: "heading_1", 2: "heading_2", 3: "heading_3"}.get(level, "heading_2")
    return {"object": "block", "type": t, t: {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}}


def _paragraph(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}}


def _bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text[:2000]}}]}}
