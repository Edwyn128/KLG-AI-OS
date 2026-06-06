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
    Only needed if you enable the ChatGPT Deep Research hand-off — where
    Alfred writes a research prompt and triggers a ChatGPT session for
    long-form legal research (4,000–6,000 word memos).
    Leave empty if you're not using that feature yet.
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

    # ── Security ──────────────────────────────────────────────────────────────

    app_password: str = ""
    """
    OPTIONAL in dev, REQUIRED in production.
    Shared password for HTTP Basic Auth — all 7 team members use the same one.
    The browser prompts once and caches it for the session.
    Set a strong value in Railway environment variables.
    When empty, auth is disabled (dev mode only — never deploy with this empty).
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

    # ── Model Selection ───────────────────────────────────────────────────────
    # Centralizing model IDs here means a model upgrade is a one-line .env change.
    # You don't have to hunt through multiple files to swap claude-sonnet-4-6
    # for claude-opus-4-7 when you want more reasoning power.

    alfred_model: str = "claude-sonnet-4-6"
    """
    The Claude model Alfred uses for skill execution and conversation.
    claude-sonnet-4-6 is the recommended default — fast, highly capable,
    cost-effective for the volume of daily queries Alfred handles.
    Switch to claude-opus-4-7 for the most demanding synthesis tasks.
    """

    bloodhound_model: str = "claude-sonnet-4-6"
    """
    The Claude model Bloodhound uses for signal triage and analysis.
    Bloodhound runs daily/weekly, so cost per run matters.
    Sonnet is the right balance; upgrade to Opus only if triage quality suffers.
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
