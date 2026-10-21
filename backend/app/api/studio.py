"""Template Studio and a business's own templates.

Flow: upload an old draft -> analyst proposes the variable parts -> a person edits the proposal ->
build a template (not yet usable) -> the owner approves it -> cases can start from it."""
import re
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.models.fields import FieldSpec, FieldType
from app.models.orm import TemplateVersion
from app.repositories import catalog as cat
from app.repositories.cases import NotFound, TenantRepo
from app.services import storage, studio
from app.services.auth import Principal
from app.services.llm import LLMError, get_llm_provider
from app.services.template_files import template_path
from docx import Document

router = APIRouter(prefix="/api")

VERIFY_CHECKS = [("identity_verified", "I have verified the client's identity document"),
                 ("facts_checked_with_client", "I have read these facts back to the client")]


class SelectionIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)
    field_id: str = Field(default="", max_length=60)
    label: str = Field(default="", max_length=80)
    type: str
    required: bool = True
    high_impact: bool = False
    occurrence: int | None = Field(default=None, ge=0, le=500)
    link_to: str | None = None
    options: list[str] | None = Field(default=None, max_length=20)


class BuildIn(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    title: str = Field(min_length=3, max_length=120)
    source_name: str | None = Field(default=None, max_length=200)
    jurisdiction: str | None = Field(default=None, max_length=100)
    template_key: str | None = Field(default=None, max_length=60)  # add a new version to an existing template
    add_verification_checks: bool = False
    selections: list[SelectionIn] = Field(max_length=80)


def _agent(session: Session, p: Principal):
    """The analyst model is used only if the business consented and a provider is configured."""
    if not cat.get_tenant(session, p.tenant_id).ai_consent:
        return None
    try:
        prov = get_llm_provider()
    except LLMError:
        return None
    return None if prov.name == "demo" else prov


@router.post("/studio/analyze")
async def analyze(file: UploadFile = File(...), p: Principal = Depends(deps.require("operator")),
                  session: Session = Depends(deps.get_session)):
    data = await file.read(storage.get_settings().max_upload_bytes + 1)
    name = storage.safe_display_name(file.filename or "draft.docx")
    try:
        ext = storage.validate_upload(name, data)
    except storage.UploadRejected as exc:
        raise HTTPException(422, str(exc)) from None
    if ext != ".docx":
        raise HTTPException(422, "Template Studio reads Word (.docx) files. Save your draft as .docx and try again.")
    stored = storage.save_bytes(p.tenant_id, "studio", data, ".docx")
    path = storage.resolve(p.tenant_id, "studio", stored)
    try:
        cands, warnings = studio.analyze(path)
        doc_text = studio.full_text(Document(str(path)))
    except Exception as exc:  # noqa: BLE001 - a damaged document must produce a readable message
        storage.delete(p.tenant_id, "studio", stored)
        raise HTTPException(422, "That file could not be read as a Word document. Is it damaged or password-protected?") from exc
    agent_note, agent_used = "Rule-based suggestions only. Turn on AI services in the sidebar to let an analyst model help.", False
    prov = _agent(session, p)
    if prov:
        cands, notes = studio.agent_refine(cands, doc_text, prov)
        agent_used = True
        agent_note = " ".join(notes) or f"Labels and extra details were suggested by {prov.name}. Check each one."
    TenantRepo(session, p.tenant_id).audit("studio_analyzed", None, p.user_id, candidates=len(cands), agent=agent_used)
    return {"upload_id": stored.removesuffix(".docx"), "filename": name, "candidates": [c.as_dict() for c in cands],
            "warnings": warnings, "agent": {"used": agent_used, "note": agent_note}}


def _next_version(existing: list[TemplateVersion]) -> str:
    if not existing:
        return "1.0"
    major, minor = (existing[0].version.split(".") + ["0"])[:2]
    return f"{major}.{int(minor) + 1}"


@router.post("/studio/build", status_code=201)
def build(body: BuildIn, p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session)):
    try:
        src = storage.resolve(p.tenant_id, "studio", f"{body.upload_id}.docx")
    except FileNotFoundError:
        raise HTTPException(404, "That upload was not found. Upload the draft again.") from None
    repo = cat.TemplateRepo(session, p.tenant_id)
    key = body.template_key
    if key:
        versions = repo.latest_any(key)
        if not versions or versions[0].tenant_id != p.tenant_id:
            raise HTTPException(404, "That template does not exist for your business.")
    else:
        key = f"{re.sub(r'[^a-z0-9]+', '-', body.title.lower()).strip('-')[:36] or 'template'}-{body.upload_id[:4]}"
        versions = repo.latest_any(key)
    sels = [studio.Selection(text=s.text, field_id=s.field_id, label=s.label or s.field_id, type=s.type, required=s.required,
                             high_impact=s.high_impact, occurrence=s.occurrence, link_to=s.link_to, options=s.options)
            for s in body.selections]
    stored, out = storage.new_path(p.tenant_id, "templates", ".docx")
    try:
        result = studio.build(src, sels, out)
    except studio.StudioError as exc:
        raise HTTPException(422, str(exc)) from None
    storage.commit(p.tenant_id, "templates", stored)  # durable copy of the template's wording
    fields: list[FieldSpec] = result["fields"]
    verify: list[str] = []
    if body.add_verification_checks:
        for fid, label in VERIFY_CHECKS:
            if fid not in {f.id for f in fields}:
                fields.append(FieldSpec(id=fid, label=label, type=FieldType.YESNO, required=True, group="verification"))
            verify.append(fid)
    if not fields:
        storage.delete(p.tenant_id, "templates", stored)
        raise HTTPException(422, "Pick at least one detail that changes from client to client.")
    version = _next_version(versions)
    tv = TemplateVersion(tenant_id=p.tenant_id, template_key=key, version=version, workspace="custom", title=body.title.strip(),
                         file_name=stored, is_demo=False, approved=False, jurisdiction=body.jurisdiction, verify_fields=verify,
                         field_specs=[f.model_dump(mode="json") for f in fields],
                         source_note=f"Built in Template Studio from {body.source_name or 'an uploaded draft'}. Not usable until approved.")
    session.add(tv)
    session.commit()
    TenantRepo(session, p.tenant_id).audit("template_created", None, p.user_id, template_id=tv.id, key=key, version=version,
                                            fields=len(fields))
    return {"template": template_out(tv), "preview": result["blocks"], "leftovers": result["leftovers"],
            "problems": result["problems"], "replaced": result["counts"]}


def template_out(t: TemplateVersion) -> dict:
    return {"id": t.id, "key": t.template_key, "version": t.version, "workspace": t.workspace, "title": t.title,
            "is_demo": t.is_demo, "approved": t.approved, "jurisdiction": t.jurisdiction, "verify_fields": t.verify_fields,
            "note": t.source_note, "last_verified": t.last_verified, "owned_by_business": t.tenant_id is not None,
            "fields": [{"id": f["id"], "label": f["label"], "type": f["type"], "required": f.get("required", False)}
                       for f in (t.field_specs or [])]}


def _own(repo: cat.TemplateRepo, template_id: str, tenant_id: str) -> TemplateVersion:
    try:
        tv = repo.get(template_id)
    except NotFound:
        raise HTTPException(404, "Template not found.") from None
    if tv.tenant_id != tenant_id:
        raise HTTPException(403, "Bundled templates cannot be changed.")
    return tv


@router.post("/templates/{template_id}/approve")
def approve(template_id: str, p: Principal = Depends(deps.require("owner")), session: Session = Depends(deps.get_session)):
    """The owner signs off the template's wording. Only approved templates can start a case."""
    tv = _own(cat.TemplateRepo(session, p.tenant_id), template_id, p.tenant_id)
    tv.approved = True
    session.commit()
    TenantRepo(session, p.tenant_id).audit("template_approved", None, p.user_id, template_id=tv.id, key=tv.template_key, version=tv.version)
    return template_out(tv)


@router.post("/templates/{template_id}/retire")
def retire(template_id: str, p: Principal = Depends(deps.require("owner")), session: Session = Depends(deps.get_session)):
    tv = _own(cat.TemplateRepo(session, p.tenant_id), template_id, p.tenant_id)
    tv.approved = False
    session.commit()
    TenantRepo(session, p.tenant_id).audit("template_retired", None, p.user_id, template_id=tv.id, key=tv.template_key, version=tv.version)
    return template_out(tv)


@router.get("/templates/{template_id}/preview")
def preview(template_id: str, p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    """The template with placeholders shown as labelled blanks, so wording can be checked before approval."""
    try:
        tv = cat.TemplateRepo(session, p.tenant_id).get(template_id)
        path = template_path(tv)
    except (NotFound, FileNotFoundError):
        raise HTTPException(404, "Template not found.") from None
    fields = [FieldSpec(**d) for d in (tv.field_specs or [])]
    from app.services import rendering
    import tempfile
    sample = {f.id: rendering.mark(f.id, f"‹{f.label}›") for f in fields}
    sample.update({f"{f.id}_words": rendering.mark(f.id, f"‹{f.label} in words›") for f in fields if f.type == FieldType.CURRENCY})
    with tempfile.TemporaryDirectory() as tmp:
        blocks = rendering.read_blocks(rendering.render_docx(path, sample, Path(tmp) / "p.docx"))
    return {"template": template_out(tv), "blocks": blocks}
