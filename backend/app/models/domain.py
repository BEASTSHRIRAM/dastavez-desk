"""Domain value objects shared by services and the agent graph."""
from typing import Any

from pydantic import BaseModel, Field


class ExtractedFact(BaseModel):
    """A candidate value proposed from untrusted text. Never persisted without validation."""
    field_id: str
    value: Any
    quote: str | None = None  # exact words in the source that justify the value
    confidence: float = 0.8
    ambiguous: bool = False  # e.g. day/month order or year had to be assumed
    origin: str = "transcript"  # transcript | attachment:<id> | party:<id>


class ExtractionResult(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # concise, user-visible
