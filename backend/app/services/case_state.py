"""Resolve stored facts into the values a document is built from, and evaluate them.

Precedence: a human-confirmed value always beats source/suggested ones, so an AI interpretation
can never silently overwrite verified data. Two different unconfirmed values for one field are a
conflict that pauses the workflow until a person picks one."""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.models.fields import FieldSpec, FieldType, Issue
from app.models.orm import Fact
from app.services.values import from_json, is_active, is_present, to_json
from app.verticals.base import WorkspaceConfig

STATUS_RANK = {"confirmed": 2, "source": 1, "suggested": 0}


@dataclass
class Resolved:
    field_id: str
    value: Any = None
    status: str = "none"  # confirmed | source | suggested | default | none
    fact_id: str | None = None
    confidence: float | None = None
    provenance: dict = field(default_factory=dict)
    conflict: list[dict] | None = None


@dataclass
class Evaluation:
    resolved: dict[str, Resolved]
    values: dict[str, Any]  # typed values of active fields
    computed: dict[str, Any]
    active: list[FieldSpec]
    missing: list[FieldSpec]
    conflicts: list[Resolved]
    unconfirmed: list[FieldSpec]  # high-impact values nobody has confirmed yet
    issues: list[Issue]

    @property
    def blocking(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]


def resolve(config: WorkspaceConfig, facts: list[Fact]) -> dict[str, Resolved]:
    by_field: dict[str, list[Fact]] = {}
    for f in facts:
        by_field.setdefault(f.field_id, []).append(f)
    out: dict[str, Resolved] = {}
    for spec in config.fields:
        rows = by_field.get(spec.id, [])
        confirmed = [f for f in rows if f.status == "confirmed"]
        if confirmed:
            f = confirmed[-1]
            raw = f.value.get("v")
            out[spec.id] = Resolved(spec.id, from_json(spec, raw), "confirmed" if raw is not None else "none",
                                    f.id, f.confidence, f.provenance)
            continue
        rows = [f for f in rows if f.status in ("source", "suggested")]
        if not rows:
            out[spec.id] = Resolved(spec.id)
            continue
        distinct: dict[str, Fact] = {}
        for f in rows:
            distinct[json.dumps(f.value.get("v"), sort_keys=True, default=str)] = f  # latest per distinct value
        if len(distinct) > 1 and spec.type != FieldType.PARTY:
            options = [{"value": f.value.get("v"), "origin": f.provenance.get("origin"), "quote": f.provenance.get("quote")}
                       for f in distinct.values()]
            out[spec.id] = Resolved(spec.id, None, "none", conflict=options)
            continue
        best = max(rows, key=lambda f: (STATUS_RANK[f.status], f.created_at))
        out[spec.id] = Resolved(spec.id, from_json(spec, best.value.get("v")), best.status, best.id,
                                best.confidence, best.provenance)
    return out


def evaluate(config: WorkspaceConfig, facts: list[Fact]) -> Evaluation:
    resolved = resolve(config, facts)
    values: dict[str, Any] = {}
    active: list[FieldSpec] = []
    for spec in config.fields:  # order matters: `when` refers to earlier fields
        if not is_active(spec, values):
            continue
        active.append(spec)
        r = resolved[spec.id]
        if is_present(r.value):
            values[spec.id] = r.value
        elif spec.default is not None and not r.conflict:
            values[spec.id] = spec.default
            resolved[spec.id] = Resolved(spec.id, spec.default, "default", provenance={"origin": spec.default_source})

    issues: list[Issue] = []
    missing = [s for s in active if s.required and not is_present(values.get(s.id)) and not resolved[s.id].conflict]
    conflicts = [resolved[s.id] for s in active if resolved[s.id].conflict]
    for s in missing:
        issues.append(Issue(field_id=s.id, code="missing", message=f"{s.label} is required."))
    for c in conflicts:
        issues.append(Issue(field_id=c.field_id, code="conflict",
                            message=f"{config.field(c.field_id).label}: two different values were found. Choose one."))
    for fid in config.verify_fields:
        if fid in values and values[fid] is not True:
            issues.append(Issue(field_id=fid, code="unverified", message=f"{config.field(fid).label}: must be confirmed as yes."))

    computed = config.compute({**values}) if config.compute else {}
    if config.check:
        issues += config.check({**values, **computed})

    unconfirmed = [s for s in active if s.high_impact and is_present(values.get(s.id))
                   and resolved[s.id].status in ("suggested", "source")]
    return Evaluation(resolved, values, computed, active, missing, conflicts, unconfirmed, issues)


def values_hash(ev: Evaluation, template_ids: dict[str, str]) -> str:
    """Approval binds to exactly what was reviewed: active values, computed values and template versions."""
    payload = {
        "values": {k: to_json(v) for k, v in sorted(ev.values.items())},
        "computed": {k: to_json(v) if not isinstance(v, (list, dict)) else json.loads(json.dumps(v, default=str))
                     for k, v in sorted(ev.computed.items())},
        "templates": dict(sorted(template_ids.items())),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
