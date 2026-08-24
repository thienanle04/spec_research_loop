"""Research-owned Citation and related-work snapshot rows."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Citation(Base):
    """A working or immutable revision snapshot of one logical Citation."""

    __tablename__ = "research_citations"
    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'warning', 'rejected')",
            name="ck_research_citations_verification_status",
        ),
        UniqueConstraint(
            "session_id",
            "stage_revision_id",
            "id",
            name="uq_research_citations_revision_id",
        ),
        Index(
            "uq_research_citations_working_id",
            "session_id",
            "id",
            unique=True,
            postgresql_where=text("stage_revision_id IS NULL"),
        ),
        Index(
            "uq_research_citations_working_doi",
            "session_id",
            "doi",
            unique=True,
            postgresql_where=text("stage_revision_id IS NULL AND doi IS NOT NULL"),
        ),
        Index(
            "uq_research_citations_working_provider_id",
            "session_id",
            "provider",
            "provider_source_id",
            unique=True,
            postgresql_where=text(
                "stage_revision_id IS NULL AND provider IS NOT NULL "
                "AND provider_source_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_research_citations_session_revision",
            "session_id",
            "stage_revision_id",
        ),
    )

    row_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    # Stable logical identity. row_id identifies the physical snapshot row.
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, default=uuid4
    )
    citation_key: Mapped[str] = mapped_column(String(200), nullable=False)
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
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    venue: Mapped[str | None] = mapped_column(Text, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_source_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    retrieval_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verification_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    source_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
    )
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


class RelatedWorkFinding(Base):
    """A source-linked finding in the related-work matrix."""

    __tablename__ = "research_related_work_findings"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "stage_revision_id",
            "id",
            name="uq_research_findings_revision_id",
        ),
        ForeignKeyConstraint(
            ["session_id", "stage_revision_id", "citation_id"],
            [
                "research_citations.session_id",
                "research_citations.stage_revision_id",
                "research_citations.id",
            ],
            name="fk_research_findings_citation_snapshot",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_research_findings_confidence",
        ),
        CheckConstraint(
            "grounding_status IN ('pending', 'grounded', 'warning', 'rejected')",
            name="ck_research_findings_grounding_status",
        ),
        Index(
            "uq_research_findings_working_id",
            "session_id",
            "id",
            unique=True,
            postgresql_where=text("stage_revision_id IS NULL"),
        ),
        Index(
            "ix_research_findings_session_revision",
            "session_id",
            "stage_revision_id",
        ),
        Index(
            "ix_research_findings_working_citation",
            "session_id",
            "citation_id",
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
    citation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    what_was_done: Mapped[str] = mapped_column(Text, nullable=False)
    method_or_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitation: Mapped[str] = mapped_column(Text, nullable=False)
    relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    supporting_passage: Mapped[str] = mapped_column(Text, nullable=False)
    source_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    grounding_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
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
