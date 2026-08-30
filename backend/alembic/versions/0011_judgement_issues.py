"""add judgement issue and conference score tables

Revision ID: 0011_judgement_issues
Revises: 0010_generated_since_prepare
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011_judgement_issues"
down_revision: str | Sequence[str] | None = "0010_generated_since_prepare"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FINDING_KINDS = (
    "gap_unsupported_by_sources",
    "gap_already_addressed",
    "gap_untestable",
    "contribution_not_novel",
    "contribution_overclaimed",
    "unsupported_citation",
    "claim_broader_than_experiment",
    "experiment_insufficient_for_claim",
)
_SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")


def upgrade() -> None:
    op.create_table(
        "judgement_issues",
        sa.Column("row_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node", sa.String(length=64), nullable=False),
        sa.Column("finding_kind", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggestion", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_card_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "finding_kind IN (" + ", ".join(f"'{item}'" for item in _FINDING_KINDS) + ")",
            name="ck_judgement_issues_finding_kind",
        ),
        sa.CheckConstraint(
            "severity IN (" + ", ".join(f"'{item}'" for item in _SEVERITIES) + ")",
            name="ck_judgement_issues_severity",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["loop_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stage_revision_id"], ["loop_stage_revisions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "session_id",
            "stage_revision_id",
            "id",
            name="uq_judgement_issues_revision_id",
        ),
    )
    op.create_index(
        "uq_judgement_issues_working_id",
        "judgement_issues",
        ["session_id", "id"],
        unique=True,
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )
    op.create_index(
        "ix_judgement_issues_session_revision",
        "judgement_issues",
        ["session_id", "stage_revision_id"],
    )
    op.create_index(
        "ix_judgement_issues_working_node",
        "judgement_issues",
        ["session_id", "node"],
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )
    op.create_table(
        "judgement_conference_scores",
        sa.Column("row_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("originality", sa.Integer(), nullable=False),
        sa.Column("significance", sa.Integer(), nullable=False),
        sa.Column("soundness", sa.Integer(), nullable=False),
        sa.Column("clarity", sa.Integer(), nullable=False),
        sa.Column("reproducibility", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["loop_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["stage_revision_id"], ["loop_stage_revisions.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "session_id",
            "stage_revision_id",
            name="uq_judgement_conference_scores_revision",
        ),
    )
    op.create_index(
        "uq_judgement_conference_scores_working",
        "judgement_conference_scores",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text("stage_revision_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_judgement_conference_scores_working",
        table_name="judgement_conference_scores",
    )
    op.drop_table("judgement_conference_scores")
    op.drop_index("ix_judgement_issues_working_node", table_name="judgement_issues")
    op.drop_index("ix_judgement_issues_session_revision", table_name="judgement_issues")
    op.drop_index("uq_judgement_issues_working_id", table_name="judgement_issues")
    op.drop_table("judgement_issues")
