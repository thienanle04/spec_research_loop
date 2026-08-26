"""merge research and spec migration heads

Revision ID: 0008_merge_research_spec_heads
Revises: 0007_related_work_retrieval, b1f4ea86d35c
Create Date: 2026-08-24
"""

from collections.abc import Sequence


revision: str = "0008_merge_research_spec_heads"
down_revision: str | Sequence[str] | None = (
    "0007_related_work_retrieval",
    "b1f4ea86d35c",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
