"""
alfred/skills/klg_notebooklm_handoff.py — Package materials for Google NotebookLM.

Prepares an optimized upload package for Google NotebookLM: selects the right
documents to include, generates a source inventory, and produces a set of
starter prompts designed for document-based Q&A in NotebookLM's interface.
"""
from __future__ import annotations

import logging

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_HANDOFF_PROMPT = """\
You are a KLG senior appellate attorney preparing a matter's research materials
for upload to Google NotebookLM. Your job is to:
1. Organize and prioritize the available documents for upload
2. Generate a structured source inventory
3. Write high-leverage starter prompts that NotebookLM can answer from the documents

NotebookLM works best with:
- Dense, text-rich PDFs (not scanned images)
- Organized, focused document sets (≤50 sources)
- Prompts that ask it to synthesize across documents rather than retrieve single facts

KLG WRITING RULES:
- Em dashes without spaces—like this
- No "furthermore," "therefore," "clearly"
- Prompts should be specific and document-anchored

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MATTER CONTEXT (from Notion)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{matter_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SHAREPOINT DOCUMENTS AVAILABLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{sharepoint_docs}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SPECIFIC INSTRUCTIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Produce:

## NOTEBOOKLM HANDOFF PACKAGE — {matter_label}

---

### PART 1: UPLOAD PRIORITY LIST

Documents to upload, in priority order:

| Priority | Document | Type | Why include | Upload notes |
|----------|----------|------|-------------|--------------|
| 🔴 Must include | | | | |
| 🟡 Should include | | | | |
| 🟢 Optional | | | | |

**Total recommended sources:** [N] (NotebookLM limit: 50)

**Documents to exclude:**
- [Document type] — Reason: [e.g., scanned image PDF, duplicate content, superseded draft]

---

### PART 2: NOTEBOOK CONFIGURATION

**Suggested notebook name:** [Matter Short Name] — [Purpose, e.g., "Record Research" or "Authority Library"]

**Notebook scope:** [1–2 sentences describing what this notebook is for]

**Team sharing:** Upload to the shared KLG Google Drive folder for this matter.

---

### PART 3: STARTER PROMPTS

These prompts are designed for NotebookLM's document-grounded Q&A.
Copy and paste each into NotebookLM after uploading the documents.

#### Orientation Prompts (run first to test the notebook)

1. **"Summarize the key facts of this case from the record and briefs."**
   Why: Confirms NotebookLM has loaded the right materials and can synthesize across them.

2. **"What are the main legal issues on appeal, and which documents address each one?"**
   Why: Creates a roadmap of the notebook's coverage.

#### Research Prompts (adapted to this matter)

3. **[Doctrine-specific prompt based on the matter's legal issues]**
   "What do the uploaded cases say about [doctrine]? List every holding relevant to our position."

4. **[Record-specific prompt]**
   "Find every mention of [key fact or event] across the uploaded record documents."

5. **[Adverse-authority prompt]**
   "What arguments does the opposing party make in their brief, and how do our cases respond?"

6. **[Synthesis prompt]**
   "If you had to pick the three strongest arguments for our client based only on the uploaded materials, what would they be?"

#### Deep-Dive Prompts (for specific briefing needs)

7–10. [Generate 4 more prompts tailored to the specific legal issues in this matter]

---

### PART 4: NOTEBOOKLM TIPS FOR THIS MATTER

Based on the document set:
- [Specific tip about a format issue, e.g., "The trial transcript is a scanned PDF — convert to OCR'd PDF before upload"]
- [Specific tip about a coverage gap, e.g., "Westlaw authority downloads are not included — add them for authority-mapping prompts"]
- [Specific tip about organization, e.g., "Create two notebooks: one for record, one for legal research"]

---

### PART 5: FOLLOW-ON WORKFLOW

After running the starter prompts:
1. Copy NotebookLM's synthesis answers into Notion under this matter's research notes
2. Flag any claims NotebookLM makes that need Westlaw verification
3. Use the Document Q&A feature to locate specific record passages when drafting
4. Run klg-research-compilation to synthesize NotebookLM output into a formal memo
\
"""


class KLGNotebookLMHandoff(Skill):
    name = "klg-notebooklm-handoff"
    required_tools = ["search_notion"]
    description = (
        "Prepare a matter's research materials for Google NotebookLM: generates a prioritized "
        "upload list, notebook configuration, and 10 starter prompts optimized for the matter's "
        "legal issues. Integrates with SharePoint document inventory. "
        "Run after record and research materials have been collected."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        instruction = ctx.user_instruction.strip()
        matter_label = ctx.matter_name or "this matter"
        matter_text = ctx.matter_summary or "(No Notion project page found.)"

        sharepoint_docs = "(SharePoint document list not available — list documents manually if known.)"
        deps = ctx.extra.get("deps")
        if deps and getattr(deps, "sharepoint", None) and ctx.matter_name:
            try:
                results = await deps.sharepoint.search_files(ctx.matter_name, top=20)
                if results:
                    lines = [
                        f"  • {r.get('name', '')} ({r.get('lastModifiedDateTime', '')[:10]})"
                        for r in results
                    ]
                    sharepoint_docs = "Documents found in SharePoint:\n" + "\n".join(lines)
            except Exception as e:
                logger.warning("klg-notebooklm-handoff: SharePoint search failed: %s", e)

        if not matter_text:
            return SkillResult(
                summary="klg-notebooklm-handoff: no matter context found.",
                output=(
                    "Provide the matter name:\n\n"
                    "`Alfred, run klg-notebooklm-handoff on [Matter Name].`\n\n"
                    "Also specify the focus of the notebook:\n"
                    "'Focus: oral argument prep' or 'Focus: opening brief research'"
                ),
                next_action="Re-run with the matter name.",
                success=False,
            )

        prompt = _HANDOFF_PROMPT.format(
            matter_summary=matter_text[:4000],
            sharepoint_docs=sharepoint_docs,
            instruction=instruction or "(No specific focus — prepare a general research notebook.)",
            matter_label=matter_label,
        )

        output_text = await self.generate(prompt, ctx)

        return SkillResult(
            summary=(
                f"NotebookLM handoff package ready for {matter_label}. "
                "Upload list, starter prompts, and workflow guide complete."
            ),
            output=f"**NotebookLM Handoff — {matter_label}**\n\n{output_text}",
            next_action=(
                "1. Collect Priority 🔴 documents from SharePoint.\n"
                "2. Convert any scanned PDFs to OCR'd text before upload.\n"
                "3. Upload to NotebookLM and run the Orientation Prompts first.\n"
                "4. Share the notebook with the matter team in Google Drive."
            ),
            success=True,
        )
