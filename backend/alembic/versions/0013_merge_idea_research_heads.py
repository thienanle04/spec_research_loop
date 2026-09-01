"""merge idea judgement and research table-index heads

Revision ID: 0013_merge_idea_research_heads
Revises: 0012_aggregator_report, 6c9ed46d30ba
Create Date: 2026-08-31
"""

from collections.abc import Sequence


revision: str = "0013_merge_idea_research_heads"
down_revision: str | Sequence[str] | None = (
    "0012_aggregator_report",
    "6c9ed46d30ba",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
