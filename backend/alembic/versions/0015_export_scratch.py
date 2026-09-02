"""export scratch and snapshot tables

Revision ID: 0015_export_scratch
Revises: 0014_decision_detail
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0015_export_scratch"
down_revision: str | Sequence[str] | None = "0014_decision_detail"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "loop_export_scratches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spec_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document", postgresql.JSONB(astext_type=sa.Text()), nullable=False
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
        sa.ForeignKeyConstraint(
            ["session_id"], ["loop_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["spec_version_id"], ["loop_spec_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id",
            "spec_version_id",
            name="uq_loop_export_scratches_session_spec_version",
        ),
    )
    op.create_index(
        op.f("ix_loop_export_scratches_session_id"),
        "loop_export_scratches",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_loop_export_scratches_spec_version_id"),
        "loop_export_scratches",
        ["spec_version_id"],
        unique=False,
    )
    op.create_table(
        "loop_export_scratch_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("export_scratch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("spec_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_n", sa.Integer(), nullable=False),
        sa.Column(
            "document", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["loop_sessions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["export_scratch_id"],
            ["loop_export_scratches.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["spec_version_id"], ["loop_spec_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "export_scratch_id",
            "snapshot_n",
            name="uq_loop_export_scratch_snapshots_scratch_n",
        ),
    )
    op.create_index(
        op.f("ix_loop_export_scratch_snapshots_session_id"),
        "loop_export_scratch_snapshots",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_loop_export_scratch_snapshots_export_scratch_id"),
        "loop_export_scratch_snapshots",
        ["export_scratch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_loop_export_scratch_snapshots_spec_version_id"),
        "loop_export_scratch_snapshots",
        ["spec_version_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_loop_export_scratch_snapshots_spec_version_id"),
        table_name="loop_export_scratch_snapshots",
    )
    op.drop_index(
        op.f("ix_loop_export_scratch_snapshots_export_scratch_id"),
        table_name="loop_export_scratch_snapshots",
    )
    op.drop_index(
        op.f("ix_loop_export_scratch_snapshots_session_id"),
        table_name="loop_export_scratch_snapshots",
    )
    op.drop_table("loop_export_scratch_snapshots")
    op.drop_index(
        op.f("ix_loop_export_scratches_spec_version_id"),
        table_name="loop_export_scratches",
    )
    op.drop_index(
        op.f("ix_loop_export_scratches_session_id"),
        table_name="loop_export_scratches",
    )
    op.drop_table("loop_export_scratches")
