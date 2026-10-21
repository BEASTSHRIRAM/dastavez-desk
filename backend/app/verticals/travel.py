import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from app.models.fields import FieldSpec, FieldType, Issue
from app.verticals.base import NAME, DocumentSpec, ExtractRule, WorkspaceConfig

DATA_FILE = Path(__file__).parent / "data" / "travel_requirements.json"


def load_requirements() -> dict[str, Any]:
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))["destinations"]


def lookup_requirements(destination: str | None) -> dict[str, Any] | None:
    if not destination:
        return None
    for name, entry in load_requirements().items():
        if name.casefold() == destination.strip().casefold():
            return {"destination": name, **entry}
    return None


def _item_applies(item: dict, v: dict[str, Any]) -> bool:
    cond = item.get("when")
    if not cond:
        return True
    return bool(v.get(cond["field"])) == cond.get("present", True)


def _compute(v: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    s, e = v.get("trip_start"), v.get("trip_end")
    if isinstance(s, date) and isinstance(e, date) and e >= s:
        out["trip_days"] = (e - s).days + 1
        out["itinerary_days"] = [{"day": i + 1, "date": s + timedelta(days=i)} for i in range(out["trip_days"])]
    req = lookup_requirements(v.get("destination"))
    if req:
        out["requirements_source"] = req["source"]
        out["requirements_verified"] = req.get("last_verified") or "Not verified"
        out["checklist"] = [i["label"] + (f" ({i['note']})" if i.get("note") else "")
                            for i in req["items"] if _item_applies(i, v)]
    return out


def _check(v: dict[str, Any]) -> list[Issue]:
    issues = []
    s, e = v.get("trip_start"), v.get("trip_end")
    if isinstance(s, date) and isinstance(e, date) and e < s:
        issues.append(Issue(field_id="trip_end", code="invalid", message="Return date is before the departure date."))
    if v.get("destination") and "checklist" not in v:
        issues.append(Issue(field_id="destination", code="template", severity="warning",
                            message=f"No administrator-approved requirements are on file for {v['destination']}. "
                                    "No checklist was generated. Add a verified, dated source first."))
    elif v.get("requirements_verified") == "Not verified":
        issues.append(Issue(field_id="destination", code="unverified", severity="warning",
                            message="Requirements come from a demonstration dataset with no verified date."))
    return issues


TRAVEL = WorkspaceConfig(
    id="travel",
    name="Travel & Visa",
    tagline="Itineraries, routes, document packets",
    description="Collect an applicant's trip once, then generate the itinerary, checklist and cover-letter drafts.",
    material="routes",
    example_prompt=("Prepare a travel-document checklist for the applicant Kavita Menon, travelling to Demoland from "
                    "1 December 2026 until 10 December 2026 for tourism. She is staying at the Harbour View Hotel. "
                    "Create the itinerary draft and ask me for missing information."),
    classify_keywords=["travel", "visa", "itinerary", "passport", "destination", "trip", "flight", "tourism"],
    fields=[
        FieldSpec(id="applicant_name", label="Applicant full name", type=FieldType.PERSON, required=True,
                  high_impact=True, group="applicant"),
        FieldSpec(id="nationality", label="Nationality", type=FieldType.TEXT, required=True, high_impact=True, group="applicant"),
        FieldSpec(id="occupation", label="Occupation or employer", type=FieldType.TEXT, group="applicant",
                  help="Never invented. Leave blank if the applicant has not said."),
        FieldSpec(id="destination", label="Destination country", type=FieldType.TEXT, required=True, high_impact=True, group="trip"),
        FieldSpec(id="trip_start", label="Departure date", type=FieldType.DATE, required=True, high_impact=True, group="trip"),
        FieldSpec(id="trip_end", label="Return date", type=FieldType.DATE, required=True, high_impact=True, group="trip"),
        FieldSpec(id="trip_purpose", label="Purpose of travel", type=FieldType.SELECT, required=True,
                  options=["Tourism", "Business", "Family visit", "Study", "Other"], group="trip"),
        FieldSpec(id="accommodation", label="Accommodation", type=FieldType.LONGTEXT, required=True, group="trip",
                  help="Only what the applicant has actually arranged. This tool makes no bookings."),
        FieldSpec(id="transport_summary", label="Transport summary", type=FieldType.LONGTEXT, group="trip"),
    ],
    rules=[
        ExtractRule(field_id="applicant_name", kind="name", patterns=[
            rf"\b(?:applicant|traveller|traveler|client|customer)(?:'s)?(?:\s+name)?(?:\s+is|\s+named|:)?\s+(?P<v>{NAME})"]),
        ExtractRule(field_id="nationality", kind="text", patterns=[
            r"\bnationality\s*(?:is|:)\s*(?P<v>[A-Za-z]+)", r"\b(?P<v>[A-Z][a-z]+)\s+(?:national|citizen|passport holder)\b"]),
        ExtractRule(field_id="destination", kind="text", patterns=[
            r"\b(?:travell?ing|travel|going|trip|visa)\s+to\s+(?P<v>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)?)"]),
        ExtractRule(field_id="trip_start", kind="date", keywords=[r"\bfrom\b", r"\bdepart\w*(?:\s+on)?\b", r"\bleaving(?:\s+on)?\b"], window=30),
        ExtractRule(field_id="trip_end", kind="date", keywords=[r"\buntil\b", r"\btill\b", r"\breturn\w*(?:\s+on)?\b", r"\bto\b(?=\s+\d|\s+(?:the\s+)?\w+\s+\w+\s+\d)"], window=30),
        ExtractRule(field_id="trip_purpose", kind="select", choices={
            "Tourism": [r"touris[mt]", r"holiday", r"vacation"], "Business": [r"business"],
            "Family visit": [r"family", r"relatives"], "Study": [r"\bstudy\b", r"\bstudies\b"]}),
        ExtractRule(field_id="accommodation", kind="text", patterns=[
            r"\b(?:staying|stay)\s+(?:at|in|with)\s+(?P<v>[^.\n]+)", r"\baccommodation\s*(?:is|:)\s*(?P<v>[^.\n]+)"]),
        ExtractRule(field_id="occupation", kind="text", patterns=[
            r"\b(?:works|working)\s+(?:as|at|for)\s+(?P<v>[^.\n,]+)", r"\boccupation\s*(?:is|:)\s*(?P<v>[^.\n,]+)"]),
    ],
    documents=[
        DocumentSpec(key="travel_checklist", title="Supporting-document checklist", template_key="travel_checklist", primary=True),
        DocumentSpec(key="itinerary_draft", title="Itinerary draft", template_key="travel_itinerary"),
        DocumentSpec(key="cover_letter", title="Travel cover-letter draft", template_key="travel_cover_letter"),
        DocumentSpec(key="missing_info_report", title="Missing-information report", template_key="travel_missing_info"),
    ],
    disclaimers=[
        "This tool does not guarantee visa approval or determine eligibility.",
        "Requirements are shown only with their source and last-verified date. Nothing is booked or submitted.",
    ],
    other_workflows=["Interview-preparation notes"],
    compute=_compute,
    check=_check,
)
