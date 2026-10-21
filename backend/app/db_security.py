"""Supabase exposes every table in the `public` schema through its REST API to the `anon` and
`authenticated` roles unless row-level security is on. This backend is the only intended client
(it connects as a privileged role, which bypasses RLS), so every table is locked: RLS enabled with no
policies, and the API roles stripped of grants. Idempotent; a no-op outside PostgreSQL."""
from sqlalchemy import text
from sqlalchemy.engine import Engine


def lock_down_postgres(engine: Engine) -> int:
    """Returns the number of tables newly locked. Already-locked tables are skipped, so a steady-state
    call takes no table locks at all."""
    if engine.dialect.name != "postgresql":
        return 0
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '15s'"))  # fail loudly instead of waiting forever
        tables = conn.execute(text(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relrowsecurity")).scalars().all()
        for name in tables:
            quoted = '"' + name.replace('"', '""') + '"'  # names come from the catalog, quoted defensively anyway
            conn.execute(text(f"ALTER TABLE public.{quoted} ENABLE ROW LEVEL SECURITY"))
        conn.execute(text("""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
              END IF;
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL ON ALL TABLES IN SCHEMA public FROM authenticated;
              END IF;
            END $$;
        """))
    return len(tables)
