"""add generated_since_prepare on Node Head

Revision ID: 0010_generated_since_prepare
Revises: 0009_preserve_working_drafts
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_generated_since_prepare"
down_revision: str | Sequence[str] | None = "0009_preserve_working_drafts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "loop_node_heads",
        sa.Column(
            "generated_since_prepare",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("loop_node_heads", "generated_since_prepare")
