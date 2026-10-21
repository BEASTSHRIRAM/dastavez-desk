from app.config import Settings, normalize_db_url
from app.db_security import lock_down_postgres
from app.db import engine


def test_postgres_url_forms_are_normalised_for_psycopg3():
    assert normalize_db_url("postgres://u:p@host:5432/db").startswith("postgresql+psycopg://u:p@host")
    assert normalize_db_url("postgresql://u:p@localhost/db") == "postgresql+psycopg://u:p@localhost/db"  # no forced SSL locally
    assert normalize_db_url("sqlite:///x.db") == "sqlite:///x.db"


def test_supabase_urls_get_ssl_and_pooler_detection():
    direct = normalize_db_url("postgresql://postgres:pw@db.abcdef.supabase.co:5432/postgres")
    assert direct.endswith("?sslmode=require")
    assert normalize_db_url(direct) == direct  # idempotent, no duplicate parameter
    assert normalize_db_url("postgresql://u:p@x.supabase.com:5432/db?application_name=a").endswith("&sslmode=require")
    tx = Settings(database_url="postgresql://u:p@aws-0-ap.pooler.supabase.com:6543/postgres")
    session_mode = Settings(database_url="postgresql://u:p@aws-0-ap.pooler.supabase.com:5432/postgres")
    assert tx.is_pooled and not session_mode.is_pooled


def test_rls_lockdown_is_a_noop_on_sqlite():
    assert lock_down_postgres(engine) == 0
