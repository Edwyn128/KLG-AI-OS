"""
alfred/skills/klg_conflict_waiver.py — Joint representation conflict waiver letter.

Generates a conflict disclosure and consent letter for joint representation
on KLG letterhead (Phase 1: formatted markdown; Phase 2: .docx via letterhead template).

The skill gathers information interactively when fields are missing, then
produces a six-point disclosure letter with case-specific conflict examples
and signature blocks for each client.
"""
from __future__ import annotations

import logging
from datetime import date

from alfred.skills.base import Skill, SkillContext, SkillResult

logger = logging.getLogger(__name__)

_LETTER_PROMPT = """You are drafting a joint-representation conflict waiver letter for Kowal Law Group (KLG),
a California appellate litigation firm. Tim Kowal is the managing attorney.

MATTER INFORMATION:
{matter_info}

CLIENT INFORMATION:
{client_info}

DELIVERY: {delivery}
DATE: {letter_date}

Draft a conflict disclosure and consent letter with the following structure:

1. KLG letterhead block (firm name, address, phone, website)
2. Date
3. Salutation addressing the primary client by first name
4. Opening paragraph: matter caption, court, case number, brief statement of joint representation
5. Six disclosure points covering:
   a. Nature of joint representation and KLG's duty to each client
   b. Potential conflicts of interest inherent in joint representation
   c. Case-specific conflict scenarios (use the scenarios provided, or generate 2–3 realistic examples based on the case type)
   d. Right to consult independent counsel before signing
   e. Confidentiality limitations between jointly represented clients
   f. Right to terminate joint representation and seek independent counsel at any time
6. Consent and waiver paragraph
7. Signature blocks for EACH client (name, printed name line, date line, address, email)
8. Attorney signature block for Tim Kowal

FORMATTING RULES:
- Professional letter format, not a brief
- Address primary contact by first name in salutation
- Use full legal names in all other references
- Clear paragraph breaks between disclosure points
- Signature blocks must be complete (name, address, email for each client)
- Do NOT include engagement terms, rates, or retainer language — this letter covers conflict only

OUTPUT: Produce the complete letter as formatted markdown. Use --- as a section separator where appropriate.
"""

_GATHER_PROMPT = """You are Alfred, KLG's executive assistant. A team member wants to generate a joint-representation conflict waiver letter.

The following information is MISSING and must be gathered before the letter can be drafted:
{missing_fields}

Please ask the user for this information in a single, clear message. Group related fields together.
Be brief and professional — you're talking to a colleague, not a client.
"""


class KLGConflictWaiver(Skill):
    name = "klg-conflict-waiver"
    description = (
        "Generates a conflict disclosure and consent letter for joint representation, "
        "with six-point disclosures and signature blocks for each client."
    )

    async def execute(self, ctx: SkillContext) -> SkillResult:
        extra = ctx.extra or {}

        # Collect required fields from extra or user instruction
        clients = extra.get("clients", [])
        matter_caption = extra.get("matter_caption", "")
        court = extra.get("court", "")
        case_number = extra.get("case_number", "")
        delivery = extra.get("delivery", "email")
        conflict_scenarios = extra.get("conflict_scenarios", "")
        letter_date = extra.get("date", date.today().strftime("%B %d, %Y"))

        # Check for minimum required fields
        missing = []
        if not clients or len(clients) < 2:
            missing.append("full legal names, mailing addresses, and email addresses for each client (minimum 2)")
        if not matter_caption:
            missing.append("matter caption (e.g., 'Smith v. City of Los Angeles')")
        if not court:
            missing.append("court name and division")
        if not case_number:
            missing.append("case number")

        if missing:
            missing_list = "\n".join(f"- {m}" for m in missing)
            return SkillResult(
                summary="klg-conflict-waiver: information gathering needed before letter can be drafted.",
                output=(
                    "To draft the conflict waiver letter, I need the following information:\n\n"
                    f"{missing_list}\n\n"
                    "Please provide these details and I'll generate the complete letter."
                ),
                next_action="Provide the missing client and matter information, then re-run the skill.",
                success=False,
            )

        # Build input strings for the prompt
        client_info = _format_client_info(clients)
        matter_info = _format_matter_info(matter_caption, court, case_number, conflict_scenarios)

        # Generate the letter
        from config import settings
        from pydantic_ai import Agent
        from alfred.model_factory import build_model

        agent: Agent[None, str] = Agent(model=build_model(settings.alfred_model), output_type=str)

        prompt = _LETTER_PROMPT.format(
            matter_info=matter_info,
            client_info=client_info,
            delivery=delivery,
            letter_date=letter_date,
        )

        result = await agent.run(prompt)
        letter_text = result.output

        client_names = ", ".join(c.get("name", "Client") for c in clients)

        return SkillResult(
            summary=(
                f"Conflict waiver letter drafted for {matter_caption}. "
                f"Clients: {client_names}."
            ),
            output=(
                f"**Conflict Waiver Letter — {matter_caption}**\n\n"
                f"{letter_text}\n\n"
                "---\n"
                "**Next steps:**\n"
                "- Review the letter for accuracy before sending\n"
                "- Confirm case-specific conflict scenarios are accurate\n"
                "- Send to each client for signature\n"
                "- .docx on KLG letterhead available in Phase 2 (port of klg-brief-assembly pipeline)"
            ),
            next_action=(
                "Review the letter and send to clients for signature. "
                "Phase 2 will add .docx output on KLG letterhead."
            ),
            success=True,
        )


def _format_client_info(clients: list[dict]) -> str:
    lines = []
    for i, c in enumerate(clients, 1):
        lines.append(f"CLIENT {i}:")
        lines.append(f"  Name: {c.get('name', 'Unknown')}")
        if c.get("address"):
            lines.append(f"  Address: {c['address']}")
        if c.get("email"):
            lines.append(f"  Email: {c['email']}")
        if c.get("primary"):
            lines.append("  (Primary contact — addressed in salutation)")
    return "\n".join(lines)


def _format_matter_info(caption: str, court: str, case_number: str, scenarios: str) -> str:
    parts = [
        f"Caption: {caption}",
        f"Court: {court}",
        f"Case Number: {case_number}",
    ]
    if scenarios:
        parts.append(f"Case-specific conflict scenarios to include:\n{scenarios}")
    return "\n".join(parts)
