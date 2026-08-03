"""
config.py — Centralized configuration for the KLG AI Operating System.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHY THIS FILE EXISTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This file is the single source of truth for all configuration. Every other
module in this codebase imports `settings` from here — nothing reads
os.environ directly. This discipline gives us three things:

  1. FAIL FAST: If ANTHROPIC_API_KEY is missing, the app crashes at startup
     with a clear error, not mid-request with a confusing KeyError buried in
     a stack trace three calls deep.

  2. ONE PLACE TO CHANGE: When a variable name changes (e.g., NOTION_TOKEN →
     NOTION_API_TOKEN), you update it here. Everywhere else just uses
     `settings.notion_token` and doesn't care what the env var is called.

  3. SELF-DOCUMENTING: Opening this file tells you exactly what env vars the
     whole application needs. No more hunting through random files wondering
     why production is broken.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW IT WORKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pydantic-settings reads variables in this priority order (highest wins):
  1. Real environment variables (set in your shell or deployment platform)
  2. Values in the .env file in the project root
  3. Default values declared in the Settings class below

If a field has no default and no value is found in (1) or (2), pydantic-settings
raises a ValidationError at import time — the app never starts.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    from config import settings

    client = AsyncClient(auth=settings.notion_token)
    model  = AnthropicModel(settings.alfred_model)
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    All environment-driven configuration for the KLG AI OS.

    Fields with no default value are REQUIRED — the app will not start
    without them. Fields with a default value are OPTIONAL — they work
    out of the box but can be overridden via .env or environment variable.
    """

    model_config = SettingsConfigDict(
        # Load from a .env file in the same directory as this file.
        # python-dotenv handles the file reading; pydantic-settings validates.
        env_file=".env",
        env_file_encoding="utf-8",
        # ANTHROPIC_API_KEY and anthropic_api_key are treated identically.
        # This is the standard Python convention for env var names.
        case_sensitive=False,
        # Silently ignore env vars that don't map to any field here.
        # Without this, a stray DEBUG_MODE=1 in your shell would crash startup.
        extra="ignore",
    )

    # ── AI API Keys ───────────────────────────────────────────────────────────

    anthropic_api_key: str
    """
    REQUIRED. Your Anthropic API key (starts with sk-ant-).
    Alfred runs on Claude via this key. Every Alfred skill execution and
    every Bloodhound triage pass uses this key.
    Get one at: https://console.anthropic.com/settings/keys
    """

    openai_api_key: str = ""
    """
    OPTIONAL. Your OpenAI API key.
    Required for GPT-4o and GPT-4o-mini model routing via Alfred's chat endpoints,
    and for the ChatGPT Deep Research tool (long-form legal research memos).
    Leave empty if you're not using those features yet.
    """

    google_api_key: str = ""
    """
    OPTIONAL. Google AI API key (starts with AIza...).
    Required for Gemini model routing via Alfred's chat endpoints.
    Get one at: https://aistudio.google.com/app/apikey
    Set GOOGLE_API_KEY in Railway env vars to activate.
    """

    perplexity_api_key: str = ""
    """
    OPTIONAL. Perplexity API key (starts with pplx-).
    Required for Perplexity Sonar model routing via Alfred's chat endpoints.
    Sonar Pro provides real-time web search grounded in cited sources — useful
    for legal news, docket lookups, and current-events research.
    Get one at: https://www.perplexity.ai/settings/api
    Set PERPLEXITY_API_KEY in Railway env vars to activate.
    """

    tavily_api_key: str = ""
    """
    OPTIONAL. Tavily API key (starts with tvly-).
    Powers Alfred's web_search tool — mid-conversation web search built
    specifically for AI/LLM use. Returns synthesized answers + source results
    with quality filtering. Better than DuckDuckGo for legal research queries.
    Free tier: 1,000 searches/month (sufficient for a 6-person firm).
    Get one at: https://app.tavily.com
    Set TAVILY_API_KEY in Railway env vars to activate.
    """


    # ── Notion ────────────────────────────────────────────────────────────────

    notion_token: str
    """
    REQUIRED. Notion internal integration token (starts with ntn_ or secret_).

    This token is what lets the app read and write to your Notion workspace.
    Think of it as the app's username+password for Notion combined.

    IMPORTANT STEP PEOPLE MISS: After creating the integration at
    notion.so/my-integrations, you must also go into each Notion database
    and share it with the integration (database "..." menu → Add connections).
    Without this, the API returns 404 for pages that definitely exist.
    """

    notion_projects_db_id: str = ""
    """
    The Notion database ID for the Projects/Matters database.

    This is the Layer 1 database — it holds all active matter project pages
    (Petersen, Sakauye, Diller, etc.). Alfred reads this to answer questions
    like "what's pending on Petersen?" and writes to it after skill execution.

    Leave empty during initial setup; fill in once you've located the DB ID.
    """

    notion_watch_list_db_id: str = ""
    """
    Bloodhound's Watch List database ID.
    One row per case being actively tracked (case name, court, docket,
    issue area, tier, procedural posture, KLG nexus note, status).
    """

    notion_issues_db_id: str = ""
    """
    Bloodhound's Issues & Causes database ID.
    One row per doctrinal issue KLG cares about (e.g., "supersedeas exceptions",
    "First Amendment overbreadth", "public employee speech"). Tier 1 issues
    are seeded from closed-case post-mortems and stay permanently.
    """

    notion_contacts_db_id: str = ""
    """
    The extended Contacts database ID.
    Extended with relations to Issues, Cases, and Podcast Episodes so that
    prior guests, co-counsel, and network nodes are tied to the doctrinal map.
    """

    notion_comms_log_db_id: str = ""
    """
    Comms Log database ID.
    Every email sent to CaseFile@KowalLawGroup.com or Events@KowalLawGroup.com
    lands here as a row. Fields include: From, To, Comm Date, Email Text,
    Summary, Actions (Respond/Done/N/A), Pin, and relations to Projects and
    Case Portal. Alfred reads this to surface unprocessed communications,
    matter-specific email threads, and pinned items needing attention.
    """

    notion_users_db_id: str = ""
    """
    KLG Users database ID — stores per-user role flags and permissions.
    Create a Notion database called "KLG Users" with: Name (title),
    Display Name (text), Role (select), Email (email), is_admin (checkbox),
    is_super_admin (checkbox), is_accounting (checkbox), Active (checkbox),
    and task-permission checkboxes. Share with the Notion integration, then
    set NOTION_USERS_DB_ID in Railway env vars.
    Leave empty to fall back to the hardcoded role sets in main.py.
    """

    notion_alfred_notes_db_id: str = ""
    """
    Alfred Notes database ID — Alfred's persistent cross-session memory layer.

    Create a Notion database called "Alfred Notes" with these properties:
      Name (title)        — short label, e.g. "Tim: prefers firm deadlines"
      Category (select)   — Preference | Matter | OppCounsel | Deadline | FirmKnowledge | Other
      Matter (text)       — matter name this note relates to (blank = firm-wide)
      Body (rich_text)    — full note content
      Recorded By (text)  — who triggered the save
      Active (checkbox)   — true by default; set false to retire without deleting

    Set NOTION_ALFRED_NOTES_DB_ID in Railway env vars after creating the database.
    Leave empty to disable Alfred Notes (Alfred will operate without persistent memory).
    """

    # ── Slack ─────────────────────────────────────────────────────────────────

    slack_bot_token: str = ""
    """
    OPTIONAL. Slack bot token (starts with xoxb-).

    Required for the Layer 3 background agents (deadline-watch, weekly agenda,
    hygiene scan) to post their alerts to Slack. If empty, those agents will
    log to the console instead of posting to Slack — useful during development.

    ARCHITECTURAL NOTE: Background agents post to Slack but NEVER modify
    Notion project pages directly. Only skills (Layer 2) write to Notion.
    This separation keeps the audit trail clean and prevents agents from
    accidentally overwriting in-progress skill work.
    """

    slack_case_management_channel: str = "#case-management"
    """
    The Slack channel where weekly agenda and hygiene alerts go.
    The bot must be invited to this channel before it can post.
    Individual matter alerts go to matter-specific channels (configured per matter).
    """

    # ── SharePoint / Microsoft Graph ──────────────────────────────────────────

    sharepoint_tenant_id: str = ""
    """
    Azure AD tenant ID (GUID). Found in Azure Portal → Azure Active Directory → Overview.
    Required for SharePoint file search and document access via Microsoft Graph.
    """

    sharepoint_client_id: str = ""
    """
    Azure app registration client ID. Required for SharePoint access.
    Grant the app: Sites.Read.All and Files.Read.All in Microsoft Graph permissions.
    """

    sharepoint_client_secret: str = ""
    """
    Azure app registration client secret. Create in Azure Portal → App registrations
    → Certificates & secrets → New client secret.
    """

    sharepoint_site_url: str = ""
    """
    The base SharePoint site URL, e.g. https://yourorg.sharepoint.com/sites/KLG
    Alfred uses this to scope file searches to the KLG document library.
    """

    sharepoint_monitor_folder: str = "/Matters"
    """
    Root SharePoint folder path to watch for file and folder changes.
    The delta monitor tracks everything under this path.
    Default: /Matters  (KLG's top-level matter folder)
    """

    sharepoint_monitor_channel: str = "#sharepoint-activity"
    """
    Slack channel where SharePoint change notifications are posted.
    Create this channel and invite the bot before enabling the monitor.
    Set SHAREPOINT_MONITOR_CHANNEL in Railway env vars to override the default.
    """

    notion_system_state_db_id: str = ""
    """
    KLG System State database ID — lightweight Notion KV store for persisting
    system tokens across Railway redeploys (e.g., SharePoint delta links).

    Create a Notion database called "KLG System State" with two properties:
      Name  (title)      — key string
      Value (rich_text)  — stored value (up to 2000 chars)

    Share the database with the Notion integration and paste the DB ID here.
    Leave empty to skip delta token persistence (monitor resets on each deploy).
    """

    # ── Slack (inbound / events) ──────────────────────────────────────────────

    slack_signing_secret: str = ""
    """
    Slack app signing secret — used to verify that inbound webhook requests
    actually came from Slack. Find it at api.slack.com/apps → your app
    → Basic Information → App Credentials → Signing Secret.
    Required for the /slack/events endpoint (letting users message Alfred from Slack).
    """

    slack_alfred_channel: str = "#alfred"
    """
    The Slack channel Alfred listens in for direct queries. The bot must be
    invited to this channel. Messages that @mention the bot or start with
    'Alfred,' are routed to the Alfred agent.
    """

    slack_hygiene_enabled: bool = True
    """
    Set SLACK_HYGIENE_ENABLED=false in Railway to disable the Monday morning
    hygiene scan without disabling other Slack agents (deadline watch, weekly
    agenda, case check-in). Default true. Tim requested this be disabled while
    the matter data quality was being corrected.
    """

    slack_checkin_enabled: bool = True
    """
    Set SLACK_CHECKIN_ENABLED=false in Railway to disable the Monday/Thursday
    case check-in posts to individual matter channels. Default true.
    """

    # ── Security ──────────────────────────────────────────────────────────────

    app_password: str = ""
    """
    Master/admin override password. Accepts any username when used.
    Useful for Edwyn to log in as any user for support purposes.
    When empty AND app_passwords is empty, auth is fully disabled (dev only).
    """

    app_passwords: str = ""
    """
    Per-user passwords as a JSON object. Each team member authenticates
    with their own password tied to their identity.
    Example value for Railway:
      {"Tim":"KLG-TIM-ACCESS128","Edwyn":"KLG-EDWYN-ACCESS128",
       "William":"KLG-WILLIAM-ACCESS128","Brittney":"KLG-BRITTNEY-ACCESS128",
       "Ted":"KLG-TED-ACCESS128","Stu":"KLG-STU-ACCESS128",
       "Richard":"KLG-RICHARD-ACCESS128"}
    When set, users authenticate as username:password.
    app_password (master) is always checked as a fallback.
    """

    client_matter_map: str = ""
    """
    JSON map from client username (lowercase) to permitted matter name(s).
    Single: {"smith_client": "Smith v. CDCR"}
    Multi:  {"jones_client": ["Jones AOB", "Jones Reply"]}

    If a username appears in this map, that session is a client session:
    Alfred restricts every tool and endpoint to the listed matter(s) only,
    hides firm internals, staff names, and the Bloodhound system, and
    disables all write access.

    Leave empty to disable client mode entirely (the default — all
    authenticated users are treated as internal firm users).
    """

    microsoft_client_id: str = ""
    """
    Azure AD app registration client ID for Microsoft OAuth sign-in.
    Create at portal.azure.com → App registrations → New registration.
    Redirect URI to add: <APP_PUBLIC_URL>/auth/microsoft/callback
    Required permissions: openid, profile, email, User.Read
    Leave empty to disable "Sign in with Microsoft" on the login page.
    """

    microsoft_tenant_id: str = "common"
    """
    Azure AD tenant ID (GUID) or "common" for multi-tenant / personal accounts.
    For a single law firm, set this to your firm's Azure tenant ID so only
    @kowallaw.com accounts can sign in. Find it in Azure Portal → Overview.
    Default "common" accepts any Microsoft account (fine for dev/testing).
    """

    microsoft_client_secret: str = ""
    """
    Azure AD app client secret. Create in App registrations → Certificates & secrets.
    Required together with microsoft_client_id to complete the OAuth flow.
    """

    alfred_session_secret: str = ""
    """
    Random secret used to sign Alfred's session JWT tokens (issued after OAuth login).
    Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    Set ALFRED_SESSION_SECRET in Railway env vars. Must be at least 32 chars.
    If empty, Microsoft SSO is disabled even if the client credentials are set.
    """

    cron_secret: str = ""
    """
    Shared secret for Railway Cron Jobs. Set CRON_SECRET in Railway env vars.
    Cron requests send 'X-Cron-Secret: <value>' — the auth middleware accepts
    this as an alternative to Basic Auth so Railway can hit trigger endpoints
    without embedding a username/password in the cron command.
    """

    disable_scheduler: bool = False
    """
    Set DISABLE_SCHEDULER=true in Railway to skip APScheduler startup.
    All jobs are then driven by Railway Cron Jobs hitting the trigger endpoints.
    Keep False for local dev (APScheduler is useful there).
    """

    # ── Application ───────────────────────────────────────────────────────────

    app_host: str = "0.0.0.0"
    """
    Host to bind the FastAPI server to.
    0.0.0.0 means "listen on all network interfaces" — correct for deployment.
    Use 127.0.0.1 if you want local-only access during development.
    """

    app_port: int = 8000
    """Port number for the FastAPI server. Change if 8000 is already in use."""

    debug: bool = False
    """
    Enable FastAPI's debug mode.
    In debug mode: detailed error tracebacks are shown in the browser,
    the server auto-reloads on code changes, and extra logging is enabled.
    NEVER set to True in production — detailed tracebacks can expose secrets.
    """

    app_public_url: str = ""
    """
    The public-facing URL of this deployment (e.g. https://klg-ai-os.up.railway.app).
    Set APP_PUBLIC_URL in Railway environment variables.
    Used to restrict CORS to only this origin in production.
    Leave blank to allow only localhost (correct for local dev).
    """

    # ── Model Selection ───────────────────────────────────────────────────────
    # Centralizing model IDs here means a model upgrade is a one-line .env change.
    # You don't have to hunt through multiple files to swap claude-sonnet-4-6
    # for claude-opus-4-7 when you want more reasoning power.

    alfred_model: str = "gpt-4o"
    """
    The model Alfred uses for skill execution and conversation.
    Defaults to gpt-4o (OpenAI). Switch providers via ALFRED_MODEL in Railway
    env vars — no code change needed:
      gpt-4o             → OpenAI GPT-4o (default)
      gpt-4o-mini        → OpenAI GPT-4o-mini (cheaper, lighter tasks)
      claude-sonnet-4-6  → Anthropic Claude Sonnet
      claude-opus-4-8    → Anthropic Claude Opus (most capable)
      gemini-1.5-pro     → Google Gemini Pro
    """

    alfred_model_fallbacks: str = "claude-haiku-4-5-20251001,gpt-4o"
    """
    Comma-separated list of fallback models to try if alfred_model hits a
    billing/quota/rate-limit error. Alfred walks this list in order until one succeeds.

    Default chain:
      1. claude-haiku-4-5-20251001 — same Anthropic API key, but Tier 1 rate limit
         is 25k input TPM vs 10k for Sonnet. Handles temporary per-minute spikes
         without leaving the Anthropic ecosystem.
      2. gpt-4o — cross-provider backstop. Requires OPENAI_API_KEY in Railway.
         Silently skipped if the key is not configured.

    Override via ALFRED_MODEL_FALLBACKS in Railway env vars.
    Leave empty to disable automatic fallback.
    """

    max_upload_size_mb: int = 50
    """
    Maximum size for a single file upload to /alfred/upload, in megabytes.
    Files larger than this must use the chunked upload endpoint (/alfred/upload/chunk).
    Default 50MB keeps each request safely under Railway's 100MB proxy limit.
    Court-filing PDFs at 100–250KB/page: ~50MB covers ~200–500 pages per chunk.
    Multi-volume appendix records (400+ pages/volume) require multiple chunks.
    """

    bloodhound_model: str = "gpt-4o"
    """
    The model Bloodhound uses for signal triage and analysis.
    Defaults to gpt-4o. Set BLOODHOUND_MODEL=claude-sonnet-4-6 in Railway once
    the anthropic SDK version compatibility issue with pydantic-ai is resolved.
    """


# =============================================================================
# MODULE-LEVEL SINGLETON
# =============================================================================
#
# We instantiate Settings exactly once here. Every other module imports this
# object. This means:
#   - Validation runs once at startup, not on every import
#   - All modules share the same settings object (no risk of two instances
#     reading different .env files)
#   - Mocking in tests is easy: just patch `config.settings`
#
settings = Settings()
