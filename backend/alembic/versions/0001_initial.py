"""Initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tables are created via Base.metadata.create_all on startup for MVP.
    # This revision documents the schema baseline for Alembic history.
    pass


def downgrade() -> None:
    pass
