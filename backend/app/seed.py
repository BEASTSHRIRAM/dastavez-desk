"""Idempotent bootstrap: tables, template registry and fictional demonstration data.
All people, addresses and numbers below are invented."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Base, engine
from app.db_security import lock_down_postgres
from app.models import orm
from app.services.auth import hash_password
from app.templates.builder import TEMPLATES, ensure_templates, template_file

DEMO_PASSWORD = "demo-pass"
VERIFY = {"declaration_address": ["identity_verified", "facts_checked_with_client"],
          "declaration_name": ["identity_verified", "facts_checked_with_client"],
          "declaration_general": ["identity_verified", "facts_checked_with_client"]}


def seed_templates(session: Session) -> None:
    for key, spec in TEMPLATES.items():
        for version in spec["versions"]:
            exists = session.scalar(select(orm.TemplateVersion).where(
                orm.TemplateVersion.template_key == key, orm.TemplateVersion.version == version,
                orm.TemplateVersion.tenant_id.is_(None)))
            if exists:
                continue
            superseded = key == "declaration_address" and version == "1.0"
            session.add(orm.TemplateVersion(
                tenant_id=None, template_key=key, version=version, workspace=spec["workspace"], title=spec["title"],
                file_name=template_file(key, version).name, is_demo=True, approved=not superseded,
                jurisdiction=spec.get("jurisdiction"), verify_fields=VERIFY.get(key, []),
                source_note=("Superseded by v1.1. Kept for the audit trail." if superseded
                             else "Bundled demonstration template. Replace with your own approved wording."),
                last_verified=None))
    session.commit()


def _tenant(session: Session, name: str) -> orm.Tenant:
    t = session.scalar(select(orm.Tenant).where(orm.Tenant.name == name))
    if not t:
        t = orm.Tenant(name=name)
        session.add(t)
        session.commit()
    return t


def _user(session: Session, tenant: orm.Tenant, email: str, name: str, role: str) -> None:
    if not session.scalar(select(orm.User).where(orm.User.email == email)):
        session.add(orm.User(tenant_id=tenant.id, email=email, name=name, role=role,
                             password_hash=hash_password(DEMO_PASSWORD)))
        session.commit()


def _party(session: Session, tenant: orm.Tenant, **kw) -> None:
    if not session.scalar(select(orm.Party).where(orm.Party.tenant_id == tenant.id, orm.Party.full_name == kw["full_name"])):
        session.add(orm.Party(tenant_id=tenant.id, **kw))
        session.commit()


def seed_demo(session: Session) -> None:
    a = _tenant(session, "Kapoor & Associates (demo)")
    b = _tenant(session, "Lakeside Services (demo)")
    _user(session, a, "owner@demo.test", "Demo Owner", "owner")
    _user(session, a, "operator@demo.test", "Demo Operator", "operator")
    _user(session, a, "viewer@demo.test", "Demo Viewer", "viewer")
    _user(session, b, "other@demo.test", "Other Business Owner", "owner")
    _party(session, a, kind="landlord", full_name="Meera Kapoor", verified=True, phone="9000000001",
           address="Flat 12, Sunrise Apartments, Baner Road, Pune 411045")
    _party(session, a, kind="landlord", full_name="Arjun Desai", verified=True, phone="9000000002",
           address="7 Orchard Lane, Kothrud, Pune 411038")
    _party(session, a, kind="supplier", full_name="Sharma Office Supplies", phone="9000000003",
           address="Shop 4, Market Yard, Pune")
    _party(session, b, kind="landlord", full_name="Private Landlord of Lakeside", verified=True,
           address="1 Hidden Road, Nashik")


def ensure_columns() -> None:
    """create_all never alters existing tables. Add columns introduced after a database was first created
    (idempotent), so an existing Supabase database keeps working without a manual migration."""
    from sqlalchemy import inspect, text
    wanted = {"template_versions": [("field_specs", "JSON")]}
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def bootstrap() -> None:
    ensure_templates()
    Base.metadata.create_all(engine)
    ensure_columns()
    with Session(engine) as session:
        seed_templates(session)
        if get_settings().seed_demo:
            seed_demo(session)
    if not engine.dialect.name.startswith("sqlite"):
        _prepare_postgres_checkpoints()
    lock_down_postgres(engine)


def _prepare_postgres_checkpoints() -> None:
    """Create the LangGraph checkpoint tables once, at startup, before any request holds a transaction
    (its setup builds indexes CONCURRENTLY, which waits for every open transaction). A cancelled earlier
    attempt can leave an INVALID index behind; drop those so setup rebuilds them."""
    from sqlalchemy import text
    from app.agents.checkpoint import get_checkpointer
    with engine.begin() as conn:
        bad = conn.execute(text("select c.relname from pg_index i join pg_class c on c.oid = i.indexrelid "
                                "where not i.indisvalid and c.relname like 'checkpoint%'")).scalars().all()
        for name in bad:
            conn.execute(text('DROP INDEX IF EXISTS public."' + name.replace('"', '""') + '"'))
    get_checkpointer()


if __name__ == "__main__":
    bootstrap()
    print("Seeded. Demo logins: owner@demo.test / operator@demo.test / viewer@demo.test, password:", DEMO_PASSWORD)
