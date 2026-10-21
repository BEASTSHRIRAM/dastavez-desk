"""Relational model. Every business-owned row carries tenant_id; repositories
always filter on it so knowing a record ID never grants access."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    ai_consent: Mapped[bool] = mapped_column(default=False)  # consent before sending records to 3rd-party AI
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="operator")  # owner | operator | viewer
    password_hash: Mapped[str] = mapped_column(String(300))


class TenantOwned:
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)


class Party(TenantOwned, Base):
    """A saved client/landlord/tenant record. Reusable only inside its tenant."""
    __tablename__ = "parties"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(30))  # landlord | tenant | applicant | supplier | client
    full_name: Mapped[str] = mapped_column(String(200), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    verified: Mapped[bool] = mapped_column(default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TemplateVersion(Base):
    """Versioned template. tenant_id NULL means a built-in demonstration template."""
    __tablename__ = "template_versions"
    __table_args__ = (UniqueConstraint("template_key", "version", "tenant_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), index=True)
    template_key: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(20))
    workspace: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(200))
    file_name: Mapped[str] = mapped_column(String(200))
    is_demo: Mapped[bool] = mapped_column(default=True)
    approved: Mapped[bool] = mapped_column(default=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(100))
    verify_fields: Mapped[list] = mapped_column(JSON, default=list)
    field_specs: Mapped[list] = mapped_column(JSON, default=list)  # custom templates: the fields their placeholders need
    source_note: Mapped[str | None] = mapped_column(Text)
    last_verified: Mapped[str | None] = mapped_column(String(20))


class Case(TenantOwned, Base):
    __tablename__ = "cases"
    __table_args__ = (Index("ix_cases_tenant_status", "tenant_id", "status"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    workspace: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200), default="Untitled case")
    status: Mapped[str] = mapped_column(String(30), default="intake")  # intake|awaiting_input|review|approved|exported|cancelled
    thread_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # LangGraph checkpoint thread
    transcript: Mapped[str | None] = mapped_column(Text)  # original spoken/typed input, preserved verbatim
    template_version_id: Mapped[str | None] = mapped_column(ForeignKey("template_versions.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    extra: Mapped[dict] = mapped_column(JSON, default=dict)  # workspace payloads, e.g. form mapping
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    facts: Mapped[list["Fact"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Fact(TenantOwned, Base):
    """One value for one field. 'source' = stated by client/operator or read from a record,
    'suggested' = AI-derived, 'confirmed' = a human accepted it. Kept as separate rows so an
    AI interpretation can never silently overwrite verified data."""
    __tablename__ = "facts"
    __table_args__ = (Index("ix_facts_case_field", "case_id", "field_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    field_id: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict] = mapped_column(JSON)  # {"v": <typed value>}
    status: Mapped[str] = mapped_column(String(20))  # source | suggested | confirmed
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)  # {origin, span, party_id,...}
    confidence: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    case: Mapped[Case] = relationship(back_populates="facts")


class Attachment(TenantOwned, Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(300))
    stored_name: Mapped[str] = mapped_column(String(100))  # server-generated, never user-controlled
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30), default="supporting")  # supporting | form | audio
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # e.g. inspected form fields
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GeneratedDocument(TenantOwned, Base):
    __tablename__ = "generated_documents"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    doc_key: Mapped[str] = mapped_column(String(80))  # e.g. rental_agreement, handover_checklist
    title: Mapped[str] = mapped_column(String(200))
    fmt: Mapped[str] = mapped_column(String(10))  # docx | pdf | xlsx | csv
    stored_name: Mapped[str] = mapped_column(String(100))
    is_sample: Mapped[bool] = mapped_column(default=True)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(TenantOwned, Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    values_hash: Mapped[str] = mapped_column(String(64))  # approval binds to the exact reviewed values
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(TenantOwned, Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkflowEvent(TenantOwned, Base):
    """Typed progress events streamed over SSE (no chain-of-thought)."""
    __tablename__ = "workflow_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(300))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
