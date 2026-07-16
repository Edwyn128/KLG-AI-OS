"""
alfred/skills/base.py — Base class and result type for all KLG skills.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This file defines the Skill base class that every KLG skill inherits from.
It enforces the 5-step lifecycle pattern at the code level — every skill
MUST implement `execute()`, and `execute()` MUST return a SkillResult.

WHY A BASE CLASS?
  Without a base class, each skill is a standalone script with its own
  calling convention. With a base class:
    - The SkillRunner can call any skill the same way (skill.execute(context))
    - Skills are automatically registered and discoverable
    - The audit trail (Step 4: log to Notion) happens in the base class,
      so individual skills don't have to remember to do it
    - Adding firm-wide behavior (e.g., Slack notification on completion)
      requires changing the base class, not every individual skill

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE 5-STEP LIFECYCLE (how it maps to this base class)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Step 1 — Locate the project page   →  run() calls find_matter()
  Step 2 — Read context              →  run() calls get_matter_summary()
  Step 3 — Do the work               →  run() calls execute() [subclass implements this]
  Step 4 — Update Layer 1            →  run() calls log_skill_action() after execute()
  Step 5 — Tee up what's next        →  SkillResult.next_action field

SUBCLASSES ONLY IMPLEMENT STEP 3. The base class handles Steps 1, 2, 4, and
the Step 5 surface (via SkillResult). This keeps individual skills focused on
their specific domain logic.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillContext:
    """
    All the context a skill needs to do its work.

    This is assembled by the SkillRunner (alfred/skill_runner.py) before
    calling execute(). The skill receives a fully populated context — it
    does not need to query Notion itself for the matter it's working on.

    Attributes:
        matter_id:      Notion page ID of the matter project page.
        matter_name:    Human-readable matter name (e.g., "Petersen").
        matter_summary: Full text summary of the matter's current state
                        (properties + body content, as returned by
                        ProjectPages.get_matter_summary()).
        matter_props:   Raw flat dict of all matter properties (for skills
                        that need specific structured values like Target Date).
        user_instruction: The specific instruction the user gave when
                          invoking the skill. Example: "Draft the cover page
                          for the respondent's brief."
        extra:          Any additional parameters the skill runner passes in.
                        Skills can define what goes here in their own docstrings.
    """

    matter_id: str
    matter_name: str
    matter_summary: str
    matter_props: dict[str, Any]
    user_instruction: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    """
    The output a skill returns after completing Step 3 (Do the work).

    The SkillRunner uses this to:
      - Log the summary to the matter page (Step 4)
      - Surface the next_action to the user (Step 5)
      - Return the full output to Alfred for presentation

    Attributes:
        summary:        One-to-two sentence description of what the skill did.
                        This is what gets logged to the Notion project page
                        (the audit trail entry). Be specific and past-tense:
                        "Drafted respondent's brief cover page (3 paragraphs).
                        Saved to SharePoint /Petersen/Briefs/."
        output:         The full output of the skill — a drafted document,
                        a research summary, a structured list, etc. This is
                        what gets presented to the user or pasted into Notion.
        next_action:    Step 5 of the lifecycle: what should happen next?
                        This is the skill's recommendation for the team.
                        Example: "Review draft cover page and confirm before
                        proceeding to Section I."
        notion_updates: Optional dict of property updates to write back to
                        the matter's project page (passed to NotionBridge.update_page).
                        Only include if the skill changes structured properties.
                        Example: {"Status": {"select": {"name": "Review needed"}}}
        success:        Whether the skill completed successfully. Set to False
                        and explain in summary if something went wrong.
    """

    summary: str
    output: str
    next_action: str = ""
    notion_updates: dict[str, Any] = field(default_factory=dict)
    file_attachments: list[dict] = field(default_factory=list)
    """
    Files produced by this skill, returned as download links in the chat UI.
    Each entry: {"filename": "Brief.docx", "content_b64": "<base64>",
                 "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    """
    success: bool = True


class Skill(ABC):
    """
    Abstract base class for all KLG skills.

    Every skill in alfred/skills/ inherits from this class and implements
    the execute() method. The run() method on this base class orchestrates
    the 5-step lifecycle around whatever execute() returns.

    SUBCLASS EXAMPLE:

        class BriefElevation(Skill):
            name = "klg-brief-elevation"
            description = "Elevate a respondent's brief from draft to filing-ready."

            async def execute(self, ctx: SkillContext) -> SkillResult:
                # Step 3: Do the work — draft, analyze, compose
                draft = await alfred_agent.run(
                    f"Based on this matter context, draft a brief introduction:\\n{ctx.matter_summary}",
                    ...
                )
                return SkillResult(
                    summary="Drafted brief introduction section.",
                    output=draft.data,
                    next_action="Review draft and confirm before proceeding to argument section.",
                    notion_updates={"Status": {"select": {"name": "Review needed"}}},
                )
    """

    name: str = "klg-unnamed-skill"
    """
    The canonical skill name. Used in Notion audit trail logs and in the
    skill registry. Must start with "klg-". Override in every subclass.
    """

    description: str = "No description provided."
    """
    One-sentence description of what this skill does.
    Shown in the web UI's skill picker.
    """

    long_running: bool = False
    """
    Set to True for skills that take longer than Railway's ~100s proxy timeout.
    When True, run_skill dispatches this skill as a background job and returns
    a job_id immediately. The caller polls GET /alfred/jobs/{job_id} for the result.
    Skills that produce large documents (novella, record-digest) should set this.
    """

    required_tools: list[str] = []
    """
    Tool names this skill may call during AI execution.
    Must be a subset of the keys in SKILL_TOOLS (alfred/agent.py).
    Scoped to least privilege — only list tools the skill actually needs.
    run_skill is never a valid entry (no recursive invocation).
    Skills that don't override this get a plain toolless completion (original behavior).
    """

    async def generate(self, prompt: str, ctx: SkillContext) -> str:
        """
        Run an AI completion with this skill's scoped tool access.

        Call this instead of skill_generate(prompt) when the skill needs to
        make tool calls during execution (web search, Notion lookup, etc.).
        Tools are scoped to self.required_tools — the ephemeral agent only sees
        the tools declared on this skill class.

        Falls back to a plain toolless completion if required_tools is empty
        or deps are not available (preserves backward compatibility).
        """
        deps = ctx.extra.get("deps")
        if deps is not None and self.required_tools:
            return await skill_generate(prompt, deps=deps, allowed_tools=self.required_tools)
        return await skill_generate(prompt)

    @abstractmethod
    async def execute(self, ctx: SkillContext) -> SkillResult:
        """
        STEP 3 of the skill lifecycle: Do the work.

        This is the only method subclasses must implement. The base class
        handles Steps 1, 2, 4, and 5 via run().

        Implementations should:
          - Use ctx.matter_summary and ctx.matter_props to understand the current state
          - Use ctx.user_instruction to understand what specifically was requested
          - Call AI models, draft documents, query APIs as needed
          - Return a SkillResult with the output and next action

        Args:
            ctx: Fully populated SkillContext with matter state and user instruction.

        Returns:
            SkillResult with the skill's output, summary, and next action.
        """
        ...

    async def run(
        self,
        ctx: SkillContext,
        project_pages: Any,  # ProjectPages — typed loosely to avoid circular import
    ) -> SkillResult:
        """
        Execute the full 5-step skill lifecycle.

        Called by the SkillRunner. Subclasses should NOT override this —
        override execute() instead.

        Steps:
          1 + 2 — Context already in ctx (assembled by SkillRunner before this call)
          3     — Calls execute(ctx) [the subclass implementation]
          4     — Logs the result summary to the Notion project page
          5     — Returns the SkillResult (caller surfaces next_action to user)

        Args:
            ctx:           The skill context (matter state + user instruction).
            project_pages: The ProjectPages instance for logging back to Notion.

        Returns:
            The SkillResult from execute(), with Step 4 (Notion logging) completed.
        """
        logger.info(
            "Skill '%s' starting on matter '%s'", self.name, ctx.matter_name
        )

        # Step 3: Execute the skill's domain logic
        result = await self.execute(ctx)

        # Step 4: Update Layer 1 — log what was done to the project page.
        # This happens even if success=False (we want to record the attempt).
        try:
            status_prefix = "" if result.success else "[FAILED] "
            await project_pages.log_skill_action(
                page_id=ctx.matter_id,
                skill_name=self.name,
                action_summary=f"{status_prefix}{result.summary}",
            )

            # If the skill specified property updates (e.g., Status → "Review needed"),
            # apply them to the project page now.
            if result.notion_updates:
                from notion_bridge.client import NotionBridge  # local import
                # Note: project_pages has access to the bridge via _bridge attribute
                await project_pages._bridge.update_page(
                    page_id=ctx.matter_id,
                    properties=result.notion_updates,
                )
                logger.info(
                    "Skill '%s': applied %d Notion property update(s) to matter '%s'",
                    self.name,
                    len(result.notion_updates),
                    ctx.matter_name,
                )

        except Exception as e:
            # A failure in Step 4 should NOT mask a successful Step 3.
            # Log the error and continue — the skill output is still valuable.
            logger.error(
                "Skill '%s': Step 4 (Notion update) failed for matter '%s': %s",
                self.name,
                ctx.matter_name,
                e,
            )

        logger.info(
            "Skill '%s' completed on matter '%s'. Success: %s",
            self.name,
            ctx.matter_name,
            result.success,
        )

        # Step 5 is handled by the caller (SkillRunner / Alfred) surfacing
        # result.next_action to the user.
        return result


# =============================================================================
# SHARED SKILL UTILITIES
# Imported by individual skills — do not duplicate these in skill files.
# =============================================================================

async def skill_generate(
    prompt: str,
    deps: Any = None,
    allowed_tools: list[str] | None = None,
) -> str:
    """Run a prompt through the configured Alfred model and return the output.

    When deps and allowed_tools are both provided, the ephemeral agent gets
    those tools registered so the AI can call Notion, web search, etc. during
    its execution. Without them, runs as a plain one-shot completion.

    Call via Skill.generate(prompt, ctx) rather than directly — the base class
    resolves deps and required_tools automatically.
    """
    from pydantic_ai import Agent
    from alfred.model_factory import build_model
    from config import settings

    if deps is not None and allowed_tools:
        # Local import to avoid circular dependency (alfred.agent imports alfred.skills).
        from alfred.agent import AlfredDependencies, SKILL_TOOLS  # type: ignore[attr-defined]

        skill_agent: Agent[AlfredDependencies, str] = Agent(
            model=build_model(settings.alfred_model),
            deps_type=AlfredDependencies,
            output_type=str,
        )
        registered = 0
        for name in allowed_tools:
            fn = SKILL_TOOLS.get(name)
            if fn is not None:
                skill_agent.tool(fn)
                registered += 1

        logger.debug(
            "skill_generate: scoped agent with %d/%d tool(s): %s",
            registered, len(allowed_tools), allowed_tools,
        )
        result = await skill_agent.run(prompt, deps=deps)
    else:
        bare_agent: Agent[None, str] = Agent(
            model=build_model(settings.alfred_model),
            output_type=str,
        )
        result = await bare_agent.run(prompt)

    return result.output


def skill_read_file_text(path: str) -> str:
    """Read text from .txt, .docx, .pdf, or any plain-text file. Returns empty string on failure."""
    import zipfile
    import xml.etree.ElementTree as ET
    from pathlib import Path

    p = Path(path)
    if p.suffix.lower() == ".txt":
        return p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            pages: list[str] = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        pages.append(text)
            return "\n\n".join(pages)
        except Exception as e:
            logger.warning("skill_read_file_text: PDF extraction failed: %s", e)
            return ""
    if p.suffix.lower() in (".doc", ".docx"):
        try:
            texts: list[str] = []
            with zipfile.ZipFile(path) as z:
                with z.open("word/document.xml") as f:
                    tree = ET.parse(f)
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    for t in tree.findall(".//w:t", ns):
                        if t.text:
                            texts.append(t.text)
            return " ".join(texts)
        except Exception:
            pass
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


async def skill_fetch_sharepoint(deps: Any, matter_name: str, skill_label: str = "skill") -> str:
    """Search SharePoint for documents related to a matter. Returns formatted list or fallback message."""
    if not deps or not getattr(deps, "sharepoint", None) or not matter_name:
        return "(SharePoint not configured.)"
    try:
        results = await deps.sharepoint.search_files(matter_name, top=5)
        if not results:
            return f"(No SharePoint documents found for '{matter_name}'.)"
        lines = [
            f"  • {r.get('name', '')} — {r.get('lastModifiedDateTime', '')[:10]}\n"
            f"    {r.get('webUrl', '')}"
            for r in results
        ]
        return "Documents found:\n" + "\n".join(lines)
    except Exception as e:
        logger.warning("%s: SharePoint search failed: %s", skill_label, e)
        return "(SharePoint search failed — continuing without document list.)"
