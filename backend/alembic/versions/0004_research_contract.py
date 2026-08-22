"""add research Citation and related-work contracts

Revision ID: 0004_research_contract
Revises: 0003_loop_session_version
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_research_contract"
down_revision: str | Sequence[str] | None = "0003_loop_session_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_citations",
        sa.Column("row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("citation_key", sa.String(length=200), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("authors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("provider_source_id", sa.String(length=255), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'warning', 'rejected')",
            name="ck_research_citations_verification_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["loop_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stage_revision_id"],
            ["loop_stage_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("row_id"),
        sa.UniqueConstraint(
            "session_id",
            "stage_revision_id",
            "id",
            name="uq_research_citations_revision_id",
        ),
    )
    op.create_index(
        "ix_research_citations_session_revision",
        "research_citations",
        ["session_id", "stage_revision_id"],
        unique=False,
    )
    op.create_index(
        "uq_research_citations_working_id",
        "research_citations",
        ["session_id", "id"],
        unique=True,
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )
    op.create_index(
        "uq_research_citations_working_doi",
        "research_citations",
        ["session_id", "doi"],
        unique=True,
        postgresql_where=sa.text("stage_revision_id IS NULL AND doi IS NOT NULL"),
    )
    op.create_index(
        "uq_research_citations_working_provider_id",
        "research_citations",
        ["session_id", "provider", "provider_source_id"],
        unique=True,
        postgresql_where=sa.text(
            "stage_revision_id IS NULL AND provider IS NOT NULL "
            "AND provider_source_id IS NOT NULL"
        ),
    )

    op.create_table(
        "research_related_work_findings",
        sa.Column("row_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("citation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("what_was_done", sa.Text(), nullable=False),
        sa.Column("method_or_feedback", sa.Text(), nullable=True),
        sa.Column("limitation", sa.Text(), nullable=False),
        sa.Column("relevance", sa.Text(), nullable=True),
        sa.Column("supporting_passage", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_research_findings_confidence",
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'warning', 'rejected')",
            name="ck_research_findings_verification_status",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["loop_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stage_revision_id"],
            ["loop_stage_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id", "stage_revision_id", "citation_id"],
            [
                "research_citations.session_id",
                "research_citations.stage_revision_id",
                "research_citations.id",
            ],
            name="fk_research_findings_citation_snapshot",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("row_id"),
        sa.UniqueConstraint(
            "session_id",
            "stage_revision_id",
            "id",
            name="uq_research_findings_revision_id",
        ),
    )
    op.create_index(
        "ix_research_findings_session_revision",
        "research_related_work_findings",
        ["session_id", "stage_revision_id"],
        unique=False,
    )
    op.create_index(
        "uq_research_findings_working_id",
        "research_related_work_findings",
        ["session_id", "id"],
        unique=True,
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )
    op.create_index(
        "ix_research_findings_working_citation",
        "research_related_work_findings",
        ["session_id", "citation_id"],
        unique=False,
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_research_findings_working_citation",
        table_name="research_related_work_findings",
    )
    op.drop_index(
        "uq_research_findings_working_id",
        table_name="research_related_work_findings",
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )
    op.drop_index(
        "ix_research_findings_session_revision",
        table_name="research_related_work_findings",
    )
    op.drop_table("research_related_work_findings")
    op.drop_index(
        "uq_research_citations_working_provider_id",
        table_name="research_citations",
    )
    op.drop_index(
        "uq_research_citations_working_doi",
        table_name="research_citations",
    )
    op.drop_index(
        "uq_research_citations_working_id",
        table_name="research_citations",
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )
    op.drop_index(
        "ix_research_citations_session_revision", table_name="research_citations"
    )
    op.drop_table("research_citations")
