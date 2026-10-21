import calendar
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from app.models.fields import FieldSpec, FieldType, Issue
from app.verticals.base import NAME, DocumentSpec, ExtractRule, WorkspaceConfig


def add_months(d: date, months: int) -> date:
    idx = d.month - 1 + months
    year, month = d.year + idx // 12, idx % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _compute(v: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rent, dep = v.get("monthly_rent"), v.get("security_deposit")
    if isinstance(rent, Decimal) and isinstance(dep, Decimal):
        out["first_payment_total"] = rent + dep
        if rent > 0:
            out["deposit_in_months"] = (dep / rent).quantize(Decimal("0.1"))
    start, months = v.get("start_date"), v.get("lease_months")
    if isinstance(start, date) and isinstance(months, (int, Decimal)) and int(months) > 0:
        out["end_date"] = add_months(start, int(months)) - timedelta(days=1)
    return out


def _check(v: dict[str, Any]) -> list[Issue]:
    issues = []
    ratio = v.get("deposit_in_months")
    if isinstance(ratio, Decimal) and ratio > 6:
        issues.append(Issue(field_id="security_deposit", code="invalid", severity="warning",
                            message=f"Deposit is {ratio} months of rent. Confirm the amount with the parties."))
    return issues


PROPERTY = WorkspaceConfig(
    id="property",
    name="Property & Rental",
    tagline="Architectural, spatial, measured",
    description="Rental-agreement drafts and handover checklists from one set of verified case facts.",
    material="architectural",
    example_prompt=("Create a rental agreement draft for a new tenant. The landlord is already saved. The tenant is "
                    "Rahul Sharma, rent is eighteen thousand per month, the deposit is fifty thousand, and the "
                    "tenancy begins on the first of November. Use my usual reviewed template. Ask me anything "
                    "important that's missing."),
    classify_keywords=["rental", "rent", "tenant", "landlord", "tenancy", "lease", "deposit", "handover", "property"],
    fields=[
        FieldSpec(id="landlord_party", label="Landlord", type=FieldType.PARTY, party_kind="landlord", required=True,
                  high_impact=True, group="parties",
                  help="Saved landlord details are reused only after you confirm the right person."),
        FieldSpec(id="tenant_name", label="Tenant full name", type=FieldType.PERSON, required=True, high_impact=True,
                  group="parties"),
        FieldSpec(id="tenant_address", label="Tenant permanent address", type=FieldType.ADDRESS, group="parties"),
        FieldSpec(id="property_address", label="Property address", type=FieldType.ADDRESS, required=True,
                  high_impact=True, group="property"),
        FieldSpec(id="monthly_rent", label="Monthly rent (INR)", type=FieldType.CURRENCY, required=True,
                  high_impact=True, min=0, group="money"),
        FieldSpec(id="security_deposit", label="Security deposit (INR)", type=FieldType.CURRENCY, required=True,
                  high_impact=True, min=0, group="money", help="Zero is a valid answer. Blank is not."),
        FieldSpec(id="start_date", label="Tenancy start date", type=FieldType.DATE, required=True, high_impact=True,
                  group="terms"),
        FieldSpec(id="lease_months", label="Lease term (months)", type=FieldType.NUMBER, required=True, min=1, max=120,
                  high_impact=True, group="terms"),
        FieldSpec(id="rent_due_day", label="Rent due day of month", type=FieldType.NUMBER, min=1, max=28, default=5,
                  default_source="Template rental_agreement v1.0 default", group="terms"),
        FieldSpec(id="notice_period_days", label="Notice period (days)", type=FieldType.NUMBER, min=0, max=180,
                  default=30, default_source="Template rental_agreement v1.0 default", group="terms"),
        FieldSpec(id="furnished", label="Is the property furnished?", type=FieldType.YESNO, required=True, group="property"),
        FieldSpec(id="inventory_summary", label="Furnishings and fittings included", type=FieldType.LONGTEXT,
                  required=True, group="property", when={"field": "furnished", "equals": True},
                  help="One item per line. Used for the handover checklist."),
    ],
    rules=[
        # Party fields hold a hint (a name, or True for "use the saved one"); the resolver turns it into a record.
        ExtractRule(field_id="landlord_party", kind="name", patterns=[
            rf"\blandlord(?:\s+is|\s+named|:)?\s+(?P<v>{NAME})"]),
        ExtractRule(field_id="landlord_party", kind="yesno", yes=[
            r"landlord\s+(?:is\s+)?already\s+saved", r"\b(?:saved|existing|selected)\s+landlord\b",
            r"\breuse\b.{0,40}\blandlord\b"]),
        ExtractRule(field_id="tenant_name", kind="name", patterns=[
            rf"\btenant(?:\s+is|\s+named|\s+name\s+is|:)?\s+(?P<v>{NAME})"]),
        ExtractRule(field_id="monthly_rent", kind="amount", keywords=[r"\brent\b(?:\s+(?:is|of|will be|at))?"], window=30),
        ExtractRule(field_id="security_deposit", kind="amount",
                    keywords=[r"\b(?:security\s+)?deposit\b(?:\s+(?:is|of|will be|at))?"], window=30),
        ExtractRule(field_id="start_date", kind="date",
                    keywords=[r"\b(?:tenancy|lease|agreement)?\s*(?:begins?|starts?|commenc\w+)\b(?:\s+on)?", r"\bfrom\b"],
                    window=45),
        ExtractRule(field_id="lease_months", kind="duration_months"),
        ExtractRule(field_id="property_address", kind="text", patterns=[
            r"\b(?:property|flat|apartment|house)\s+(?:address\s+)?(?:is|at|:)\s*(?P<v>[^.\n]+)"]),
        ExtractRule(field_id="tenant_address", kind="text", patterns=[
            r"\btenant(?:'s)?\s+(?:permanent\s+)?address\s*(?:is|:)\s*(?P<v>[^.\n]+)"]),
        ExtractRule(field_id="furnished", kind="yesno", no=[r"\bunfurnished\b"],
                    yes=[r"\b(?:fully|semi[- ]?)?furnished\b"]),
    ],
    documents=[
        DocumentSpec(key="rental_agreement", title="Rental agreement draft", template_key="rental_agreement", primary=True),
        DocumentSpec(key="handover_checklist", title="Handover checklist", template_key="handover_checklist"),
    ],
    disclaimers=[
        "Demonstration template. A draft is not signed or executed, and carries no legal obligations until the parties agree.",
        "Saved landlord details are reused only after you confirm the correct party.",
    ],
    other_workflows=["Rent receipts", "Maintenance-request records", "Property visit notes"],
    compute=_compute,
    check=_check,
)
