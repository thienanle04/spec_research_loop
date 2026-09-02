"""optional JSONB detail on loop decisions

Revision ID: 0014_decision_detail
Revises: 0013_merge_idea_research_heads
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014_decision_detail"
down_revision: str | Sequence[str] | None = "0013_merge_idea_research_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "loop_decisions",
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("loop_decisions", "detail")
