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
from app.services import documents, rendering
from app.services.case_state import Evaluation, evaluate
from app.services.manifest import ManifestInput, build_manifest
from app.verticals import get_workspace
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
        return cls(session, repo, PartyRepo(session, tenant_id), TemplateRepo(session, tenant_id), case,
                   get_workspace(case.workspace))

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
            plan_issues=[p.issue for p in plans if p.issue])
        return build_manifest(m, view)
