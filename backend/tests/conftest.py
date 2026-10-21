"""Test environment: a throwaway SQLite database and storage directory, set before the app imports."""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="dastavez-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["LLM_PROVIDER"] = "demo"
os.environ["STT_PROVIDER"] = "demo"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["SEED_DEMO"] = "true"

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import db, seed  # noqa: E402
from app.agents import runner  # noqa: E402
from app.agents.checkpoint import reset_checkpointer  # noqa: E402
from app.models import orm  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts from a freshly seeded database and a fresh graph."""
    db.Base.metadata.drop_all(db.engine)
    seed.bootstrap()
    reset_checkpointer()
    runner.reset_graph()
    yield


@pytest.fixture
def session():
    with Session(db.engine) as s:
        yield s


@pytest.fixture
def ids(session):
    """Handy ids for the two seeded businesses."""
    a = session.scalar(select(orm.Tenant).where(orm.Tenant.name.like("Kapoor%")))
    b = session.scalar(select(orm.Tenant).where(orm.Tenant.name.like("Lakeside%")))
    op = session.scalar(select(orm.User).where(orm.User.email == "operator@demo.test"))
    other = session.scalar(select(orm.User).where(orm.User.email == "other@demo.test"))
    return {"tenant_a": a.id, "tenant_b": b.id, "op": op.id, "other": other.id}
