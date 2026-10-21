"""Consistency guard: checks a finished draft against everything else the business knows.

Three things a person misses at 6 pm and a rejected or leaked document costs real trouble for:
  1. residue: names, phones or addresses of *other* clients showing up in this client's draft;
  2. spelling drift: the same person written two ways between what was said and what was attached;
  3. words vs numerals: "Rs. 18,000 (Rupees Eighteen Thousand only)" must agree with itself.

All deterministic. Results are findings for a person to judge; nothing here edits a document."""
import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.models.fields import Issue
from app.services.parsing import parse_number_words


@dataclass(frozen=True)
class OtherEntity:
    kind: str  # name | phone | address
    text: str
    source: str  # shown to the operator, e.g. "saved record Arjun Desai"


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def check_residue(doc_title: str, doc_text: str, own: set[str], others: list[OtherEntity]) -> list[Issue]:
    """Flag other clients' details found in this draft. `own` holds the case's own values (casefolded)."""
    low = doc_text.casefold()
    squashed = re.sub(r"[\s-]", "", doc_text)
    found: dict[tuple[str, str], Issue] = {}
    for e in others:
        t = e.text.strip()
        c = t.casefold()
        if not t or c in own:
            continue
        if e.kind == "address" and any(c in o or o in c for o in own if len(o) >= 12 and len(c) >= 12):
            continue  # overlapping addresses are the same place written differently
        hit = False
        if e.kind == "name":
            hit = len(t) >= 7 and len(t.split()) >= 2 and re.search(rf"(?<!\w){re.escape(c)}(?!\w)", low) is not None
        elif e.kind == "phone":
            d = _digits(t)
            hit = len(d) == 10 and re.search(rf"(?<!\d){d}(?!\d)", squashed) is not None
        elif e.kind == "address":
            hit = len(c) >= 18 and c in low
        if hit:
            k = (e.kind, c)
            found.setdefault(k, Issue(
                code="leak", severity="warning", key=_key(doc_title, e.kind, c),
                message=f"{doc_title} contains the {e.kind} \"{t}\" ({e.source}), which is not part of this case. "
                        "It may be left over from another client's document."))
    return list(found.values())


_NAME = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,3}\b")


def check_name_drift(values: dict[str, str], texts: dict[str, str]) -> list[Issue]:
    """The same person spelled two ways: 'Anita Verma' in the case, 'Anitha Verma' in an attached note."""
    issues: list[Issue] = []
    for field_label, value in values.items():
        v = value.casefold()
        for where, text in texts.items():
            for m in _NAME.finditer(text):
                cand = m.group(0)
                c = cand.casefold()
                if c == v or set(v.split()) <= set(c.split()) or set(c.split()) <= set(v.split()):
                    continue  # a fuller or shorter form of the same name is not a misspelling
                if SequenceMatcher(None, v, c).ratio() >= 0.85:
                    issues.append(Issue(code="spelling", severity="warning", key=_key("spell", v, c),
                                        message=f"{field_label} is \"{value}\", but {where} says \"{cand}\". Check the spelling."))
    return issues


_WORDS = re.compile(r"(?:Rs\.?|₹|INR)\s*([\d,]+(?:\.\d{1,2})?)(?:/-)?\s*\(\s*(Rupees[^()]*?only)\s*\)", re.I)


def words_value(words: str) -> Decimal | None:
    w = re.sub(r"(?i)^\s*rupees\s*|\s*only\s*$", "", words)
    parts = re.split(r"(?i)\s+and\s+paise\s+", w, maxsplit=1)
    r = parse_number_words(parts[0])
    if r is None:
        return None
    total = Decimal(r[0])
    if len(parts) == 2:
        p = parse_number_words(parts[1])
        if p is None:
            return None
        total += Decimal(p[0]) / 100
    return total


def check_words_vs_numerals(doc_title: str, doc_text: str) -> list[Issue]:
    issues = []
    for m in _WORDS.finditer(doc_text):
        try:
            numeral = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            continue
        spoken = words_value(m.group(2))
        if spoken is None or spoken != numeral:
            issues.append(Issue(code="amount_mismatch", severity="error", key=_key(doc_title, m.group(0)),
                                message=f"{doc_title}: the figure \"{m.group(1)}\" and the words \"{m.group(2)}\" do not match."))
    return issues
