"""Validate and persist human answers. Used twice on purpose: the API rejects bad input with
per-field errors, and the graph re-validates before writing (a resume payload is not trusted)."""
from typing import Any

from app.models.fields import FieldType
from app.models.orm import Fact
from app.repositories.catalog import PartyRepo
from app.repositories.cases import NotFound, TenantRepo
from app.services.case_state import Evaluation
from app.services.values import ValueError_, coerce, to_json
from app.verticals.base import WorkspaceConfig


def validate_answers(config: WorkspaceConfig, parties: PartyRepo, answers: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (typed values, errors by field id). Unknown fields and blanks are ignored or rejected."""
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    known = {f.id: f for f in config.fields}
    for fid, raw in answers.items():
        spec = known.get(fid)
        if spec is None:
            errors[fid] = "This field does not exist for this workspace."
            continue
        try:
            value = coerce(spec, raw)
        except ValueError_ as exc:
            errors[fid] = str(exc)
            continue
        if value is None:
            continue
        if spec.type == FieldType.PARTY:
            try:
                parties.get(value)  # must belong to this tenant, or it is simply 'not found'
            except NotFound:
                errors[fid] = "That saved record is not available."
                continue
            if spec.party_kind and parties.get(value).kind != spec.party_kind:
                errors[fid] = "That saved record is the wrong kind."
                continue
        clean[fid] = value
    return clean, errors


def apply_answers(repo: TenantRepo, case_id: str, user_id: str, clean: dict[str, Any]) -> list[Fact]:
    """Human-entered values are 'confirmed' facts. They beat anything extracted."""
    return [repo.add_fact(case_id, fid, to_json(v), "confirmed", {"origin": "operator", "by": user_id}, 1.0)
            for fid, v in clean.items()]


def confirm_current(repo: TenantRepo, case_id: str, user_id: str, ev: Evaluation, field_ids: list[str]) -> list[str]:
    """Mark the currently displayed value of each listed field as confirmed. Returns ids actually confirmed."""
    done = []
    for fid in field_ids:
        r = ev.resolved.get(fid)
        if r is None or r.value is None or r.conflict:
            continue
        prov = {**r.provenance, "confirmed_by": user_id, "origin": r.provenance.get("origin", "operator")}
        repo.add_fact(case_id, fid, to_json(r.value), "confirmed", prov, 1.0)
        done.append(fid)
    return done
