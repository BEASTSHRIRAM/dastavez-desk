from datetime import date

from app.models.fields import FieldSpec, FieldType, Issue
from app.verticals.base import NAME, DocumentSpec, ExtractRule, WorkspaceConfig

JURISDICTIONS = ["Maharashtra", "Karnataka", "Delhi", "Tamil Nadu", "Telangana", "Gujarat", "Other (operator to specify)"]


def _check(v: dict) -> list[Issue]:
    issues = []
    d = v.get("declaration_date")
    if isinstance(d, date) and d > date.today():
        issues.append(Issue(field_id="declaration_date", code="invalid", severity="warning",
                            message="Declaration date is in the future. Confirm it is intentional."))
    return issues


LEGAL = WorkspaceConfig(
    id="legal",
    name="Legal Documents",
    tagline="Structured, precise, archival",
    description="Turn client facts into drafts from approved templates. Approved wording is never rewritten.",
    material="archival",
    example_prompt=("Prepare a declaration using our approved template. The applicant is Anita Verma, the new address "
                    "is 14 Lake View Road, Pune. Change the address and date, but don't change the approved wording. "
                    "Ask me if anything required is missing."),
    classify_keywords=["affidavit", "declaration", "deponent", "applicant", "approved template", "notar", "attest"],
    fields=[
        FieldSpec(id="declaration_purpose", label="Declaration type", type=FieldType.SELECT, required=True,
                  options=["Address declaration", "Name declaration", "General declaration"], group="template",
                  help="Selects the approved demonstration template."),
        FieldSpec(id="applicant_name", label="Applicant full name", type=FieldType.PERSON, required=True,
                  high_impact=True, group="parties"),
        FieldSpec(id="applicant_address", label="Applicant address (as to be declared)", type=FieldType.ADDRESS,
                  required=True, high_impact=True, group="parties",
                  when={"field": "declaration_purpose", "in": ["Address declaration", "General declaration"]}),
        FieldSpec(id="previous_address", label="Previous address", type=FieldType.ADDRESS, group="parties",
                  when={"field": "declaration_purpose", "equals": "Address declaration"}),
        FieldSpec(id="previous_name", label="Previous name", type=FieldType.PERSON, required=True, high_impact=True,
                  group="parties", when={"field": "declaration_purpose", "equals": "Name declaration"}),
        FieldSpec(id="declaration_statement", label="Statement of facts", type=FieldType.LONGTEXT, required=True,
                  group="facts", help="Client-provided facts only. The operator does not add legal conclusions.",
                  when={"field": "declaration_purpose", "equals": "General declaration"}),
        FieldSpec(id="declaration_date", label="Declaration date", type=FieldType.DATE, required=True,
                  high_impact=True, group="template", date_bias="future"),
        FieldSpec(id="jurisdiction", label="Jurisdiction", type=FieldType.SELECT, required=True,
                  options=JURISDICTIONS, group="template", help="Configurable per business."),
        FieldSpec(id="identity_verified", label="I have verified the applicant's identity document",
                  type=FieldType.YESNO, required=True, group="verification"),
        FieldSpec(id="facts_checked_with_client", label="I have read these facts back to the client",
                  type=FieldType.YESNO, required=True, group="verification"),
    ],
    rules=[
        ExtractRule(field_id="declaration_purpose", kind="select", choices={
            "Name declaration": [r"name (?:change|declaration)", r"change (?:of|in) name"],
            "Address declaration": [r"address (?:declaration|change)", r"change (?:of|the|in) (?:the )?address", r"new address"],
            "General declaration": [r"general declaration"],
        }),
        ExtractRule(field_id="applicant_name", kind="name", patterns=[
            rf"\b(?:applicant|declarant|deponent|client|customer)(?:'s)?(?:\s+name)?(?:\s+is|\s+named|:)?\s+(?P<v>{NAME})"]),
        ExtractRule(field_id="previous_address", kind="text", patterns=[
            r"\b(?:previous|old|earlier)\s+address\s*(?:is|was|:)\s*(?P<v>[^.\n]+)"]),
        ExtractRule(field_id="applicant_address", kind="text", patterns=[
            r"(?<!previous )(?<!old )(?<!earlier )\b(?:(?:new|current)\s+)?address\s*(?:is|:)\s*(?P<v>[^.\n]+)"]),
        ExtractRule(field_id="previous_name", kind="name", patterns=[
            rf"\b(?:previous|old|earlier)\s+name\s*(?:is|was|:)\s*(?P<v>{NAME})"]),
        ExtractRule(field_id="declaration_date", kind="date", keywords=[r"\bdated?\b", r"\bon\b"], window=40),
        ExtractRule(field_id="jurisdiction", kind="select", choices={j: [rf"\b{j.split(' (')[0]}\b"] for j in JURISDICTIONS[:-1]}),
        ExtractRule(field_id="identity_verified", kind="yesno",
                    yes=[r"(?:id|identity|aadhaar|document)s?\s+(?:has been |is |was )?verified", r"verified (?:the )?(?:id|identity)"]),
    ],
    documents=[
        DocumentSpec(key="declaration", title="Declaration draft", primary=True,
                     template_by={"field": "declaration_purpose", "map": {
                         "Address declaration": "declaration_address", "Name declaration": "declaration_name",
                         "General declaration": "declaration_general"}}),
        DocumentSpec(key="verification_checklist", title="Operator verification checklist",
                     template_key="legal_verification_checklist"),
    ],
    disclaimers=[
        "Demonstration templates only. This is not legal advice and the draft is not a legally valid document.",
        "No signatures, witnesses, attestations, stamps or notarisation are added by this system.",
    ],
    verify_fields=["identity_verified", "facts_checked_with_client"],
    other_workflows=["Client information sheets", "Supporting-document checklists"],
    check=_check,
)
