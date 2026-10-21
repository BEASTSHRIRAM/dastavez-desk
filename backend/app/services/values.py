"""Typed values: coercion and server-side validation per field type, JSON (de)serialisation,
conditional visibility and display formatting. Every value that reaches persisted business data,
whether typed by a person or proposed by a model, passes through coerce()."""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.fields import FieldSpec, FieldType
from app.services.parsing import format_date_long, format_inr, parse_date


class ValueError_(ValueError):
    """Raised with a message that is safe to show to the operator."""


def is_present(value: Any) -> bool:
    """Missing is None or blank text. Zero, 0.00 and False are real answers."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def coerce(spec: FieldSpec, raw: Any) -> Any:
    """Return a typed value or raise ValueError_. None/blank means 'not provided'."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    t = spec.type
    if t in (FieldType.TEXT, FieldType.LONGTEXT, FieldType.PERSON, FieldType.ADDRESS):
        text = re.sub(r"[ \t]+", " ", str(raw)).strip()
        if len(text) > (5000 if t == FieldType.LONGTEXT else 500):
            raise ValueError_(f"{spec.label} is too long.")
        if spec.pattern and not re.fullmatch(spec.pattern, text):
            raise ValueError_(f"{spec.label} is not in the expected format.")
        return text
    if t == FieldType.PHONE:
        digits = re.sub(r"[\s-]", "", str(raw))
        if spec.pattern and not re.fullmatch(spec.pattern, digits):
            raise ValueError_(f"{spec.label} must be 10 digits.")
        return digits
    if t in (FieldType.CURRENCY, FieldType.NUMBER):
        if isinstance(raw, float):
            raw = str(raw)
        try:
            num = Decimal(str(raw).replace(",", "").strip())
        except InvalidOperation:
            raise ValueError_(f"{spec.label} must be a number.") from None
        if not num.is_finite():
            raise ValueError_(f"{spec.label} must be a number.")
        if spec.min is not None and num < Decimal(str(spec.min)):
            raise ValueError_(f"{spec.label} must be at least {spec.min:g}.")
        if spec.max is not None and num > Decimal(str(spec.max)):
            raise ValueError_(f"{spec.label} must be at most {spec.max:g}.")
        if t == FieldType.CURRENCY:
            return num.quantize(Decimal("0.01"))
        return int(num) if num == num.to_integral_value() else num
    if t == FieldType.DATE:
        if isinstance(raw, date):
            return raw
        found = parse_date(str(raw), date.today(), spec.date_bias)
        if not found:
            raise ValueError_(f"{spec.label} is not a valid date. Use YYYY-MM-DD.")
        return found[0]
    if t == FieldType.YESNO:
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("yes", "y", "true", "1"):
            return True
        if s in ("no", "n", "false", "0"):
            return False
        raise ValueError_(f"{spec.label} must be yes or no.")
    if t == FieldType.SELECT:
        s = str(raw).strip()
        if spec.options and s not in spec.options:
            raise ValueError_(f"{spec.label} must be one of the listed options.")
        return s
    if t == FieldType.MULTISELECT:
        items = raw if isinstance(raw, list) else [raw]
        bad = [i for i in items if spec.options and i not in spec.options]
        if bad:
            raise ValueError_(f"{spec.label} contains an option that is not allowed.")
        return [str(i) for i in items]
    if t == FieldType.PARTY:
        s = str(raw).strip()
        if not re.fullmatch(r"[0-9a-f]{32}", s):
            raise ValueError_(f"{spec.label} must reference a saved record.")
        return s
    raise ValueError_(f"Unsupported field type for {spec.label}.")


def to_json(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def from_json(spec: FieldSpec, raw: Any) -> Any:
    if raw is None:
        return None
    if spec.type == FieldType.DATE and isinstance(raw, str):
        return date.fromisoformat(raw)
    if spec.type == FieldType.CURRENCY:
        return Decimal(str(raw))
    return raw


def is_active(spec: FieldSpec, values: dict[str, Any]) -> bool:
    """Evaluate a field's `when` predicate against the current values."""
    cond = spec.when
    if not cond:
        return True
    current = values.get(cond["field"])
    if "equals" in cond:
        return current == cond["equals"]
    if "in" in cond:
        return current in cond["in"]
    if "not_in" in cond:
        return is_present(current) and current not in cond["not_in"]
    if "present" in cond:
        return is_present(current) == cond["present"]
    return True


def display(spec: FieldSpec, value: Any) -> str:
    """Human-readable text for documents and previews."""
    if not is_present(value):
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, date):
        return format_date_long(value)
    if isinstance(value, Decimal) and spec.type == FieldType.CURRENCY:
        return f"Rs. {format_inr(value)}"
    if isinstance(value, list):
        return ", ".join(map(str, value))
    return str(value)
