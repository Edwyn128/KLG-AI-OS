"""
api/routes/admin.py — KLG User Management endpoints.

Accessible only to super-admin users (currently: Stu).
Reads/writes the KLG Users Notion database (NOTION_USERS_DB_ID).
Falls back gracefully if the DB is not yet configured.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.routes.alfred import get_verified_username, _SUPER_ADMIN_USERS
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["Admin"])


# ── Auth guard ───────────────────────────────────────────────────────────────

def require_super_admin(request: Request) -> str:
    """Dependency: ensures only super-admin users can reach admin endpoints."""
    username = get_verified_username(request) or ""
    if username.lower() not in _SUPER_ADMIN_USERS:
        raise HTTPException(403, "Admin access required")
    return username


# ── Notion helpers ───────────────────────────────────────────────────────────

def _get_notion_bridge():
    """Return a NotionBridge instance, or None if the token isn't configured."""
    if not settings.notion_token:
        return None
    try:
        from notion_bridge.client import NotionBridge
        return NotionBridge(settings.notion_token)
    except Exception:
        return None


def _normalize_user(page: dict) -> dict:
    """Map Notion KLG Users page properties to a flat dict."""
    props = page.get("properties", {})

    def _text(key: str) -> str:
        val = props.get(key, {})
        if "title" in val:
            return "".join(t.get("plain_text", "") for t in val["title"])
        if "rich_text" in val:
            return "".join(t.get("plain_text", "") for t in val["rich_text"])
        return val.get("email", {}).get("email", "") if "email" in val else ""

    def _check(key: str) -> bool:
        return props.get(key, {}).get("checkbox", False)

    def _select(key: str) -> str:
        return (props.get(key, {}).get("select") or {}).get("name", "")

    return {
        "id": page.get("id", ""),
        "name": _text("Name"),
        "display_name": _text("Display Name"),
        "role": _select("Role"),
        "email": _text("Email"),
        "is_admin": _check("is_admin"),
        "is_super_admin": _check("is_super_admin"),
        "is_accounting": _check("is_accounting"),
        "can_create_matters": _check("can_create_matters"),
        "can_edit_matters": _check("can_edit_matters"),
        "can_create_tasks": _check("can_create_tasks"),
        "can_edit_tasks": _check("can_edit_tasks"),
        "can_complete_tasks": _check("can_complete_tasks"),
        "can_delete_tasks": _check("can_delete_tasks"),
        "active": _check("Active"),
        "allowed_matters": _text("Allowed Matters"),
    }


def _build_notion_props(data: dict) -> dict:
    """Convert a flat user dict to Notion property format for PATCH/POST."""
    props: dict[str, Any] = {}

    if "name" in data:
        props["Name"] = {"title": [{"text": {"content": data["name"]}}]}
    if "display_name" in data:
        props["Display Name"] = {"rich_text": [{"text": {"content": data["display_name"]}}]}
    if "role" in data:
        props["Role"] = {"select": {"name": data["role"]}}
    if "email" in data:
        props["Email"] = {"email": data["email"] or None}
    if "allowed_matters" in data:
        props["Allowed Matters"] = {"rich_text": [{"text": {"content": data["allowed_matters"]}}]}

    for flag in ("is_admin", "is_super_admin", "is_accounting",
                 "can_create_matters", "can_edit_matters",
                 "can_create_tasks", "can_edit_tasks",
                 "can_complete_tasks", "can_delete_tasks", "Active"):
        key = flag[0].upper() + flag[1:] if flag == "active" else flag
        if flag in data:
            # Map snake_case → Notion property name
            notion_key = {
                "is_admin": "is_admin",
                "is_super_admin": "is_super_admin",
                "is_accounting": "is_accounting",
                "can_create_matters": "can_create_matters",
                "can_edit_matters": "can_edit_matters",
                "can_create_tasks": "can_create_tasks",
                "can_edit_tasks": "can_edit_tasks",
                "can_complete_tasks": "can_complete_tasks",
                "can_delete_tasks": "can_delete_tasks",
                "active": "Active",
            }.get(flag, flag)
            props[notion_key] = {"checkbox": bool(data[flag])}

    return props


# ── Request/response models ──────────────────────────────────────────────────

class UserPatch(BaseModel):
    display_name: str | None = None
    role: str | None = None
    email: str | None = None
    is_admin: bool | None = None
    is_super_admin: bool | None = None
    is_accounting: bool | None = None
    can_create_matters: bool | None = None
    can_edit_matters: bool | None = None
    can_create_tasks: bool | None = None
    can_edit_tasks: bool | None = None
    can_complete_tasks: bool | None = None
    can_delete_tasks: bool | None = None
    active: bool | None = None
    allowed_matters: str | None = None


class UserCreate(UserPatch):
    name: str  # login username — required


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/users", summary="List all KLG users")
async def list_users(_username: str = Depends(require_super_admin)) -> dict:
    db_id = settings.notion_users_db_id
    if not db_id:
        return {"users": [], "count": 0, "notice": "NOTION_USERS_DB_ID not configured"}

    bridge = _get_notion_bridge()
    if not bridge:
        raise HTTPException(503, "Notion bridge unavailable")

    try:
        pages = await bridge.query_database(db_id)
        users = [_normalize_user(p) for p in pages]
        return {"users": users, "count": len(users)}
    except Exception as e:
        logger.exception("Failed to list users: %s", e)
        raise HTTPException(500, "Failed to fetch users from Notion") from e


@router.post("/users", summary="Create a new KLG user")
async def create_user(
    body: UserCreate,
    _username: str = Depends(require_super_admin),
) -> dict:
    db_id = settings.notion_users_db_id
    if not db_id:
        raise HTTPException(503, "NOTION_USERS_DB_ID not configured")

    bridge = _get_notion_bridge()
    if not bridge:
        raise HTTPException(503, "Notion bridge unavailable")

    props = _build_notion_props(body.model_dump(exclude_none=True))
    if "Name" not in props:
        raise HTTPException(422, "name is required")

    try:
        page = await bridge.create_page(database_id=db_id, properties=props)
        return _normalize_user(page)
    except Exception as e:
        logger.exception("Failed to create user: %s", e)
        raise HTTPException(500, "Failed to create user in Notion") from e


@router.patch("/users/{user_id}", summary="Update a KLG user's permissions")
async def update_user(
    user_id: str,
    body: UserPatch,
    _username: str = Depends(require_super_admin),
) -> dict:
    db_id = settings.notion_users_db_id
    if not db_id:
        raise HTTPException(503, "NOTION_USERS_DB_ID not configured")

    bridge = _get_notion_bridge()
    if not bridge:
        raise HTTPException(503, "Notion bridge unavailable")

    props = _build_notion_props(body.model_dump(exclude_none=True))
    if not props:
        raise HTTPException(422, "No fields to update")

    try:
        page = await bridge.update_page(user_id, properties=props)
        return _normalize_user(page)
    except Exception as e:
        logger.exception("Failed to update user %s: %s", user_id, e)
        raise HTTPException(500, "Failed to update user in Notion") from e


@router.delete("/users/{user_id}", summary="Deactivate a KLG user")
async def delete_user(
    user_id: str,
    _username: str = Depends(require_super_admin),
) -> dict:
    db_id = settings.notion_users_db_id
    if not db_id:
        raise HTTPException(503, "NOTION_USERS_DB_ID not configured")

    bridge = _get_notion_bridge()
    if not bridge:
        raise HTTPException(503, "Notion bridge unavailable")

    try:
        page = await bridge.update_page(user_id, properties={"Active": {"checkbox": False}})
        return {"ok": True, "user_id": user_id, "active": False}
    except Exception as e:
        logger.exception("Failed to deactivate user %s: %s", user_id, e)
        raise HTTPException(500, "Failed to deactivate user in Notion") from e
