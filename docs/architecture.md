# Alfred Architecture: Three Layers

## Layer 1 — Interface

Two tiers, both routing through the same Layer 2 brain.

### Primary: Deep Work (Custom Web App / Open WebUI)

Where long sessions happen: brief drafting, case assessment, full skill workflows, multi-session research.

- Left sidebar: KLG Skills list (Case Assessment, Response Plan, Brief Elevation, Oral Argument)
- Model selector in chat header: Claude / ChatGPT / Gemini — model-agnostic by design
- Supported models: Sonnet 4.6, Opus 4.6/4.7, Gemini 3.1 Pro, GPT-5.x, and open-source models

The reason we use Open WebUI or a custom app rather than Claude.ai is **model flexibility**. Claude.ai locks the team to Claude. The custom interface does not — the team can direct any query to any foundation model from the same window.

### Secondary: Quick Query (Slack Bot)

Single-exchange requests that don't need a full session.

- Lives in `#alfred-quick-query` channel
- Deadline lookups, matter status, task creation
- Example: `@Alfred What's the next deadline on Moda?` → `Next filing deadline: Reply brief due May 14.`

Both tiers route through the same Layer 2 routing layer.

---

## Layer 2 — Routing (Alfred's Brain)

A software application hosted on a cloud server (DigitalOcean droplet or similar). It sits between the interface and the models. Open WebUI (or whatever we use) is configured to point to the routing layer's address instead of pointing directly to a model API.

### Four-Step Pipeline

```
Incoming Query
     │
     ▼
1. Query Classification
     │  categorizes: "Legal Analysis — Brief Drafting"
     ▼
2. Skill Selection
     │  loads: skills/klg-response-plan.md from GitHub
     ▼
3. Model Routing
     │  primary: Claude Opus
     │  secondary: ChatGPT GPT-5 (braiding enabled)
     ▼
4. API Dispatch
     │  fires parallel API calls
     ▼
Synthesized Response → Interface
```

### Routing Decision Log (JSON)

Each query produces a routing log entry:

```json
{
  "query_type": "brief_drafting",
  "skill": "klg-response-plan",
  "primary_model": "Claude Opus",
  "secondary_model": "ChatGPT GPT-5",
  "braiding": true
}
```

### Braiding

When `braiding: true`, the routing layer fires **parallel, isolated** calls to Claude and ChatGPT on the same query. Both responses surface in the interface for attorney comparison. This replaces the current manual workaround of running both tools separately.

**Claude Opus output:** Issues, Authorities (with citations), Argument Structure
**ChatGPT output:** Strategic Frame, Risk Points, Persuasive Angle

### Skills Storage

Skills are `.md` files in the `skills/` directory of this repo. The routing layer reads the correct file on each call and injects it as the system prompt — the same way Claude.ai loads a project instruction at the start of every session.

**Promotion path:**
1. Develop and refine the skill in Claude.ai
2. Copy the skill text to `skills/<skill-name>.md`
3. Commit to GitHub
4. Routing layer picks it up automatically on the next call

Storing skills in GitHub rather than inside Claude.ai makes them **model-agnostic**: the same skill file can be loaded into a Claude call, a ChatGPT call, or any other foundation model.

---

## Layer 3 — Models (The Intelligence)

| Model | Role |
|---|---|
| Claude API (Opus/Sonnet) | Primary — all legal reasoning, skill execution, production work |
| ChatGPT API | Braiding — independent strategic review |
| Image models | Visual generation |
| Claude Haiku | High-volume, low-complexity tasks (cost control) |

No free or local models in the production stack.

Claude.ai remains the **development environment** — nothing changes about how we build and refine skills there.

---

## Notion as the Data Layer

Notion is what makes Alfred firm-specific rather than generic. Before dispatching to models, the routing layer pulls context from Notion:

- Matter context from the Projects database and Case Portals
- Team workload from Team Portals and Tasks
- Prior research from WestLaw Research
- Communications from the Comms Log
- Bloodhound signal from the Watch List and Issues & Causes databases

Without the Notion connection, Alfred has no knowledge of KLG matters, deadlines, or institutional memory — it's just a model selector.

See `docs/notion-integration.md` for the full database access map and setup steps.
