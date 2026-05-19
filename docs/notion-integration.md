# Notion Integration Guide

Alfred and Bloodhound connect to the KLG Notion workspace via a single internal integration token. This page documents setup, the database access map, and the schemas for the two new databases that need to be created.

---

## Setup

### Step 1: Create the Integration (Tim's action)

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **New integration**
3. Name it **KLG AI OS**, associate with the KLG workspace
4. Under **Capabilities**, enable: Read content, Update content, Insert content
5. Copy the Internal Integration Token — it starts with `ntn_` or `secret_`
6. Share the token with Edwyn via a secure channel (not Slack plaintext)

### Step 2: Connect Databases to the Integration

For every database Alfred or Bloodhound needs to read, you must explicitly grant access:

1. Open the database in Notion
2. Click the `...` menu (top right) → **Connections** → **Add connections**
3. Select **KLG AI OS**

> Without this step the API returns a 404 even with a valid token. This is by Notion's design — integration tokens don't have blanket workspace access.

### Step 3: Set the Token in Your Environment

```bash
NOTION_TOKEN=your_token_here
```

See `.env.example` for all required environment variables.

---

## Database Access Map

### Alfred (reads from / writes to)

| Database | Collection URL | Access | Purpose |
|---|---|---|---|
| Projects | `collection://df007c24-ffac-40d7-8e91-fb6763b6ecf6` | Read/Write | Matter milestones, deadlines, owner assignments |
| Tasks | `collection://c60b4989-61ac-40b3-956f-8fdce828da32` | Read/Write | Task tracking, task creation |
| Comms Log | `collection://2e40fc06-a06c-81f0-aca8-000bce804f3f` | Read | Meeting notes, huddles, communications digest |
| WestLaw Research | `collection://30a0fc06-a06c-8141-8dcf-000bc4b6733c` | Read | Legal research library queries |
| AI OS Improvement Backlog | `collection://68dcce51-defa-45aa-b7c7-389f37c16005` | Read/Write | Logs skill improvement suggestions |
| Case Portals | Page tree `/2c00fc06a06c80d2b752c77a5b871b95` | Read | Per-matter context |
| Team Portals | Page `/3240fc06a06c80f394a2e04ff536d738` | Read | Team member workload views |
| Watch List *(new)* | TBD after creation | Read | Bloodhound cross-queries during case assessment |
| Issues & Causes *(new)* | TBD after creation | Read | Doctrinal context for case assessments |

### Bloodhound (reads from / writes to)

| Database | Access | Purpose |
|---|---|---|
| Watch List *(new)* | Read/Write | Core database — one row per tracked case |
| Issues & Causes *(new)* | Read/Write | Doctrinal map — one row per issue area |
| Contacts | Read/Write | Speaker and co-counsel relations (extended) |
| Projects | Read | Closed-case post-mortems seed the Watch List |
| Comms Log | Read | Ingests newsletter digests and alert summaries |

---

## New Databases to Create

Both databases go inside the existing KLG workspace. Recommended location: under the AI OS page (`/27a0fc06a06c80d2bdc0c77d2e5e67c9`) or as a dedicated "Bloodhound" section on the Firm Resources Portal.

### Watch List Database

One row per case being tracked outside KLG's own active matters.

| Property | Type | Notes |
|---|---|---|
| Case Name | Title | Required |
| Court | Select | 9th Cir, SCOTUS, EDCA, CDCA, etc. |
| Docket No. | Text | Full docket string |
| Issue Area | Multi-select → Relation | Relation to Issues & Causes DB |
| Tier | Select | 1 = permanent watch, 2 = active tracking, 3 = passive |
| Source | Select | CourtListener, Newsletter, Referral, PLF, etc. |
| Procedural Posture | Text | Brief summary of current stage |
| Next Deadline | Date | Next filing or argument date |
| KLG Nexus Note | Text | Why this matters to KLG |
| Status | Select | Watching / Engaged / Closed |
| Added By | Person | |
| Last Updated | Last edited time | |

### Issues & Causes Database

One row per doctrinal issue or policy area KLG cares about. This list is evergreen — rows are almost never deleted, only tiered down.

| Property | Type | Notes |
|---|---|---|
| Issue Name | Title | Required |
| Tier | Select | 1 = permanent, 2 = active interest, 3 = passive |
| Seeded From | Relation | → Projects (closed matters that raised this issue) |
| Description | Text | 2–4 sentences on why KLG cares |
| Active Cases | Relation | → Watch List (cases currently touching this issue) |
| Key Contacts | Relation | → Contacts DB |
| Active | Checkbox | |

### Contacts Database Extensions

Add these three relation properties to the existing Contacts database:

- **Issues & Causes** → Issues & Causes DB (which issues this person focuses on)
- **Cases (Watch List)** → Watch List DB (cases they're counsel on or amicus filers)
- **Podcast Episodes** → Podcast Episodes DB (if it exists; otherwise create a stub)

---

## The Comms Log as Bloodhound's Intake Pipeline

The Comms Log already functions as the firm's digest layer for meetings and huddles. Bloodhound extends it by using it as the intake channel for external signals.

**William's intake practice:**
- Legal newsletter digests → one Comms Log entry per newsletter/alert, tagged with source and date
- CourtListener alert summaries → one entry per new filing on a tracked issue
- Movement-org press releases (PLF, IJ, NCLA, FIRE, Cato) → one entry per relevant announcement

Each entry is 2–4 sentences. Alfred and Bloodhound read the Comms Log and triage entries automatically into the Watch List and Issues & Causes databases.

A Comms Log entry template for intake:

```
Source: [newsletter name / CourtListener / org name]
Date received: [date]
Summary: [2–4 sentences on what it says and why it matters to KLG]
Issue tags: [issue areas from Issues & Causes DB]
Action taken: [Logged / Triaged to Watch List / No action needed]
```

---

## Key Notion Pages

| Resource | URL |
|---|---|
| KLG Firm Resources Portal | `/1a2a5a8fc17c41bda5bebbb63c10599f` |
| AI OS Hub | `/27a0fc06a06c80d2bdc0c77d2e5e67c9` |
| Alfred & Bloodhound Architecture Doc | `/3650fc06a06c817dac91cbd3eb230af1` |
| KLG AI OS Rollout Project | `/3580fc06a06c8152ba12c5b9ebc0b6eb` |
| AI OS Improvement Backlog | `/a8b8f7ea2d34420eb450728638efd917` |
| Projects DB | `/01c88dba9dd8471582f4335837d3fa89` |
