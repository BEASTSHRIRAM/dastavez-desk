"""Checkpointer factory: PostgreSQL in production, SQLite for zero-setup local runs.
The checkpointer stores resumable graph state; it never holds the business records."""
import sqlite3
from pathlib import Path

from app.config import get_settings

_saver = None


def get_checkpointer():
    global _saver
    if _saver is not None:
        return _saver
    s = get_settings()
    if s.is_sqlite:
        from langgraph.checkpoint.sqlite import SqliteSaver
        path = Path(s.storage_dir) / "checkpoints.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        _saver = SqliteSaver(sqlite3.connect(path, check_same_thread=False))
    else:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg.rows import dict_row
        url = s.db_url.replace("postgresql+psycopg://", "postgresql://")
        # prepare_threshold=None keeps this working behind Supabase's transaction pooler
        conn = psycopg.connect(url, autocommit=True, row_factory=dict_row, prepare_threshold=None)
        _saver = PostgresSaver(conn)
        _saver.setup()
        from app import db
        from app.db_security import lock_down_postgres
        lock_down_postgres(db.engine)  # the checkpoint tables are created here, so lock them too
    return _saver


def reset_checkpointer() -> None:
    """Tests and settings reloads only."""
    global _saver
    _saver = None
