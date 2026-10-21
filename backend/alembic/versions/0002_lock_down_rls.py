"""Enable row-level security on every table (matters on Supabase, a no-op elsewhere)."""
from alembic import op

from app.db_security import lock_down_postgres

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    lock_down_postgres(op.get_bind().engine)


def downgrade() -> None:
    pass  # leaving RLS on is the safe state
