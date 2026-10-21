"""Build the UI manifest for a case from its current state.

Which questions appear is decided here from real state (missing required fields, conflicts, uncertain
values, ambiguous party records), never from a fixed form. Output is validated by UiManifest."""
from dataclasses import dataclass, field
from typing import Any

from app.models.fields import FieldSpec, FieldType
from app.models.orm import Case, Party
from app.models.ui_manifest import (ApprovalPanel, ChangeComparison, ConflictChoice, ConflictOption, DocumentChecklist,
                                    DocumentPreviewC, ExportDocument, ExportOptions, FieldComponent, FileAttachment,
                                    IssueItem, MissingInfoWarning, PartyOption, Provenance, Section, SourceEvidence,
                                    UiManifest, Validation)
from app.services.case_state import Evaluation
from app.services.values import display, to_json
from app.verticals.base import WorkspaceConfig

KIND = {FieldType.TEXT: "text_input", FieldType.LONGTEXT: "long_text", FieldType.PERSON: "person",
        FieldType.ADDRESS: "address", FieldType.PHONE: "phone", FieldType.CURRENCY: "currency",
        FieldType.NUMBER: "number", FieldType.DATE: "date", FieldType.SELECT: "select",
        FieldType.MULTISELECT: "multi_select", FieldType.YESNO: "yes_no", FieldType.PARTY: "party_select"}
LOW_CONFIDENCE = 0.7


@dataclass
class ManifestInput:
    config: WorkspaceConfig
    case: Case
    ev: Evaluation
    parties: dict[str, list[Party]] = field(default_factory=dict)  # party_kind -> saved parties
    attachments: list[Any] = field(default_factory=list)
    form_fields: list[str] = field(default_factory=list)
    form_mapping: dict[str, str] = field(default_factory=dict)
    previews: list[dict[str, Any]] = field(default_factory=list)
    exported: list[dict[str, Any]] = field(default_factory=list)
    pdf_available: bool = False
    approved: bool = False
    plan_issues: list[Any] = field(default_factory=list)


def _field_component(m: ManifestInput, spec: FieldSpec, *, optional: bool = False, confirm: bool = False) -> FieldComponent:
    r = m.ev.resolved[spec.id]
    value = r.value if r.value is not None else None
    comp = FieldComponent(
        component=KIND[spec.type], field_id=spec.id, label=spec.label, required=spec.required, help=spec.help,
        value=to_json(value), high_impact=spec.high_impact, needs_confirmation=confirm, optional=optional,
        validation=Validation(min=spec.min, max=spec.max, pattern=spec.pattern, options=spec.options),
        provenance=Provenance(origin=r.provenance.get("origin"), quote=r.provenance.get("quote"),
                              status=r.status if r.status in ("confirmed", "source", "suggested", "default") else "none",
                              confidence=r.confidence))
    if spec.type == FieldType.PARTY:
        comp.party_options = [PartyOption(id=p.id, label=p.full_name, detail=p.address)
                              for p in m.parties.get(spec.party_kind or "", [])]
    return comp


def _evidence(m: ManifestInput) -> SourceEvidence:
    items = []
    for spec in m.ev.active:
        r = m.ev.resolved[spec.id]
        if r.value is None or r.status in ("none", "default"):
            continue
        shown = display(spec, r.value) if spec.type != FieldType.PARTY else _party_name(m, spec, r.value)
        items.append({"field_id": spec.id, "label": spec.label, "value": shown, "quote": r.provenance.get("quote"),
                      "origin": r.provenance.get("origin"), "status": r.status, "confidence": r.confidence})
    return SourceEvidence(items=items)


def _party_name(m: ManifestInput, spec: FieldSpec, party_id: str) -> str:
    for p in m.parties.get(spec.party_kind or "", []):
        if p.id == party_id:
            return p.full_name
    return "Saved record"


def _issues(m: ManifestInput) -> list[IssueItem]:
    return [IssueItem(field_id=i.field_id, code=i.code, severity=i.severity, message=i.message)
            for i in [*m.ev.issues, *m.plan_issues]]


def build_manifest(m: ManifestInput, view: str | None = None) -> UiManifest:
    """`view="review"` lets an already-approved case be re-opened read-only for inspection."""
    case = m.case
    status = case.status
    if status in ("intake", "cancelled") or (status == "awaiting_input" and not case.transcript):
        return UiManifest(case_id=case.id, stage="intake", title="Tell me about the job",
                          subtitle="Speak or type. You will review everything before anything is produced.",
                          sections=[])
    if status == "awaiting_input":
        return _questions(m)
    if status == "review" or (view == "review" and status in ("approved", "exported")):
        return _review(m)
    return _export(m, complete=(status == "exported"))


def _questions(m: ManifestInput) -> UiManifest:
    cfg, ev = m.config, m.ev
    sections: list[Section] = []
    heard = _evidence(m)
    if heard.items:
        sections.append(Section(title="What I understood", description="Taken from your words. Check anything that looks wrong.",
                                components=[heard]))
    need: list = []
    missing_ids = [s.id for s in ev.missing]
    if missing_ids:
        need.append(MissingInfoWarning(message=f"{len(missing_ids)} required detail{'s' if len(missing_ids) != 1 else ''} not found.",
                                       field_ids=missing_ids))
    for c in ev.conflicts:
        need.append(ConflictChoice(field_id=c.field_id, label=cfg.field(c.field_id).label,
                                   options=[ConflictOption(**o) for o in (c.conflict or [])]))
    asked: set[str] = set()
    for spec in ev.active:
        r = ev.resolved[spec.id]
        if r.conflict:
            continue
        if spec.id in missing_ids:
            need.append(_field_component(m, spec))
            asked.add(spec.id)
        elif spec.type == FieldType.PARTY and r.status != "confirmed":
            need.append(_field_component(m, spec, confirm=True))
            asked.add(spec.id)
        elif r.status == "suggested" and (r.confidence is not None and r.confidence < LOW_CONFIDENCE) and spec.id in ev.values:
            need.append(_field_component(m, spec, confirm=True))
            asked.add(spec.id)
    if need:
        sections.append(Section(title="What I still need", description="Only what the job requires.", components=need))
    if cfg.id == "government":
        sections.append(Section(title="Application form", components=[FileAttachment(
            label="Upload the application form", kind="form", accept=[".pdf", ".docx", ".txt"],
            help="Only the field labels are read. Map each to an answer below.",
            uploaded=[{"id": a.id, "name": a.original_name} for a in m.attachments if a.kind == "form"],
            mapping=m.form_mapping, mappable_fields=[{"id": s.id, "label": s.label} for s in ev.active])]))
    optional = [_field_component(m, s, optional=True) for s in ev.active
                if not s.required and s.id not in ev.values and s.id not in asked and s.type != FieldType.PARTY]
    if optional:
        sections.append(Section(title="Optional details", components=optional))
    return UiManifest(case_id=m.case.id, stage="questions", title="A few things to confirm",
                      subtitle="I filled in everything I could. These are the gaps.", sections=sections)


def _review(m: ManifestInput) -> UiManifest:
    cfg, ev = m.config, m.ev
    sections: list[Section] = []
    confirm = [{"field_id": s.id, "label": s.label,
                "value": display(s, ev.values[s.id]) if s.type != FieldType.PARTY else _party_name(m, s, ev.values[s.id])}
               for s in ev.unconfirmed]
    issues = _issues(m)
    sections.append(Section(title="Approval", components=[ApprovalPanel(
        issues=issues, confirm_fields=[] if m.approved else confirm,
        can_approve=not any(i.severity == "error" for i in issues) and not m.approved, approved=m.approved,
        disclaimers=cfg.disclaimers)]))
    for p in m.previews:
        comps: list = [DocumentPreviewC(doc_key=p["doc_key"], title=p["title"], blocks=p["blocks"],
                                        template=p.get("template"), unavailable=p.get("unavailable"))]
        if p.get("changes"):
            comps.append(ChangeComparison(doc_key=p["doc_key"], title=p["title"], sections=p["changes"]))
        sections.append(Section(title=p["title"], components=comps))
    if "checklist" in ev.computed:
        sections.append(Section(title="Checklist", components=[DocumentChecklist(
            title="Supporting documents", items=ev.computed["checklist"], source=ev.computed.get("requirements_source"),
            last_verified=ev.computed.get("requirements_verified"))]))
    sections.append(Section(title="Where each value came from", components=[_evidence(m)]))
    if not m.approved:
        sections.append(Section(title="Edit details", description="Correct anything the draft got wrong. The draft updates after you save.",
                                components=[_field_component(m, s) for s in ev.active]))
    return UiManifest(case_id=m.case.id, stage="review", title="Review the draft",
                      subtitle="Nothing is exported until you approve it.", sections=sections)


def _export(m: ManifestInput, complete: bool) -> UiManifest:
    docs = [ExportDocument(doc_key=p["doc_key"], title=p["title"], formats=p["formats"]) for p in m.previews]
    return UiManifest(case_id=m.case.id, stage="complete" if complete else "export",
                      title="Export" if not complete else "Done", subtitle="Choose a format per document.",
                      sections=[Section(title="Documents", components=[ExportOptions(
                          documents=docs, pdf_available=m.pdf_available, exported=m.exported)])])
