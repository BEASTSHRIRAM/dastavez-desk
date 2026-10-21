"""Tenant-scoped file storage with upload validation.

Stored names are server-generated; the user-supplied filename is kept only as display metadata.
Every path is resolved and checked to stay inside the tenant's directory.

Files live on local disk (fast, and what the document libraries need), and, when Supabase Storage is
configured, are also mirrored to a private bucket. That makes them durable on a serverless host such as
Vercel, where local disk is per-instance and disappears: resolve() restores a missing file from the bucket.
The bucket key is `<tenant id>/<kind>/<stored name>`, so tenants stay separated there too."""
import re
import uuid
from pathlib import Path

import httpx

from app.config import get_settings

# (extension) -> predicate on the first bytes. A file whose content does not match its extension is rejected.
MAGIC = {
    ".pdf": lambda b: b.startswith(b"%PDF-"),
    ".docx": lambda b: b.startswith(b"PK\x03\x04"),
    ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".wav": lambda b: b[:4] == b"RIFF" and b[8:12] == b"WAVE",
    ".mp3": lambda b: b.startswith(b"ID3") or b[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"),
    ".webm": lambda b: b.startswith(b"\x1a\x45\xdf\xa3"),
    ".m4a": lambda b: b[4:8] == b"ftyp",
}
TEXT_TYPES = {".txt", ".csv"}
STORED_NAME = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$")


class UploadRejected(ValueError):
    """Message is safe to show to the operator."""


class StorageError(RuntimeError):
    """The durable store could not be reached. Message is safe to show."""


def safe_display_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[^\w.\- ]", "_", base).strip(" .")
    return (base or "upload")[:120]


def validate_upload(filename: str, data: bytes) -> str:
    """Return the normalised extension, or raise UploadRejected."""
    s = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in s.allowed_upload_types:
        raise UploadRejected(f"Files of type {ext or 'unknown'} are not accepted. Allowed: "
                             + ", ".join(sorted(s.allowed_upload_types)) + ".")
    if len(data) == 0:
        raise UploadRejected("The file is empty.")
    if len(data) > s.max_upload_bytes:
        raise UploadRejected(f"The file is larger than {s.max_upload_bytes // (1024 * 1024)} MB.")
    if ext in TEXT_TYPES:
        try:
            data[:4096].decode("utf-8")
        except UnicodeDecodeError:
            raise UploadRejected("Text files must be UTF-8.") from None
    elif not MAGIC[ext](data[:16]):
        raise UploadRejected(f"The file content does not look like a {ext} file.")
    return ext


# ---------------------------------------------------------------- durable mirror (Supabase Storage)
_bucket_ready = False


def _api() -> tuple[str, dict[str, str]]:
    s = get_settings()
    return s.supabase_url.rstrip("/") + "/storage/v1", {"Authorization": f"Bearer {s.supabase_service_key}",
                                                         "apikey": s.supabase_service_key}


def _guard(call):
    try:
        return call()
    except httpx.HTTPError as exc:
        raise StorageError(f"File storage is not reachable ({exc.__class__.__name__}). Try again in a moment.") from exc


def _ensure_bucket() -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    base, headers = _api()
    bucket = get_settings().supabase_bucket
    r = _guard(lambda: httpx.post(f"{base}/bucket", headers=headers, json={"id": bucket, "name": bucket, "public": False}, timeout=30))
    if r.status_code not in (200, 201, 400, 409):  # 400/409: it already exists
        raise StorageError(f"File storage refused to create its bucket ({r.status_code}). Check the service key.")
    _bucket_ready = True


def _key(tenant_id: str, kind: str, stored: str) -> str:
    return f"{tenant_id}/{kind}/{stored}"


def _push(tenant_id: str, kind: str, stored: str, data: bytes) -> None:
    if not get_settings().remote_storage:
        return
    _ensure_bucket()
    base, headers = _api()
    r = _guard(lambda: httpx.post(f"{base}/object/{get_settings().supabase_bucket}/{_key(tenant_id, kind, stored)}",
                                  headers={**headers, "x-upsert": "true", "content-type": "application/octet-stream"},
                                  content=data, timeout=60))
    if r.status_code >= 300:
        raise StorageError(f"The file could not be saved to storage ({r.status_code}).")


def _pull(tenant_id: str, kind: str, stored: str) -> bytes | None:
    if not get_settings().remote_storage:
        return None
    base, headers = _api()
    r = _guard(lambda: httpx.get(f"{base}/object/authenticated/{get_settings().supabase_bucket}/{_key(tenant_id, kind, stored)}",
                                 headers=headers, timeout=60))
    if r.status_code in (400, 404):
        return None
    if r.status_code >= 300:
        raise StorageError(f"The file could not be read from storage ({r.status_code}).")
    return r.content


def _drop(tenant_id: str, kind: str, stored: str) -> None:
    if not get_settings().remote_storage:
        return
    base, headers = _api()
    _guard(lambda: httpx.request("DELETE", f"{base}/object/{get_settings().supabase_bucket}", headers=headers,
                                 json={"prefixes": [_key(tenant_id, kind, stored)]}, timeout=30))


# ---------------------------------------------------------------- local files
def _tenant_dir(tenant_id: str, kind: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", tenant_id):
        raise ValueError("Invalid tenant id")
    d = get_settings().storage_dir / tenant_id / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_bytes(tenant_id: str, kind: str, data: bytes, ext: str) -> str:
    stored = f"{uuid.uuid4().hex}{ext}"
    (_tenant_dir(tenant_id, kind) / stored).write_bytes(data)
    _push(tenant_id, kind, stored, data)
    return stored


def new_path(tenant_id: str, kind: str, ext: str) -> tuple[str, Path]:
    """A fresh local path for a file the caller is about to write. Call commit() once it is written."""
    stored = f"{uuid.uuid4().hex}{ext}"
    return stored, _tenant_dir(tenant_id, kind) / stored


def commit(tenant_id: str, kind: str, stored_name: str) -> None:
    """Mirror a file written through new_path() to durable storage (no-op without it)."""
    if get_settings().remote_storage:
        _push(tenant_id, kind, stored_name, (_tenant_dir(tenant_id, kind) / stored_name).read_bytes())


def resolve(tenant_id: str, kind: str, stored_name: str) -> Path:
    """Path of a stored file; raises FileNotFoundError for anything outside the tenant directory.
    A file missing locally (another serverless instance wrote it) is restored from durable storage."""
    if Path(stored_name).name != stored_name or not STORED_NAME.match(stored_name):
        raise FileNotFoundError(stored_name)
    base = _tenant_dir(tenant_id, kind).resolve()
    path = (base / stored_name).resolve()
    if base not in path.parents:
        raise FileNotFoundError(stored_name)
    if not path.is_file():
        data = _pull(tenant_id, kind, stored_name)
        if data is None:
            raise FileNotFoundError(stored_name)
        path.write_bytes(data)
    return path


def delete(tenant_id: str, kind: str, stored_name: str) -> None:
    try:
        resolve(tenant_id, kind, stored_name).unlink()
    except FileNotFoundError:
        pass
    if STORED_NAME.match(stored_name):
        _drop(tenant_id, kind, stored_name)
