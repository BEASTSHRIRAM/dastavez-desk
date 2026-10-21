"""Real PDF export. Needs LibreOffice or Microsoft Word on the machine; skipped (not faked) without one."""
import io

import pytest
from pypdf import PdfReader

from app.services import rendering
from tests.helpers import answer, approve, client, components, login, manifest, new_case

pytestmark = pytest.mark.skipif(not rendering.pdf_available(), reason="no DOCX-to-PDF converter installed")

TEXT = ("Create a rental agreement. The tenant is Rahul Sharma, rent is eighteen thousand, the deposit is fifty "
        "thousand, tenancy begins on 1 November 2026 for 11 months. The landlord is already saved.")


def test_approved_rental_agreement_exports_as_a_real_pdf_with_the_reviewed_values():
    h = login()
    case = new_case(h, "property", TEXT)
    landlord = next(c for c in components(manifest(h, case["id"])) if c.get("field_id") == "landlord_party")["party_options"][0]
    answer(h, case["id"], {"landlord_party": landlord["id"], "property_address": "Flat 4B, Green Heights, Pune", "furnished": "no"})
    approve(h, case["id"])
    out = client.post(f"/api/cases/{case['id']}/export", json={"formats": {"rental_agreement": ["pdf", "docx"]}}, headers=h).json()
    assert {d["fmt"] for d in out["documents"]} == {"pdf", "docx"} and out["export_failures"] == []
    pdf = next(d for d in out["documents"] if d["fmt"] == "pdf")
    r = client.get(f"/api/documents/{pdf['id']}/download", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF-")
    text = "".join(page.extract_text() for page in PdfReader(io.BytesIO(r.content)).pages)
    for expected in ("RENTAL AGREEMENT", "Rahul Sharma", "Rs. 18,000.00", "Rs. 68,000.00", "30 September 2027"):
        assert expected in text, expected
