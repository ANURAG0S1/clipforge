"""job created_at

Revision ID: 38332dcc4a77
Revises: 3432d6953d68
Create Date: 2026-11-16 18:19:00.053240
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "38332dcc4a77"
down_revision: str | None = "3432d6953d68"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("jobs", "created_at")
