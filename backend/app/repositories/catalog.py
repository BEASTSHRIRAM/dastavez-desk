"""Tenants, users, saved parties and templates."""
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.orm import Party, TemplateVersion, Tenant, User
from app.repositories.cases import NotFound


def user_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(User.email == email.lower()))


def user_by_id(session: Session, user_id: str, tenant_id: str) -> User | None:
    return session.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))


def get_tenant(session: Session, tenant_id: str) -> Tenant:
    tenant = session.get(Tenant, tenant_id)
    if not tenant:
        raise NotFound("Business not found")
    return tenant


class PartyRepo:
    def __init__(self, session: Session, tenant_id: str):
        self.s, self.tenant_id = session, tenant_id

    def list(self, kind: str | None = None) -> list[Party]:
        q = select(Party).where(Party.tenant_id == self.tenant_id, Party.deleted_at.is_(None))
        if kind:
            q = q.where(Party.kind == kind)
        return list(self.s.scalars(q.order_by(Party.full_name)))

    def get(self, party_id: str) -> Party:
        party = self.s.scalar(select(Party).where(Party.id == party_id, Party.tenant_id == self.tenant_id,
                                                  Party.deleted_at.is_(None)))
        if not party:
            raise NotFound("Saved record not found")
        return party

    def create(self, **kw) -> Party:
        party = Party(tenant_id=self.tenant_id, **kw)
        self.s.add(party)
        self.s.commit()
        return party

    def soft_delete(self, party: Party) -> None:
        party.deleted_at = datetime.now(timezone.utc)
        self.s.commit()


class TemplateRepo:
    """Built-in demonstration templates (tenant_id NULL) plus any the tenant owns."""

    def __init__(self, session: Session, tenant_id: str):
        self.s, self.tenant_id = session, tenant_id

    def _visible(self):
        return or_(TemplateVersion.tenant_id.is_(None), TemplateVersion.tenant_id == self.tenant_id)

    def list(self, workspace: str | None = None) -> list[TemplateVersion]:
        q = select(TemplateVersion).where(self._visible())
        if workspace:
            q = q.where(TemplateVersion.workspace == workspace)
        return list(self.s.scalars(q.order_by(TemplateVersion.template_key, TemplateVersion.version)))

    def get(self, template_id: str) -> TemplateVersion:
        tv = self.s.scalar(select(TemplateVersion).where(TemplateVersion.id == template_id, self._visible()))
        if not tv:
            raise NotFound("Template not found")
        return tv

    def latest_approved(self, template_key: str) -> list[TemplateVersion]:
        """All approved versions of a key, highest version first. Tenant-owned versions rank above built-ins
        at the same version."""
        rows = self.s.scalars(select(TemplateVersion).where(
            self._visible(), TemplateVersion.template_key == template_key, TemplateVersion.approved.is_(True)))
        def vkey(t: TemplateVersion):
            return tuple(int(p) if p.isdigit() else 0 for p in t.version.split(".")), t.tenant_id is not None
        return sorted(rows, key=vkey, reverse=True)
