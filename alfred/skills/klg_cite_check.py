"""
alfred/skills/klg_cite_check.py — Two-phase citation audit.

Phase A: Audits citation format and completeness, flags hallucination risks,
         produces a Westlaw pull list. Runs immediately on uploaded brief.
Phase B: Cross-checks citations against Westlaw source text for existence,
         accuracy, and good-law status. Requires Westlaw .doc upload.

Requires: alfred/skills/references/citation-rules.md
"""
from __future__ import annotations

import logging
from pathlib import Path

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_REFERENCES_DIR = Path(__file__).parent / "references"
_CITATION_RULES_PATH = _REFERENCES_DIR / "citation-rules.md"

_PLACEHOLDER_MARKER = "PLACEHOLDER"

_PHASE_A_PROMPT = """You are a KLG citation auditor performing Phase A of a two-phase cite check.

CITATION RULES:
{citation_rules}

BRIEF TEXT:
{brief_text}

Perform a Phase A citation audit:

## PHASE A — FORMAT AUDIT

### Citation Inventory
Extract every legal citation from the brief. For each, provide:
- Citation as written in the brief
- Citation type (case, statute, rule, secondary source)
- Format assessment: ✅ Correct / ⚠️ Minor issue / ❌ Format error
- If issue: specific format problem and correction

### Hallucination Risk Assessment
For each case citation, assess hallucination risk:
🟢 LOW RISK — citation format is specific and plausible (full cite with reporter and page)
🟡 MEDIUM RISK — partial cite, missing reporter or page, unusual format
🔴 HIGH RISK — vague cite, suspicious volume/page combination, unfamiliar reporter

### Westlaw Pull List
List every case citation that needs Westlaw verification, sorted by risk:
HIGH RISK (verify first):
[citation] — [reason for high risk]

MEDIUM RISK:
[citation]

LOW RISK (spot check):
[citation]

### Format Issues Log
Numbered list of all format errors with: citation, rule violated, corrected form.

### Summary
Total citations found: N
By risk: HIGH: N, MEDIUM: N, LOW: N
Format errors: N
Recommendation: [what to verify in Westlaw before filing]

---
After the audit, include:
**WESTLAW FIND & PRINT LIST**
Copy-pasteable list of citations to paste into Westlaw Find & Print:
[citation 1]
[citation 2]
...
"""

_PHASE_B_PROMPT = """You are a KLG citation auditor performing Phase B — Westlaw verification.

CITATION RULES:
{citation_rules}

BRIEF CITATIONS (from Phase A):
{phase_a_inventory}

WESTLAW SOURCE TEXT:
{westlaw_text}

For each citation in the brief, cross-check against the Westlaw source text:

## PHASE B — WESTLAW VERIFICATION

For each citation, provide a traffic-light rating:
🟢 VERIFIED — citation exists, text matches, good law
🟡 PARTIAL — citation exists but text mismatch or minor inaccuracy
🔴 PROBLEM — citation not found in Westlaw output, significant mismatch, or bad law
⚫ NOT CHECKED — not included in Westlaw pull

Format:
### [Citation as written in brief]
Status: [🟢/🟡/🔴/⚫]
Westlaw: [what Westlaw shows]
Issue: [if 🟡 or 🔴: specific problem]
Action required: [if 🟡 or 🔴: what attorney must do]

### Summary
Citations verified: N
🟢 Clean: N | 🟡 Issues: N | 🔴 Problems: N | ⚫ Not checked: N

### Priority Action List
Numbered list of every 🔴 PROBLEM citation with required action before filing.
"""


class KLGCiteCheck(Skill):
    name = "klg-cite-check"
    description = (
        "Two-phase citation audit: Phase A audits format and flags hallucination risk "
        "(runs immediately); Phase B cross-checks against Westlaw source text."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        citation_rules = _load_citation_rules()
        if citation_rules is None:
            return SkillResult(
                summary="klg-cite-check: citation rules reference file not populated.",
                output=(
                    "The KLG Citation Rules reference file has not been populated yet.\n\n"
                    "To activate this skill:\n"
                    "1. Export `references/citation-rules.md` from the Claude.ai project\n"
                    "2. Replace the contents of `alfred/skills/references/citation-rules.md`\n"
                    "3. Redeploy Alfred\n\n"
                    "Once the reference file is populated, this skill will be fully operational."
                ),
                next_action="Populate alfred/skills/references/citation-rules.md and redeploy.",
                success=False,
            )

        extra = ctx.extra or {}
        phase = extra.get("phase", "A")
        file_tokens = extra.get("file_tokens", [])

        if phase == "B":
            return await self._run_phase_b(ctx, citation_rules, file_tokens)
        return await self._run_phase_a(ctx, citation_rules, file_tokens)

    async def _run_phase_a(
        self, ctx: SkillContext, citation_rules: str, file_tokens: list[str]
    ) -> SkillResult:
        brief_text = await _extract_text_from_token(file_tokens, ctx.user_instruction)
        if not brief_text:
            return SkillResult(
                summary="klg-cite-check Phase A: no brief text provided.",
                output=(
                    "To run a citation audit, upload the brief and include its file token.\n\n"
                    "Example: Upload the brief, then say: 'Alfred, run klg-cite-check on [filename]'"
                ),
                next_action="Upload the brief and re-run the skill.",
                success=False,
            )

        result_text = await _generate(
            _PHASE_A_PROMPT.format(
                citation_rules=citation_rules[:8000],
                brief_text=brief_text[:20000],
            )
        )

        matter_label = ctx.matter_name or "Brief"

        return SkillResult(
            summary=f"Cite check Phase A complete for {matter_label}.",
            output=(
                f"**Citation Audit — Phase A — {matter_label}**\n\n"
                f"{result_text}\n\n"
                "---\n"
                "**Next step (Phase B):** Run Westlaw Find & Print on the pull list above, "
                "then upload the Westlaw .doc and run klg-cite-check Phase B."
            ),
            next_action=(
                "Run Westlaw Find & Print on the pull list. "
                "Then upload the Westlaw .doc and run klg-cite-check Phase B."
            ),
            success=True,
        )

    async def _run_phase_b(
        self, ctx: SkillContext, citation_rules: str, file_tokens: list[str]
    ) -> SkillResult:
        phase_a_inventory = ctx.extra.get("phase_a_inventory", "")
        westlaw_text = await _extract_text_from_token(file_tokens, "")

        if not westlaw_text:
            return SkillResult(
                summary="klg-cite-check Phase B: no Westlaw source text provided.",
                output=(
                    "Phase B requires the Westlaw Find & Print output. "
                    "Upload the Westlaw .doc file and re-run with phase=B."
                ),
                next_action="Upload the Westlaw .doc and re-run klg-cite-check Phase B.",
                success=False,
            )

        result_text = await _generate(
            _PHASE_B_PROMPT.format(
                citation_rules=citation_rules[:4000],
                phase_a_inventory=phase_a_inventory[:4000],
                westlaw_text=westlaw_text[:20000],
            )
        )

        matter_label = ctx.matter_name or "Brief"

        return SkillResult(
            summary=f"Cite check Phase B complete for {matter_label}.",
            output=(
                f"**Citation Audit — Phase B — {matter_label}**\n\n"
                f"{result_text}\n\n"
                "---\n"
                "Address all 🔴 PROBLEM citations before filing."
            ),
            next_action=(
                "Resolve all 🔴 PROBLEM citations. "
                "Then run klg-style-guide-check for the final pre-filing pass."
            ),
            success=True,
        )


def _load_citation_rules() -> str | None:
    if not _CITATION_RULES_PATH.exists():
        return None
    content = _CITATION_RULES_PATH.read_text(encoding="utf-8")
    if _PLACEHOLDER_MARKER in content:
        return None
    return content


async def _extract_text_from_token(file_tokens: list[str], fallback: str) -> str:
    if not file_tokens:
        return fallback
    try:
        from alfred.file_store import consume_token, delete_file
        path = consume_token(file_tokens[0])
        if not path:
            return fallback
        text = _read_file_text(path)
        delete_file(path)
        return text or fallback
    except Exception as e:
        logger.error("klg-cite-check: file extraction failed: %s", e)
        return fallback


def _read_file_text(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".txt":
        return p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() in (".doc", ".docx"):
        try:
            import zipfile
            import xml.etree.ElementTree as ET
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


async def _generate(prompt: str) -> str:
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
