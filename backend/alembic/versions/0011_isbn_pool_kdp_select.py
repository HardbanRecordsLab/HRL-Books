"""ISBN pool + KDP Select flag on titles

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-18 12:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "isbn_pool",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("isbn", sa.String(13), nullable=False),
        sa.Column("note", sa.String(200), nullable=False, server_default=""),
        sa.Column("edition_id", sa.String(36), sa.ForeignKey("editions.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "isbn"),
    )
    op.add_column("books", sa.Column("kdp_select", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("books", "kdp_select")
    op.drop_table("isbn_pool")
