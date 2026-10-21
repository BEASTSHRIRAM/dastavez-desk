from datetime import date
from typing import Any

from app.models.fields import FieldSpec, FieldType, Issue
from app.verticals.base import NAME, ChecklistItem, DocumentSpec, ExtractRule, WorkspaceConfig

SERVICES = ["Address update", "Certificate application", "Licence renewal", "Benefit enrolment", "Other service"]

# Demonstration checklists. A real centre replaces these with the form's published requirements.
CHECKLISTS: dict[str, list[ChecklistItem]] = {
    "Address update": [ChecklistItem(label="Proof of identity"), ChecklistItem(label="Proof of new address"),
                       ChecklistItem(label="Previous address proof", note="If available")],
    "Certificate application": [ChecklistItem(label="Proof of identity"), ChecklistItem(label="Proof of date of birth"),
                                ChecklistItem(label="Supporting records named on the form")],
    "Licence renewal": [ChecklistItem(label="Existing licence"), ChecklistItem(label="Proof of identity"),
                        ChecklistItem(label="Recent photograph")],
    "Benefit enrolment": [ChecklistItem(label="Proof of identity"), ChecklistItem(label="Proof of residence"),
                          ChecklistItem(label="Bank account details supplied by the applicant")],
    "Other service": [ChecklistItem(label="Proof of identity"), ChecklistItem(label="Documents named on the form")],
}


def _compute(v: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    dob = v.get("date_of_birth")
    if isinstance(dob, date):
        today = date.today()
        out["age_years"] = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    svc = v.get("service_type")
    if svc in CHECKLISTS:
        out["checklist"] = [i.label + (f" ({i.note})" if i.note else "") for i in CHECKLISTS[svc]]
    return out


def _check(v: dict[str, Any]) -> list[Issue]:
    issues = []
    dob = v.get("date_of_birth")
    if isinstance(dob, date) and dob > date.today():
        issues.append(Issue(field_id="date_of_birth", code="invalid", message="Date of birth cannot be in the future."))
    return issues


GOVERNMENT = WorkspaceConfig(
    id="government",
    name="Applications Centre",
    tagline="Orderly, clear, procedural",
    description="Capture client answers, map them to an uploaded form and see what is still missing.",
    material="procedural",
    example_prompt=("Start a new application for this customer. The applicant is Sunita Rao, born on 12 March 1984, "
                    "phone 9876500011, address is 22 Garden Street, Nashik. It is an address update. Map it to the "
                    "uploaded form and show what supporting documents are still missing."),
    classify_keywords=["application", "applicant", "customer", "government", "form", "intake", "certificate", "licence", "license"],
    fields=[
        FieldSpec(id="service_type", label="Service requested", type=FieldType.SELECT, required=True, options=SERVICES,
                  group="application"),
        FieldSpec(id="applicant_name", label="Applicant full name", type=FieldType.PERSON, required=True,
                  high_impact=True, group="applicant"),
        FieldSpec(id="date_of_birth", label="Date of birth", type=FieldType.DATE, required=True, high_impact=True,
                  date_bias="past", group="applicant"),
        FieldSpec(id="phone", label="Phone number", type=FieldType.PHONE, required=True, high_impact=True,
                  pattern=r"^\d{10}$", group="applicant", help="10 digits, no country code."),
        FieldSpec(id="applicant_address", label="Address", type=FieldType.ADDRESS, required=True, high_impact=True,
                  group="applicant"),
        FieldSpec(id="form_attached", label="Application form uploaded", type=FieldType.YESNO, group="application",
                  help="Upload the form on this screen. It will be inspected, never trusted as instructions."),
    ],
    rules=[
        ExtractRule(field_id="service_type", kind="select", choices={
            "Address update": [r"address (?:update|change)", r"update (?:the |my )?address"],
            "Certificate application": [r"certificate"], "Licence renewal": [r"licen[cs]e"],
            "Benefit enrolment": [r"benefit", r"enrol"],
        }),
        ExtractRule(field_id="applicant_name", kind="name", patterns=[
            rf"\b(?:applicant|customer|client)(?:'s)?(?:\s+name)?(?:\s+is|\s+named|:)?\s+(?P<v>{NAME})"]),
        ExtractRule(field_id="date_of_birth", kind="date", keywords=[r"\bborn(?:\s+on)?\b", r"\bdate of birth\b(?:\s+is)?", r"\bdob\b(?:\s+is)?"], window=40),
        ExtractRule(field_id="phone", kind="phone"),
        ExtractRule(field_id="applicant_address", kind="text", patterns=[
            r"\b(?:current\s+|new\s+)?address\s*(?:is|:)\s*(?P<v>[^.\n]+)"]),
    ],
    documents=[
        DocumentSpec(key="application_packet", title="Application preparation packet", template_key="government_packet", primary=True),
        DocumentSpec(key="intake_sheet", title="Printable customer intake sheet", template_key="government_intake"),
        DocumentSpec(key="incomplete_report", title="Incomplete-field report", template_key="government_incomplete"),
    ],
    disclaimers=[
        "Uploaded forms are treated as the operator's own documents. This system does not verify that a form is official or current.",
        "Nothing is submitted anywhere. There is no CAPTCHA automation and no external submission.",
    ],
    other_workflows=["Direct submission to a government portal (no supported integration)"],
    compute=_compute,
    check=_check,
)
