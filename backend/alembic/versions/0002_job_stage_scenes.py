"""Ensure job_stage enum includes SCENES

Revision ID: 0002_job_stage_scenes
Revises: 0001_initial
Create Date: 2026-09-04
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002_job_stage_scenes"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # create_all does not ALTER existing Postgres enums; add SCENES if missing.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'job_stage'
            ) AND NOT EXISTS (
                SELECT 1
                FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'job_stage' AND e.enumlabel = 'SCENES'
            ) THEN
                ALTER TYPE job_stage ADD VALUE 'SCENES';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Postgres cannot easily remove enum values; leave SCENES in place.
    pass
