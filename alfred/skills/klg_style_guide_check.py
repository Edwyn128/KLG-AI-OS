"""
alfred/skills/klg_style_guide_check.py — KLG Style Guide conformance review.

Reviews an appellate brief against the KLG Style Guide and produces a
redlined .docx with Word tracked changes (author "Claude") plus a written
conformance report.

Phase 1: Returns conformance report as markdown (no .docx tracked changes).
Phase 2: Adds redlined .docx output via the docx pipeline (pack/unpack/tracked-changes).

Requires: alfred/skills/references/klg-style-guide.md
"""
from __future__ import annotations

import logging
from pathlib import Path

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_REFERENCES_DIR = Path(__file__).parent / "references"
_STYLE_GUIDE_PATH = _REFERENCES_DIR / "klg-style-guide.md"

_PLACEHOLDER_MARKER = "PLACEHOLDER"

_REVIEW_PROMPT = """You are a KLG style editor reviewing an appellate brief.

KLG STYLE GUIDE:
{style_guide}

BRIEF SCOPE: {scope}
TARGET COURT: {court}

BRIEF TEXT TO REVIEW:
{brief_text}

Produce a conformance report with the following sections:

## CONFORMANCE REPORT

### Summary
[2–3 sentence overall assessment: what's strong, what needs work, pass/conditional pass/revise]

### Critical Issues (must fix before filing)
[Numbered list. Each issue: location, rule violated, specific text, suggested correction.
If none: "None identified."]

### Style Issues (should fix)
[Numbered list. Same format as critical issues.]

### Mechanical Issues (minor)
[Bulleted list. Citation format, spacing, punctuation, etc.]

### Strong Points
[What the brief does well from a style perspective — 3–5 bullets]

### Word/Page Count Assessment
[If limits were provided: current count vs. limit, projection]

---
After the report, provide a REDLINE SUMMARY — a list of specific text replacements:
Format each as:
FIND: [exact text to find]
REPLACE: [replacement text]
REASON: [one-line reason referencing the style guide rule]

Only include replacements you are confident in. Do not invent replacements for text that
doesn't appear in the brief.
"""


class KLGStyleGuideCheck(Skill):
    name = "klg-style-guide-check"
    description = (
        "Reviews an appellate brief against the KLG Style Guide and produces a "
        "conformance report. Phase 1: markdown report. Phase 2: tracked-changes .docx."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        # Load style guide
        style_guide = _load_style_guide()
        if style_guide is None:
            return SkillResult(
                summary="klg-style-guide-check: style guide reference file not populated.",
                output=(
                    "The KLG Style Guide reference file has not been populated yet.\n\n"
                    "To activate this skill:\n"
                    "1. Export `references/klg-style-guide.md` from the Claude.ai project\n"
                    "2. Replace the contents of `alfred/skills/references/klg-style-guide.md`\n"
                    "3. Redeploy Alfred\n\n"
                    "Once the reference file is populated, this skill will be fully operational."
                ),
                next_action="Populate alfred/skills/references/klg-style-guide.md and redeploy.",
                success=False,
            )

        # Get brief text
        brief_text = await _extract_brief_text(ctx)
        if not brief_text:
            return SkillResult(
                summary="klg-style-guide-check: no brief text provided.",
                output=(
                    "To run a style guide check, upload the brief .docx file and include "
                    "its file token in your request.\n\n"
                    "Example: Upload the brief, then say: "
                    "'Alfred, run klg-style-guide-check on [filename]'"
                ),
                next_action="Upload the brief .docx and re-run the skill.",
                success=False,
            )

        extra = ctx.extra or {}
        scope = extra.get("scope", "full edit")
        court = extra.get("court", "California Court of Appeal")
        word_limit = extra.get("word_limit", "")
        if word_limit:
            court = f"{court} (word limit: {word_limit})"

        from config import settings
        from pydantic_ai import Agent
        from alfred.model_factory import build_model

        agent: Agent[None, str] = Agent(model=build_model(settings.alfred_model), output_type=str)

        prompt = _REVIEW_PROMPT.format(
            style_guide=style_guide[:12000],
            scope=scope,
            court=court,
            brief_text=brief_text[:20000],
        )

        result = await agent.run(prompt)
        report = result.output

        matter_label = ctx.matter_name or "Brief"

        return SkillResult(
            summary=f"Style guide check complete for {matter_label}. Scope: {scope}.",
            output=(
                f"**Style Guide Check — {matter_label}**\n\n"
                f"{report}\n\n"
                "---\n"
                "**Phase 2 note:** Tracked-changes .docx output (author: 'Claude') "
                "will be available after the docx pipeline is ported."
            ),
            next_action=(
                "Review the conformance report. Address critical issues before filing. "
                "Phase 2 will deliver a redlined .docx with Word tracked changes."
            ),
            success=True,
        )


def _load_style_guide() -> str | None:
    """Load the style guide from the references directory."""
    if not _STYLE_GUIDE_PATH.exists():
        return None
    content = _STYLE_GUIDE_PATH.read_text(encoding="utf-8")
    if _PLACEHOLDER_MARKER in content:
        return None
    return content


async def _extract_brief_text(ctx: SkillContext) -> str:
    """
    Extract text from an uploaded brief file.
    Phase 1: reads plain text or attempts basic .docx text extraction.
    Phase 2: will use the full unpack/pack pipeline.
    """
    file_tokens = ctx.extra.get("file_tokens", [])
    if not file_tokens:
        return ctx.user_instruction or ""

    try:
        from alfred.file_store import consume_token, delete_file
        token = file_tokens[0]
        path = consume_token(token)
        if not path:
            return ctx.user_instruction or ""

        text = _read_file_text(path)
        delete_file(path)
        return text
    except Exception as e:
        logger.error("klg-style-guide-check: file extraction failed: %s", e)
        return ctx.user_instruction or ""


def _read_file_text(path: str) -> str:
    """Read text from a file. Handles .txt and basic .docx (Phase 1)."""
    p = Path(path)
    if p.suffix.lower() == ".txt":
        return p.read_text(encoding="utf-8", errors="replace")

    if p.suffix.lower() == ".docx":
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            texts = []
            with zipfile.ZipFile(path) as z:
                with z.open("word/document.xml") as f:
                    tree = ET.parse(f)
                    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                    for t in tree.findall(".//w:t", ns):
                        if t.text:
                            texts.append(t.text)
            return " ".join(texts)
        except Exception as e:
            logger.warning("klg-style-guide-check: .docx text extraction failed: %s", e)

    # Fall back to reading as text
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
