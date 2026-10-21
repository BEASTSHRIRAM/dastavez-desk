"""Assemble documents for a case: template selection, context, preview, comparison and export.

Spec reading order: values (typed) -> display strings -> template placeholders. The preview and the
exported file are rendered from the same template and context, so they cannot drift apart."""
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.models.fields import Issue
from app.models.orm import Party, TemplateVersion
from app.repositories.catalog import TemplateRepo
from app.services import exporting, rendering
from app.services.case_state import Evaluation
from app.services.parsing import format_date_long, format_inr
from app.services.values import display
from app.templates.builder import template_file
from app.verticals.base import DocumentSpec, WorkspaceConfig

MISSING = "[missing]"


@dataclass
class DocPlan:
    spec: DocumentSpec
    template: TemplateVersion | None = None
    issue: Issue | None = None


@dataclass
class Sources:
    """Everything besides field values a template may reference."""
    party: Party | None = None
    form_name: str = ""
    form_fields: list[str] = field(default_factory=list)
    form_mapping: dict[str, str] = field(default_factory=dict)  # form label -> field_id


# ---------------------------------------------------------------- template selection
def plan_documents(repo: TemplateRepo, config: WorkspaceConfig, values: dict[str, Any]) -> list[DocPlan]:
    plans = []
    for spec in config.documents:
        if spec.kind == "ledger":
            plans.append(DocPlan(spec))
            continue
        key = spec.template_key
        if spec.template_by:
            chosen = values.get(spec.template_by["field"])
            key = spec.template_by["map"].get(chosen) if chosen else None
            if key is None:
                plans.append(DocPlan(spec, issue=Issue(field_id=spec.template_by["field"], code="template",
                                                       message="Choose the declaration type to select a template.")))
                continue
        candidates = repo.latest_approved(key)
        if not candidates:
            plans.append(DocPlan(spec, issue=Issue(code="template", message=f"No approved version of template '{key}' is available.")))
        else:
            plans.append(DocPlan(spec, template=candidates[0]))
    return plans


# ---------------------------------------------------------------- context
def _fmt_computed(key: str, v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v) if key.endswith(("_months", "_pct")) else f"Rs. {format_inr(v)}"
    if isinstance(v, date):
        return format_date_long(v)
    return v


def _split_lines(text: str | None) -> list[str]:
    return [ln.strip(" -*\t") for ln in re.split(r"[\n;]", text or "") if ln.strip(" -*\t")]


def build_context(config: WorkspaceConfig, ev: Evaluation, src: Sources, plan: DocPlan, marker: bool) -> dict[str, Any]:
    def wrap(fid: str, text: str) -> str:
        return rendering.mark(fid, text) if marker else text

    ctx: dict[str, Any] = {}
    for spec in config.fields:
        text = display(spec, ev.values.get(spec.id))
        if spec.type.value == "party":
            text = ""
        ctx[spec.id] = wrap(spec.id, text) if text else (MISSING if spec.required and spec.id in {s.id for s in ev.active} else "")
        # templates branch on <field>_flag (a real bool); the plain field name holds display text
        ctx[f"{spec.id}_flag"] = ev.values.get(spec.id) is True
    for key, v in ev.computed.items():
        if isinstance(v, list):
            ctx[key] = v
        else:
            ctx[key] = _fmt_computed(key, v)
    p = src.party
    ctx["landlord_name"] = wrap("landlord_party", p.full_name) if p else MISSING
    ctx["landlord_address"] = wrap("landlord_party", p.address or "") if p and p.address else ""
    ctx["landlord_phone"] = p.phone if p and p.phone else ""
    ctx["template_key"] = plan.template.template_key if plan.template else ""
    ctx["template_version"] = plan.template.version if plan.template else ""
    ctx["requirements_source"] = ev.computed.get("requirements_source") or "No requirements source on file."
    ctx["requirements_verified"] = ev.computed.get("requirements_verified") or "Not verified"

    # ---- list/table extras per workspace
    furnished_items = _split_lines(ev.values.get("inventory_summary"))
    ctx["inventory_items"] = (["Walls, floors and ceilings", "Doors, windows and locks", "Electrical and plumbing points"]
                              + (furnished_items or ["No furnishings listed"]))
    ctx["form_name"] = src.form_name or "No form uploaded"
    mapping = [{"form_field": f, "answer": display(config.field(fid), ev.values.get(fid)) or MISSING}
               for f, fid in src.form_mapping.items() if fid in config.field_ids()]
    ctx["form_mapping"] = mapping or [{"form_field": "(no fields mapped)", "answer": ""}]
    unmapped = [f for f in src.form_fields if f not in src.form_mapping]
    unanswered = [m["form_field"] for m in mapping if m["answer"] == MISSING]
    ctx["unmapped_form_fields"] = (unmapped + [f"{f} (mapped, no answer yet)" for f in unanswered]) or ["None"]
    ctx.setdefault("checklist", ["No checklist available for this selection"])
    days = ev.computed.get("itinerary_days") or []
    transport = ev.values.get("transport_summary") or "transport to be confirmed"
    ctx["itinerary_days"] = [
        {"day": d["day"], "date": format_date_long(d["date"]),
         "plan": ("Arrival. " + transport) if i == 0 else "Departure" if i == len(days) - 1 and len(days) > 1
         else "To be planned with the applicant"} for i, d in enumerate(days)] or [{"day": "", "date": "", "plan": "Dates needed"}]
    missing = [s.label for s in ev.missing] + [config.field(f).label for f in ("occupation", "transport_summary")
                                                if f in config.field_ids() and f not in ev.values]
    ctx["missing_items"] = missing or ["Nothing outstanding"]
    return ctx


# ---------------------------------------------------------------- preview and export
def _ledger_table(config: WorkspaceConfig, ev: Evaluation, status: str) -> list[list[str]]:
    row = exporting.ledger_row(ev.values, ev.computed, status)
    def txt(v):
        return format_date_long(v) if isinstance(v, date) else f"{v:.2f}" if isinstance(v, Decimal) else "" if v is None else str(v)
    return [exporting.LEDGER_HEADERS, [txt(v) for v in row]]


def preview(config: WorkspaceConfig, ev: Evaluation, src: Sources, plan: DocPlan, work_dir: Path) -> dict[str, Any]:
    base = {"doc_key": plan.spec.key, "title": plan.spec.title, "primary": plan.spec.primary,
            "formats": plan.spec.formats, "is_sample": True}
    if plan.spec.kind == "ledger":
        table = _ledger_table(config, ev, "Draft - pending approval")
        return {**base, "blocks": [{"type": "table", "rows": table, "header": True}], "changes": [], "template": None}
    if plan.template is None:
        return {**base, "blocks": [], "changes": [], "template": None, "unavailable": plan.issue.message if plan.issue else "No template"}
    path = template_file(plan.template.template_key, plan.template.version)
    ctx = build_context(config, ev, src, plan, marker=True)
    tmp = rendering.render_docx(path, ctx, work_dir / f"preview_{plan.spec.key}.docx")
    return {**base, "blocks": rendering.read_blocks(tmp),
            "changes": rendering.compare_with_template(path, ctx),
            "template": {"id": plan.template.id, "key": plan.template.template_key, "version": plan.template.version,
                         "title": plan.template.title, "is_demo": plan.template.is_demo,
                         "jurisdiction": plan.template.jurisdiction}}


def export_file(config: WorkspaceConfig, ev: Evaluation, src: Sources, plan: DocPlan, fmt: str, out: Path) -> Path:
    """Write one real file. Raises rendering.PdfUnavailable for PDFs that cannot be produced."""
    if plan.spec.kind == "ledger":
        rows = [exporting.ledger_row(ev.values, ev.computed, "Approved")]
        return exporting.write_xlsx(out, rows) if fmt == "xlsx" else exporting.write_csv(out, rows)
    path = template_file(plan.template.template_key, plan.template.version)
    ctx = build_context(config, ev, src, plan, marker=False)
    if fmt == "docx":
        return rendering.render_docx(path, ctx, out)
    docx = rendering.render_docx(path, ctx, out.with_suffix(".src.docx"))
    try:
        return rendering.docx_to_pdf(docx, out)
    finally:
        docx.unlink(missing_ok=True)
