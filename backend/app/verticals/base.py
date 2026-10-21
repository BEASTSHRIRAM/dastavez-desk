"""Workspace configuration schema. A workspace is data: fields, extraction rules,
documents and deterministic checks. The engine in services/ and agents/ never branches on a
workspace id; it reads these structures."""
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.models.fields import FieldSpec, Issue

# A name is 1-4 words, case-insensitive, and must not start with filler words that appear after
# phrases such as "the landlord is already saved".
NAME = (r"(?!(?:is|are|was|named|has|have|already|saved|same|existing|selected|my|our|the|a|an|yesterday|today|tomorrow|not|new|unknown)\b)"
        r"[A-Za-z][A-Za-z.'-]*(?:\s+(?!(?:and|has|is|was|lives|wants|needs|with|of|from|at|the|date|rent|"
        r"deposit|paid|on|for|to|who|whose|will|should|please|use|ask|change|create|prepare|begins|starts|"
        r"purchase|bought|by)\b)[A-Za-z][A-Za-z.'-]*){0,3}")


class ExtractRule(BaseModel):
    """How the deterministic (demo-mode) extractor finds one field in free text."""
    field_id: str
    kind: str  # amount | date | text | name | yesno | select | duration_months | phone
    keywords: list[str] = Field(default_factory=list)  # regex fragments; amount/date: look just after these
    patterns: list[str] = Field(default_factory=list)  # regexes with a named group (?P<v>...)
    yes: list[str] = Field(default_factory=list)
    no: list[str] = Field(default_factory=list)
    choices: dict[str, list[str]] = Field(default_factory=dict)  # select: option -> regex keywords
    template: str | None = None  # text: format string using {v}
    window: int = 40


class DocumentSpec(BaseModel):
    key: str
    title: str
    template_key: str | None = None  # None for generated spreadsheets
    template_by: dict[str, Any] | None = None  # {"field": id, "map": {value: template_key}}
    formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    kind: str = "document"  # document | ledger
    primary: bool = False


class ChecklistItem(BaseModel):
    label: str
    note: str | None = None
    when: dict[str, Any] | None = None


class WorkspaceConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    tagline: str
    description: str
    material: str  # visual identity hint for the frontend
    example_prompt: str
    classify_keywords: list[str]
    fields: list[FieldSpec]
    rules: list[ExtractRule]
    documents: list[DocumentSpec]
    disclaimers: list[str]
    verify_fields: list[str] = Field(default_factory=list)
    other_workflows: list[str] = Field(default_factory=list)  # listed, but not implemented in this MVP
    party_fields: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Deterministic rules run after validation, e.g. totals and flags. Pure functions of the values.
    compute: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    check: Callable[[dict[str, Any]], list[Issue]] | None = None

    def field(self, field_id: str) -> FieldSpec:
        for f in self.fields:
            if f.id == field_id:
                return f
        raise KeyError(field_id)

    def field_ids(self) -> list[str]:
        return [f.id for f in self.fields]
