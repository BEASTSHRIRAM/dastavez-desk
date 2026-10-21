"""The reviewer agent: findings must cite real words; it is off without consent; it never blocks on failure."""
import pytest

from app.agents import nodes
from app.services import reviewer
from app.services.llm import LLMError
from tests.helpers import answer, client, components, login, manifest, new_case

TEXT = ("Create a rental agreement. The tenant is Rahul Sharma, rent is eighteen thousand, the deposit is fifty "
        "thousand, tenancy begins on 1 November 2026 for 11 months. The landlord is already saved.")


class Fake:
    name = "fake"

    def __init__(self, findings=None, error=None):
        self.findings, self.error, self.calls = findings or [], error, 0

    EXTRACTED = [  # what a hosted model would return for TEXT; every quote is verbatim from it
        {"field_id": "tenant_name", "value": "Rahul Sharma", "quote": "tenant is Rahul Sharma", "confidence": 0.95},
        {"field_id": "monthly_rent", "value": "18000", "quote": "rent is eighteen thousand", "confidence": 0.95},
        {"field_id": "security_deposit", "value": "50000", "quote": "deposit is fifty thousand", "confidence": 0.95},
        {"field_id": "start_date", "value": "2026-11-01", "quote": "tenancy begins on 1 November 2026", "confidence": 0.95},
        {"field_id": "lease_months", "value": 11, "quote": "for 11 months", "confidence": 0.95}]

    def complete_json(self, system, user):
        if system.startswith("You extract"):  # the extraction step also goes through the provider
            return {"facts": self.EXTRACTED}
        self.calls += 1
        if self.error:
            raise LLMError(self.error)
        return {"findings": self.findings}


def test_findings_that_do_not_cite_real_words_are_discarded():
    fake = Fake([
        {"message": "Tenant name differs.", "quote": "Rahul Sharma", "where": "draft"},
        {"message": "Invented problem.", "quote": "words nobody wrote", "where": "draft"},
        {"message": "No quote at all.", "quote": "", "where": "said"},
        {"message": "Spoken, not drafted.", "quote": "tenancy begins on 1 November", "where": "said"},
    ])
    out = reviewer.review(fake, "The tenant is Rahul Sharma, tenancy begins on 1 November", {"Tenant": "Rahul Sharma"}, "Tenant: Rahul Sharma")
    assert [i.message.split(" (")[0] for i in out] == ["Reviewer: Tenant name differs.", "Reviewer: Spoken, not drafted."]
    assert all(i.severity == "warning" and i.code == "agent_review" for i in out)  # it can warn, never block


def test_a_failed_review_is_a_note_not_an_error():
    issues, note = reviewer.safe_review(Fake(error="timeout"), "said", {}, "draft")
    assert issues == [] and "not available" in note


def _review_flow(h, monkeypatch, fake, consent):
    owner = login("owner@demo.test")
    client.put("/api/tenant/consent", json={"ai_consent": consent}, headers=owner)
    monkeypatch.setattr(nodes, "get_llm_provider", lambda *a, **k: fake)
    case = new_case(h, "property", TEXT)
    landlord = next(c for c in components(manifest(h, case["id"])) if c.get("field_id") == "landlord_party")["party_options"][0]["id"]
    answer(h, case["id"], {"landlord_party": landlord, "property_address": "Flat 4B, Green Heights, Pune 411045", "furnished": "no"})
    return case, components(manifest(h, case["id"]), "approval_panel")[0]


def test_reviewer_findings_appear_in_the_approval_panel_when_the_business_consented(monkeypatch):
    h = login()
    fake = Fake([{"message": "Rent in the draft should be checked.", "quote": "Monthly rent is", "where": "draft"}])
    case, panel = _review_flow(h, monkeypatch, fake, consent=True)
    assert fake.calls >= 1
    hit = [i for i in panel["issues"] if i["code"] == "agent_review"]
    assert hit and hit[0]["severity"] == "warning" and panel["can_approve"] is True
    events = [e["type"] for e in client.get(f"/api/cases/{case['id']}/events", headers=h).json()]
    assert "agent_review_done" in events


def test_the_reviewer_never_runs_without_consent(monkeypatch):
    fake = Fake([{"message": "x", "quote": "Monthly rent is", "where": "draft"}])
    _, panel = _review_flow(login(), monkeypatch, fake, consent=False)
    assert fake.calls == 0 and not [i for i in panel["issues"] if i["code"] == "agent_review"]


def test_a_reviewer_outage_does_not_stop_the_case(monkeypatch):
    h = login()
    case, panel = _review_flow(h, monkeypatch, Fake(error="provider down"), consent=True)
    assert client.get(f"/api/cases/{case['id']}", headers=h).json()["status"] == "review" and panel["can_approve"]
