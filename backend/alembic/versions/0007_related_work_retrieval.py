"""add Related Work retrieval and S3 text metadata

Revision ID: 0007_related_work_retrieval
Revises: 0006_related_work_evidence
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_related_work_retrieval"
down_revision: str | Sequence[str] | None = "0006_related_work_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "research_citations",
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "research_citations",
        sa.Column("pinned", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("research_citations", sa.Column("retrieval_score", sa.Float()))
    op.add_column("research_citations", sa.Column("text_object_key", sa.Text()))
    op.add_column("research_citations", sa.Column("text_source_url", sa.Text()))
    op.add_column(
        "research_citations", sa.Column("text_source_kind", sa.String(length=32))
    )
    op.add_column(
        "research_citations", sa.Column("text_checksum", sa.String(length=64))
    )
    op.add_column("research_citations", sa.Column("text_char_count", sa.Integer()))
    op.add_column(
        "research_citations",
        sa.Column("text_retrieved_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "research_related_work_findings", sa.Column("source_object_key", sa.Text())
    )
    op.add_column(
        "research_related_work_findings", sa.Column("source_location", sa.Text())
    )
    op.create_index(
        "ix_research_citations_working_active",
        "research_citations",
        ["session_id", "is_active", "pinned"],
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_citations_working_active", table_name="research_citations"
    )
    op.drop_column("research_related_work_findings", "source_location")
    op.drop_column("research_related_work_findings", "source_object_key")
    op.drop_column("research_citations", "text_retrieved_at")
    op.drop_column("research_citations", "text_char_count")
    op.drop_column("research_citations", "text_checksum")
    op.drop_column("research_citations", "text_source_kind")
    op.drop_column("research_citations", "text_source_url")
    op.drop_column("research_citations", "text_object_key")
    op.drop_column("research_citations", "retrieval_score")
    op.drop_column("research_citations", "pinned")
    op.drop_column("research_citations", "is_active")
