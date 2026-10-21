"""The generative-UI contract.

The agent returns a UiManifest: JSON that selects components from this closed set. There is no
field for HTML, JavaScript or arbitrary props, so a model (or an attacker steering one) cannot
make the frontend execute anything. `extra="forbid"` rejects any unknown key. The frontend
validates the same shape again before rendering."""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Provenance(_Strict):
    origin: str | None = None  # transcript | attachment | party | template default | operator
    quote: str | None = None
    status: Literal["confirmed", "source", "suggested", "default", "none"] = "none"
    confidence: float | None = None


class Validation(_Strict):
    min: float | None = None
    max: float | None = None
    pattern: str | None = None
    options: list[str] = Field(default_factory=list)


class PartyOption(_Strict):
    id: str
    label: str
    detail: str | None = None


FieldKind = Literal["text_input", "long_text", "person", "address", "phone", "currency", "number", "date",
                    "select", "multi_select", "yes_no", "party_select"]


class FieldComponent(_Strict):
    component: FieldKind
    field_id: str
    label: str
    required: bool = False
    help: str | None = None
    value: Any = None  # a proposed value the operator can accept or edit
    validation: Validation = Field(default_factory=Validation)
    provenance: Provenance = Field(default_factory=Provenance)
    high_impact: bool = False
    needs_confirmation: bool = False
    optional: bool = False
    party_options: list[PartyOption] = Field(default_factory=list)


class MissingInfoWarning(_Strict):
    component: Literal["missing_info"] = "missing_info"
    message: str
    field_ids: list[str]


class ConflictOption(_Strict):
    value: Any
    origin: str | None = None
    quote: str | None = None


class ConflictChoice(_Strict):
    component: Literal["conflict_choice"] = "conflict_choice"
    field_id: str
    label: str
    options: list[ConflictOption]


class SourceEvidence(_Strict):
    component: Literal["source_evidence"] = "source_evidence"
    items: list[dict[str, Any]]  # {field_id, label, value, quote, status, confidence}


class FileAttachment(_Strict):
    component: Literal["file_attachment"] = "file_attachment"
    label: str
    kind: Literal["form", "supporting"]
    accept: list[str]
    help: str | None = None
    uploaded: list[dict[str, Any]] = Field(default_factory=list)
    mapping: dict[str, str] = Field(default_factory=dict)  # form label -> field id
    mappable_fields: list[dict[str, str]] = Field(default_factory=list)  # {id, label}


class DocumentChecklist(_Strict):
    component: Literal["document_checklist"] = "document_checklist"
    title: str
    items: list[str]
    source: str | None = None
    last_verified: str | None = None


class ChangeComparison(_Strict):
    component: Literal["change_comparison"] = "change_comparison"
    doc_key: str
    title: str
    sections: list[dict[str, Any]]


class DocumentPreviewC(_Strict):
    component: Literal["document_preview"] = "document_preview"
    doc_key: str
    title: str
    blocks: list[dict[str, Any]]
    template: dict[str, Any] | None = None
    unavailable: str | None = None


class IssueItem(_Strict):
    key: str | None = None
    field_id: str | None = None
    code: str
    severity: Literal["error", "warning"]
    message: str


class ApprovalPanel(_Strict):
    component: Literal["approval_panel"] = "approval_panel"
    issues: list[IssueItem]
    confirm_fields: list[dict[str, Any]]  # high-impact values that must be confirmed: {field_id, label, value}
    can_approve: bool
    approved: bool = False
    acknowledgements: list[dict[str, Any]] = Field(default_factory=list)  # possible leftovers a person must clear
    disclaimers: list[str] = Field(default_factory=list)


class ClientMessage(_Strict):
    """A ready-to-send request list for the client. The operator copies it; the app never sends anything."""
    component: Literal["client_message"] = "client_message"
    title: str
    text: str


class ExportDocument(_Strict):
    doc_key: str
    title: str
    formats: list[str]


class ExportOptions(_Strict):
    component: Literal["export_options"] = "export_options"
    documents: list[ExportDocument]
    pdf_available: bool
    exported: list[dict[str, Any]] = Field(default_factory=list)


Component = Annotated[
    FieldComponent | MissingInfoWarning | ConflictChoice | SourceEvidence | FileAttachment | DocumentChecklist
    | ChangeComparison | DocumentPreviewC | ApprovalPanel | ExportOptions | ClientMessage,
    Field(discriminator="component"),
]


class Section(_Strict):
    title: str
    description: str | None = None
    components: list[Component]


class UiManifest(_Strict):
    version: Literal[1] = 1
    case_id: str
    stage: Literal["intake", "questions", "review", "export", "complete"]
    title: str
    subtitle: str | None = None
    sections: list[Section]
