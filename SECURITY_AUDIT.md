# KLG AI OS — Security Audit (Pre-Phase-3 Baseline)

Date: June 10, 2026
Scope: full codebase (Alfred, Bloodhound, bridges, agents, API, web UI, deployment)
Purpose: identify every gap that would become a breach vector in a client-facing
version (per-matter tokens, client-mode Alfred), and document what must change
before Phase 3 is specced.

This is an AI-generated audit. Findings were verified against source with
file:line references, but attorney and engineering review is required before
acting on the recommendations. Nothing here is a sign-off.

---

## Executive summary

The system is acceptable for internal-only use by a small trusted team. It is
not safe to expose to clients in its current form, for one structural reason
above all the individual findings:

There is no authorization layer, only authentication. One shared password
(or any per-user password) grants access to every matter, every document
search, every tool, and every agent trigger. Nothing in the codebase asks
"is this user allowed to see this matter?" because today the answer is always
yes. A client-facing version inverts that assumption, so per-matter scoping
must be designed in, not bolted on.

Verified during this audit: `.env` is gitignored and has never been committed
(`git log --all -- .env` is empty). Live API keys exist only in the local
`.env` and Railway env vars. Keep it that way; rotate any key that ever
appears in logs or screen shares.

---

## Findings

Severity reflects impact on a future client-facing deployment. Items marked
[INTERNAL-OK] are tolerable today but block Phase 3.

### Critical

C1. No per-matter or per-user authorization. [INTERNAL-OK]
- `api/routes/alfred.py:454` `/alfred/matters` returns every matter to any
  authenticated caller. `api/routes/cases.py` `/cases/{page_id}` returns full
  matter detail for any page id.
- Alfred's tools are equally unscoped: `get_all_active_matters`
  (`notion_bridge/project_pages.py`), `search_notion` (workspace-wide
  full-text search, `alfred/agent.py:528`), `search_sharepoint` (all of
  SharePoint when `folder_path` is empty, `alfred/agent.py:913`),
  `get_team_workload` (any person's workload, `alfred/agent.py:746`).
- Phase 3 requirement: every data access must carry a validated
  user-and-matter context, enforced server side (Notion relation filters,
  SharePoint folder scoping per client), not in the prompt.

C2. Client-supplied identity. The `user` field on `ChatRequest`
(`api/routes/alfred.py:69`) is a free-text string used for logging and the
Comms Log. Any authenticated caller can claim to be Tim. The master password
(`main.py:135`) compounds this: it validates any username, so audit trails
cannot distinguish people. Replace with identity derived from the credential,
and retire the master password before any client exposure.

C3. CORS wildcard in production. `main.py:345` sets `allow_origins=["*"]`
with `allow_credentials=True` when `debug` is false. The comment above it
says the wildcard is intentionally absent; the code contradicts the comment.
Today exploitability is limited because the Basic Auth header is attached by
the app's own JavaScript, not by the browser. It still must be pinned to the
Railway origin now, and absolutely before any token or cookie scheme exists.

C4. Prompt injection reaches tools that write and send. Untrusted text enters
the model context from three directions with no sanitization or privilege
separation:
- Bloodhound RSS feed content → triage agent (`bloodhound/feed_ingestor.py:247`,
  `bloodhound/signals.py:154` caps length but does not strip payloads).
- Slack messages → Alfred (`api/routes/slack.py`).
- Notion page bodies → Alfred via every summary tool.
An injected instruction can then invoke `send_slack_message` (exfiltration to
any DM or channel, `alfred/agent.py:977`), `update_matter_status`,
`create_new_matter`, or `log_action_to_matter`. Mitigations: read-only triage
agent for Bloodhound; for Alfred, treat retrieved content as data (delimiter
framing), require confirmation for outbound sends triggered by retrieved
content, and channel allow-lists. For a client mode: no write or send tools
at all.

### High

H1. Credentials persisted in browser localStorage with no expiry
(`web/index.html:594,670`). Plaintext password, survives indefinitely, shared
machines retain it, any XSS reads it. Move to short-lived server-issued
session tokens (httpOnly cookies) before Phase 3; at minimum switch to
sessionStorage and add an inactivity timeout now.

H2. XSS via unescaped Notion-controlled data in the case file view.
`web/index.html` interpolates the matter name and related fields into
`innerHTML` without `escapeHtml()` in the case header rendering (around line
1987), while other paths escape correctly. Chat rendering escapes `<>&`
before formatting, so the chat path is materially safer than it first looks,
but the case-view gap means a matter name containing markup executes in every
viewer's browser. Fix by escaping all interpolations or building nodes with
`textContent`. Add a Content-Security-Policy header as a backstop.

H3. No security headers at all. No CSP, X-Frame-Options, X-Content-Type-
Options, HSTS, or Referrer-Policy anywhere in `main.py`. One small middleware
fixes this.

H4. Slack signature verification is conditional. `api/routes/slack.py:68`
verifies the HMAC only when `SLACK_SIGNING_SECRET` is set; unset, the
endpoint accepts any POST as a Slack event. Fail closed: if Slack is
configured without a signing secret, refuse to process events (or refuse to
start).

H5. Cron secret is a full-bypass static credential. A valid `X-Cron-Secret`
header skips Basic Auth and rate limiting for every endpoint
(`main.py:171-177`). Scope it to the agent-trigger endpoints only, and rate
limit it.

### Medium

M1. Rate limiting covers POST only (`main.py:154`). GET endpoints, including
`/auth/check`, are brute-forceable and enumerable without throttling. Extend
the limiter to all methods and add lockout/backoff on `/auth/check`.

M2. Activity log role check is a hardcoded set. `_ACTIVITY_ALLOWED =
{"tim", "stu"}` plus username parsing from the Basic header
(`api/routes/alfred.py:355-388`). Works today; combined with the master
password (C2), anyone holding it can read the firm-wide activity feed by
sending username "tim".

M3. Comms Log stores full prompts and responses. `log_interaction`
(`notion_bridge/comms_log.py:157-183`) writes the user's message and Alfred's
full reply, including matter detail, into a firm-wide Notion database. Fine
internally; a client-facing version must log metadata only (timestamp, tool
names, model), never content, and never into a shared log.

M4. Slack file proxy lacks an ownership check. `/slack/file/{file_id}`
(`api/routes/cases.py:132`) downloads any file the bot can reach, regardless
of which case the viewer opened. Validate the file belongs to the matter's
channel.

M5. Conversation history is client-held with no scoping or TTL.
`ChatRequest.history` round-trips the full serialized conversation through
the browser (`api/routes/alfred.py:83-118`). Internally tolerable; for
clients, history must live server side, keyed to the authenticated session,
with expiry and revocation.

M6. Container runs as root (`Dockerfile` has no `USER` directive). Add a
non-root user.

M7. MCP server (`mcp_server.py`) exposes full read/write tools with no
authentication of its own. It is safe only as a local, single-operator
process. Never deploy it as a shared or remote service without adding auth.

### Low

L1. `/docs` and `/redoc` correctly gated behind `debug`, but nothing stops a
production deploy with `DEBUG=true`. Log a loud warning (or refuse) when
debug is on and a Railway env is detected.
L2. Loose dependency pins (`fastapi>=0.115.0`, `mcp>=1.0.0`). Pin upper
bounds; enable Dependabot.
L3. No Slack event replay protection beyond the 5-minute timestamp window.
Track event ids if this ever matters.

### Corrections to raw scan output

Two findings from the automated pass were wrong and are excluded:
- "/alfred/chat has no authentication" — false. `_BasicAuthMiddleware`
  (`main.py:335`) covers every route outside the exempt list, including all
  Alfred routes. The real issue there is C2 (unverified identity), not
  missing auth.
- "Chat markdown rendering is trivially XSS-able" — overstated. The chat
  path escapes HTML before insertion. The exploitable gap is the case-view
  interpolation (H2).

---

## Client-facing readiness: what Phase 3 requires before any spec

1. Identity and tokens. Per-client credential (signed token carrying
   client_id + matter_id, short expiry, revocable). No shared passwords, no
   master password, identity always derived server side.
2. Authorization middleware. Every endpoint and every tool call filters by
   the token's matter scope. Deny by default. The current endpoints cannot be
   reused as-is; they need a scoped variant or a mandatory filter layer.
3. A separate client agent, not a prompt switch on Alfred. Client-mode must
   be a different agent object with its own system prompt and a minimal
   read-only toolset (one tool: get_client_matter_status(matter_id from
   token)). Prompt-level restrictions on the full-tool Alfred are not a
   security boundary; prompt injection (C4) defeats them.
4. Server-side sessions, metadata-only logging, audit trail per access.
5. Data partitioning upstream: client-visible status fields in Notion kept
   separate from strategy/work-product fields; SharePoint foldered per
   client; Bloodhound and Comms Log never reachable from the client path.
6. Web hardening from H1-H3, CSRF protection, and an external penetration
   test before launch.

## Draft: what client-mode Alfred may and may not disclose

Draft for Tim's review and sign-off. This list defines the entire universe of
client-mode output; anything not listed as allowed is denied.

Allowed (status and next steps only):
- Current procedural stage of the client's own matter (e.g., "Respondent's
  brief filed; awaiting reply brief deadline").
- Court-set deadlines and hearing dates already known to the client or on the
  public docket.
- The next procedural step and a plain-language explanation of what it means.
- Documents already filed or served in the client's matter (titles and dates,
  not drafts).
- Logistics: who to contact at the firm, how to send documents.

Never disclosed, regardless of phrasing:
- Strategy, case theory, candid assessments, or odds of success.
- Work product: drafts, research memos, internal notes, Comms Log content.
- Internal assignments, team workload, or scheduling ("who is working on my
  case and what else are they doing" is out).
- Anything about any other matter or client, including existence.
- Bloodhound intelligence, Watch List content, or doctrine tracking.
- Settlement positions or negotiation posture.
- Internal soft deadlines or reminders not set by a court.
- Legal advice. Client-mode Alfred reports status; it does not advise. Any
  "should I" question gets a referral to the attorney.

Enforcement note: this policy must be enforced by the toolset (the client
agent can only read a pre-filtered status view), not by the prompt alone. The
prompt states the policy; the architecture makes violations impossible.

---

## Suggested remediation order (internal hardening, pre-Phase-3)

1. C3 CORS pin, H3 security headers, H4 fail-closed Slack verification
   (small, same-day changes).
2. M1 rate limiting on all methods + /auth/check lockout; H5 cron scope.
3. H2 case-view escaping; H1 session handling in the web UI.
4. C2 retire master password, derive identity from credentials.
5. C4 prompt-injection mitigations (read-only Bloodhound triage, confirm
   outbound sends, content framing).
6. M6 non-root container; L2 dependency pinning.
Then, and only then, spec Phase 3 against the readiness list above.
