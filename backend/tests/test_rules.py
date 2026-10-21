"""Unit tests: schemas, parsing, deterministic money, missing fields, template selection, persistence."""
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.agents import runner
from app.agents.checkpoint import reset_checkpointer
from app.models.fields import FieldSpec, FieldType
from app.models.orm import Fact
from app.models.ui_manifest import UiManifest
from app.repositories.cases import TenantRepo
from app.repositories.catalog import TemplateRepo
from app.services import documents
from app.services.case_state import evaluate
from app.services.extraction import classify_workspace, extract_with_rules
from app.services.parsing import format_inr, parse_amount, parse_date
from app.services.values import ValueError_, coerce, is_present
from app.verticals import WORKSPACES
from app.verticals.accounting import split_tax
from app.verticals.property import add_months

TODAY = date(2026, 10, 21)


# ------------------------------------------------------------------ parsing
@pytest.mark.parametrize("text,expected", [
    ("rent is eighteen thousand per month", "18000"), ("for forty-two hundred rupees", "4200"),
    ("two lakh fifty thousand", "250000"), ("Rs 4,200.50 by UPI", "4200.50"), ("one hundred and fifty", "150"),
    ("₹1,25,000", "125000"), ("12k", "12000")])
def test_amounts_parse_to_exact_decimals(text, expected):
    assert parse_amount(text)[0] == Decimal(expected)


def test_dates_resolve_relative_to_today_and_flag_assumptions():
    d, ambiguous, _ = parse_date("the first of November", TODAY)
    assert d == date(2026, 11, 1) and ambiguous  # year was assumed
    assert parse_date("5 March 2027", TODAY)[:2] == (date(2027, 3, 5), False)
    assert parse_date("yesterday", TODAY, "past")[0] == date(2026, 10, 20)
    assert parse_date("03/04/2026", TODAY)[:2] == (date(2026, 4, 3), True)  # DD/MM, but flagged: could be read either way
    assert parse_date("31 February", TODAY) is None


def test_indian_digit_grouping_and_month_arithmetic():
    assert format_inr(Decimal("1234567.5")) == "12,34,567.50" and format_inr(0) == "0.00"
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


# ------------------------------------------------------------------ deterministic money
def test_tax_split_is_exact_and_never_loses_a_paisa():
    base, tax, total = split_tax(Decimal("4200"), Decimal("18"), True)
    assert (base, tax, total) == (Decimal("3559.32"), Decimal("640.68"), Decimal("4200.00"))
    base, tax, total = split_tax(Decimal("999.99"), Decimal("12"), False)
    assert (base, tax, total) == (Decimal("999.99"), Decimal("120.00"), Decimal("1119.99"))
    for amount in ("0.01", "1", "33.33", "100000.07"):
        b, t, tot = split_tax(Decimal(amount), Decimal("5"), True)
        assert b + t == tot == Decimal(amount).quantize(Decimal("0.01"))


def test_floats_never_reach_money():
    spec = FieldSpec(id="a", label="Amount", type=FieldType.CURRENCY, min=0)
    assert coerce(spec, 0.1) == Decimal("0.10")
    assert isinstance(coerce(spec, "18,000"), Decimal)
    with pytest.raises(ValueError_):
        coerce(spec, "-5")
    with pytest.raises(ValueError_):
        coerce(spec, "NaN")


# ------------------------------------------------------------------ missing vs zero
def test_zero_is_a_real_answer_but_blank_is_missing():
    assert is_present(Decimal("0.00")) and is_present(0) and is_present(False)
    assert not is_present(None) and not is_present("  ") and not is_present([])
    deposit = WORKSPACES["property"].field("security_deposit")
    assert coerce(deposit, "0") == Decimal("0.00") and coerce(deposit, "") is None


def _facts(cfg, **vals):
    return [Fact(field_id=k, value={"v": v}, status="confirmed", provenance={}, confidence=1.0, id=k) for k, v in vals.items()]


def test_missing_required_fields_are_detected_and_zero_deposit_is_not_missing():
    cfg = WORKSPACES["property"]
    ev = evaluate(cfg, _facts(cfg, tenant_name="Rahul Sharma", monthly_rent="18000.00", security_deposit="0.00"))
    missing = {s.id for s in ev.missing}
    assert "security_deposit" not in missing and "monthly_rent" not in missing
    assert {"landlord_party", "property_address", "start_date", "lease_months", "furnished"} <= missing
    assert ev.values["rent_due_day"] == 5 and ev.resolved["rent_due_day"].status == "default"


def test_conditional_questions_appear_only_when_the_answer_requires_them():
    cfg = WORKSPACES["property"]
    base = dict(furnished=False)
    assert "inventory_summary" not in {s.id for s in evaluate(cfg, _facts(cfg, **base)).missing}
    assert "inventory_summary" in {s.id for s in evaluate(cfg, _facts(cfg, furnished=True)).missing}
    legal = WORKSPACES["legal"]
    assert "previous_name" not in {s.id for s in evaluate(legal, _facts(legal, declaration_purpose="Address declaration")).missing}
    assert "previous_name" in {s.id for s in evaluate(legal, _facts(legal, declaration_purpose="Name declaration")).missing}


def test_confirmed_values_beat_suggestions_and_unconfirmed_differences_conflict():
    cfg = WORKSPACES["property"]
    sug = lambda v, i: Fact(field_id="monthly_rent", value={"v": v}, status="suggested", provenance={"origin": i}, confidence=0.9, id=i)
    ev = evaluate(cfg, [sug("18000.00", "a"), sug("20000.00", "b")])
    assert ev.resolved["monthly_rent"].conflict and "monthly_rent" not in ev.values
    fixed = Fact(field_id="monthly_rent", value={"v": "18000.00"}, status="confirmed", provenance={}, confidence=1.0, id="c")
    ev = evaluate(cfg, [sug("18000.00", "a"), sug("20000.00", "b"), fixed])
    assert ev.values["monthly_rent"] == Decimal("18000.00") and not ev.conflicts


def test_verification_fields_must_be_yes():
    cfg = WORKSPACES["legal"]
    ev = evaluate(cfg, _facts(cfg, identity_verified=False, facts_checked_with_client=True))
    assert any(i.code == "unverified" and i.field_id == "identity_verified" for i in ev.blocking)


# ------------------------------------------------------------------ extraction and classification
def test_each_workspace_example_is_classified_to_itself():
    for wid, w in WORKSPACES.items():
        assert classify_workspace(w.example_prompt)[0] == wid


def test_extraction_keeps_the_exact_quote_and_never_invents_values():
    cfg = WORKSPACES["property"]
    result = extract_with_rules(cfg, "Please draft something for a tenant.", TODAY)
    assert result.facts == []  # nothing stated, nothing extracted
    facts = {f.field_id: f for f in extract_with_rules(cfg, "The tenant is Rahul Sharma and the deposit is 0.", TODAY).facts}
    assert facts["tenant_name"].quote == "tenant is Rahul Sharma" and facts["security_deposit"].value == Decimal("0")


def test_hosted_extraction_drops_values_whose_quote_is_not_in_the_source():
    from app.services.extraction import extract_with_llm

    class FakeLLM:
        name = "fake"
        def complete_json(self, system, user):
            return {"facts": [
                {"field_id": "tenant_name", "value": "Rahul Sharma", "quote": "tenant is Rahul Sharma", "confidence": 0.9},
                {"field_id": "monthly_rent", "value": "99999", "quote": "rent is ninety nine thousand", "confidence": 0.9},
                {"field_id": "not_a_field", "value": "x", "quote": "tenant", "confidence": 1}]}

    out = extract_with_llm(WORKSPACES["property"], "The tenant is Rahul Sharma.", FakeLLM(), TODAY)
    assert [f.field_id for f in out.facts] == ["tenant_name"] and any("monthly_rent" in n for n in out.notes)


# ------------------------------------------------------------------ schemas
def test_ui_manifest_rejects_anything_outside_the_approved_components():
    ok = {"case_id": "c", "stage": "questions", "title": "t", "sections": [{"title": "s", "components": [
        {"component": "text_input", "field_id": "a", "label": "A"}]}]}
    UiManifest.model_validate(ok)
    for bad in ({"component": "script", "src": "alert(1)"},
                {"component": "text_input", "field_id": "a", "label": "A", "html": "<img onerror=x>"},
                {"component": "text_input", "field_id": "a"}):
        with pytest.raises(ValidationError):
            UiManifest.model_validate({**ok, "sections": [{"title": "s", "components": [bad]}]})
    with pytest.raises(ValidationError):
        UiManifest.model_validate({**ok, "onload": "evil()"})


# ------------------------------------------------------------------ template selection
def test_latest_approved_template_version_wins_and_superseded_is_skipped(session):
    repo = TemplateRepo(session, "x" * 32)
    versions = repo.latest_approved("declaration_address")
    assert [v.version for v in versions] == ["1.1"]  # 1.0 is superseded, not approved
    plans = documents.plan_documents(repo, WORKSPACES["legal"], {"declaration_purpose": "Name declaration"})
    assert plans[0].template.template_key == "declaration_name"
    plans = documents.plan_documents(repo, WORKSPACES["legal"], {})
    assert plans[0].template is None and plans[0].issue.field_id == "declaration_purpose"  # ambiguous until chosen


def test_unapproved_templates_are_never_selected(session):
    from app.models.orm import TemplateVersion
    from sqlalchemy import update
    session.execute(update(TemplateVersion).where(TemplateVersion.template_key == "rental_agreement").values(approved=False))
    session.commit()
    plans = documents.plan_documents(TemplateRepo(session, "x" * 32), WORKSPACES["property"], {})
    assert plans[0].template is None and "No approved version" in plans[0].issue.message


def test_template_files_exist_for_every_registered_version(session):
    from app.templates.builder import template_file
    for t in TemplateRepo(session, "x" * 32).list():
        assert template_file(t.template_key, t.version).exists(), t.template_key


# ------------------------------------------------------------------ persistence and resume
def test_workflow_survives_a_process_restart(session, ids):
    text = WORKSPACES["property"].example_prompt
    repo = TenantRepo(session, ids["tenant_a"])
    case, _ = repo.create_case(user_id=ids["op"], workspace="property", title="t", transcript=text)
    runner.start(ids["tenant_a"], case.id, case.thread_id, ids["op"], "property", text)
    before = {f.field_id for f in repo.facts(case.id)}
    # Simulate a restart: drop the in-memory graph and checkpointer, rebuild from the stored checkpoint.
    runner.reset_graph()
    reset_checkpointer()
    info = runner.pending_interrupt(case.thread_id)
    assert info and info["type"] == "missing_information"
    landlord = next(p for p in TenantRepo(session, ids["tenant_a"]).s.query(__import__("app.models.orm", fromlist=["Party"]).Party)
                    if p.tenant_id == ids["tenant_a"] and p.full_name == "Meera Kapoor")
    runner.resume(ids["tenant_a"], case.id, case.thread_id, {"answers": {
        "landlord_party": landlord.id, "property_address": "Flat 2", "lease_months": 11, "furnished": "no"}})
    session.expire_all()
    assert repo.get_case(case.id).status == "review"
    assert before <= {f.field_id for f in repo.facts(case.id)}  # earlier facts were never lost


def test_a_failed_run_keeps_its_answers_and_can_be_retried(session, ids, monkeypatch):
    from app.agents import nodes
    text = WORKSPACES["accounting"].example_prompt
    repo = TenantRepo(session, ids["tenant_a"])
    case, _ = repo.create_case(user_id=ids["op"], workspace="accounting", title="t", transcript=text)
    real, calls = nodes.render_document_preview, {"n": 0}

    def flaky(state):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("renderer crashed")
        return real(state)

    flaky.__name__ = "render_document_preview"
    monkeypatch.setattr(nodes, "render_document_preview", flaky)
    runner.reset_graph()
    runner.start(ids["tenant_a"], case.id, case.thread_id, ids["op"], "accounting", text)
    session.expire_all()
    assert repo.get_case(case.id).status == "awaiting_input"  # needs a supplier first
    runner.resume(ids["tenant_a"], case.id, case.thread_id, {"answers": {"supplier": "Sharma Office Supplies"}})
    session.expire_all()
    assert repo.get_case(case.id).status == "failed"
    assert "workflow_error" in [e.type for e in repo.events_after(case.id)]
    assert any(f.field_id == "supplier" and f.status == "confirmed" for f in repo.facts(case.id))  # answer not lost
    runner.retry(ids["tenant_a"], case.id, case.thread_id)  # continues from the last checkpoint
    session.expire_all()
    assert repo.get_case(case.id).status == "review"


def test_preview_keeps_the_page_header_banner_and_footer():
    from app.services.rendering import read_blocks
    from app.templates.builder import template_file
    blocks = read_blocks(template_file("rental_agreement", "1.0"))
    assert blocks[0]["type"] == "header" and "NOT LEGAL ADVICE" in blocks[0]["text"]
    assert blocks[-1]["type"] == "footer" and "Draft pending human review" in blocks[-1]["text"]
    assert [b["header"] for b in blocks if b["type"] == "table"] == [False]  # key/value table has no header row
