"""Field vocabulary shared by workspace configs, extraction, validation and the UI manifest."""
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FieldType(StrEnum):
    TEXT = "text"
    LONGTEXT = "longtext"
    PERSON = "person"
    ADDRESS = "address"
    PHONE = "phone"
    CURRENCY = "currency"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    MULTISELECT = "multiselect"
    YESNO = "yesno"
    PARTY = "party"  # reference to a saved party record, resolved inside the tenant only


class FieldSpec(BaseModel):
    id: str
    label: str
    type: FieldType = FieldType.TEXT
    required: bool = False
    help: str | None = None
    options: list[str] = Field(default_factory=list)
    party_kind: str | None = None
    min: float | None = None
    max: float | None = None
    pattern: str | None = None
    # The question only applies when this predicate holds: {"field": id, "equals": value}
    when: dict[str, Any] | None = None
    # Mistakes here are costly (names, money, IDs, legal dates): never auto-confirmed.
    high_impact: bool = False
    # A default is only allowed when the approved template supplies it.
    default: Any = None
    default_source: str | None = None
    date_bias: str = "future"  # how to resolve a date written without a year
    group: str = "details"


class Issue(BaseModel):
    field_id: str | None = None
    code: str  # missing | invalid | conflict | unconfirmed | unverified | template
    severity: str = "error"  # error blocks approval; warning is surfaced
    message: str
    key: str | None = None  # stable id so a person can acknowledge a finding
