# Alfred — Routing Layer

This directory contains the Layer 2 routing application: the software that sits between the interface and the AI models.

## What It Does

1. Receives a query from the interface (web app or Slack bot)
2. Classifies the query type
3. Selects the appropriate skill file from `../skills/`
4. Routes to the correct model(s) — Claude as primary, ChatGPT for braiding
5. Dispatches API calls and returns the response

## Architecture

```
Interface (web app / Slack bot)
        │
        ▼
  ┌─────────────┐
  │   Alfred    │  ← this directory
  │   Routing   │
  │    Layer    │
  └──────┬──────┘
         │
    ┌────┴────┐
    │  Skills │  ← ../skills/
    └────┬────┘
         │
   ┌─────┴─────┐
   │  Model    │
   │  APIs     │
   │           │
   │  Claude   │
   │  ChatGPT  │
   └───────────┘
```

## Braiding

When `BRAIDING_ENABLED=true` (see `.env.example`), flagged queries fire parallel isolated calls to both Claude and ChatGPT. Both responses surface in the interface for comparison before a synthesized reply is returned.

## Skills

Skills are `.md` files in `../skills/`. The routing layer reads the correct file per query and injects it as the system prompt. Changing a skill = editing the `.md` file and committing. No redeploy needed.

## Environment

Requires `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `NOTION_TOKEN`, and `SLACK_BOT_TOKEN`. See `.env.example` at the repo root.
