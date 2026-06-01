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
