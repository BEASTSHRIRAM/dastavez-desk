"""DOCX rendering, preview extraction, template comparison and PDF conversion.

Preview and export share one pipeline: the same template is rendered twice, once with plain values
(the file the operator downloads) and once with ⟦field¦value⟧ markers (so the preview can highlight
every filled field and link it back to its input). What the operator reviews is what is exported."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from docxtpl import DocxTemplate
from jinja2 import Environment

from app.config import get_settings

MARK_RE = re.compile(r"⟦([^¦⟧]+)¦([^⟧]*)⟧")


class PdfUnavailable(RuntimeError):
    """LibreOffice is missing or the conversion failed. Never reported as a finished PDF."""


def mark(field_id: str, text: str) -> str:
    return f"⟦{field_id}¦{text}⟧" if text else text


def render_docx(template: Path, context: dict[str, Any], out: Path) -> Path:
    tpl = DocxTemplate(str(template))
    tpl.render(context, autoescape=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    tpl.save(str(out))
    return out


def _iter_body(doc):
    """Yield Paragraph and Table objects in document order."""
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


def read_blocks(path: Path) -> list[dict[str, Any]]:
    """Structured blocks for the HTML preview. Marker text is left in for the frontend to highlight."""
    doc = Document(str(path))
    blocks: list[dict[str, Any]] = []
    sec = doc.sections[0]
    header = " ".join(p.text for p in sec.header.paragraphs if p.text.strip())
    footer = " ".join(p.text for p in sec.footer.paragraphs if p.text.strip())
    for item in _iter_body(doc):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style = item.style.name if item.style is not None else ""
            kind = "title" if style == "Title" else "heading" if style.startswith("Heading") else \
                "bullet" if "List" in style else "paragraph"
            italic = bool(item.runs) and all(r.italic for r in item.runs if r.text.strip())
            blocks.append({"type": kind, "text": text, "note": italic})
        else:
            rows = [[c.text.strip() for c in r.cells] for r in item.rows]
            # a header row is one whose every non-empty run is bold (key/value tables only bold the label column)
            runs = [run for c in item.rows[0].cells for par in c.paragraphs for run in par.runs if run.text.strip()] if item.rows else []
            is_header = len(item.rows[0].cells) > 1 and bool(runs) and all(run.bold for run in runs)
            rows = [r for r in rows if any(r)]
            if rows:
                blocks.append({"type": "table", "rows": rows, "header": is_header})
    return [{"type": "header", "text": header}, *blocks, {"type": "footer", "text": footer}]


def blocks_plain_text(blocks: list[dict[str, Any]]) -> str:
    out = []
    for b in blocks:
        if b["type"] == "table":
            out += [" | ".join(r) for r in b["rows"]]
        else:
            out.append(b["text"])
    return MARK_RE.sub(lambda m: m.group(2), "\n".join(out))


def compare_with_template(template: Path, context: dict[str, Any]) -> list[dict[str, Any]]:
    """Section-by-section: approved template wording vs. the draft. A section is 'changed' only
    where a placeholder was filled; fixed approved wording is reported as unchanged."""
    env = Environment(autoescape=False)
    doc = Document(str(template))
    sections: list[dict[str, Any]] = []
    stack: list[bool] = []  # visibility of nested {%p if %} blocks; for-loops are skipped

    def handle(text: str) -> None:
        text = text.strip()
        if not text:
            return
        m = re.fullmatch(r"\{%p?\s*(if|for|endif|endfor)\b(.*?)%\}", text)
        if m:
            kw, rest = m.group(1), m.group(2).strip()
            if kw == "if":
                stack.append(bool(env.compile_expression(rest)(context)))
            elif kw == "for":
                stack.append(False)
            else:
                stack.pop()
            return
        if stack and not all(stack):
            return
        if "{{" in text:
            rendered = env.from_string(text).render(**context)
            sections.append({"approved": re.sub(r"\{\{\s*([\w.]+)\s*\}\}", r"[\1]", text), "draft": rendered, "changed": True})
        else:
            sections.append({"approved": text, "draft": text, "changed": False})

    for item in _iter_body(doc):
        if isinstance(item, Paragraph):
            handle(item.text)
        else:
            in_loop = False  # rows between {%tr for %} and {%tr endfor %} belong to a list, not fixed wording
            for row in item.rows:
                markers = " ".join(c.text for c in row.cells)
                if "{%tr" in markers:
                    in_loop = "endfor" not in markers
                    continue
                if in_loop:
                    continue
                for cell in row.cells:
                    handle(cell.text)
    return sections


def _soffice() -> str | None:
    configured = get_settings().soffice_path
    if configured and Path(configured).exists():
        return configured
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for guess in (r"C:\Program Files\LibreOffice\program\soffice.exe", r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if Path(guess).exists():
            return guess
    return None


def _word_installed() -> bool:
    """Microsoft Word on Windows can convert DOCX to PDF with full fidelity through COM automation."""
    if sys.platform != "win32" or not shutil.which("powershell"):
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\winword.exe"):
            return True
    except OSError:
        return False


def pick_converter() -> str | None:
    """'soffice' (LibreOffice), 'word', or None. LibreOffice is preferred: it runs headless and in servers."""
    if _soffice():
        return "soffice"
    return "word" if _word_installed() else None


def pdf_available() -> bool:
    return pick_converter() is not None


# Word allows one automation client at a time, so conversions through it are serialised.
_word_lock = threading.Lock()
_WORD_SCRIPT = (
    "$ErrorActionPreference='Stop';$w=$null;"
    "try{$w=New-Object -ComObject Word.Application;$w.Visible=$false;$w.DisplayAlerts=0;"
    "$d=$w.Documents.Open($env:DASTAVEZ_IN,$false,$true);$d.ExportAsFixedFormat($env:DASTAVEZ_OUT,17);$d.Close($false)}"
    "finally{if($w){$w.Quit()}}"
)


def _convert_with_word(docx: Path, out: Path) -> None:
    env = {**os.environ, "DASTAVEZ_IN": str(docx.resolve()), "DASTAVEZ_OUT": str(out.resolve())}
    with _word_lock:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _WORD_SCRIPT],
                       check=True, capture_output=True, timeout=120, env=env)


def _convert_with_soffice(exe: str, docx: Path, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(docx)],
                       check=True, capture_output=True, timeout=120, env={**os.environ, "HOME": tmp})
        produced = Path(tmp) / f"{docx.stem}.pdf"
        if produced.exists():
            shutil.move(str(produced), out)


def docx_to_pdf(docx: Path, out: Path) -> Path:
    converter = pick_converter()
    if converter is None:
        raise PdfUnavailable("PDF export needs LibreOffice or Microsoft Word on the server. Install one (or set "
                             "SOFFICE_PATH), then retry. The DOCX file is ready now.")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    try:
        if converter == "word":
            _convert_with_word(docx, out)
        else:
            _convert_with_soffice(_soffice() or "", docx, out)
    except (subprocess.SubprocessError, OSError) as exc:
        raise PdfUnavailable(f"PDF conversion with {'Microsoft Word' if converter == 'word' else 'LibreOffice'} failed "
                             f"({exc.__class__.__name__}). The DOCX file is ready.") from exc
    if not out.exists() or out.stat().st_size == 0:
        raise PdfUnavailable("PDF conversion produced no file. The DOCX file is ready.")
    return out
