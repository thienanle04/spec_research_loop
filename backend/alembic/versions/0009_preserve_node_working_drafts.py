"""preserve node-scoped Working Draft narratives

Revision ID: 0009_preserve_working_drafts
Revises: 0008_merge_research_spec_heads
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009_preserve_working_drafts"
down_revision: str | Sequence[str] | None = "0008_merge_research_spec_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "loop_sessions",
        sa.Column(
            "working_draft_narratives",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE loop_sessions
        SET working_draft_narratives = jsonb_build_object(
            working_draft_node,
            working_draft_narrative
        )
        """
    )


def downgrade() -> None:
    op.drop_column("loop_sessions", "working_draft_narratives")
