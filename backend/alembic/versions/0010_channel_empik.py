"""channel virtualo -> empik (Empik Selfpublishing covers Empik, Empik Go and Virtualo)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-11 18:00:00
"""
from alembic import op

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

TABLES = ("listings", "royalty_imports", "royalty_lines")


def upgrade() -> None:
    for t in TABLES:
        op.execute(f"UPDATE {t} SET channel = 'empik' WHERE channel = 'virtualo'")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"UPDATE {t} SET channel = 'virtualo' WHERE channel = 'empik'")
