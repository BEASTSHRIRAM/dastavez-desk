"""Auth, workspaces, templates, saved parties, consent and capabilities."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api import deps
from app.config import get_settings
from app.repositories import catalog as cat
from app.repositories.cases import NotFound
from app.services import rendering
from app.services.auth import Principal, issue_token, verify_password
from app.verticals import WORKSPACES

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    email: str
    password: str


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/auth/login")
def login(body: LoginIn, session: Session = Depends(deps.get_session)):
    user = cat.user_by_email(session, body.email.strip().lower())
    # Same message for unknown email and wrong password, so accounts cannot be enumerated.
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    tenant = cat.get_tenant(session, user.tenant_id)
    token = issue_token(Principal(user.id, user.tenant_id, user.role))
    return {"token": token, "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
            "business": {"id": tenant.id, "name": tenant.name, "ai_consent": tenant.ai_consent}}


@router.get("/me")
def me(p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    user = cat.user_by_id(session, p.user_id, p.tenant_id)
    if not user:
        raise HTTPException(401, "Sign in again.")
    tenant = cat.get_tenant(session, p.tenant_id)
    return {"user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
            "business": {"id": tenant.id, "name": tenant.name, "ai_consent": tenant.ai_consent}}


@router.get("/capabilities")
def capabilities(p: Principal = Depends(deps.principal), session: Session = Depends(deps.get_session)):
    s = get_settings()
    tenant = cat.get_tenant(session, p.tenant_id)
    return {"demo_mode": s.llm_provider == "demo", "llm_provider": s.llm_provider, "stt_provider": s.stt_provider,
            "server_transcription": s.stt_provider != "demo" and bool(s.stt_api_key),
            "pdf_available": rendering.pdf_available(), "ai_consent": tenant.ai_consent}


class ConsentIn(BaseModel):
    ai_consent: bool


@router.put("/tenant/consent")
def set_consent(body: ConsentIn, p: Principal = Depends(deps.require("owner")), session: Session = Depends(deps.get_session)):
    tenant = cat.get_tenant(session, p.tenant_id)
    tenant.ai_consent = body.ai_consent
    session.commit()
    deps.TenantRepo(session, p.tenant_id).audit("ai_consent_changed", None, p.user_id, ai_consent=body.ai_consent)
    return {"ai_consent": tenant.ai_consent}


@router.get("/workspaces")
def list_workspaces(_: Principal = Depends(deps.principal)):
    return [{"id": w.id, "name": w.name, "tagline": w.tagline, "description": w.description, "material": w.material,
             "example_prompt": w.example_prompt, "disclaimers": w.disclaimers, "other_workflows": w.other_workflows,
             "documents": [{"key": d.key, "title": d.title, "formats": d.formats, "primary": d.primary} for d in w.documents],
             "fields": [{"id": f.id, "label": f.label, "type": f.type.value, "required": f.required} for f in w.fields]}
            for w in WORKSPACES.values()]


def _template_out(t):
    return {"id": t.id, "key": t.template_key, "version": t.version, "workspace": t.workspace, "title": t.title,
            "is_demo": t.is_demo, "approved": t.approved, "jurisdiction": t.jurisdiction,
            "verify_fields": t.verify_fields, "note": t.source_note, "last_verified": t.last_verified,
            "owned_by_business": t.tenant_id is not None}


@router.get("/templates")
def list_templates(workspace: str | None = None, repo: cat.TemplateRepo = Depends(deps.templates)):
    return [_template_out(t) for t in repo.list(workspace)]


@router.get("/templates/{template_id}")
def get_template(template_id: str, repo: cat.TemplateRepo = Depends(deps.templates)):
    try:
        return _template_out(repo.get(template_id))
    except NotFound:
        raise HTTPException(404, "Template not found.") from None


class PartyIn(BaseModel):
    kind: str = Field(pattern="^(landlord|tenant|applicant|supplier|client)$")
    full_name: str = Field(min_length=2, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)


def _party_out(p):
    return {"id": p.id, "kind": p.kind, "full_name": p.full_name, "address": p.address, "phone": p.phone,
            "verified": p.verified}


@router.get("/parties")
def list_parties(kind: str | None = None, repo: cat.PartyRepo = Depends(deps.parties)):
    return [_party_out(p) for p in repo.list(kind)]


@router.post("/parties", status_code=201)
def create_party(body: PartyIn, p: Principal = Depends(deps.require("operator")), repo: cat.PartyRepo = Depends(deps.parties),
                 session: Session = Depends(deps.get_session)):
    party = repo.create(kind=body.kind, full_name=body.full_name.strip(), address=body.address, phone=body.phone)
    deps.TenantRepo(session, p.tenant_id).audit("party_created", None, p.user_id, party_id=party.id)
    return _party_out(party)


@router.delete("/parties/{party_id}", status_code=204)
def delete_party(party_id: str, p: Principal = Depends(deps.require("owner")), repo: cat.PartyRepo = Depends(deps.parties),
                 session: Session = Depends(deps.get_session)):
    try:
        repo.soft_delete(repo.get(party_id))
    except NotFound:
        raise HTTPException(404, "Saved record not found.") from None
    deps.TenantRepo(session, p.tenant_id).audit("party_deleted", None, p.user_id, party_id=party_id)
