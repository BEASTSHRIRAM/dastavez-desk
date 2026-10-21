"""Deterministic parsing of spoken numbers, money and dates. Money is always Decimal."""
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}
SCALES = {"thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "million": 1_000_000, "crore": 10_000_000}
NUMBER_WORDS = set(UNITS) | set(TENS) | set(SCALES) | {"hundred", "and"}

ORDINALS = {w: i + 1 for i, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth "
    "fifteenth sixteenth seventeenth eighteenth nineteenth twentieth".split())}
ORDINALS.update({"twenty-first": 21, "twenty first": 21, "twenty-second": 22, "twenty second": 22,
                 "twenty-third": 23, "twenty third": 23, "twenty-fourth": 24, "twenty fourth": 24,
                 "twenty-fifth": 25, "twenty fifth": 25, "twenty-sixth": 26, "twenty sixth": 26,
                 "twenty-seventh": 27, "twenty seventh": 27, "twenty-eighth": 28, "twenty eighth": 28,
                 "twenty-ninth": 29, "twenty ninth": 29, "thirtieth": 30, "thirty-first": 31, "thirty first": 31})

MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))


def words_to_int(tokens: list[str]) -> int | None:
    total = current = 0
    seen = False
    for t in tokens:
        if t == "and":
            continue
        if t in UNITS:
            current += UNITS[t]
        elif t in TENS:
            current += TENS[t]
        elif t == "hundred":
            current = (current or 1) * 100
        elif t in SCALES:
            total += (current or 1) * SCALES[t]
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


def parse_number_words(text: str) -> tuple[int, int] | None:
    """Find the first run of number words in text. Returns (value, end_index) or None.
    Hyphens count as word breaks, so "forty-two" reads as "forty two"."""
    tokens = [(m.group(0).lower(), m.start(), m.end()) for m in re.finditer(r"[A-Za-z]+", text)]
    i = 0
    while i < len(tokens):
        if tokens[i][0] in NUMBER_WORDS and tokens[i][0] != "and":
            j = i
            while j + 1 < len(tokens) and tokens[j + 1][0] in NUMBER_WORDS and tokens[j + 1][1] - tokens[j][2] <= 2:
                j += 1
            run = [t[0] for t in tokens[i:j + 1]]
            while run and run[-1] == "and":
                run.pop()
            value = words_to_int(run)
            if value is not None:
                return value, tokens[i + len(run) - 1][2]
        i += 1
    return None


_AMOUNT_DIGITS = re.compile(r"(?:₹|rs\.?|inr)?\s*(\d[\d,]*(?:\.\d{1,2})?)\s*(k|thousand|lakh|lakhs|crore)?\b", re.I)


def parse_amount(text: str) -> tuple[Decimal, int] | None:
    """Parse the first money amount in text (digits or words). Returns (Decimal, end_index)."""
    m = _AMOUNT_DIGITS.search(text)
    w = parse_number_words(text)
    if m and (not w or m.start() <= w[1]):
        try:
            value = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            return None
        mult = {"k": 1_000, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "crore": 10_000_000}.get(
            (m.group(2) or "").lower(), 1)
        return value * mult, m.end()
    if w:
        return Decimal(w[0]), w[1]
    return None


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def format_inr(value: Decimal | int | float | str) -> str:
    """Indian digit grouping, e.g. 1234567.5 -> 12,34,567.50."""
    d = quantize_money(Decimal(str(value)))
    whole, frac = f"{abs(d):.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    if head:
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        whole = f"{head},{tail}"
    return f"{'-' if d < 0 else ''}{whole}.{frac}"


def _next_occurrence(month: int, day: int, today: date, bias: str) -> date | None:
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if bias == "future" and cand >= today:
            return cand
        if bias == "past" and today - timedelta(days=366) < cand <= today:
            return cand
    return None


def parse_date(text: str, today: date, bias: str = "future") -> tuple[date, bool, int] | None:
    """Parse the first date in text. Returns (date, ambiguous, end_index).
    `ambiguous` is True when the day/month order or the year had to be assumed."""
    low = text.lower()
    iso = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
    if iso:
        try:
            return date(int(iso[1]), int(iso[2]), int(iso[3])), False, iso.end()
        except ValueError:
            return None
    ord_words = "|".join(sorted(ORDINALS, key=len, reverse=True))
    found = {
        "rel": re.search(r"\b(today|tomorrow|yesterday|day before yesterday)\b", low),
        "dm": re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*(?:of\s+)?({MONTH_RE})\b(?:,?\s*(\d{{4}}))?", low),
        "md": re.search(rf"\b({MONTH_RE})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s*(\d{{4}}))?", low),
        "ow": re.search(rf"\b({ord_words})\s+(?:of\s+)?({MONTH_RE})\b(?:,?\s*(\d{{4}}))?", low),
        "slash": re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", low),
    }
    candidates = [(m.start(), kind, m) for kind, m in found.items() if m]
    if not candidates:
        return None
    _, kind, m = min(candidates, key=lambda c: c[0])
    try:
        if kind == "rel":
            offs = {"today": 0, "tomorrow": 1, "yesterday": -1, "day before yesterday": -2}[m.group(1)]
            return today + timedelta(days=offs), False, m.end()
        if kind == "slash":
            # Locale is India (DD/MM/YYYY). Flag when the order could be read the other way.
            d1, d2 = int(m[1]), int(m[2])
            return date(int(m[3]), d2, d1), d1 <= 12 and d2 <= 12 and d1 != d2, m.end()
        if kind == "dm":
            day, month, year = int(m[1]), MONTHS[m[2]], m[3]
        elif kind == "md":
            day, month, year = int(m[2]), MONTHS[m[1]], m[3]
        else:
            day, month, year = ORDINALS[m[1]], MONTHS[m[2]], m[3]
        if year:
            return date(int(year), month, day), False, m.end()
        guess = _next_occurrence(month, day, today, bias)
        return (guess, True, m.end()) if guess else None
    except (ValueError, KeyError):
        return None


def format_date_long(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
         "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _words_below_thousand(n: int) -> list[str]:
    out: list[str] = []
    if n >= 100:
        out += [_ONES[n // 100], "Hundred"]
        n %= 100
        if n:
            out.append("and")
    if n >= 20:
        out.append(_TENS[n // 10] + (f" {_ONES[n % 10]}" if n % 10 else ""))
    elif n:
        out.append(_ONES[n])
    return out


def int_to_words(n: int) -> str:
    """Indian numbering: 1,25,000 is 'One Lakh Twenty Five Thousand'."""
    if n == 0:
        return "Zero"
    parts: list[str] = []
    for value, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1_000, "Thousand")):
        if n >= value:
            parts += [*_words_below_thousand(n // value), name]
            n %= value
    parts += _words_below_thousand(n)
    return " ".join(parts)


def amount_in_words(value: Decimal) -> str:
    """'Rupees Eighteen Thousand only'. Deterministic, so a document never carries a number and a different spelling."""
    d = quantize_money(Decimal(value))
    rupees, paise = int(d), int((d - int(d)) * 100)
    text = f"Rupees {int_to_words(rupees)}"
    if paise:
        text += f" and Paise {int_to_words(paise)}"
    return text + " only"
