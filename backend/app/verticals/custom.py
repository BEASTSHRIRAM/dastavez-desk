"""A business's own template, turned into a workspace on the fly.

The same engine runs it: fields come from the template, extraction rules are generated from each
field's label (so demo mode can read "the declarant name is Neha Singh"), and the single document is
the template itself."""
import re

from app.models.fields import FieldSpec, FieldType
from app.models.orm import TemplateVersion
from app.verticals.base import NAME, DocumentSpec, ExtractRule, WorkspaceConfig

# Names the engine itself puts in a template's context. A custom field may not reuse them.
RESERVED = {"template_key", "template_version", "form_name", "form_mapping", "inventory_items", "itinerary_days",
            "missing_items", "checklist", "requirements_source", "requirements_verified", "unmapped_form_fields",
            "landlord_name", "landlord_address", "landlord_phone", "item"}
FIELD_ID = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def valid_field_id(fid: str) -> str | None:
    """Return a reason the id cannot be used, or None."""
    if not FIELD_ID.match(fid):
        return "Use lowercase letters, digits and underscores, starting with a letter."
    if fid in RESERVED or fid.endswith(("_flag", "_words")):
        return "That name is reserved by the system."
    return None


def _label_pattern(label: str) -> str:
    base = re.sub(r"\(.*?\)", "", label).strip()
    words = [re.escape(w) for w in base.split() if w]
    full = r"\s+".join(words)
    if len(words) > 1 and words[-1].lower() in ("name", "date", "number", "address"):
        return rf"(?:{full}|{r'\s+'.join(words[:-1])})"  # "tenant name" is also introduced as just "tenant"
    return full


def autogen_rules(fields: list[FieldSpec]) -> list[ExtractRule]:
    rules: list[ExtractRule] = []
    for f in fields:
        lab = _label_pattern(f.label)
        intro = r"(?:\s+(?:is|are|was|were|of|on|at|will be|:))?"
        if f.type == FieldType.CURRENCY:
            rules.append(ExtractRule(field_id=f.id, kind="amount", keywords=[rf"\b{lab}\b{intro}"], window=30))
        elif f.type == FieldType.DATE:
            rules.append(ExtractRule(field_id=f.id, kind="date", keywords=[rf"\b{lab}\b{intro}"], window=40))
        elif f.type == FieldType.PERSON:
            rules.append(ExtractRule(field_id=f.id, kind="name", patterns=[rf"\b{lab}\b(?:\s+is|\s+named|\s+was|:)?\s+(?P<v>{NAME})"]))
        elif f.type == FieldType.PHONE:
            rules.append(ExtractRule(field_id=f.id, kind="phone"))
        elif f.type == FieldType.SELECT and f.options:
            rules.append(ExtractRule(field_id=f.id, kind="select", choices={o: [rf"(?<!\w){re.escape(o)}(?!\w)"] for o in f.options}))
        elif f.type in (FieldType.TEXT, FieldType.LONGTEXT, FieldType.ADDRESS, FieldType.NUMBER):
            rules.append(ExtractRule(field_id=f.id, kind="text", patterns=[rf"\b{lab}\b\s*(?:is|are|was|were|:)\s*(?P<v>[^.\n]+)"]))
    return rules


def config_for(tv: TemplateVersion) -> WorkspaceConfig:
    fields = [FieldSpec(**d) for d in (tv.field_specs or [])]
    return WorkspaceConfig(
        id="custom", name=tv.title, tagline="Your own template",
        description="A template your business added. Its wording is used exactly as written.",
        material="archival", example_prompt="", classify_keywords=[],
        fields=fields, rules=autogen_rules(fields),
        documents=[DocumentSpec(key="document", title=tv.title, template_key=tv.template_key, primary=True)],
        verify_fields=list(tv.verify_fields or []),
        disclaimers=["This draft uses your business's own template. Check the wording and every value before relying on it.",
                     "Nothing is signed, stamped, notarised, sent or filed by this system."],
    )
