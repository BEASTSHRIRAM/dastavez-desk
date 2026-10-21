"""Tenant-scoped file storage with upload validation.

Stored names are server-generated; the user-supplied filename is kept only as display metadata.
Every path is resolved and checked to stay inside the tenant's directory."""
import re
import uuid
from pathlib import Path

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


class UploadRejected(ValueError):
    """Message is safe to show to the operator."""


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


def _tenant_dir(tenant_id: str, kind: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", tenant_id):
        raise ValueError("Invalid tenant id")
    d = get_settings().storage_dir / tenant_id / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_bytes(tenant_id: str, kind: str, data: bytes, ext: str) -> str:
    stored = f"{uuid.uuid4().hex}{ext}"
    (_tenant_dir(tenant_id, kind) / stored).write_bytes(data)
    return stored


def new_path(tenant_id: str, kind: str, ext: str) -> tuple[str, Path]:
    stored = f"{uuid.uuid4().hex}{ext}"
    return stored, _tenant_dir(tenant_id, kind) / stored


def resolve(tenant_id: str, kind: str, stored_name: str) -> Path:
    """Path of a stored file; raises FileNotFoundError for anything outside the tenant directory."""
    base = _tenant_dir(tenant_id, kind).resolve()
    path = (base / stored_name).resolve()
    if base not in path.parents or not path.is_file():
        raise FileNotFoundError(stored_name)
    return path


def delete(tenant_id: str, kind: str, stored_name: str) -> None:
    try:
        resolve(tenant_id, kind, stored_name).unlink()
    except FileNotFoundError:
        pass
