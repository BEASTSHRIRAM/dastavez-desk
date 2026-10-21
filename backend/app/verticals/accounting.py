from datetime import date
from decimal import Decimal
from typing import Any

from app.models.fields import FieldSpec, FieldType, Issue
from app.services.parsing import quantize_money
from app.verticals.base import NAME, DocumentSpec, ExtractRule, WorkspaceConfig

CATEGORIES = ["Office expenses", "Equipment", "Travel", "Utilities", "Professional fees", "Rent",
              "Repairs & maintenance", "Software & subscriptions", "Other"]
PAYMENT_METHODS = ["UPI", "Cash", "Card", "Bank transfer", "Cheque"]
TAX_RATES = {"No tax / not applicable": Decimal("0"), "5%": Decimal("5"), "12%": Decimal("12"),
             "18%": Decimal("18"), "28%": Decimal("28")}


def split_tax(amount: Decimal, rate_pct: Decimal, inclusive: bool) -> tuple[Decimal, Decimal, Decimal]:
    """Deterministic base / tax / total. Never delegated to a language model."""
    if inclusive:
        base = quantize_money(amount / (1 + rate_pct / 100))
        return base, quantize_money(amount - base), quantize_money(amount)
    tax = quantize_money(amount * rate_pct / 100)
    return quantize_money(amount), tax, quantize_money(amount + tax)


def _compute(v: dict[str, Any]) -> dict[str, Any]:
    amount = v.get("amount")
    if not isinstance(amount, Decimal):
        return {}
    rate = TAX_RATES.get(v.get("tax_rate") or "No tax / not applicable", Decimal("0"))
    base, tax, total = split_tax(amount, rate, bool(v.get("amount_includes_tax")))
    return {"base_amount": base, "tax_amount": tax, "total_amount": total, "tax_rate_pct": rate}


def _check(v: dict[str, Any]) -> list[Issue]:
    issues = []
    d = v.get("expense_date")
    if isinstance(d, date) and d > date.today():
        issues.append(Issue(field_id="expense_date", code="invalid", message="Expense date is in the future."))
    amount = v.get("amount")
    if isinstance(amount, Decimal) and v.get("payment_method") == "Cash" and amount > Decimal("10000"):
        issues.append(Issue(field_id="payment_method", code="unverified", severity="warning",
                            message="Large cash payment. Check the tax treatment with your accountant."))
    if not v.get("bill_number"):
        issues.append(Issue(field_id="bill_number", code="unverified", severity="warning",
                            message="No bill or invoice number recorded. Attach the bill before reconciling."))
    return issues


ACCOUNTING = WorkspaceConfig(
    id="accounting",
    name="Bookkeeping",
    tagline="Aligned records, ledgers, financial documents",
    description="Dictate an expense and get a typed, categorised record with deterministic totals and a spreadsheet.",
    material="ledger",
    example_prompt=("Record a printer purchase for forty-two hundred rupees, paid by UPI to the supplier yesterday. "
                    "Categorise it as an office expense, but flag anything that needs verification."),
    classify_keywords=["expense", "invoice", "purchase", "paid", "payment", "receipt", "ledger", "categori", "upi", "rupees"],
    fields=[
        FieldSpec(id="description", label="Description", type=FieldType.TEXT, required=True, group="transaction"),
        FieldSpec(id="amount", label="Amount paid (INR)", type=FieldType.CURRENCY, required=True, high_impact=True,
                  min=0.01, group="transaction"),
        FieldSpec(id="expense_date", label="Date of expense", type=FieldType.DATE, required=True, high_impact=True,
                  date_bias="past", group="transaction"),
        FieldSpec(id="payment_method", label="Payment method", type=FieldType.SELECT, required=True,
                  options=PAYMENT_METHODS, group="transaction"),
        FieldSpec(id="supplier", label="Supplier", type=FieldType.TEXT, required=True, high_impact=True, group="transaction"),
        FieldSpec(id="category", label="Category", type=FieldType.SELECT, required=True, options=CATEGORIES,
                  group="classification", help="A suggestion until you confirm it."),
        FieldSpec(id="tax_rate", label="Tax rate on this bill", type=FieldType.SELECT, options=list(TAX_RATES),
                  group="classification"),
        FieldSpec(id="amount_includes_tax", label="Does the amount include tax?", type=FieldType.YESNO, required=True,
                  group="classification", when={"field": "tax_rate", "in": ["5%", "12%", "18%", "28%"]}),
        FieldSpec(id="bill_number", label="Bill or invoice number", type=FieldType.TEXT, group="transaction"),
    ],
    rules=[
        ExtractRule(field_id="description", kind="text", template="{v} purchase", patterns=[
            r"\b(?:record|log|enter|add|book)\s+(?:an?\s+|the\s+)?(?P<v>[a-z][a-z ]{1,30}?)\s+(?:purchase|expense|payment|bill)\b"]),
        ExtractRule(field_id="amount", kind="amount",
                    keywords=[r"\bfor\b", r"\bworth\b", r"\bcosting\b", r"\bamount(?:\s+of)?\b", r"\btotal\b", r"₹", r"\brs\.?", r"\binr\b"],
                    window=18),
        ExtractRule(field_id="expense_date", kind="date", keywords=[r"\byesterday\b", r"\btoday\b", r"\bon\b", r"\bdated?\b"], window=30),
        ExtractRule(field_id="payment_method", kind="select", choices={
            "UPI": [r"\bupi\b", r"gpay", r"phonepe"], "Cash": [r"\bcash\b"], "Card": [r"\bcard\b"],
            "Bank transfer": [r"bank transfer", r"\bneft\b", r"\bimps\b", r"\brtgs\b"], "Cheque": [r"\bche(?:que|ck)\b"]}),
        ExtractRule(field_id="supplier", kind="name", patterns=[
            rf"\b(?:supplier|vendor|shop|store)(?:\s+(?:is|named|called))?\s+(?P<v>{NAME})"]),
        ExtractRule(field_id="category", kind="select", choices={
            "Office expenses": [r"\boffice\b", r"stationery", r"\bprinter\b", r"\bpaper\b", r"toner"],
            "Equipment": [r"\blaptop\b", r"\bcomputer\b", r"\bequipment\b"],
            "Travel": [r"\btravel\b", r"\bflight\b", r"\btaxi\b", r"\bfuel\b"],
            "Utilities": [r"electricity", r"\bwater bill\b", r"internet"],
            "Professional fees": [r"consult", r"professional fee"], "Rent": [r"\brent\b"],
            "Repairs & maintenance": [r"repair", r"maintenance"], "Software & subscriptions": [r"software", r"subscription"]}),
        ExtractRule(field_id="tax_rate", kind="select",
                    choices={f"{r}%": [rf"\b{r}\s*(?:%|percent)\s*(?:gst|tax)?"] for r in (5, 12, 18, 28)}),
        ExtractRule(field_id="bill_number", kind="text", patterns=[
            r"\b(?:bill|invoice)\s*(?:number|no\.?|#)\s*(?:is|:)?\s*(?P<v>[A-Za-z0-9/-]+)"]),
    ],
    documents=[
        DocumentSpec(key="expense_voucher", title="Expense voucher", template_key="accounting_voucher", primary=True),
        DocumentSpec(key="ledger_entry", title="Ledger entry", kind="ledger", formats=["xlsx", "csv"]),
    ],
    disclaimers=[
        "Amounts and tax are calculated by deterministic code with decimal arithmetic. Categories are suggestions until you confirm them.",
        "Nothing is paid, filed or sent to an external accounting system.",
    ],
    other_workflows=["Invoice drafts", "Payment-follow-up records", "Monthly expense summaries", "Reconciliation review queues"],
    compute=_compute,
    check=_check,
)
