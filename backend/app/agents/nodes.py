"""LangGraph nodes. Each node does one job, returns a partial state update and talks to the
database only through tenant-scoped repositories.

LangGraph re-runs an interrupted node from its first line on resume. So side effects (status
changes, events, audit) live in the node *before* each interrupt node, and the interrupt nodes
only wait, then apply validated input."""
import re
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator

from langgraph.types import interrupt

from app import db
from app.models.fields import FieldType
from app.models.ui_manifest import UiManifest
from app.repositories.catalog import get_tenant
from app.services import answers as answers_svc
from app.services import documents, extraction, forms, rendering, reviewer, storage
from app.services.case_state import values_hash
from app.services.case_view import CaseContext
from app.services.llm import DemoProvider, LLMError, get_llm_provider
from app.services.values import ValueError_, coerce, to_json
from app.agents.state import WorkflowState

MAX_TRANSCRIPT = 8000


class WorkflowCancelled(Exception):
    pass


@contextmanager
def scope(state: WorkflowState) -> Iterator[CaseContext]:
    with db.SessionLocal() as session:
        cc = CaseContext.load(session, state["tenant_id"], state["case_id"])
        if cc.case.status == "cancelled":
            raise WorkflowCancelled()
        yield cc


def _clean_text(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", text or "").strip()[:MAX_TRANSCRIPT]


# 1 ------------------------------------------------------------------------------------------
def intake_request(state: WorkflowState) -> dict:
    with scope(state) as cc:
        text = _clean_text(state.get("transcript") or cc.case.transcript or "")
        if not text:
            cc.repo.emit(cc.case.id, "workflow_error", "There was nothing to process. Say or type what you need.")
            raise ValueError("empty transcript")
        cc.repo.update_case(cc.case, status="processing", transcript=cc.case.transcript or text)
        cc.repo.emit(cc.case.id, "intake_received", "Request received.")
        cc.repo.audit("workflow_started", cc.case.id, state.get("user_id"), workspace=cc.case.workspace)
    return {"transcript": text, "today": state.get("today") or date.today().isoformat(), "approval_status": "pending",
            "export_refs": [], "notes": []}


# 2 ------------------------------------------------------------------------------------------
def classify_workspace_and_intent(state: WorkflowState) -> dict:
    with scope(state) as cc:
        best, scores = extraction.classify_workspace(state["transcript"])
        suggested = None
        if best and best != cc.case.workspace and scores[best] >= scores.get(cc.case.workspace, 0) + 2:
            suggested = best
            cc.repo.emit(cc.case.id, "workspace_suggestion",
                         f"This sounds like the {extraction.WORKSPACES[best].name} workspace. Continuing in {cc.config.name}.",
                         suggested=best)
        primary = next((d for d in cc.config.documents if d.primary), cc.config.documents[0])
        cc.repo.emit(cc.case.id, "intent_identified", f"Preparing: {primary.title}.")
    return {"suggested_workspace": suggested}


# 3 ------------------------------------------------------------------------------------------
def extract_structured_facts(state: WorkflowState) -> dict:
    with scope(state) as cc:
        cfg, repo, case = cc.config, cc.repo, cc.case
        try:
            provider = get_llm_provider()
        except LLMError:
            provider = DemoProvider()
        allow = get_tenant(cc.session, case.tenant_id).ai_consent
        today = date.fromisoformat(state["today"])
        sources = [("transcript", state["transcript"])]
        for att in repo.attachments(case.id, "supporting"):
            ext = Path(att.stored_name).suffix
            try:
                text = forms.read_text_for_extraction(storage.resolve(case.tenant_id, "files", att.stored_name), ext)
            except FileNotFoundError:
                continue
            if text.strip():
                sources.append((f"attachment:{att.id}", text))
        existing = {(f.field_id, str(f.value.get("v")), f.provenance.get("origin")) for f in repo.facts(case.id)}
        notes: list[str] = []
        stored: list[str] = []
        hints = dict((case.extra or {}).get("party_hints") or {})
        for origin, text in sources:
            result = extraction.extract(cfg, text, provider, today, origin, allow_hosted=allow)
            notes += result.notes
            for f in result.facts:
                spec = cfg.field(f.field_id)
                if spec.type == FieldType.PARTY:
                    hints.setdefault(f.field_id, [])
                    if f.value not in hints[f.field_id]:
                        hints[f.field_id].append(f.value)
                    continue
                try:
                    value = to_json(coerce(spec, f.value))
                except ValueError_:
                    notes.append(f"Ignored a value for {spec.label} because it was not valid.")
                    continue
                if value is None or (f.field_id, str(value), origin) in existing:
                    continue
                repo.add_fact(case.id, f.field_id, value, "suggested",
                              {"origin": origin, "quote": f.quote, "ambiguous": f.ambiguous}, f.confidence)
                existing.add((f.field_id, str(value), origin))
                stored.append(f.field_id)
        repo.set_extra(case, party_hints=hints)
        repo.emit(case.id, "facts_extracted", f"Found {len(set(stored))} detail{'s' if len(set(stored)) != 1 else ''} in what you said.",
                  fields=sorted(set(stored)))
        repo.audit("facts_extracted", case.id, state.get("user_id"), fields=sorted(set(stored)), provider=provider.name)
    return {"extracted_fields": sorted(set(stored)), "notes": notes}


def _reviewer_provider(cc):
    """The reviewer runs only when the business consented to AI services and a real provider is configured."""
    if not get_tenant(cc.session, cc.case.tenant_id).ai_consent:
        return None
    try:
        prov = get_llm_provider()
    except LLMError:
        return None
    return None if prov.name == "demo" else prov


# 4 ------------------------------------------------------------------------------------------
def resolve_existing_records(state: WorkflowState) -> dict:
    """Match 'the landlord is already saved' to a record, strictly inside this tenant."""
    with scope(state) as cc:
        ev = cc.evaluation()
        hints = (cc.case.extra or {}).get("party_hints") or {}
        for spec in cc.config.fields:
            if spec.type != FieldType.PARTY or ev.resolved[spec.id].status == "confirmed" or spec.id in ev.values:
                continue
            candidates = cc.parties.list(spec.party_kind)
            names = [h for h in hints.get(spec.id, []) if isinstance(h, str)]
            if names:
                needle = names[0].casefold()
                candidates = [p for p in candidates if needle in p.full_name.casefold()
                              or p.full_name.casefold() in needle]
            if len(candidates) == 1 and (names or hints.get(spec.id)):
                p = candidates[0]
                cc.repo.add_fact(cc.case.id, spec.id, p.id, "source",
                                 {"origin": "saved record", "party_id": p.id, "quote": names[0] if names else "saved record"}, 0.8)
                cc.repo.emit(cc.case.id, "record_resolved", f"Matched {spec.label.lower()}: {p.full_name}. Please confirm.",
                             field_id=spec.id)
            elif len(candidates) > 1:
                cc.repo.emit(cc.case.id, "record_ambiguous",
                             f"{len(candidates)} saved {spec.label.lower()} records could match. Choose one.", field_id=spec.id)
    return {}


# 5 ------------------------------------------------------------------------------------------
def select_approved_template(state: WorkflowState) -> dict:
    with scope(state) as cc:
        ev = cc.evaluation()
        plans = cc.plans(ev)
        ids = {p.spec.key: p.template.id for p in plans if p.template}
        primary = next((p for p in plans if p.spec.primary and p.template), None)
        if primary and cc.case.template_version_id != primary.template.id:
            cc.repo.update_case(cc.case, template_version_id=primary.template.id)
            cc.repo.emit(cc.case.id, "template_selected",
                         f"Using {primary.template.title}, version {primary.template.version}.",
                         template=primary.template.template_key, version=primary.template.version)
    return {"template_ids": ids, "reopen": False, "export_done": False}


# 6 ------------------------------------------------------------------------------------------
def validate_required_fields(state: WorkflowState) -> dict:
    with scope(state) as cc:
        ev = cc.evaluation()
        fields = []
        for i in ev.blocking:
            if i.field_id and i.field_id not in fields:
                fields.append(i.field_id)
        return {"missing": [s.id for s in ev.missing], "blocking_fields": fields,
                "pending": "missing" if fields else "review"}


def route_after_validation(state: WorkflowState) -> str:
    return "build_dynamic_ui_manifest" if state["pending"] == "missing" else "apply_deterministic_rules"


# 7 ------------------------------------------------------------------------------------------
def build_dynamic_ui_manifest(state: WorkflowState) -> dict:
    """Builds and validates the manifest for the current pause and announces it. The API rebuilds the
    manifest live on each read, so what the user sees always reflects the latest state."""
    with scope(state) as cc:
        errors = state.get("last_answer_errors") or {}
        cc.repo.set_extra(cc.case, answer_errors=errors)
        if state["pending"] == "missing":
            cc.repo.update_case(cc.case, status="awaiting_input")
            n = len(state.get("blocking_fields", []))
            message = f"I need {n} more detail{'s' if n != 1 else ''} to continue."
            event = ("missing_fields", {"fields": state.get("blocking_fields", [])})
        else:
            cc.repo.update_case(cc.case, status="review")
            message, event = "Draft ready. Review and approve it to continue.", ("approval_required", {})
        UiManifest.model_validate(cc.manifest().model_dump())  # a manifest that fails the schema never ships
        cc.repo.emit(cc.case.id, event[0], message, **event[1])
    return {}


def route_after_manifest(state: WorkflowState) -> str:
    return "request_missing_information" if state["pending"] == "missing" else "request_human_review"


def request_missing_information(state: WorkflowState) -> dict:
    payload = interrupt({"type": "missing_information", "fields": state.get("blocking_fields", [])})
    if (payload or {}).get("action") == "cancel":
        with scope(state) as cc:
            cc.repo.update_case(cc.case, status="cancelled")
            cc.repo.audit("cancelled", cc.case.id, state.get("user_id"))
        return {"cancelled": True}
    with scope(state) as cc:
        clean, errors = answers_svc.validate_answers(cc.config, cc.parties, (payload or {}).get("answers") or {})
        answers_svc.apply_answers(cc.repo, cc.case.id, state["user_id"], clean)
        confirm = (payload or {}).get("confirm") or []
        if confirm:
            answers_svc.confirm_current(cc.repo, cc.case.id, state["user_id"], cc.evaluation(), confirm)
        if clean:
            cc.repo.audit("answers_recorded", cc.case.id, state["user_id"], fields=sorted(clean))
    return {"last_answer_errors": errors}


# 8 ------------------------------------------------------------------------------------------
def apply_deterministic_rules(state: WorkflowState) -> dict:
    with scope(state) as cc:
        ev = cc.evaluation()
        cc.repo.set_extra(cc.case, computed={k: to_json(v) if not isinstance(v, (list, dict)) else str(v)
                                             for k, v in ev.computed.items()})
        for issue in ev.issues:
            if issue.severity == "warning":
                cc.repo.emit(cc.case.id, "validation_warning", issue.message, field_id=issue.field_id, code=issue.code)
    return {}


# 9 ------------------------------------------------------------------------------------------
def render_document_preview(state: WorkflowState) -> dict:
    with scope(state) as cc:
        ev = cc.evaluation()
        previews = cc.previews(ev)
        ready = [p["doc_key"] for p in previews if p["blocks"]]
        cc.repo.emit(cc.case.id, "preview_ready", f"Rendered {len(ready)} document preview{'s' if len(ready) != 1 else ''}.",
                     docs=ready)
        found = cc.consistency(ev, previews)
        agent = _reviewer_provider(cc)
        if agent:  # the reviewer agent: a second model reads the draft against what was said
            primary = next((p for p in previews if p.get("primary") and p.get("blocks")), None)
            if primary:
                facts = {s.label: documents.display(s, ev.values[s.id]) for s in ev.active if s.id in ev.values and s.type.value != "party"}
                extra, note = reviewer.safe_review(agent, cc.case.transcript or "", facts, rendering.blocks_plain_text(primary["blocks"]))
                found += extra
                cc.repo.emit(cc.case.id, "agent_review_done", note or f"The reviewer agent read the draft and raised {len(extra)} point{'s' if len(extra) != 1 else ''}.",
                             count=len(extra))
        cc.repo.set_extra(cc.case, consistency=[{"code": i.code, "severity": i.severity, "message": i.message, "key": i.key} for i in found])
        if found:
            cc.repo.emit(cc.case.id, "consistency_checked", f"Consistency check found {len(found)} thing{'s' if len(found) != 1 else ''} to look at.",
                         count=len(found))
        cc.repo.audit("preview_generated", cc.case.id, state.get("user_id"), docs=ready)
    return {"preview_docs": ready}


# 10 -----------------------------------------------------------------------------------------
def request_human_review(state: WorkflowState) -> dict:
    payload = interrupt({"type": "review", "docs": state.get("preview_docs", [])}) or {}
    action = payload.get("action")
    if action == "cancel":
        with scope(state) as cc:
            cc.repo.update_case(cc.case, status="cancelled")
            cc.repo.audit("cancelled", cc.case.id, state.get("user_id"))
        return {"cancelled": True}
    with scope(state) as cc:
        if action == "edit":
            clean, errors = answers_svc.validate_answers(cc.config, cc.parties, payload.get("answers") or {})
            answers_svc.apply_answers(cc.repo, cc.case.id, state["user_id"], clean)
            if clean:
                cc.repo.audit("answers_recorded", cc.case.id, state["user_id"], fields=sorted(clean), stage="review")
            return {"last_answer_errors": errors, "pending": "review", "approval_status": "pending"}
        if action != "approve":
            return {"pending": "review", "approval_status": "pending"}
        ev = cc.evaluation()
        must = {s.id for s in ev.unconfirmed}
        offered = set(payload.get("confirm") or [])
        problems = {}
        if ev.blocking:
            problems["_blocking"] = "Resolve the listed issues before approving."
        if must - offered:
            problems["_unconfirmed"] = "Confirm every highlighted value before approving."
        found = (cc.case.extra or {}).get("consistency") or []
        leaks = {c["key"] for c in found if c["code"] == "leak"}
        if leaks - set(payload.get("acknowledge") or []):
            problems["_leak"] = "Check each possible leftover from another client and tick it before approving."
        if any(c["severity"] == "error" for c in found):
            problems["_consistency"] = "A figure and its words disagree. Fix the document before approving."
        if problems:
            cc.repo.emit(cc.case.id, "validation_warning", next(iter(problems.values())), code="approval_blocked")
            return {"last_answer_errors": problems, "approval_status": "pending", "pending": "review"}
        answers_svc.confirm_current(cc.repo, cc.case.id, state["user_id"], ev, sorted(must))
        ev = cc.evaluation()
        plans = cc.plans(ev)
        h = values_hash(ev, {p.spec.key: p.template.id for p in plans if p.template})
        approval = cc.repo.add_approval(cc.case.id, state["user_id"], h, payload.get("note"))
        cc.repo.update_case(cc.case, status="approved")
        cc.repo.audit("approved", cc.case.id, state["user_id"], approval_id=approval.id, values_hash=h,
                      acknowledged=sorted(payload.get("acknowledge") or []))
        cc.repo.emit(cc.case.id, "approved", "Approved. You can export now.")
        return {"approval_status": "approved", "approval_id": approval.id, "last_answer_errors": {}}


def route_after_review(state: WorkflowState) -> str:
    if state.get("cancelled"):
        return "__end__"
    if state.get("approval_status") == "approved":
        return "export_approved_documents"
    if state.get("last_answer_errors") and set(state["last_answer_errors"]) <= {"_blocking", "_unconfirmed", "_leak", "_consistency"}:
        return "build_dynamic_ui_manifest"
    return "select_approved_template"


# 11 -----------------------------------------------------------------------------------------
class NotApproved(Exception):
    """Export was requested without a recorded approval that matches the current values."""


def assert_approved(cc: CaseContext, ev, plans) -> str:
    ap = cc.repo.latest_approval(cc.case.id)
    if ap is None or cc.case.status not in ("approved", "exported"):
        raise NotApproved("This draft has not been approved.")
    h = values_hash(ev, {p.spec.key: p.template.id for p in plans if p.template})
    if ap.values_hash != h:
        raise NotApproved("The draft changed after it was approved. Approve it again before exporting.")
    return ap.id


def run_exports(cc: CaseContext, formats: dict[str, list[str]], actor: str | None) -> tuple[list[str], list[str]]:
    """Generate the requested files for an approved case. Returns (document ids, honest failure messages)."""
    ev = cc.evaluation()
    plans = cc.plans(ev)
    approval_id = assert_approved(cc, ev, plans)
    src = cc.sources(ev)
    existing = {(d.doc_key, d.fmt): d for d in cc.repo.documents(cc.case.id) if d.approval_id == approval_id}
    ids: list[str] = []
    failures: list[str] = []
    for plan in plans:
        for fmt in formats.get(plan.spec.key, []):
            if fmt not in plan.spec.formats:
                failures.append(f"{plan.spec.title}: {fmt.upper()} is not a supported format.")
                continue
            if plan.template is None and plan.spec.kind != "ledger":
                failures.append(f"{plan.spec.title}: no approved template is available.")
                continue
            if (plan.spec.key, fmt) in existing:  # idempotent: the same approved export is never duplicated
                ids.append(existing[(plan.spec.key, fmt)].id)
                continue
            stored, path = storage.new_path(cc.case.tenant_id, "documents", f".{fmt}")
            try:
                documents.export_file(cc.config, ev, src, plan, fmt, path)
            except rendering.PdfUnavailable as exc:
                failures.append(f"{plan.spec.title}: {exc}")
                cc.repo.emit(cc.case.id, "export_failed", f"{plan.spec.title} ({fmt.upper()}) could not be created. {exc}")
                continue
            if not path.exists() or path.stat().st_size == 0:
                failures.append(f"{plan.spec.title}: the {fmt.upper()} file was not created.")
                continue
            storage.commit(cc.case.tenant_id, "documents", stored)  # durable copy, so any instance can serve the download
            doc = cc.repo.add_document(cc.case.id, doc_key=plan.spec.key, title=plan.spec.title, fmt=fmt,
                                       stored_name=stored, is_sample=True, approval_id=approval_id)
            ids.append(doc.id)
            cc.repo.audit("exported", cc.case.id, actor, document_id=doc.id, doc_key=plan.spec.key, fmt=fmt)
            cc.repo.emit(cc.case.id, "export_ready", f"{plan.spec.title} ({fmt.upper()}) is ready to download.",
                         document_id=doc.id)
    if ids:
        cc.repo.update_case(cc.case, status="exported")
    return ids, failures


def export_approved_documents(state: WorkflowState) -> dict:
    req = interrupt({"type": "export", "approval_id": state.get("approval_id")}) or {}
    action = req.get("action")
    if action == "finish":
        return {"export_done": True}
    if action == "reopen":
        with scope(state) as cc:
            cc.repo.update_case(cc.case, status="review")
            cc.repo.audit("reopened", cc.case.id, state.get("user_id"))
        return {"reopen": True, "approval_status": "pending", "pending": "review"}
    if action == "export":
        with scope(state) as cc:
            try:
                ids, failures = run_exports(cc, req.get("formats") or {}, state.get("user_id"))
            except NotApproved as exc:
                cc.repo.emit(cc.case.id, "export_failed", str(exc))
                return {}
            if failures:
                cc.repo.set_extra(cc.case, export_failures=failures)
            else:
                cc.repo.set_extra(cc.case, export_failures=[])
        return {"export_refs": [*state.get("export_refs", []), *ids]}
    return {}


def route_after_export(state: WorkflowState) -> str:
    if state.get("reopen"):
        return "select_approved_template"
    return "persist_audit_event" if state.get("export_done") else "export_approved_documents"


# 12 -----------------------------------------------------------------------------------------
def persist_audit_event(state: WorkflowState) -> dict:
    with scope(state) as cc:
        cc.repo.audit("workflow_completed", cc.case.id, state.get("user_id"), exports=len(state.get("export_refs", [])))
        cc.repo.emit(cc.case.id, "workflow_complete", "All done.")
    return {}
