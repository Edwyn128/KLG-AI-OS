#!/usr/bin/env python3
"""
alfred/skills/scripts/simulate_skills.py -- Automated simulation of all KLG skills.

Three modes:

  structure   Validate skill files via AST: name, description, execute(),
              required_tools validity, registry registration, and skills.ts coverage.
              No network calls, no dependencies. Free and instant.

  dry         Run each skill's Python logic against a real Notion matter, but
              replace Claude calls with a canned stub. Costs: 0 tokens.
              Catches Python exceptions, file-handling bugs, early-return paths.

  live        Full end-to-end: real Claude calls, real Notion writes.
              Uses --model (default: claude-haiku-4-5-20251001) to keep cost low.
              Expect ~32 LLM calls; budget ~$0.50-2.00 total.

Usage:
    cd c:/Users/Stu/klg-ai-os
    python alfred/skills/scripts/simulate_skills.py --mode structure
    python alfred/skills/scripts/simulate_skills.py --mode dry --matter "Williams v. Allstate"
    python alfred/skills/scripts/simulate_skills.py --mode live --matter "Petersen" --only klg-daily-triage,klg-dz-overlay
    python alfred/skills/scripts/simulate_skills.py --mode live --matter "Shen" --skip klg-cite-check,klg-prebill-audit

Options:
    --mode      structure | dry | live  [default: structure]
    --matter    Notion matter name (required for dry/live)
    --only      Comma-separated skill names to include (default: all)
    --skip      Comma-separated skill names to skip
    --model     Claude model for live mode [default: claude-haiku-4-5-20251001]
    --no-write  Skip Notion Step-4 write-back in live mode
    --output    Path to write JSON results [default: stdout only]
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import json
import os
import re
import sys
import tempfile
import time
import textwrap
from pathlib import Path
from typing import NamedTuple

# Force UTF-8 on Windows consoles to avoid encoding crashes
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add project root to sys.path
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env", override=False)
except ImportError:
    pass

# ANSI colors
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _ok(s):   return f"{GREEN}[OK]   {s}{RESET}"
def _fail(s): return f"{RED}[FAIL] {s}{RESET}"
def _info(s): return f"{CYAN}{s}{RESET}"
def _bold(s): return f"{BOLD}{s}{RESET}"


# ---------------------------------------------------------------------------
# SkillRun result
# ---------------------------------------------------------------------------

class SkillRun(NamedTuple):
    name: str
    mode: str
    success: bool
    elapsed: float
    output_preview: str
    error: str
    required_files: bool


# ---------------------------------------------------------------------------
# Mock files for file-based skills
# ---------------------------------------------------------------------------

_MOCK_BRIEF = """\
APPELLANT'S OPENING BRIEF -- TEST MATTER

STATEMENT OF FACTS
Appellant John Doe was employed as a public employee for 12 years.
On January 15, 2024, Appellant spoke at a press conference on public corruption.
He was terminated on February 1, 2024, two weeks after the speech.
(RT 45:5-18; AA at 23.)

ARGUMENT
I. THE TRIAL COURT ERRED IN GRANTING SUMMARY JUDGMENT
Under Garcetti v. Ceballos (2006) 547 U.S. 410, the First Amendment protects
public employees who speak as citizens on matters of public concern. (Id. at 418.)

II. THE STANDARD OF REVIEW IS DE NOVO
Summary judgment rulings receive de novo review. Aguilar v. Atlantic Richfield
Co. (2001) 25 Cal.4th 826, 843. The trial court erred. (AA at 141.)

CONCLUSION
The judgment should be reversed.
"""

_MOCK_TRANSCRIPT = """\
REPORTER'S TRANSCRIPT OF PROCEEDINGS -- TEST MATTER
Volume 1 -- January 10, 2024

THE COURT: Good morning. This is Doe v. City, case 12345.
MR. SMITH: Plaintiff is ready, Your Honor.
MS. JONES: Defendant is ready.

DIRECT EXAMINATION OF JOHN DOE BY MR. SMITH:
Q. State your name.  A. John Doe.  (RT 45:5)
Q. How long employed?  A. Twelve years.  (RT 45:10)
Q. What happened January 15?  A. I reported misconduct.  (RT 46:2-8)
Q. What happened after?  A. I was terminated two weeks later.  (RT 46:15-18)
"""

_MOCK_DOCKET = """\
DOCKET / APPENDIX INDEX -- TEST MATTER
Document                                    AA Pages
1. Complaint                                1-24
2. Answer                                   25-40
3. Motion for Summary Judgment              41-85
4. Opposition to Motion                     86-120
5. Reply                                    121-140
6. Trial Court Order                        141-148
7. Notice of Appeal                         149-152
8. Declaration of John Doe                  153-175
"""

_MOCK_COMPILE = """\
PROPOSED APPENDIX COMPILE FOLDER
1. Complaint (pages 1-24)
3. Motion for Summary Judgment (pages 41-85)
6. Trial Court Order (pages 141-148)
8. Declaration of John Doe (pages 153-175)
"""

_MOCK_SEPARATE_STATEMENT = """\
DEFENDANT'S SEPARATE STATEMENT OF UNDISPUTED MATERIAL FACTS

No. 1: Plaintiff was employed by Defendant as of January 1, 2024.
Supporting Evidence: Declaration of HR Director, para. 3.

No. 2: On January 15, 2024, Plaintiff sent an email to the press.
Supporting Evidence: Exhibit A (email); HR Director Decl. para. 6.

No. 3: Plaintiff was terminated on February 1, 2024.
Supporting Evidence: Termination letter, Exhibit B; HR Director Decl. para. 8.
"""

_MOCK_CSV = """\
Matter,Date,Timekeeper,Hours,Activity Description,Rate
Test v. City,2024-06-01,T. Kowal,0.25 0.50,Review email review documents telephone call,450
Test v. City,2024-06-02,T. Kowal,2.0,Draft draft draft brief MSJ opposition,450
Test v. City,2024-06-03,E. Nakano,0.10,TC,350
Test v. City,2024-06-04,T. Kowal,5.0,Review deposition transcript draft outline analyze exhibits,450
Test v. City,2024-06-05,B. Sanders,0.25,Filing,250
"""

# Map skill name -> list of (filename, content) for mock file injection
_MOCK_FILES: dict[str, list[tuple[str, str]]] = {
    "klg-brief-elevation":               [("brief.txt", _MOCK_BRIEF)],
    "klg-record-navigator":              [("transcript.txt", _MOCK_TRANSCRIPT)],
    "klg-response-plan":                 [("brief.txt", _MOCK_BRIEF)],
    "klg-appendix-audit":                [("docket.txt", _MOCK_DOCKET), ("compile.txt", _MOCK_COMPILE)],
    "klg-style-guide-check":             [("brief.txt", _MOCK_BRIEF)],
    "klg-cite-check":                    [("brief.txt", _MOCK_BRIEF)],
    "klg-prebill-audit":                 [("timesheets.csv", _MOCK_CSV)],
    "klg-record-digest":                 [("transcript.txt", _MOCK_TRANSCRIPT)],
    "klg-opposition-separate-statement": [("separate_statement.txt", _MOCK_SEPARATE_STATEMENT)],
    "klg-appendix-cites":                [("brief.txt", _MOCK_BRIEF)],
}

# Default user_instruction for skills that need a non-empty one
_DEFAULT_INSTRUCTIONS: dict[str, str] = {
    "klg-authority-map":             "Garcetti public employee speech retaliation",
    "klg-issue-framing":             "MSJ granted on 1983 claim -- court found no policy",
    "klg-standard-of-review":        "Summary judgment on 1983 claim -- appeal in 9th Circuit",
    "klg-oral-argument-prep":        "9th Circuit, Oct 15, First Amendment and qualified immunity, 15 min",
    "klg-oral-argument-full":        "9th Circuit, Judges Smith/Jones/Brown, Oct 15, 1st Amend + Monell, 15 min",
    "klg-matter-intake":             "Test v. City -- public employee 1st Amendment, 9th Circuit appeal",
    "klg-amicus-assessment":         "Smith v. County, 9th Cir., qualified immunity scope",
    "klg-podcast-guest-prep":        "Prof. Jane Smith, sovereign immunity, 2024 law review article",
    "klg-conflict-waiver":           "Jointly representing John and Jane Smith -- adverse on fee allocation",
    "klg-deep-research-prompts":     "Whether qualified immunity bars 1983 supervisor liability claims",
    "klg-research-compilation":      "First Amendment retaliation under Garcetti",
    "klg-brief-assembly":            "Introduction and Statement of Facts for appellant's opening brief",
    "klg-notebooklm-handoff":        "opening brief research",
    "klg-court-doc-renamer":         "AOB draft, RT volumes 1-3, Clerk transcript, Exhibits A through F",
    "klg-authority-library":         "Garcetti public employee speech retaliation",
    "klg-content-research":          "Prof. Jane Smith sovereign immunity article for CALP podcast episode",
}

# Skills whose Python name intentionally differs from the frontend skills.ts id
_TS_ID_ALIASES: dict[str, str] = {
    "klg-case-assessment":  "case-research",      # frontend uses descriptive id
    "klg-podcast-guest-prep": "calp-episode-prep", # frontend uses show-specific id
}

# Known valid Alfred tools (mirrors alfred/agent.py SKILL_TOOLS keys)
_VALID_TOOLS: set[str] = {
    "find_and_summarize_matter", "get_upcoming_deadlines", "get_team_workload",
    "search_notion", "save_note", "recall_notes", "log_action_to_matter",
    "update_matter_status", "update_matter", "create_new_matter",
    "get_bloodhound_watch_list", "send_slack_message", "web_search",
    "deep_research_with_chatgpt", "run_skill", "create_matter_task",
    "update_matter_task", "get_matter_tasks", "seed_matter_tasks",
    "search_sharepoint", "read_sharepoint_file",
}


# ---------------------------------------------------------------------------
# Mode: structure (AST-based, no imports, no deps)
# ---------------------------------------------------------------------------

def _ast_skill_info(path: Path) -> dict:
    """Extract skill metadata from a .py file using AST -- no code execution."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return {"syntax_error": str(e)}

    info: dict = {
        "name": None, "description": None,
        "required_tools": [], "has_execute": False,
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, ast.Assign):
                for tgt in item.targets:
                    if not isinstance(tgt, ast.Name):
                        continue
                    if tgt.id == "name" and isinstance(item.value, ast.Constant):
                        info["name"] = item.value.value
                    elif tgt.id == "description" and isinstance(item.value, ast.Constant):
                        info["description"] = item.value.value
                    elif tgt.id == "required_tools" and isinstance(item.value, ast.List):
                        info["required_tools"] = [
                            e.value for e in item.value.elts
                            if isinstance(e, ast.Constant)
                        ]
            if isinstance(item, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if item.name == "execute":
                    info["has_execute"] = True
    return info


def run_structure_check(only: set, skip: set) -> list:
    print(_bold("\n--- STRUCTURE CHECK ---\n"))
    skills_dir = _ROOT / "alfred" / "skills"

    # Skill file stems imported in __init__.py (e.g. "from alfred.skills.klg_foo import ...")
    init_text = (skills_dir / "__init__.py").read_text(encoding="utf-8")
    imported_stems: set[str] = set(re.findall(r"from alfred\.skills\.(klg_\w+) import", init_text))

    # IDs in skills.ts
    ts_text = (_ROOT / "web-next" / "src" / "data" / "skills.ts").read_text(encoding="utf-8")
    ts_ids: set[str] = set(re.findall(r"id:\s*'([^']+)'", ts_text))

    results = []
    skill_files = sorted(skills_dir.glob("klg_*.py"))
    print(f"  Scanning {len(skill_files)} skill files...\n")

    for fpath in skill_files:
        info = _ast_skill_info(fpath)
        skill_name = info.get("name") or fpath.stem.replace("_", "-")

        if only and skill_name not in only:
            continue
        if skill_name in skip:
            continue

        errors = []
        if "syntax_error" in info:
            errors.append(f"SyntaxError: {info['syntax_error']}")
        else:
            if not info.get("name"):
                errors.append("missing name attribute")
            if not info.get("description"):
                errors.append("missing/empty description")
            if not info.get("has_execute"):
                errors.append("no execute() method")
            bad = [t for t in info.get("required_tools", []) if t not in _VALID_TOOLS]
            if bad:
                errors.append(f"unknown required_tools: {bad}")
            if fpath.stem not in imported_stems:
                errors.append("NOT imported in __init__.py")
            ts_id = _TS_ID_ALIASES.get(skill_name, (skill_name or "").removeprefix("klg-"))
            if ts_id not in ts_ids and skill_name not in ts_ids:
                errors.append("no matching id in skills.ts")

        ok = not errors
        has_files = skill_name in _MOCK_FILES
        label = f"{skill_name:<50} {'[file]' if has_files else '      '}"
        if ok:
            print(f"  {_ok(label)}")
        else:
            print(f"  {_fail(label)}  {', '.join(errors)}")

        results.append(SkillRun(
            name=skill_name, mode="structure", success=ok, elapsed=0.0,
            output_preview="ok" if ok else ", ".join(errors),
            error="" if ok else ", ".join(errors),
            required_files=has_files,
        ))

    print(f"\n  {len(skill_files)} files | {len(imported_stems)} imported in __init__.py | {len(ts_ids)} entries in skills.ts\n")
    return results


# ---------------------------------------------------------------------------
# Mode: dry / live
# ---------------------------------------------------------------------------

async def _get_matter_context(matter_name: str) -> tuple:
    """Return (matter_id, summary_text, props_dict) from Notion."""
    from config import settings
    from notion_bridge.client import NotionBridge
    from notion_bridge.project_pages import ProjectPages

    bridge = NotionBridge(token=settings.notion_token)
    pages = ProjectPages(bridge)
    matter = await pages.find_matter(matter_name)
    if not matter:
        raise ValueError(f"Matter '{matter_name}' not found in Notion")
    matter_id = matter["id"]
    summary = await pages.get_matter_summary(matter_id) or ""
    return matter_id, summary, matter


def _register_mock_files(skill_name: str) -> list:
    """Create temp files and register them in file_store. Returns token list."""
    from alfred.file_store import register_file
    tokens = []
    for filename, content in _MOCK_FILES.get(skill_name, []):
        suffix = Path(filename).suffix or ".txt"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, encoding="utf-8", delete=False
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        tokens.append(register_file(tmp_path, filename))
    return tokens


async def _run_one_skill(
    skill_name: str, matter_id: str, matter_name: str,
    matter_summary: str, matter_props: dict,
    mode: str, model: str, no_write: bool,
) -> SkillRun:
    from alfred.skills import SKILL_REGISTRY
    from alfred.skills.base import SkillContext
    import alfred.skills.base as _base

    skill = SKILL_REGISTRY.get(skill_name)
    if skill is None:
        return SkillRun(skill_name, mode, False, 0.0, "", "not in SKILL_REGISTRY", False)

    file_tokens = _register_mock_files(skill_name)
    instruction = _DEFAULT_INSTRUCTIONS.get(skill_name, "")

    ctx = SkillContext(
        matter_id=matter_id, matter_name=matter_name,
        matter_summary=matter_summary, matter_props=matter_props,
        user_instruction=instruction,
        extra={"file_tokens": file_tokens},
    )

    orig_generate = _base.skill_generate

    if mode == "dry":
        async def _mock(prompt, deps=None, allowed_tools=None):
            return (
                f"[DRY-RUN] {skill_name} ran OK. "
                f"Matter={matter_name}. "
                f"Tools={allowed_tools or []}. Instruction={instruction[:60]}."
            )
        _base.skill_generate = _mock
    elif mode == "live":
        async def _haiku(prompt, deps=None, allowed_tools=None):
            from pydantic_ai import Agent
            from pydantic_ai.models.anthropic import AnthropicModel
            short = prompt[:1500] + "\n\n[SIMULATION -- respond in under 80 words]"
            agent: Agent[None, str] = Agent(
                model=AnthropicModel(model), output_type=str
            )
            res = await agent.run(short)
            return res.output
        _base.skill_generate = _haiku

    t0 = time.monotonic()
    try:
        if no_write or mode == "dry":
            result = await skill.execute(ctx)
        else:
            from notion_bridge.client import NotionBridge
            from notion_bridge.project_pages import ProjectPages
            from config import settings
            bridge = NotionBridge(token=settings.notion_token)
            pages = ProjectPages(bridge)
            result = await skill.run(ctx, pages)

        elapsed = time.monotonic() - t0
        preview = textwrap.shorten(result.output or "", width=100, placeholder="...")
        return SkillRun(
            name=skill_name, mode=mode, success=result.success,
            elapsed=elapsed, output_preview=preview,
            error="" if result.success else result.summary,
            required_files=skill_name in _MOCK_FILES,
        )
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return SkillRun(
            name=skill_name, mode=mode, success=False,
            elapsed=elapsed, output_preview="",
            error=type(exc).__name__ + ": " + str(exc)[:120],
            required_files=skill_name in _MOCK_FILES,
        )
    finally:
        _base.skill_generate = orig_generate


async def run_simulation(
    mode: str, matter_name: str, only: set, skip: set,
    model: str, no_write: bool,
) -> list:
    print(_bold(f"\n--- {mode.upper()} SIMULATION --- matter: {matter_name} ---\n"))

    print(_info(f"  Fetching Notion context for '{matter_name}'..."))
    try:
        matter_id, matter_summary, matter_props = await _get_matter_context(matter_name)
        print(_ok(f"  Matter: {matter_id[:8]}...  summary: {len(matter_summary)} chars\n"))
    except Exception as e:
        print(_fail(f"  Could not fetch matter: {e}"))
        print("  Check NOTION_TOKEN and NOTION_PROJECTS_DB_ID in .env")
        return []

    # Determine which skills to run from the registry
    from alfred.skills import SKILL_REGISTRY
    names = sorted(
        n for n in SKILL_REGISTRY
        if (not only or n in only) and n not in skip
    )
    print(f"  Running {len(names)} skills (mode={mode}, model={model})\n")

    results = []
    for name in names:
        has_files = name in _MOCK_FILES
        marker = " [file]" if has_files else "       "
        print(f"  {name}{marker}...", end=" ", flush=True)
        run = await _run_one_skill(
            skill_name=name, matter_id=matter_id, matter_name=matter_name,
            matter_summary=matter_summary, matter_props=matter_props,
            mode=mode, model=model, no_write=no_write,
        )
        results.append(run)
        if run.success:
            print(_ok(f"{run.elapsed:.1f}s") + f"  {run.output_preview[:80]}")
        else:
            print(_fail(f"{run.elapsed:.1f}s") + f"  {run.error[:100]}")

    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(results: list, mode: str) -> None:
    if not results:
        return
    passed = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    file_skills = [r for r in results if r.required_files]

    print(_bold(f"\n--- RESULTS --- {mode.upper()} ---\n"))
    print(f"  Total     : {len(results)}")
    print(_ok(f"  Passed    : {len(passed)}"))
    if failed:
        print(_fail(f"  Failed    : {len(failed)}"))
    print(f"  File-based: {len(file_skills)} (mock files injected)")

    if mode != "structure":
        total = sum(r.elapsed for r in results)
        print(f"  Time      : {total:.1f}s total, {total/max(len(results),1):.1f}s avg")

    if failed:
        print(f"\n{BOLD}{RED}Failed:{RESET}")
        for r in failed:
            print(f"  {_fail(r.name)}")
            print(f"    {r.error}")

    if mode == "structure" and not failed:
        print(_ok("\n  All skill files valid. Registry complete. Frontend coverage confirmed."))

    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulate all KLG skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mode", choices=["structure", "dry", "live"], default="structure")
    parser.add_argument("--matter", default="")
    parser.add_argument("--only", default="")
    parser.add_argument("--skip", default="")
    parser.add_argument("--model", default="claude-haiku-4-5-20251001")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    if args.mode in ("dry", "live") and not args.matter:
        print(_fail("--matter is required for dry and live modes"))
        return 1

    if args.mode == "structure":
        results = run_structure_check(only, skip)
    else:
        results = asyncio.run(run_simulation(
            mode=args.mode, matter_name=args.matter,
            only=only, skip=skip, model=args.model, no_write=args.no_write,
        ))

    print_report(results, args.mode)

    if args.output:
        data = [
            {
                "name": r.name, "mode": r.mode, "success": r.success,
                "elapsed_s": round(r.elapsed, 2), "error": r.error,
                "output_preview": r.output_preview, "required_files": r.required_files,
            }
            for r in results
        ]
        Path(args.output).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"Results written to: {args.output}")

    return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
