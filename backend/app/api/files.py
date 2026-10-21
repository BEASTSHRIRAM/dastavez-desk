"""Attachments, form mapping and document downloads. Every lookup is tenant-scoped."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.api.cases import load
from app.repositories.cases import NotFound, TenantRepo
from app.services import forms, storage
from app.services.auth import Principal
from app.templates.builder import SAMPLE_FORM, ensure_templates

router = APIRouter(prefix="/api")
MEDIA = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "pdf": "application/pdf",
         "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "csv": "text/csv"}
OPEN_STATUSES = ("intake", "awaiting_input", "review")


def _att_out(a) -> dict:
    return {"id": a.id, "name": a.original_name, "kind": a.kind, "size": a.size, "content_type": a.content_type,
            "fields": a.meta.get("fields", []), "created_at": a.created_at}


def _store(cc, p: Principal, name: str, data: bytes, kind: str, content_type: str):
    try:
        ext = storage.validate_upload(name, data)
    except storage.UploadRejected as exc:
        raise HTTPException(422, str(exc)) from None
    stored = storage.save_bytes(p.tenant_id, "files", data, ext)
    meta: dict = {}
    if kind == "form":
        path = storage.resolve(p.tenant_id, "files", stored)
        meta["fields"] = forms.inspect_form(path, ext)
    att = cc.repo.add_attachment(cc.case.id, original_name=storage.safe_display_name(name), stored_name=stored,
                                 content_type=content_type[:100], size=len(data), kind=kind, meta=meta)
    cc.repo.audit("attachment_added", cc.case.id, p.user_id, attachment_id=att.id, kind=kind)
    if kind == "form":
        suggested = forms.suggest_mapping(meta["fields"], cc.config)
        cc.repo.set_extra(cc.case, form_mapping=suggested)
    return att


@router.post("/cases/{case_id}/attachments", status_code=201)
async def upload(case_id: str, kind: str = "supporting", file: UploadFile = File(...),
                 p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    if kind not in ("supporting", "form"):
        raise HTTPException(422, "Unknown attachment kind.")
    if cc.case.status not in OPEN_STATUSES:
        raise HTTPException(409, "Files can only be added before the draft is approved.")
    data = await file.read(storage.get_settings().max_upload_bytes + 1)
    att = _store(cc, p, file.filename or "upload", data, kind, file.content_type or "application/octet-stream")
    return _att_out(att) | {"mapping": (cc.case.extra or {}).get("form_mapping", {})}


@router.post("/cases/{case_id}/attachments/sample-form", status_code=201)
def use_sample_form(case_id: str, p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session)):
    """Attach the bundled demonstration form (clearly labelled as not official)."""
    cc = load(session, p, case_id)
    if cc.case.status not in OPEN_STATUSES:
        raise HTTPException(409, "Files can only be added before the draft is approved.")
    ensure_templates()
    att = _store(cc, p, "sample_demo_form.docx", Path(SAMPLE_FORM).read_bytes(), "form", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    return _att_out(att) | {"mapping": (cc.case.extra or {}).get("form_mapping", {})}


@router.get("/cases/{case_id}/attachments")
def list_attachments(case_id: str, p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    return [_att_out(a) for a in cc.repo.attachments(cc.case.id)]


@router.get("/attachments/{attachment_id}/download")
def download_attachment(attachment_id: str, repo: TenantRepo = Depends(deps.repo), p: Principal = Depends(deps.principal)):
    try:
        att = repo.get_attachment(attachment_id)
        path = storage.resolve(p.tenant_id, "files", att.stored_name)
    except (NotFound, FileNotFoundError):
        raise HTTPException(404, "File not found.") from None
    return FileResponse(path, filename=att.original_name, media_type="application/octet-stream")


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: str, p: Principal = Depends(deps.require("operator")), repo: TenantRepo = Depends(deps.repo)):
    try:
        att = repo.get_attachment(attachment_id)
    except NotFound:
        raise HTTPException(404, "File not found.") from None
    storage.delete(p.tenant_id, "files", att.stored_name)
    repo.soft_delete_attachment(att)
    repo.audit("attachment_deleted", att.case_id, p.user_id, attachment_id=att.id)


class MappingIn(BaseModel):
    mapping: dict[str, str | None]


@router.put("/cases/{case_id}/form-mapping")
def set_form_mapping(case_id: str, body: MappingIn, p: Principal = Depends(deps.require("operator")),
                     session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    form = cc.repo.attachments(cc.case.id, "form")
    labels = set(form[-1].meta.get("fields", [])) if form else set()
    valid_ids = set(cc.config.field_ids())
    clean: dict[str, str] = {}
    for label, fid in body.mapping.items():
        if label not in labels:
            raise HTTPException(422, f"'{label}' is not a field on the uploaded form.")
        if fid is None:
            continue
        if fid not in valid_ids:
            raise HTTPException(422, f"'{fid}' is not an answer field in this workspace.")
        clean[label] = fid
    cc.repo.set_extra(cc.case, form_mapping=clean)
    cc.repo.audit("form_mapping_changed", cc.case.id, p.user_id, mapped=len(clean))
    return {"mapping": clean}


@router.get("/cases/{case_id}/documents")
def list_documents(case_id: str, p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    return [{"id": d.id, "doc_key": d.doc_key, "title": d.title, "fmt": d.fmt, "is_sample": d.is_sample,
             "created_at": d.created_at} for d in cc.repo.documents(cc.case.id)]


@router.get("/documents/{document_id}/download")
def download_document(document_id: str, repo: TenantRepo = Depends(deps.repo), p: Principal = Depends(deps.principal)):
    try:
        doc = repo.get_document(document_id)
        path = storage.resolve(p.tenant_id, "documents", doc.stored_name)
    except (NotFound, FileNotFoundError):
        raise HTTPException(404, "Document not found.") from None
    if doc.approval_id is None:  # defence in depth: only approved output is ever downloadable
        raise HTTPException(409, "This document was not generated from an approved draft.")
    safe = storage.safe_display_name(f"{doc.title} (sample).{doc.fmt}" if doc.is_sample else f"{doc.title}.{doc.fmt}")
    repo.audit("downloaded", doc.case_id, p.user_id, document_id=doc.id)
    return FileResponse(path, filename=safe, media_type=MEDIA.get(doc.fmt, "application/octet-stream"))
