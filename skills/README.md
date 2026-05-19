# KLG Skills

This directory contains all KLG skill files. Each skill is a `.md` file that the Alfred routing layer loads as the system prompt when a query is classified to that skill.

## Promotion Path

1. Develop and refine the skill in Claude.ai (Project instructions)
2. Copy the final skill text into a new file here: `skills/<skill-name>.md`
3. Commit to GitHub
4. Alfred picks it up automatically on the next call — no redeploy needed

## Naming Convention

Use lowercase kebab-case: `klg-response-plan.md`, `case-assessment.md`, `brief-elevation.md`, `oral-argument.md`.

## Current Skills

| File | Skill | Status |
|---|---|---|
| `klg-response-plan.md` | KLG Response Plan | Stub — needs full skill text |

## Skill File Format

A skill file is plain Markdown. The routing layer reads it verbatim and injects it as the system prompt. Structure it exactly as you would a Claude.ai project instruction:

```markdown
# [Skill Name]

## Role
You are Alfred, KLG's AI executive assistant...

## Context
[Firm-specific context the model needs to know]

## Instructions
[Step-by-step skill execution instructions]

## Output Format
[Expected format for the response]
```
