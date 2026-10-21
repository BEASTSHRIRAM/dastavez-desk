"""Read-side assembly shared by the graph and the API: evaluation, sources and manifest input."""
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.fields import FieldType
from app.models.orm import Case
from app.models.ui_manifest import UiManifest
from app.repositories.cases import NotFound, TenantRepo
from app.repositories.catalog import PartyRepo, TemplateRepo
from app.services import consistency as cons
from app.services import documents, forms, rendering, storage
from app.services.case_state import Evaluation, evaluate
from app.services.manifest import ManifestInput, build_manifest
from app.verticals import WORKSPACES, custom, get_workspace
from app.verticals.base import WorkspaceConfig


@dataclass
class CaseContext:
    session: Session
    repo: TenantRepo
    parties: PartyRepo
    templates: TemplateRepo
    case: Case
    config: WorkspaceConfig

    @classmethod
    def load(cls, session: Session, tenant_id: str, case_id: str) -> "CaseContext":
        repo = TenantRepo(session, tenant_id)
        case = repo.get_case(case_id)
        templates = TemplateRepo(session, tenant_id)
        if case.workspace == "custom":
            key = (case.extra or {}).get("template_key", "")
            versions = templates.latest_approved(key) or templates.latest_any(key)
            if not versions:
                raise NotFound("The template for this case is no longer available")
            config = custom.config_for(versions[0])
        else:
            config = get_workspace(case.workspace)
        return cls(session, repo, PartyRepo(session, tenant_id), templates, case, config)

    def evaluation(self) -> Evaluation:
        return evaluate(self.config, self.repo.facts(self.case.id))

    def sources(self, ev: Evaluation) -> documents.Sources:
        src = documents.Sources(form_mapping=dict((self.case.extra or {}).get("form_mapping") or {}))
        for spec in self.config.fields:
            if spec.type == FieldType.PARTY and spec.id in ev.values:
                try:
                    src.party = self.parties.get(ev.values[spec.id])
                except NotFound:
                    src.party = None
        forms = self.repo.attachments(self.case.id, "form")
        if forms:
            src.form_name = forms[-1].original_name
            src.form_fields = list(forms[-1].meta.get("fields", []))
        return src

    def plans(self, ev: Evaluation) -> list[documents.DocPlan]:
        return documents.plan_documents(self.templates, self.config, ev.values)

    def previews(self, ev: Evaluation, plans: list[documents.DocPlan] | None = None) -> list[dict[str, Any]]:
        plans = plans if plans is not None else self.plans(ev)
        src = self.sources(ev)
        with tempfile.TemporaryDirectory() as tmp:
            return [documents.preview(self.config, ev, src, p, Path(tmp)) for p in plans]

    def consistency(self, ev: Evaluation, previews: list[dict[str, Any]]) -> list:
        """Run the consistency guard over the rendered drafts. Returns Issue objects."""
        src = self.sources(ev)
        own = {str(v).casefold() for v in ev.values.values() if isinstance(v, str)}
        if src.party:
            own |= {x.casefold() for x in (src.party.full_name, src.party.address, src.party.phone) if x}
        others: list[cons.OtherEntity] = []
        for p in self.parties.list():
            if src.party and p.id == src.party.id:
                continue
            others.append(cons.OtherEntity("name", p.full_name, f"saved record {p.full_name}"))
            if p.phone:
                others.append(cons.OtherEntity("phone", p.phone, f"saved record {p.full_name}"))
            if p.address:
                others.append(cons.OtherEntity("address", p.address, f"saved record {p.full_name}"))
        kinds = {"person": "name", "address": "address", "phone": "phone"}
        id_kind = {f.id: kinds[f.type.value] for w in WORKSPACES.values() for f in w.fields if f.type.value in kinds}
        for tv in self.templates.list():  # a business's own templates add their identity-like fields too
            for d in tv.field_specs or []:
                if d.get("type") in kinds:
                    id_kind.setdefault(d["id"], kinds[d["type"]])
        for f in self.repo.other_case_facts(self.case.id, set(id_kind)):
            v = f.value.get("v")
            if isinstance(v, str) and v.strip():
                others.append(cons.OtherEntity(id_kind[f.field_id], v, "found in another case"))
        issues = []
        for pv in previews:
            if not pv.get("blocks"):
                continue
            text = rendering.blocks_plain_text(pv["blocks"])
            issues += cons.check_residue(pv["title"], text, own, others)
            issues += cons.check_words_vs_numerals(pv["title"], text)
        texts = {"what you said": self.case.transcript or ""}
        for att in self.repo.attachments(self.case.id, "supporting"):
            try:
                texts["an attached file"] = forms.read_text_for_extraction(
                    storage.resolve(self.case.tenant_id, "files", att.stored_name), Path(att.stored_name).suffix)
            except FileNotFoundError:
                continue
        people = {s.label: str(ev.values[s.id]) for s in ev.active if s.type.value == "person" and ev.values.get(s.id)}
        issues += cons.check_name_drift(people, texts)
        seen, unique = set(), []
        for i in issues:
            if i.key not in seen:
                seen.add(i.key)
                unique.append(i)
        return unique

    def manifest(self, view: str | None = None) -> UiManifest:
        ev = self.evaluation()
        plans = self.plans(ev)
        status = self.case.status
        previews = self.previews(ev, plans) if status in ("review", "approved", "exported") else []
        latest = self.repo.latest_approval(self.case.id)
        forms = self.repo.attachments(self.case.id, "form")
        exported = [{"id": d.id, "doc_key": d.doc_key, "title": d.title, "fmt": d.fmt}
                    for d in self.repo.documents(self.case.id)]
        m = ManifestInput(
            config=self.config, case=self.case, ev=ev,
            parties={f.party_kind: self.parties.list(f.party_kind) for f in self.config.fields
                     if f.type == FieldType.PARTY and f.party_kind},
            attachments=self.repo.attachments(self.case.id), previews=previews, exported=exported,
            form_fields=list(forms[-1].meta.get("fields", [])) if forms else [],
            form_mapping=dict((self.case.extra or {}).get("form_mapping") or {}),
            pdf_available=rendering.pdf_available(), approved=status in ("approved", "exported"),
            plan_issues=[p.issue for p in plans if p.issue],
            consistency=list((self.case.extra or {}).get("consistency") or []))
        return build_manifest(m, view)
