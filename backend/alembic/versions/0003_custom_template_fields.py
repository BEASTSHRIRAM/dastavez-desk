"""Custom templates carry the fields their placeholders need."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("template_versions")}
    if "field_specs" not in cols:
        op.add_column("template_versions", sa.Column("field_specs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("template_versions", "field_specs")
