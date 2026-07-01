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

def start_chunk_session(upload_id: str, filename: str, total_chunks: int) -> None:
    """Initialize a chunked upload session."""
    temp_path = str(_TEMP_DIR / f"{upload_id}_{filename}")
    _CHUNK_SESSIONS[upload_id] = {
        "filename": filename,
        "total_chunks": total_chunks,
        "chunks_received": 0,
        "path": temp_path,
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
    session = _CHUNK_SESSIONS.get(upload_id)
    if session is None:
        raise ValueError(f"Unknown upload session: {upload_id[:8]}")

    raw = base64.b64decode(data_b64)

    # Chunks must arrive in order (chunk_index 0 truncates, rest append).
    mode = "wb" if chunk_index == 0 else "ab"
    with open(session["path"], mode) as f:
        f.write(raw)

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
