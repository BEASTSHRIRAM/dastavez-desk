"""Tenant-scoped persistence for cases and everything that hangs off them.
Each method filters on tenant_id: a valid ID from another tenant is indistinguishable from a missing one."""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import (Approval, Attachment, AuditEvent, Case, Fact, GeneratedDocument, WorkflowEvent, new_id)


class NotFound(LookupError):
    pass


class TenantRepo:
    def __init__(self, session: Session, tenant_id: str):
        self.s = session
        self.tenant_id = tenant_id

    # ----- cases
    def create_case(self, *, user_id: str, workspace: str, title: str, transcript: str | None = None,
                    idempotency_key: str | None = None) -> tuple[Case, bool]:
        """Returns (case, created). A repeated idempotency key returns the original case."""
        if idempotency_key:
            existing = self.s.scalar(select(Case).where(Case.tenant_id == self.tenant_id,
                                                        Case.idempotency_key == idempotency_key))
            if existing:
                return existing, False
        case = Case(tenant_id=self.tenant_id, created_by=user_id, workspace=workspace, title=title,
                    transcript=transcript, idempotency_key=idempotency_key, thread_id=new_id(), extra={})
        self.s.add(case)
        self.s.commit()
        return case, True

    def get_case(self, case_id: str) -> Case:
        case = self.s.scalar(select(Case).where(Case.id == case_id, Case.tenant_id == self.tenant_id))
        if not case:
            raise NotFound("Case not found")
        return case

    def list_cases(self, limit: int = 100) -> list[Case]:
        return list(self.s.scalars(select(Case).where(Case.tenant_id == self.tenant_id)
                                   .order_by(Case.created_at.desc()).limit(limit)))

    def update_case(self, case: Case, **fields: Any) -> Case:
        for k, v in fields.items():
            setattr(case, k, v)
        self.s.commit()
        return case

    def set_extra(self, case: Case, **fields: Any) -> None:
        case.extra = {**(case.extra or {}), **fields}  # reassign so the JSON change is detected
        self.s.commit()

    # ----- facts
    def add_fact(self, case_id: str, field_id: str, value: Any, status: str, provenance: dict | None = None,
                 confidence: float | None = None) -> Fact:
        self.get_case(case_id)
        fact = Fact(tenant_id=self.tenant_id, case_id=case_id, field_id=field_id, value={"v": value},
                    status=status, provenance=provenance or {}, confidence=confidence)
        self.s.add(fact)
        self.s.commit()
        return fact

    def facts(self, case_id: str) -> list[Fact]:
        return list(self.s.scalars(select(Fact).where(Fact.tenant_id == self.tenant_id, Fact.case_id == case_id)
                                   .order_by(Fact.created_at, Fact.id)))

    def other_case_facts(self, case_id: str, field_ids: set[str], limit: int = 400) -> list[Fact]:
        """Identity-like values from this business's *other* cases, for the residue check."""
        return list(self.s.scalars(select(Fact).where(
            Fact.tenant_id == self.tenant_id, Fact.case_id != case_id, Fact.field_id.in_(field_ids))
            .order_by(Fact.created_at.desc()).limit(limit)))

    # ----- attachments
    def add_attachment(self, case_id: str, **kw: Any) -> Attachment:
        self.get_case(case_id)
        att = Attachment(tenant_id=self.tenant_id, case_id=case_id, **kw)
        self.s.add(att)
        self.s.commit()
        return att

    def attachments(self, case_id: str, kind: str | None = None) -> list[Attachment]:
        q = select(Attachment).where(Attachment.tenant_id == self.tenant_id, Attachment.case_id == case_id,
                                     Attachment.deleted_at.is_(None))
        if kind:
            q = q.where(Attachment.kind == kind)
        return list(self.s.scalars(q.order_by(Attachment.created_at)))

    def get_attachment(self, attachment_id: str) -> Attachment:
        att = self.s.scalar(select(Attachment).where(Attachment.id == attachment_id,
                                                     Attachment.tenant_id == self.tenant_id,
                                                     Attachment.deleted_at.is_(None)))
        if not att:
            raise NotFound("Attachment not found")
        return att

    def soft_delete_attachment(self, att: Attachment) -> None:
        att.deleted_at = datetime.now(timezone.utc)
        self.s.commit()

    # ----- generated documents, approvals
    def add_document(self, case_id: str, **kw: Any) -> GeneratedDocument:
        doc = GeneratedDocument(tenant_id=self.tenant_id, case_id=case_id, **kw)
        self.s.add(doc)
        self.s.commit()
        return doc

    def documents(self, case_id: str) -> list[GeneratedDocument]:
        return list(self.s.scalars(select(GeneratedDocument).where(
            GeneratedDocument.tenant_id == self.tenant_id, GeneratedDocument.case_id == case_id)
            .order_by(GeneratedDocument.created_at)))

    def get_document(self, document_id: str) -> GeneratedDocument:
        doc = self.s.scalar(select(GeneratedDocument).where(GeneratedDocument.id == document_id,
                                                            GeneratedDocument.tenant_id == self.tenant_id))
        if not doc:
            raise NotFound("Document not found")
        return doc

    def add_approval(self, case_id: str, user_id: str, values_hash: str, note: str | None) -> Approval:
        ap = Approval(tenant_id=self.tenant_id, case_id=case_id, approved_by=user_id, values_hash=values_hash, note=note)
        self.s.add(ap)
        self.s.commit()
        return ap

    def latest_approval(self, case_id: str) -> Approval | None:
        return self.s.scalar(select(Approval).where(Approval.tenant_id == self.tenant_id, Approval.case_id == case_id)
                             .order_by(Approval.created_at.desc()))

    # ----- audit and events
    def audit(self, action: str, case_id: str | None = None, actor_id: str | None = None, **detail: Any) -> AuditEvent:
        ev = AuditEvent(tenant_id=self.tenant_id, case_id=case_id, actor_id=actor_id, action=action, detail=detail)
        self.s.add(ev)
        self.s.commit()
        return ev

    def audit_trail(self, case_id: str) -> list[AuditEvent]:
        return list(self.s.scalars(select(AuditEvent).where(AuditEvent.tenant_id == self.tenant_id,
                                                            AuditEvent.case_id == case_id)
                                   .order_by(AuditEvent.created_at, AuditEvent.id)))

    def emit(self, case_id: str, type_: str, message: str, **data: Any) -> WorkflowEvent:
        ev = WorkflowEvent(tenant_id=self.tenant_id, case_id=case_id, type=type_, message=message, data=data)
        self.s.add(ev)
        self.s.commit()
        return ev

    def events_after(self, case_id: str, after_id: int = 0) -> list[WorkflowEvent]:
        return list(self.s.scalars(select(WorkflowEvent).where(
            WorkflowEvent.tenant_id == self.tenant_id, WorkflowEvent.case_id == case_id, WorkflowEvent.id > after_id)
            .order_by(WorkflowEvent.id)))
