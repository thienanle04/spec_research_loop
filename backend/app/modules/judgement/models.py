"""Judgement typed rows: Judge Issues and Conference scores."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.modules.judgement.catalog import FindingKind, Severity

_FINDING_KIND_VALUES = ", ".join(f"'{item.value}'" for item in FindingKind)
_SEVERITY_VALUES = ", ".join(f"'{item.value}'" for item in Severity)


class JudgeIssue(Base):
    """A working or immutable Judge Issue on one Judge Run."""

    __tablename__ = "judgement_issues"
    __table_args__ = (
        CheckConstraint(
            f"finding_kind IN ({_FINDING_KIND_VALUES})",
            name="ck_judgement_issues_finding_kind",
        ),
        CheckConstraint(
            f"severity IN ({_SEVERITY_VALUES})",
            name="ck_judgement_issues_severity",
        ),
        UniqueConstraint(
            "session_id",
            "stage_revision_id",
            "id",
            name="uq_judgement_issues_revision_id",
        ),
        Index(
            "uq_judgement_issues_working_id",
            "session_id",
            "id",
            unique=True,
            postgresql_where=text("stage_revision_id IS NULL"),
        ),
        Index(
            "ix_judgement_issues_session_revision",
            "session_id",
            "stage_revision_id",
        ),
        Index(
            "ix_judgement_issues_working_node",
            "session_id",
            "node",
            postgresql_where=text("stage_revision_id IS NULL"),
        ),
    )

    row_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_stage_revisions.id", ondelete="CASCADE"),
        nullable=True,
    )
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    finding_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    suggestion: Mapped[str] = mapped_column(Text, nullable=False, default="")
    target_card_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    sort_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class ConferenceScore(Base):
    """Conference Judge criterion scores for one working or frozen Judge Run."""

    __tablename__ = "judgement_conference_scores"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "stage_revision_id",
            name="uq_judgement_conference_scores_revision",
        ),
        Index(
            "uq_judgement_conference_scores_working",
            "session_id",
            unique=True,
            postgresql_where=text("stage_revision_id IS NULL"),
        ),
    )

    row_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    stage_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_stage_revisions.id", ondelete="CASCADE"),
        nullable=True,
    )
    originality: Mapped[int] = mapped_column(Integer, nullable=False)
    significance: Mapped[int] = mapped_column(Integer, nullable=False)
    soundness: Mapped[int] = mapped_column(Integer, nullable=False)
    clarity: Mapped[int] = mapped_column(Integer, nullable=False)
    reproducibility: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
