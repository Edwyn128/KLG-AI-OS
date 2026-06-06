"""
main.py — FastAPI application entry point for the KLG AI OS.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Development (with auto-reload on code changes):
    uvicorn main:app --reload --port 8000

Production (no auto-reload, multiple workers for parallel requests):
    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2

After starting, open:
    http://localhost:8000        → Web UI (the Alfred/Bloodhound dashboard)
    http://localhost:8000/docs   → Interactive API documentation (Swagger UI)
    http://localhost:8000/redoc  → Alternative API docs (ReDoc)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WHAT HAPPENS AT STARTUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The lifespan() context manager runs setup code before the first request
and teardown code after the last request:

  STARTUP:
    1. Initialize NotionBridge (creates the async HTTP client to Notion)
    2. Initialize ProjectPages and WatchList (wrappers around the bridge)
    3. Initialize AlfredDependencies (bundles the above for Alfred's tools)
    4. Initialize Slack client (if SLACK_BOT_TOKEN is configured)
    5. Start the APScheduler (registers the three background agents)
    6. Store everything on app.state so route handlers can access them

  SHUTDOWN:
    1. Shut down APScheduler gracefully (waits for any running jobs to finish)

The lifespan pattern ensures we create one shared connection pool for Notion
and one Slack client — not one per request. This is important for performance
and for not hitting Notion/Slack rate limits unnecessarily.
"""

from __future__ import annotations

import base64
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config import settings

# Set up logging early — before importing any modules that might log at import time.
# The format includes timestamp, level, and module name for easy log scanning.
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# =============================================================================
# SECURITY — HTTP Basic Auth Middleware
# =============================================================================
#
# All routes except /health and /static/* require a correct APP_PASSWORD.
# /health is exempt so Railway's health-check probe works without credentials.
# /static/* is exempt because CSS/JS contains no client data.
# /slack/events is exempt because Slack sends its own HMAC signature instead.
#
# When APP_PASSWORD is empty (local dev), auth is bypassed entirely.
# In production on Railway, set APP_PASSWORD to a strong shared passphrase.
#

_AUTH_EXEMPT = {"/health", "/slack/events"}
_AUTH_EXEMPT_PREFIXES = ("/static/",)

# Simple in-memory rate limiter: track request counts per IP per minute.
# Applied in the middleware so it works without touching route signatures.
_rate_counts: dict[str, list[float]] = {}
_RATE_LIMIT_POST = 20   # max POST requests per IP per minute (chat + scan)
_RATE_LIMIT_WINDOW = 60  # seconds


def _check_rate_limit(ip: str) -> bool:
    """Return True if the request should be allowed, False if rate-limited."""
    import time
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW
    hits = _rate_counts.get(ip, [])
    hits = [t for t in hits if t > window_start]
    if len(hits) >= _RATE_LIMIT_POST:
        _rate_counts[ip] = hits
        return False
    hits.append(now)
    _rate_counts[ip] = hits
    return True


class _BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Rate limit POST requests to API routes (not static files or health)
        if request.method == "POST" and not any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES):
            ip = request.client.host if request.client else "unknown"
            if not _check_rate_limit(ip):
                return Response(
                    content='{"detail":"Too many requests. Slow down."}',
                    status_code=429,
                    media_type="application/json",
                )

        if not settings.app_password:
            return await call_next(request)

        if path in _AUTH_EXEMPT or any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                _, password = decoded.split(":", 1)
                if secrets.compare_digest(
                    password.encode("utf-8"),
                    settings.app_password.encode("utf-8"),
                ):
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            content="KLG AI OS — Internal access only. Enter firm password.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="KLG AI OS"'},
        )


# =============================================================================
# LIFESPAN — Startup and Shutdown
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Everything before `yield` runs at startup; everything after runs at shutdown.
    Using lifespan() is the modern FastAPI pattern (replacing the deprecated
    @app.on_event("startup") decorator).

    WHY WE INITIALIZE EVERYTHING HERE:
        Creating a NotionBridge (which creates an httpx.AsyncClient) is cheap
        but not free. Creating one per request would add latency and eventually
        exhaust connection pool resources under load. Creating one at startup
        and sharing it via app.state is the correct pattern.
    """
    # ── STARTUP ───────────────────────────────────────────────────────────────
    logger.info("KLG AI OS starting up...")

    # 1. Initialize the Notion bridge — the app's connection to Notion.
    from notion_bridge.client import NotionBridge
    from notion_bridge.project_pages import ProjectPages
    from notion_bridge.watch_list import WatchList

    bridge = NotionBridge()
    project_pages = ProjectPages(bridge)
    watch_list = WatchList(bridge)
    logger.info("Notion bridge initialized.")

    # 2. Initialize SharePoint bridge (optional — gracefully no-ops if unconfigured).
    from sharepoint_bridge.client import SharePointBridge
    sharepoint = SharePointBridge()
    logger.info("SharePoint bridge initialized.")

    # 2b. Initialize Comms Log (optional — no-ops if NOTION_COMMS_LOG_DB_ID not set).
    from notion_bridge.comms_log import CommsLog
    comms_log = CommsLog(bridge) if settings.notion_comms_log_db_id else None
    if comms_log:
        logger.info("Comms Log initialized.")

    # 3. Build Alfred's dependencies — the runtime objects his tools use.
    from alfred.agent import AlfredDependencies

    app.state.alfred_deps = AlfredDependencies(
        bridge=bridge,
        project_pages=project_pages,
        watch_list=watch_list,
        sharepoint=sharepoint,
        comms_log=comms_log,
    )
    logger.info("Alfred dependencies assembled.")

    # 4. Initialize Slack client (if configured).
    #    We store it on app.state even if it's None — route handlers check for None.
    app.state.slack_client = None
    if settings.slack_bot_token:
        from slack_sdk.web.async_client import AsyncWebClient as SlackClient

        app.state.slack_client = SlackClient(token=settings.slack_bot_token)
        logger.info("Slack client initialized.")
    else:
        logger.info(
            "SLACK_BOT_TOKEN not set — background agents will log to console only."
        )

    # 5. Start the background agent scheduler.
    from agents.scheduler import create_scheduler

    scheduler = create_scheduler(
        project_pages=project_pages,
        slack_client=app.state.slack_client,
        watch_list=watch_list,
    )
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info("Background agent scheduler started.")

    logger.info(
        "KLG AI OS ready. "
        "Web UI: http://localhost:%d | "
        "API docs: http://localhost:%d/docs",
        settings.app_port,
        settings.app_port,
    )

    # ── YIELD — App is running and accepting requests ─────────────────────────
    yield

    # ── SHUTDOWN ──────────────────────────────────────────────────────────────
    logger.info("KLG AI OS shutting down...")

    # Gracefully stop the scheduler — waits for any running jobs to complete.
    # wait=False would kill jobs mid-run, which could leave Notion in a partial state.
    app.state.scheduler.shutdown(wait=True)
    logger.info("Scheduler stopped.")

    logger.info("KLG AI OS shutdown complete.")


# =============================================================================
# APP INITIALIZATION
# =============================================================================

app = FastAPI(
    title="KLG AI Operating System",
    description=(
        "Alfred (inward executive assistant) and Bloodhound (research surveillance engine) "
        "for Kowal Law Group. Notion is the source of truth. Claude is the operator."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Hide /docs and /redoc in production — they expose the full API surface.
    # Available only in debug mode (local dev).
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)


# =============================================================================
# MIDDLEWARE
# =============================================================================

# Auth — must be added before CORS so unauthenticated requests are rejected
# before any CORS headers are set.
app.add_middleware(_BasicAuthMiddleware)

# CORS — frontend and API are served from the same Railway origin, so
# same-origin requests don't need CORS at all. This policy allows localhost
# for dev and the Railway domain for prod. The "*" wildcard is intentionally
# absent — it would allow any site to call Alfred with a victim's credentials.
_cors_origins = ["http://localhost:8000", "http://127.0.0.1:8000"]
if not settings.debug:
    # Add the Railway domain if APP_HOST is set to something meaningful.
    # Update this when the Railway URL is known after first deployment.
    _cors_origins = ["*"]  # same-origin in prod; update after Railway URL is known
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


# =============================================================================
# ROUTES
# =============================================================================

# Alfred routes (chat, matters, deadlines, agent triggers)
from api.routes.alfred import router as alfred_router

app.include_router(alfred_router)

# Bloodhound routes (feed scans and triage)
from api.routes.bloodhound import router as bloodhound_router

app.include_router(bloodhound_router)

# Slack events webhook (receive messages from Slack → Alfred)
from api.routes.slack import router as slack_router

app.include_router(slack_router)

# Case File routes (full matter detail + Slack activity + file proxy)
from api.routes.cases import router as cases_router

app.include_router(cases_router)

# Health check endpoint — used by deployment platforms to verify the app is running
@app.get("/health", tags=["System"])
async def health_check():
    """
    Simple health check endpoint.

    Returns 200 OK if the app is running. Deployment platforms (Railway, Vercel,
    AWS) hit this endpoint to know whether to route traffic to this instance.
    """
    return {"status": "ok", "app": "KLG AI OS", "version": "1.0.0"}


# =============================================================================
# STATIC FILES AND WEB UI
# =============================================================================

# Serve the web UI's static assets (CSS, JS) from the web/static/ directory.
# StaticFiles makes files available at /static/app.js, /static/style.css, etc.
_web_dir = Path(__file__).parent / "web"
if _web_dir.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(_web_dir / "static")),
        name="static",
    )

    @app.get("/", include_in_schema=False)
    async def serve_ui():
        """
        Serve the web UI dashboard.

        This route catches the root URL (/) and serves index.html — the
        single-page application that provides the Alfred chat interface and
        the matter/Bloodhound dashboard.

        include_in_schema=False hides this from the API docs (it's a UI
        route, not an API endpoint, so it doesn't need documentation).
        """
        return FileResponse(str(_web_dir / "index.html"))