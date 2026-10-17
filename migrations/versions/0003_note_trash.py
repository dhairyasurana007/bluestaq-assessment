"""note trash: notes.deleted_at

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable with no default: every existing note stays active (deleted_at NULL).
    op.add_column("notes", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("ix_notes_team_deleted", "notes", ["team_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_notes_team_deleted", table_name="notes")
    op.drop_column("notes", "deleted_at")
