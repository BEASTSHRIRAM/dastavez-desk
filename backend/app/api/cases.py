"""Cases: creation, intake, workflow control, progress events, previews and the audit trail."""
import json
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import db
from app.agents import runner
from app.agents.nodes import NotApproved, assert_approved
from app.api import deps
from app.models.orm import Case
from app.models.ui_manifest import UiManifest
from app.repositories.cases import NotFound, TenantRepo
from app.services import answers as answers_svc
from app.services import stt, storage
from app.services.auth import Principal
from app.services.case_view import CaseContext
from app.verticals import WORKSPACES

router = APIRouter(prefix="/api")
ACTIVE = ("awaiting_input", "review", "approved", "exported")


# ------------------------------------------------------------------ helpers
def load(session: Session, p: Principal, case_id: str) -> CaseContext:
    try:
        return CaseContext.load(session, p.tenant_id, case_id)
    except NotFound:
        raise HTTPException(404, "Case not found.") from None


def case_out(cc: CaseContext) -> dict[str, Any]:
    c = cc.case
    extra = c.extra or {}
    pending = runner.pending_interrupt(c.thread_id) if c.status in ACTIVE else None
    latest = cc.repo.latest_approval(c.id)
    return {"id": c.id, "workspace": c.workspace, "title": c.title, "status": c.status, "transcript": c.transcript,
            "created_at": c.created_at, "updated_at": c.updated_at, "pending": pending,
            "answer_errors": extra.get("answer_errors") or {}, "export_failures": extra.get("export_failures") or [],
            "approved_at": latest.created_at if latest and c.status in ("approved", "exported") else None,
            "documents": [{"id": d.id, "doc_key": d.doc_key, "title": d.title, "fmt": d.fmt, "is_sample": d.is_sample,
                           "created_at": d.created_at} for d in cc.repo.documents(c.id)]}


def _resume(cc: CaseContext, payload: dict[str, Any]) -> None:
    runner.resume(cc.case.tenant_id, cc.case.id, cc.case.thread_id, payload)
    cc.session.expire_all()


def _need_status(cc: CaseContext, *allowed: str) -> None:
    if cc.case.status not in allowed:
        raise HTTPException(409, f"This case is {cc.case.status.replace('_', ' ')}, so that action is not available now.")


def _check_answers(cc: CaseContext, answers: dict[str, Any]) -> None:
    _, errors = answers_svc.validate_answers(cc.config, cc.parties, answers)
    if errors:
        raise HTTPException(422, {"message": "Some answers need fixing.", "errors": errors})


# ------------------------------------------------------------------ create / read
class CaseIn(BaseModel):
    workspace: str
    template_key: str | None = Field(default=None, max_length=60)  # required for workspace "custom"
    title: str | None = Field(default=None, max_length=200)
    transcript: str | None = Field(default=None, max_length=8000)


@router.post("/cases", status_code=201)
def create_case(body: CaseIn, p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session),
                idempotency_key: str | None = Header(default=None, max_length=80)):
    title = None
    if body.workspace == "custom":
        from app.repositories.catalog import TemplateRepo
        approved = TemplateRepo(session, p.tenant_id).latest_approved(body.template_key or "")
        if not approved or approved[0].tenant_id != p.tenant_id:
            raise HTTPException(422, "That template is not approved yet. A business owner approves it in Templates first.")
        title = f"{approved[0].title} case"
    elif body.workspace not in WORKSPACES:
        raise HTTPException(422, "Unknown workspace.")
    repo = TenantRepo(session, p.tenant_id)
    case, created = repo.create_case(user_id=p.user_id, workspace=body.workspace, transcript=body.transcript,
                                     title=body.title or title or f"{WORKSPACES[body.workspace].name} case",
                                     idempotency_key=idempotency_key)
    if created:
        if body.workspace == "custom":
            repo.set_extra(case, template_key=body.template_key)
        repo.audit("case_created", case.id, p.user_id, workspace=body.workspace)
    return case_out(CaseContext.load(session, p.tenant_id, case.id)) | {"created": created}


@router.get("/cases")
def list_cases(repo: TenantRepo = Depends(deps.repo)):
    return [{"id": c.id, "workspace": c.workspace, "title": c.title, "status": c.status, "created_at": c.created_at,
             "updated_at": c.updated_at} for c in repo.list_cases()]


@router.get("/cases/{case_id}")
def get_case(case_id: str, p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    return case_out(load(session, p, case_id))


@router.get("/cases/{case_id}/manifest", response_model=UiManifest)
def get_manifest(case_id: str, view: str | None = None, p: Principal = Depends(deps.principal),
                 session: Session = Depends(deps.get_session)):
    return load(session, p, case_id).manifest(view)


@router.get("/cases/{case_id}/preview")
def get_preview(case_id: str, p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    return {"documents": cc.previews(cc.evaluation())}


@router.get("/cases/{case_id}/audit")
def get_audit(case_id: str, p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    return [{"id": a.id, "action": a.action, "actor_id": a.actor_id, "detail": a.detail, "created_at": a.created_at}
            for a in cc.repo.audit_trail(cc.case.id)]


# ------------------------------------------------------------------ transcription (never starts the agent)
@router.post("/cases/{case_id}/transcribe")
async def transcribe(case_id: str, file: UploadFile = File(...), language: str | None = None,
                     p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    from app.repositories.catalog import get_tenant
    if not get_tenant(session, p.tenant_id).ai_consent:
        raise HTTPException(403, "Your business has not agreed to send audio to a third-party speech service. "
                                 "An owner can enable this in settings, or you can type your request.")
    data = await file.read()
    try:
        storage.validate_upload(file.filename or "audio.webm", data)
        text = stt.transcribe(data, storage.safe_display_name(file.filename or "audio.webm"),
                              file.content_type or "audio/webm", language)
    except storage.UploadRejected as exc:
        raise HTTPException(422, str(exc)) from None
    except stt.SttUnavailable as exc:
        raise HTTPException(501, {"code": "stt_unconfigured", "message": str(exc)}) from None
    except stt.SttFailed as exc:
        raise HTTPException(502, {"code": "stt_failed", "message": str(exc)}) from None
    cc.repo.audit("transcribed", cc.case.id, p.user_id, chars=len(text))
    return {"transcript": text}


# ------------------------------------------------------------------ workflow control
class IntakeIn(BaseModel):
    transcript: str = Field(min_length=3, max_length=8000)


@router.post("/cases/{case_id}/intake", status_code=202)
def start_intake(case_id: str, body: IntakeIn, tasks: BackgroundTasks, p: Principal = Depends(deps.require("operator")),
                 session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    _need_status(cc, "intake")
    cc.repo.update_case(cc.case, status="processing", transcript=body.transcript)
    tasks.add_task(runner.start, p.tenant_id, cc.case.id, cc.case.thread_id, p.user_id, cc.case.workspace, body.transcript)
    return {"status": "processing"}


@router.post("/cases/{case_id}/retry", status_code=202)
def retry(case_id: str, tasks: BackgroundTasks, p: Principal = Depends(deps.require("operator")),
          session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    _need_status(cc, "failed")
    cc.repo.update_case(cc.case, status="processing")
    tasks.add_task(runner.retry, p.tenant_id, cc.case.id, cc.case.thread_id)
    return {"status": "processing"}


class AnswersIn(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    confirm: list[str] = Field(default_factory=list)  # accept the currently shown value of these fields
    conflict_choices: dict[str, Any] = Field(default_factory=dict)


@router.post("/cases/{case_id}/answers")
def submit_answers(case_id: str, body: AnswersIn, p: Principal = Depends(deps.require("operator")),
                   session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    _need_status(cc, "awaiting_input")
    merged = {**body.answers, **body.conflict_choices}
    _check_answers(cc, merged)
    _resume(cc, {"answers": merged, "confirm": body.confirm})
    return case_out(load(session, p, case_id))


@router.post("/cases/{case_id}/review/edit")
def edit_in_review(case_id: str, body: AnswersIn, p: Principal = Depends(deps.require("operator")),
                   session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    _need_status(cc, "review")
    _check_answers(cc, body.answers)
    _resume(cc, {"action": "edit", "answers": body.answers})
    return case_out(load(session, p, case_id))


class ApproveIn(BaseModel):
    confirm: list[str] = Field(default_factory=list)
    acknowledge: list[str] = Field(default_factory=list)  # keys of possible-leftover findings the person checked
    note: str | None = Field(default=None, max_length=500)


@router.post("/cases/{case_id}/approve")
def approve(case_id: str, body: ApproveIn, p: Principal = Depends(deps.require("operator")),
            session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    _need_status(cc, "review")
    _resume(cc, {"action": "approve", "confirm": body.confirm, "note": body.note, "acknowledge": body.acknowledge})
    out = case_out(load(session, p, case_id))
    if out["status"] != "approved":
        raise HTTPException(409, {"message": "The draft was not approved. Resolve the highlighted items first.",
                                  "errors": out["answer_errors"]})
    return out


class ExportIn(BaseModel):
    formats: dict[str, list[str]]


@router.post("/cases/{case_id}/export")
def export(case_id: str, body: ExportIn, p: Principal = Depends(deps.require("operator")),
           session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    if cc.case.status not in ("approved", "exported") or cc.repo.latest_approval(cc.case.id) is None:
        raise HTTPException(409, "Approve the draft before exporting it.")
    ev = cc.evaluation()
    try:
        assert_approved(cc, ev, cc.plans(ev))  # approval must match exactly what would be exported
    except NotApproved as exc:
        raise HTTPException(409, str(exc)) from None
    _resume(cc, {"action": "export", "formats": body.formats})
    out = case_out(load(session, p, case_id))
    return out | {"requested": body.formats}


@router.post("/cases/{case_id}/reopen")
def reopen(case_id: str, p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    _need_status(cc, "approved", "exported")
    _resume(cc, {"action": "reopen"})
    return case_out(load(session, p, case_id))


@router.post("/cases/{case_id}/finish")
def finish(case_id: str, p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    _need_status(cc, "approved", "exported")
    _resume(cc, {"action": "finish"})
    return case_out(load(session, p, case_id))


@router.post("/cases/{case_id}/cancel")
def cancel(case_id: str, p: Principal = Depends(deps.require("operator")), session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    if cc.case.status in ("exported", "cancelled"):
        raise HTTPException(409, "This case can no longer be cancelled.")
    cc.repo.update_case(cc.case, status="cancelled")
    cc.repo.audit("cancelled", cc.case.id, p.user_id)
    cc.repo.emit(cc.case.id, "cancelled", "Cancelled.")
    return case_out(cc)


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: str, p: Principal = Depends(deps.require("owner")), session: Session = Depends(deps.get_session)):
    """Retention control: removes the case, its facts, files and generated documents. A tenant-level audit
    record that the deletion happened is kept (without personal data)."""
    from sqlalchemy import delete, update
    from app.models import orm
    cc = load(session, p, case_id)
    for att in cc.repo.attachments(case_id):
        storage.delete(p.tenant_id, "files", att.stored_name)
    for doc in cc.repo.documents(case_id):
        storage.delete(p.tenant_id, "documents", doc.stored_name)
    t = p.tenant_id
    session.execute(update(orm.AuditEvent).where(orm.AuditEvent.case_id == case_id, orm.AuditEvent.tenant_id == t)
                    .values(case_id=None, detail={"redacted": True}))
    for model in (orm.WorkflowEvent, orm.GeneratedDocument, orm.Approval, orm.Attachment, orm.Fact):
        session.execute(delete(model).where(model.case_id == case_id, model.tenant_id == t))
    session.execute(delete(orm.Case).where(orm.Case.id == case_id, orm.Case.tenant_id == t))
    session.commit()
    cc.repo.audit("case_deleted", None, p.user_id, case_ref=case_id[:8])


# ------------------------------------------------------------------ progress events
def _event_out(e) -> dict[str, Any]:
    return {"id": e.id, "type": e.type, "message": e.message, "data": e.data, "created_at": e.created_at.isoformat()}


@router.get("/cases/{case_id}/events")
def list_events(case_id: str, after: int = 0, p: Principal = Depends(deps.principal),
                session: Session = Depends(deps.get_session)):
    cc = load(session, p, case_id)
    return [_event_out(e) for e in cc.repo.events_after(cc.case.id, after)]


@router.get("/cases/{case_id}/events/stream")
def stream_events(case_id: str, request: Request, after: int = 0, max_seconds: int = 600,
                  p: Principal = Depends(deps.principal)):
    """Server-Sent Events. Only typed progress messages are sent, never model reasoning.
    No request-scoped DB session here: one held open for the whole stream would sit 'idle in
    transaction' and block schema work such as CREATE INDEX CONCURRENTLY."""
    with db.SessionLocal() as check:
        load(check, p, case_id)  # 404 before the stream opens; the session closes immediately

    def gen():
        last, started, idle = after, time.monotonic(), 0
        while time.monotonic() - started < max_seconds:
            with db.SessionLocal() as s:
                events = TenantRepo(s, p.tenant_id).events_after(case_id, last)
            for e in events:
                last = e.id
                idle = 0
                yield f"id: {e.id}\nevent: {e.type}\ndata: {json.dumps(_event_out(e))}\n\n"
            idle += 1
            if idle % 30 == 0:
                yield ": keep-alive\n\n"
            time.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
