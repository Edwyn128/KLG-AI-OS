"""
api/routes/auth.py — OAuth authentication routes.

Microsoft OAuth2 authorization-code flow:

  1. GET /auth/microsoft
       Browser redirects to Microsoft's login page.

  2. GET /auth/microsoft/callback?code=<code>
       Microsoft redirects back here after the user authenticates.
       We exchange the code for tokens, extract the user's name from the
       id_token, issue an Alfred session JWT, and redirect to / with the
       token in the URL hash fragment (never logged by servers).

  3. Frontend reads #sso=<token>&user=<name> on load, stores the JWT, and
       calls /alfred/auth/me to resolve role / client-mode status.

SETUP (one-time per deployment):
  1. portal.azure.com → App registrations → New registration
  2. Platform: Web; Redirect URI: <APP_PUBLIC_URL>/auth/microsoft/callback
  3. API permissions: openid, profile, email, User.Read
  4. Copy client ID → MICROSOFT_CLIENT_ID
  5. Certificates & secrets → new client secret → MICROSOFT_CLIENT_SECRET
  6. For firm-only access: set MICROSOFT_TENANT_ID to your Azure tenant GUID
     (Azure Active Directory → Overview → Tenant ID).
     Use "common" for dev / multi-tenant / personal Microsoft accounts.
  7. Set ALFRED_SESSION_SECRET to a 32+ char random hex string.
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.parse

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

_MS_BASE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
_SCOPE = "openid profile email User.Read"


def _redirect_uri(request: Request) -> str:
    base = settings.app_public_url.rstrip("/") if settings.app_public_url else str(request.base_url).rstrip("/")
    return f"{base}/auth/microsoft/callback"


@router.get("/microsoft", summary="Redirect to Microsoft OAuth login", include_in_schema=False)
async def microsoft_login(request: Request) -> RedirectResponse:
    if not settings.microsoft_client_id or not settings.alfred_session_secret:
        return RedirectResponse(url="/#error=Microsoft+SSO+not+configured")

    tenant = settings.microsoft_tenant_id or "common"
    params = urllib.parse.urlencode({
        "client_id":     settings.microsoft_client_id,
        "response_type": "code",
        "redirect_uri":  _redirect_uri(request),
        "scope":         _SCOPE,
        "response_mode": "query",
        "prompt":        "select_account",
    })
    return RedirectResponse(url=f"{_MS_BASE.format(tenant=tenant)}/authorize?{params}")


@router.get("/microsoft/callback", summary="Handle Microsoft OAuth callback", include_in_schema=False)
async def microsoft_callback(
    request: Request,
    code: str = "",
    error: str = "",
    error_description: str = "",
) -> RedirectResponse:
    if error or not code:
        logger.warning("Microsoft OAuth error: %s — %s", error, error_description)
        msg = urllib.parse.quote(error_description or error or "Sign-in failed")
        return RedirectResponse(url=f"/#error={msg}")

    if not settings.alfred_session_secret:
        return RedirectResponse(url="/#error=Session+secret+not+configured")

    tenant = settings.microsoft_tenant_id or "common"
    token_url = f"{_MS_BASE.format(tenant=tenant)}/token"

    # Exchange authorization code for tokens
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(token_url, data={
                "client_id":     settings.microsoft_client_id,
                "client_secret": settings.microsoft_client_secret,
                "code":          code,
                "redirect_uri":  _redirect_uri(request),
                "grant_type":    "authorization_code",
                "scope":         _SCOPE,
            })
            resp.raise_for_status()
            token_data = resp.json()
    except Exception as e:
        logger.error("Microsoft token exchange failed: %s", e)
        return RedirectResponse(url="/#error=Token+exchange+failed")

    # Extract user identity from the id_token payload.
    # We decode without verifying the signature because we received this token
    # directly from Microsoft over an HTTPS callback — it's trustworthy by transit.
    username = "Team"
    email = ""
    try:
        parts = (token_data.get("id_token") or "").split(".")
        if len(parts) >= 2:
            pad = (4 - len(parts[1]) % 4) % 4
            claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * pad))
            email = claims.get("email") or claims.get("preferred_username") or ""
            given = claims.get("given_name") or ""
            display = claims.get("name") or ""
            if given:
                username = given.strip().title()
            elif display:
                username = display.strip().split()[0].title()
            elif email:
                username = email.split("@")[0].split(".")[0].title()
    except Exception as e:
        logger.warning("Could not parse id_token: %s", e)

    # Issue an Alfred session JWT (8 hours)
    from main import _jwt_encode
    now = int(time.time())
    token = _jwt_encode(
        {"sub": username.lower(), "name": username, "email": email, "iat": now, "exp": now + 28800},
        settings.alfred_session_secret,
    )

    # Redirect to app root with token in hash (never sent to servers in logs)
    fragment = urllib.parse.urlencode({"sso": token, "user": username})
    return RedirectResponse(url=f"/#{fragment}")
