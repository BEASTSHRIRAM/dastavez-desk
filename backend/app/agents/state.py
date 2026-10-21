"""Typed workflow state. It carries identifiers and small summaries; business data lives in the
relational tables (see models/orm.py). Graph state and business data have separate owners."""
from typing import Any, TypedDict


class WorkflowState(TypedDict, total=False):
    tenant_id: str
    case_id: str
    user_id: str
    workspace: str
    transcript: str
    today: str  # ISO date the run was started, so resumed runs resolve relative dates identically
    allow_hosted: bool
    suggested_workspace: str | None
    extracted_fields: list[str]
    notes: list[str]
    template_ids: dict[str, str]
    missing: list[str]
    blocking_fields: list[str]
    pending: str  # "missing" | "review"
    preview_docs: list[str]
    approval_status: str  # "pending" | "approved"
    approval_id: str | None
    export_refs: list[str]
    export_done: bool
    reopen: bool
    cancelled: bool
    last_answer_errors: dict[str, str]
    interrupt_info: dict[str, Any]
