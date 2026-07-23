"""
alfred/skills/klg_content_research.py — Background research for non-legal KLG content.

Researches people, cases, topics, and events for KLG's content needs:
podcast episode preparation, CLE materials, law review articles, social media,
and firm marketing. Unlike case-research (which is Westlaw-focused), this
skill leverages web search for biographical, academic, and media research.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_CONTENT_RESEARCH_PROMPT = """\
You are a KLG research assistant preparing background research for content creation.

KLG creates content in these formats:
- California Appellate Law Podcast (CALP) — appellate practice, landmark cases, guest interviews
- CLE materials — attorney education presentations
- Law review articles and legal commentary
- Social media (LinkedIn, Twitter) — case highlights, firm updates
- Firm website and marketing content

KLG WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly," "as such"
- Plain English where possible — this content is often for a general audience
- CRITICAL: Do not fabricate quotes, statistics, or publication details.
  Flag anything unverified: [VERIFY] or [NEEDS SOURCE]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESEARCH TOPIC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{topic}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTENT TYPE AND PURPOSE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Use your web_search tool to research the topic, then produce:

## CONTENT RESEARCH BRIEF — {matter_label}

**Topic:** {topic}
**Content type:** {content_type}
**Date compiled:** [Today's date]

---

### PART 1: OVERVIEW SUMMARY

A 2–3 paragraph overview of the topic that could serve as background briefing
for the content creator. Plain English. No jargon without explanation.

---

### PART 2: KEY FACTS AND FINDINGS

Organized by sub-topic:

#### [Sub-topic 1]
- [Finding] — Source: [publication/URL] [VERIFY]
- [Finding] — Source: [publication/URL] [VERIFY]

#### [Sub-topic 2]
(continue for all relevant sub-topics)

---

### PART 3: NOTABLE QUOTES

Quotable material from authoritative sources — judges, scholars, practitioners:

> "[Quote text]"
> — [Name], [Title], [Source] [VERIFY exact quote]

---

### PART 4: CONTENT ANGLES

Based on the research, the strongest content angles for KLG's audience:

1. **[Angle name]:** [1–2 sentences on why this angle works for KLG's audience]
2. **[Angle name]:** [1–2 sentences]
3. **[Angle name]:** [1–2 sentences]

---

### PART 5: SOURCE LIST

All sources consulted or cited, formatted for easy verification:

| # | Source | Author | Date | URL/Citation | Reliability |
|---|--------|--------|------|--------------|-------------|

---

### PART 6: SUGGESTED NEXT STEPS

Based on this research, what would make the content stronger?
- [Research gap that needs filling]
- [Expert to interview or quote]
- [Related KLG matter that could be a case study]

---

*All [VERIFY] flags require source confirmation before publication.*
\
"""


class KLGContentResearch(Skill):
    name = "klg-content-research"
    required_tools = ["web_search", "search_notion"]
    description = (
        "Background research for KLG content creation: podcast episodes, CLE materials, "
        "law review articles, and social media. Uses web search to research people, cases, "
        "and topics — producing a content brief with key facts, quotes, and suggested angles. "
        "Specify the topic and content type (podcast, CLE, article, social media)."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "KLG Content"

        if not instruction:
            return SkillResult(
                summary="klg-content-research: no topic specified.",
                output=(
                    "Specify the research topic and content type:\n\n"
                    "`Alfred, run klg-content-research: [topic] for [content type]`\n\n"
                    "**Examples:**\n"
                    "• `klg-content-research: Prof. Jane Smith sovereign immunity article for CALP episode`\n"
                    "• `klg-content-research: qualified immunity reform debate for CLE presentation`\n"
                    "• `klg-content-research: Ninth Circuit 2024 First Amendment decisions for LinkedIn post`"
                ),
                next_action="Specify the research topic and content type.",
                success=False,
            )

        parts = instruction.split(" for ", 1)
        topic = parts[0].strip()
        content_type = parts[1].strip() if len(parts) > 1 else "general content"

        prompt = _CONTENT_RESEARCH_PROMPT.format(
            topic=topic,
            instruction=instruction,
            content_type=content_type,
            matter_label=matter_label,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"Content research complete: '{topic}' ({content_type}). "
                "Overview, key facts, quotes, and source list ready."
            ),
            output=f"**Content Research — {topic}**\n\n{output_text}",
            next_action=(
                "1. Verify all [VERIFY] flags before publishing.\n"
                "2. Run klg-podcast-guest-prep if this is for a CALP episode.\n"
                "3. Share draft with Tim before external publication."
            ),
            success=True,
        )
