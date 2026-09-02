"""add Judge Issue Grounds JSONB

Revision ID: 0016_judge_issue_grounds
Revises: 0015_export_scratch
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_judge_issue_grounds"
down_revision: str | Sequence[str] | None = "0015_export_scratch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMPTY = sa.text("'{\"subject\": \"\", \"excerpts\": []}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "judgement_issues",
        sa.Column("grounds", postgresql.JSONB(), nullable=False, server_default=_EMPTY),
    )
    op.add_column(
        "judgement_aggregator_issues",
        sa.Column("grounds", postgresql.JSONB(), nullable=False, server_default=_EMPTY),
    )


def downgrade() -> None:
    op.drop_column("judgement_aggregator_issues", "grounds")
    op.drop_column("judgement_issues", "grounds")
