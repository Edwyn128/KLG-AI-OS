"""
sharepoint_bridge/client.py — SharePoint document access via Microsoft Graph API.

KLG uses SharePoint as document storage (briefs, exhibits, correspondence).
This module lets Alfred search and read SharePoint files so it can answer
questions like "find the last brief filed in Petersen" or "show me the
exhibits folder for Smith."

AUTHENTICATION:
    Uses OAuth2 client credentials flow (app-only access) via msal.
    The Azure app registration needs:
      - Sites.Read.All   (search and read SharePoint sites)
      - Files.Read.All   (read document library files)

    Set these in .env:
      SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID,
      SHAREPOINT_CLIENT_SECRET, SHAREPOINT_SITE_URL

GRAPH API CALLS:
    All calls go through https://graph.microsoft.com/v1.0/
    We use httpx (already a project dependency) for async HTTP.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import msal

from config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class SharePointBridge:
    """
    Async client for KLG's SharePoint document library via Microsoft Graph.

    Create one instance at startup and reuse it. The MSAL token cache is
    held in-process — tokens are refreshed automatically when they expire.

    If SharePoint credentials are not configured (empty .env values), all
    methods return empty results rather than raising — this lets the app
    run without SharePoint during development.
    """

    def __init__(self) -> None:
        self._configured = bool(
            settings.sharepoint_tenant_id
            and settings.sharepoint_client_id
            and settings.sharepoint_client_secret
            and settings.sharepoint_site_url
        )

        if not self._configured:
            logger.warning(
                "SharePointBridge: credentials not configured — "
                "set SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID, "
                "SHAREPOINT_CLIENT_SECRET, SHAREPOINT_SITE_URL in .env"
            )
            self._msal_app = None
            return

        authority = f"https://login.microsoftonline.com/{settings.sharepoint_tenant_id}"
        self._msal_app = msal.ConfidentialClientApplication(
            client_id=settings.sharepoint_client_id,
            client_credential=settings.sharepoint_client_secret,
            authority=authority,
        )
        logger.info("SharePointBridge initialized (Graph API ready)")

    # ─────────────────────────────────────────────────────────────────────────
    # TOKEN MANAGEMENT
    # ─────────────────────────────────────────────────────────────────────────

    def _get_token(self) -> str | None:
        """Get a valid access token from MSAL's cache or refresh it."""
        if not self._msal_app:
            return None

        scopes = ["https://graph.microsoft.com/.default"]

        # Try cache first (avoids a round-trip to Azure AD on every call)
        result = self._msal_app.acquire_token_silent(scopes, account=None)
        if not result:
            result = self._msal_app.acquire_token_for_client(scopes=scopes)

        if "access_token" not in result:
            logger.error(
                "SharePoint token acquisition failed: %s",
                result.get("error_description", "unknown"),
            )
            return None

        return result["access_token"]

    def _headers(self) -> dict[str, str] | None:
        token = self._get_token()
        if not token:
            return None
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # SEARCH
    # ─────────────────────────────────────────────────────────────────────────

    async def search_files(
        self, query: str, top: int = 10
    ) -> list[dict[str, Any]]:
        """
        Full-text search across KLG's SharePoint document library.

        Alfred calls this when Tim asks something like "find the last brief
        filed in Petersen" or "where is the Sakauye exhibit list?" The search
        uses Microsoft Graph's /search endpoint which indexes file names,
        content, and metadata.

        Args:
            query: Search terms. Can be a matter name, file type, document
                   title fragment, or any keyword likely in a document name.
            top:   Max results to return (default 10).

        Returns:
            List of dicts with: name, webUrl, lastModifiedDateTime, size,
            parentPath. Empty list if SharePoint is not configured or no results.
        """
        if not self._configured:
            return []

        headers = self._headers()
        if not headers:
            return []

        payload = {
            "requests": [{
                "entityTypes": ["driveItem"],
                "query": {"queryString": query},
                "from": 0,
                "size": top,
            }]
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    f"{GRAPH_BASE}/search/query",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

                hits = (
                    data.get("value", [{}])[0]
                    .get("hitsContainers", [{}])[0]
                    .get("hits", [])
                )

                results = []
                for hit in hits:
                    resource = hit.get("resource", {})
                    results.append({
                        "name": resource.get("name", ""),
                        "webUrl": resource.get("webUrl", ""),
                        "lastModifiedDateTime": resource.get("lastModifiedDateTime", ""),
                        "size": resource.get("size", 0),
                        "parentPath": (
                            resource.get("parentReference", {}).get("path", "")
                        ),
                        "driveItemId": resource.get("id", ""),
                        "driveId": resource.get("parentReference", {}).get("driveId", ""),
                    })

                logger.debug("SharePoint search('%s'): %d results", query, len(results))
                return results

            except httpx.HTTPStatusError as e:
                logger.error("SharePoint search error: %s", e)
                return []

    async def list_folder(
        self, folder_path: str = "/", top: int = 50
    ) -> list[dict[str, Any]]:
        """
        List files in a SharePoint folder path.

        Args:
            folder_path: Relative path inside the document library,
                         e.g. "/Matters/Petersen" or "/Briefs/2026".
                         Use "/" for the root.
            top:         Max items to return.

        Returns:
            List of file/folder dicts with name, type, size, webUrl, modified.
        """
        if not self._configured:
            return []

        headers = self._headers()
        if not headers:
            return []

        # Resolve the site ID first so we can address the correct drive
        site_id = await self._get_site_id()
        if not site_id:
            return []

        # Encode the path for the Graph API URL
        path_segment = f":/{folder_path.strip('/')}:" if folder_path.strip("/") else ""

        url = f"{GRAPH_BASE}/sites/{site_id}/drive/root{path_segment}/children"
        params = {"$top": top, "$select": "name,file,folder,size,webUrl,lastModifiedDateTime"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                items = resp.json().get("value", [])

                return [
                    {
                        "name": item.get("name", ""),
                        "type": "folder" if "folder" in item else "file",
                        "size": item.get("size", 0),
                        "webUrl": item.get("webUrl", ""),
                        "lastModifiedDateTime": item.get("lastModifiedDateTime", ""),
                    }
                    for item in items
                ]

            except httpx.HTTPStatusError as e:
                logger.error("SharePoint list_folder error: %s", e)
                return []

    async def get_file_content(
        self, drive_id: str, item_id: str
    ) -> str:
        """
        Download and return the text content of a SharePoint file.

        Works for .txt and .docx files. For PDFs, returns a note that
        content extraction is not yet supported (Graph doesn't return
        raw PDF text — you'd need a separate extraction step).

        Args:
            drive_id: The drive ID from a search result's driveId field.
            item_id:  The item ID from a search result's driveItemId field.

        Returns:
            The file text content, or an explanatory string if extraction fails.
        """
        if not self._configured:
            return ""

        headers = self._headers()
        if not headers:
            return ""

        url = f"{GRAPH_BASE}/drives/{drive_id}/items/{item_id}/content"

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "text" in content_type or "plain" in content_type:
                    return resp.text[:10000]  # cap at 10k chars for AI context

                # For Word docs and other binary formats, Graph returns raw bytes.
                # A full implementation would use python-docx or similar here.
                return (
                    f"[Binary file — content extraction not available. "
                    f"Open directly: {url}]"
                )

            except httpx.HTTPStatusError as e:
                logger.error("SharePoint get_file_content error: %s", e)
                return f"[Error fetching file: {e}]"

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_site_id(self) -> str | None:
        """Resolve the SharePoint site URL to a Graph site ID."""
        headers = self._headers()
        if not headers:
            return None

        # Extract hostname and site path from the configured URL
        # e.g. https://contoso.sharepoint.com/sites/KLG
        from urllib.parse import urlparse
        parsed = urlparse(settings.sharepoint_site_url)
        hostname = parsed.netloc
        site_path = parsed.path.lstrip("/")

        url = f"{GRAPH_BASE}/sites/{hostname}:/{site_path}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                return resp.json().get("id", "")
            except httpx.HTTPStatusError as e:
                logger.error("SharePoint _get_site_id error: %s", e)
                return None
