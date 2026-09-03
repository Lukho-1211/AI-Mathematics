"""Add term and week to projects

Revision ID: 0002_add_term_week
Revises: 0001_initial
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_add_term_week"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("term", sa.Integer(), nullable=True))
    op.add_column("projects", sa.Column("week", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "week")
    op.drop_column("projects", "term")
