"""separate finding grounding status

Revision ID: 0005_research_p0
Revises: 0004_research_contract
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_research_p0"
down_revision: str | Sequence[str] | None = "0004_research_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_research_findings_verification_status",
        "research_related_work_findings",
        type_="check",
    )
    op.alter_column(
        "research_related_work_findings",
        "verification_status",
        new_column_name="grounding_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="pending",
    )
    op.execute(
        "UPDATE research_related_work_findings "
        "SET grounding_status = 'grounded' WHERE grounding_status = 'verified'"
    )
    op.create_check_constraint(
        "ck_research_findings_grounding_status",
        "research_related_work_findings",
        "grounding_status IN ('pending', 'grounded', 'warning', 'rejected')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_research_findings_grounding_status",
        "research_related_work_findings",
        type_="check",
    )
    op.execute(
        "UPDATE research_related_work_findings "
        "SET grounding_status = 'verified' WHERE grounding_status = 'grounded'"
    )
    op.alter_column(
        "research_related_work_findings",
        "grounding_status",
        new_column_name="verification_status",
        existing_type=sa.String(length=16),
        existing_nullable=False,
        existing_server_default="pending",
    )
    op.create_check_constraint(
        "ck_research_findings_verification_status",
        "research_related_work_findings",
        "verification_status IN ('pending', 'verified', 'warning', 'rejected')",
    )
