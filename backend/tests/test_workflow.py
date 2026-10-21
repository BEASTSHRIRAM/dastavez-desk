"""Graph-level tests: the workflow end to end without HTTP."""
from app.agents import runner
from app.repositories.cases import TenantRepo
from app.services.case_view import CaseContext

RENTAL = ("Create a rental agreement draft for a new tenant. The landlord is already saved. The tenant is Rahul Sharma, "
          "rent is eighteen thousand per month, the deposit is fifty thousand, and the tenancy begins on the first of "
          "November. Use my usual reviewed template. Ask me anything important that's missing.")


def make_case(session, ids, workspace, text):
    repo = TenantRepo(session, ids["tenant_a"])
    case, _ = repo.create_case(user_id=ids["op"], workspace=workspace, title="t", transcript=text)
    return repo, case


def start(ids, case, workspace, text):
    runner.start(ids["tenant_a"], case.id, case.thread_id, ids["op"], workspace, text)


def test_rental_pauses_for_missing_fields_and_keeps_extracted_facts(session, ids):
    repo, case = make_case(session, ids, "property", RENTAL)
    start(ids, case, "property", RENTAL)
    session.expire_all()
    case = repo.get_case(case.id)
    assert case.status == "awaiting_input"
    info = runner.pending_interrupt(case.thread_id)
    assert info["type"] == "missing_information"
    # Two landlords are saved and none was named, so the landlord must be chosen; address and term are missing.
    assert {"landlord_party", "property_address", "lease_months", "furnished"} <= set(info["fields"])
    assert "monthly_rent" not in info["fields"] and "tenant_name" not in info["fields"]
    types = [e.type for e in repo.events_after(case.id)]
    assert "facts_extracted" in types and "missing_fields" in types


def test_resume_completes_to_review_then_approval_then_export(session, ids):
    repo, case = make_case(session, ids, "property", RENTAL)
    start(ids, case, "property", RENTAL)
    landlord = next(p for p in CaseContext.load(session, ids["tenant_a"], case.id).parties.list("landlord")
                    if p.full_name == "Meera Kapoor")
    runner.resume(ids["tenant_a"], case.id, case.thread_id, {"answers": {
        "landlord_party": landlord.id, "property_address": "Flat 4B, Green Heights, Pune",
        "lease_months": 11, "furnished": "no"}})
    session.expire_all()
    assert repo.get_case(case.id).status == "review"
    assert runner.pending_interrupt(case.thread_id)["type"] == "review"

    # Approving without confirming the highlighted high-impact values is refused.
    runner.resume(ids["tenant_a"], case.id, case.thread_id, {"action": "approve", "confirm": []})
    session.expire_all()
    assert repo.get_case(case.id).status == "review"
    assert repo.latest_approval(case.id) is None

    cc = CaseContext.load(session, ids["tenant_a"], case.id)
    must = [s.id for s in cc.evaluation().unconfirmed]
    assert "tenant_name" in must and "monthly_rent" in must
    runner.resume(ids["tenant_a"], case.id, case.thread_id, {"action": "approve", "confirm": must})
    session.expire_all()
    assert repo.get_case(case.id).status == "approved"
    assert repo.latest_approval(case.id) is not None

    runner.resume(ids["tenant_a"], case.id, case.thread_id,
                  {"action": "export", "formats": {"rental_agreement": ["docx"], "handover_checklist": ["docx"]}})
    session.expire_all()
    docs = repo.documents(case.id)
    assert {d.doc_key for d in docs} == {"rental_agreement", "handover_checklist"}
    assert repo.get_case(case.id).status == "exported"
