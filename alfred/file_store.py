"""
alfred/file_store.py — Temporary file token registry for skill file uploads.

Skills that require uploaded documents (briefs, PDFs, CSVs) receive those
files through Alfred's /alfred/upload endpoint. Each uploaded file is stored
in a system temp directory and assigned a UUID token. The token travels
through the Alfred chat request → run_skill tool → skill execute() workflow,
where the skill resolves it back to a real file path via consume_token().

Token lifecycle:
  1. POST /alfred/upload  → register_file() → returns token to the UI
  2. UI includes token in ChatRequest.file_tokens
  3. Route handler calls get_file_info() to inject filename context into the message
  4. Alfred passes token(s) to run_skill()
  5. Skill calls consume_token() → gets file path, token is destroyed
  6. Skill reads file, produces output, then deletes the temp file

Security properties:
  - Tokens are single-use: consumed once, never reusable
  - Files are auto-expired after 1 hour via cleanup_expired()
  - Filenames and sizes are logged; file contents are never logged
  - Files live in a process-local temp directory, not a shared path
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger(__name__)


class FileEntry(NamedTuple):
    path: str
    filename: str
    size_bytes: int
    created_at: float


# ── Registries ────────────────────────────────────────────────────────────────

_FILE_STORE: dict[str, FileEntry] = {}  # token → FileEntry
_CHUNK_SESSIONS: dict[str, dict] = {}   # upload_id → assembly state

# One temp directory for the lifetime of this process.
_TEMP_DIR = Path(tempfile.mkdtemp(prefix="klg_alfred_"))


# ── Single-file upload ────────────────────────────────────────────────────────

def register_file(path: str, filename: str) -> str:
    """Store a completed file and return a single-use token."""
    token = uuid.uuid4().hex
    size = os.path.getsize(path) if os.path.exists(path) else 0
    _FILE_STORE[token] = FileEntry(
        path=path, filename=filename, size_bytes=size, created_at=time.time()
    )
    logger.info(
        "FileStore: registered token %.8s for '%s' (%d bytes)", token, filename, size
    )
    return token


def get_file_info(tokens: list[str]) -> list[tuple[str, str, int]]:
    """
    Return (token, filename, size_bytes) for each valid token.
    Used by the route handler to inject file context into the Alfred message.
    """
    return [
        (t, _FILE_STORE[t].filename, _FILE_STORE[t].size_bytes)
        for t in tokens
        if t in _FILE_STORE
    ]


def peek_token(token: str) -> FileEntry | None:
    """Return the FileEntry without consuming the token (preflight check)."""
    return _FILE_STORE.get(token)


def consume_token(token: str) -> str | None:
    """
    Resolve a token to its file path and remove it from the registry.
    The caller must delete the file after use.
    Returns None if the token is unknown or already consumed.
    """
    entry = _FILE_STORE.pop(token, None)
    if entry is None:
        logger.warning("FileStore: unknown or already-consumed token %.8s", token)
        return None
    logger.info("FileStore: consumed token %.8s for '%s'", token, entry.filename)
    return entry.path


def delete_file(path: str) -> None:
    """Delete a temp file. Silently ignores missing files."""
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as e:
        logger.warning("FileStore: could not delete '%s': %s", path, e)


def cleanup_expired(max_age_seconds: int = 3600) -> int:
    """
    Delete files older than max_age_seconds and remove their tokens.
    Called periodically (e.g., from a startup background task) so crashes
    don't leave orphaned temp files on the Railway filesystem.
    Returns count of files cleaned up.
    """
    now = time.time()
    expired = [t for t, e in list(_FILE_STORE.items()) if now - e.created_at > max_age_seconds]
    count = 0
    for token in expired:
        entry = _FILE_STORE.pop(token, None)
        if entry is None:
            continue
        delete_file(entry.path)
        count += 1
        logger.info("FileStore: expired '%s' (age %.0fs)", entry.filename, now - entry.created_at)
    return count


# ── Chunked upload ────────────────────────────────────────────────────────────
#
# For files larger than the Railway proxy limit (~100MB), the client splits the
# file into base64-encoded chunks and sends them sequentially.
#
# Flow:
#   Client sends chunk_index=0 with filename and total_chunks → server creates session
#   Client sends chunk_index=1,2,… → server appends to temp file
#   When last chunk arrives, server assembles and registers a file_token
#
# Each base64 chunk of 40MB raw ≈ 53MB of JSON — safely under Railway's limit.
# A 400-page scanned PDF (80–160MB) needs 2–4 chunks at 40MB each.

_MAX_CHUNK_TOTAL_MB = 200  # hard cap on assembled chunked upload size
_MAX_CHUNKS = 1000


def _sanitize_filename(filename: str) -> str:
    """Strip path separators and non-safe characters from an uploaded filename."""
    name = Path(filename).name  # drop any directory components
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in name) or "upload"


def _normalize_upload_id(upload_id: str) -> str:
    """Return a canonical UUID string or reject the client-supplied session ID."""
    try:
        normalized = str(uuid.UUID(upload_id))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("upload_id must be a canonical UUID.") from exc
    if upload_id != normalized:
        raise ValueError("upload_id must be a lowercase, hyphenated UUID.")
    return normalized


def _assert_temp_path(path: str | Path) -> Path:
    """Resolve a chunk path and require it to be a direct child of _TEMP_DIR."""
    root = _TEMP_DIR.resolve()
    candidate = Path(path).resolve(strict=False)
    if candidate.parent != root:
        raise ValueError("Upload path escaped the temporary directory.")
    return candidate


def _discard_chunk_session(upload_id: str) -> None:
    """Remove a failed/incomplete session and its partial backing file."""
    session = _CHUNK_SESSIONS.pop(upload_id, None)
    if session is None:
        return
    try:
        _assert_temp_path(session["path"]).unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        logger.warning("FileStore: could not discard chunk session %.8s: %s", upload_id, exc)


def start_chunk_session(upload_id: str, filename: str, total_chunks: int) -> None:
    """Initialize a chunked upload session."""
    upload_id = _normalize_upload_id(upload_id)
    if not 1 <= total_chunks <= _MAX_CHUNKS:
        raise ValueError(f"total_chunks must be between 1 and {_MAX_CHUNKS}.")
    if upload_id in _CHUNK_SESSIONS:
        raise ValueError("Upload session already exists.")

    safe_name = _sanitize_filename(filename)
    # The client ID is only a registry key. The filesystem name is generated
    # exclusively by the server and then containment-checked before use.
    temp_path = _assert_temp_path(_TEMP_DIR / f"{uuid.uuid4().hex}.part")
    _CHUNK_SESSIONS[upload_id] = {
        "filename": safe_name,
        "total_chunks": total_chunks,
        "chunks_received": 0,
        "path": str(temp_path),
        "total_bytes": 0,
        "created_at": time.time(),
    }
    logger.info(
        "FileStore: chunk session %s started for '%s' (%d chunks)",
        upload_id[:8], filename, total_chunks,
    )


def append_chunk(upload_id: str, chunk_index: int, data_b64: str) -> dict:
    """
    Append a base64-encoded chunk to the assembly file.

    Returns:
      {"chunks_received": N, "total_chunks": M, "done": False}   — more to come
      {"chunks_received": N, "total_chunks": M, "done": True,
       "file_token": "..."}                                        — complete
    """
    upload_id = _normalize_upload_id(upload_id)
    session = _CHUNK_SESSIONS.get(upload_id)
    if session is None:
        raise ValueError(f"Unknown upload session: {upload_id[:8]}")

    expected_index = session["chunks_received"]
    if chunk_index != expected_index or chunk_index >= session["total_chunks"]:
        raise ValueError(f"Expected chunk {expected_index}, received {chunk_index}.")

    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Chunk data is not valid base64.") from exc

    # Enforce cumulative size cap before writing
    max_bytes = _MAX_CHUNK_TOTAL_MB * 1024 * 1024
    new_total = session["total_bytes"] + len(raw)
    if new_total > max_bytes:
        _discard_chunk_session(upload_id)
        raise ValueError(
            f"Chunked upload exceeds the {_MAX_CHUNK_TOTAL_MB} MB limit."
        )

    path = _assert_temp_path(session["path"])
    try:
        # Exclusive creation prevents an existing file or link from being
        # truncated; later chunks append only to the server-generated path.
        mode = "xb" if chunk_index == 0 else "ab"
        with path.open(mode) as file_handle:
            file_handle.write(raw)
    except OSError:
        _discard_chunk_session(upload_id)
        raise

    session["total_bytes"] = new_total
    session["chunks_received"] += 1
    done = session["chunks_received"] >= session["total_chunks"]

    if done:
        token = _finalize_chunk_session(upload_id)
        return {
            "chunks_received": session["chunks_received"],
            "total_chunks": session["total_chunks"],
            "done": True,
            "file_token": token,
        }

    return {
        "chunks_received": session["chunks_received"],
        "total_chunks": session["total_chunks"],
        "done": False,
    }


def _finalize_chunk_session(upload_id: str) -> str:
    """Register the assembled file and return its token."""
    session = _CHUNK_SESSIONS.pop(upload_id)
    token = register_file(session["path"], session["filename"])
    logger.info(
        "FileStore: chunk session %s finalized → token %.8s", upload_id[:8], token
    )
    return token
