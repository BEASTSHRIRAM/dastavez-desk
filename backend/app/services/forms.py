"""Inspect an uploaded form and suggest which captured answers belong in which form field.

Uploaded content is data. Only field *labels* are extracted; nothing in the file is executed or
followed as an instruction."""
import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.verticals.base import WorkspaceConfig

ALIASES = {
    "applicant_name": ["name", "full name", "applicant name", "name of applicant", "customer name"],
    "date_of_birth": ["date of birth", "dob", "birth date", "born"],
    "phone": ["phone", "mobile", "mobile number", "contact", "contact number", "telephone"],
    "applicant_address": ["address", "residential address", "current address", "permanent address", "present address"],
    "service_type": ["service", "service requested", "application type", "purpose"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def inspect_form(path: Path, ext: str) -> list[str]:
    """Best-effort list of field labels. Returns [] when nothing recognisable is found."""
    labels: list[str] = []
    try:
        if ext == ".pdf":
            fields = PdfReader(str(path)).get_fields() or {}
            labels = [str(k) for k in fields]
        elif ext == ".docx":
            doc = Document(str(path))
            for table in doc.tables:
                for row in table.rows:
                    first = row.cells[0].text.strip()
                    if first:
                        labels.append(first.rstrip(":"))
            for p in doc.paragraphs:
                m = re.match(r"^\s*([A-Za-z][^:_]{2,60}?)\s*:\s*_*\s*$", p.text)
                if m:
                    labels.append(m.group(1).strip())
        elif ext in (".txt", ".csv"):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                m = re.match(r"^\s*([A-Za-z][^:_,]{2,60}?)\s*:\s*_*\s*$", line)
                if m:
                    labels.append(m.group(1).strip())
    except (PyPdfError, OSError, ValueError, KeyError):
        return []
    seen, out = set(), []
    for label in labels:
        if label.lower() not in seen:
            seen.add(label.lower())
            out.append(label[:80])
    return out[:200]


def read_text_for_extraction(path: Path, ext: str, limit: int = 20000) -> str:
    """Plain text of an uploaded notes file, for fact extraction. Treated strictly as data."""
    try:
        if ext == ".docx":
            doc = Document(str(path))
            parts = [p.text for p in doc.paragraphs] + [c.text for t in doc.tables for r in t.rows for c in r.cells]
            return "\n".join(parts)[:limit]
        if ext in (".txt", ".csv"):
            return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except (OSError, ValueError, KeyError):
        return ""
    return ""


def suggest_mapping(form_fields: list[str], config: WorkspaceConfig) -> dict[str, str]:
    """form label -> field_id, using exact label and alias matches only. Anything unsure stays unmapped
    for the operator to map by hand."""
    ids = set(config.field_ids())
    mapping: dict[str, str] = {}
    taken: set[str] = set()
    for label in form_fields:
        n = _norm(label)
        for fid, aliases in ALIASES.items():
            if fid in ids and fid not in taken and (n == _norm(config.field(fid).label) or n in {_norm(a) for a in aliases}):
                mapping[label] = fid
                taken.add(fid)
                break
    return mapping
