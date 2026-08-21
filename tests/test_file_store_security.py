"""Security regression tests for Alfred's chunked upload boundary."""

from __future__ import annotations

import base64
import uuid

import pytest

from alfred import file_store


@pytest.fixture(autouse=True)
def isolated_file_store(tmp_path, monkeypatch):
    monkeypatch.setattr(file_store, "_TEMP_DIR", tmp_path)
    file_store._CHUNK_SESSIONS.clear()
    file_store._FILE_STORE.clear()
    yield
    file_store._CHUNK_SESSIONS.clear()
    file_store._FILE_STORE.clear()


@pytest.mark.parametrize(
    "upload_id",
    ["../escape", "..\\escape", "/tmp/escape", "C:\\Windows\\Temp\\escape", "not-a-uuid"],
)
def test_chunk_session_rejects_non_uuid_paths(upload_id, tmp_path):
    with pytest.raises(ValueError, match="canonical UUID"):
        file_store.start_chunk_session(upload_id, "brief.pdf", 1)

    assert list(tmp_path.iterdir()) == []
    assert file_store._CHUNK_SESSIONS == {}


def test_valid_chunk_session_uses_server_path_and_completes(tmp_path):
    upload_id = str(uuid.uuid4())
    payload = b"safe legal document"

    file_store.start_chunk_session(upload_id, "../brief.pdf", 1)
    session_path = file_store._CHUNK_SESSIONS[upload_id]["path"]
    assert file_store._assert_temp_path(session_path).parent == tmp_path.resolve()
    assert upload_id not in file_store._assert_temp_path(session_path).name

    result = file_store.append_chunk(
        upload_id,
        0,
        base64.b64encode(payload).decode("ascii"),
    )

    assert result["done"] is True
    entry = file_store.peek_token(result["file_token"])
    assert entry is not None
    assert file_store._assert_temp_path(entry.path).read_bytes() == payload
    assert entry.filename == "brief.pdf"


def test_chunk_session_rejects_out_of_order_write(tmp_path):
    upload_id = str(uuid.uuid4())
    file_store.start_chunk_session(upload_id, "brief.pdf", 2)

    with pytest.raises(ValueError, match="Expected chunk 0"):
        file_store.append_chunk(upload_id, 1, base64.b64encode(b"late").decode("ascii"))

    assert list(tmp_path.iterdir()) == []
    assert file_store._CHUNK_SESSIONS[upload_id]["chunks_received"] == 0


def test_chunk_session_rejects_invalid_base64_without_writing(tmp_path):
    upload_id = str(uuid.uuid4())
    file_store.start_chunk_session(upload_id, "brief.pdf", 1)

    with pytest.raises(ValueError, match="valid base64"):
        file_store.append_chunk(upload_id, 0, "%%%")

    assert list(tmp_path.iterdir()) == []
