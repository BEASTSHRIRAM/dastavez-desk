"""The consistency guard: other clients' details, spelling drift, words that disagree with figures."""
from app.services.consistency import OtherEntity, check_name_drift, check_residue, check_words_vs_numerals, words_value
from app.services.parsing import amount_in_words
from decimal import Decimal
import pytest
from tests.helpers import answer, approve, client, components, login, manifest, new_case

TEXT_A = ("Create a rental agreement. The tenant is Rahul Sharma, rent is eighteen thousand, the deposit is fifty "
          "thousand, tenancy begins on 1 November 2026 for 11 months. The landlord is already saved.")
TEXT_B = ("Create a rental agreement. The tenant is Neha Singh, rent is twenty thousand, the deposit is forty "
          "thousand, tenancy begins on 1 December 2026 for 12 months. The landlord is already saved.")


@pytest.mark.parametrize("value", ["18000", "4200.50", "125000", "10000000", "0", "101", "99999.99"])
def test_amount_in_words_round_trips_exactly(value):
    assert words_value(amount_in_words(Decimal(value))) == Decimal(value)


def test_a_figure_that_disagrees_with_its_words_is_an_error():
    ok = "Rent is Rs. 18,000.00 (Rupees Eighteen Thousand only)."
    bad = "Rent is Rs. 18,000.00 (Rupees Eight Thousand only)."
    assert check_words_vs_numerals("Agreement", ok) == []
    [issue] = check_words_vs_numerals("Agreement", bad)
    assert issue.severity == "error" and "do not match" in issue.message


def test_residue_finds_other_clients_but_not_this_clients_own_values():
    doc = "Tenant Rahul Sharma, phone 98765 00011, of 7 Orchard Lane, Kothrud, Pune 411038. Landlord Meera Kapoor."
    others = [OtherEntity("name", "Arjun Desai", "saved record"), OtherEntity("phone", "9876500011", "another case"),
              OtherEntity("address", "7 Orchard Lane, Kothrud, Pune 411038", "saved record"), OtherEntity("name", "Meera Kapoor", "x")]
    found = check_residue("Agreement", doc, {"meera kapoor"}, others)
    kinds = sorted(i.message.split("the ")[1].split(" ")[0] for i in found)
    assert kinds == ["address", "phone"]  # Arjun Desai is not in the draft; Meera is this case's own landlord
    assert all(i.code == "leak" and i.key for i in found)


def test_name_drift_flags_misspellings_but_not_fuller_forms_of_the_same_name():
    assert len(check_name_drift({"Tenant": "Rahul Sharma"}, {"an attached file": "Contact: Rahul Sharmaa for keys."})) == 1
    assert check_name_drift({"Tenant": "Rahul Sharma"}, {"an attached file": "Rahul Sharma Singh signed."}) == []
    assert check_name_drift({"Tenant": "Rahul Sharma"}, {"what you said": "Rahul Sharma"}) == []


def _to_review(h, text, address, name_hint="landlord_party"):
    case = new_case(h, "property", text)
    landlord = next(c for c in components(manifest(h, case["id"])) if c.get("field_id") == name_hint)["party_options"][0]["id"]
    answer(h, case["id"], {"landlord_party": landlord, "property_address": address, "furnished": "no"})
    return case


def test_another_clients_name_in_a_draft_must_be_acknowledged_before_approval():
    h = login()
    _to_review(h, TEXT_A, "Flat 4B, Green Heights, Pune 411045")  # earlier client: Rahul Sharma
    case = _to_review(h, TEXT_B, "Opposite Rahul Sharma Complex, Pune 411045")  # a new client; old name slips in
    m = manifest(h, case["id"])
    panel = components(m, "approval_panel")[0]
    assert any(i["code"] == "leak" and "Rahul Sharma" in i["message"] for i in panel["issues"])
    keys = [a["key"] for a in panel["acknowledgements"]]
    assert keys
    confirm = [f["field_id"] for f in panel["confirm_fields"]]
    refused = client.post(f"/api/cases/{case['id']}/approve", json={"confirm": confirm}, headers=h)
    assert refused.status_code == 409
    ok = client.post(f"/api/cases/{case['id']}/approve", json={"confirm": confirm, "acknowledge": keys}, headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    audit = [a for a in client.get(f"/api/cases/{case['id']}/audit", headers=h).json() if a["action"] == "approved"][0]
    assert audit["detail"]["acknowledged"] == sorted(keys)  # who checked what is on the record


def test_a_normal_second_client_raises_no_leak_findings():
    h = login()
    _to_review(h, TEXT_A, "Flat 4B, Green Heights, Pune 411045")
    case = _to_review(h, TEXT_B, "Flat 9C, Lake View, Pune 411001")
    panel = components(manifest(h, case["id"]), "approval_panel")[0]
    assert not [i for i in panel["issues"] if i["code"] == "leak"] and panel["acknowledgements"] == []


def test_built_in_agreements_state_amounts_in_figures_and_words():
    h = login()
    case = _to_review(h, TEXT_A, "Flat 4B, Green Heights, Pune 411045")
    doc = next(c for c in components(manifest(h, case["id"]), "document_preview") if c["doc_key"] == "rental_agreement")
    text = " ".join(b.get("text", "") for b in doc["blocks"])
    assert "Rupees Eighteen Thousand only" in text and "Rupees Sixty Eight Thousand only" in text
