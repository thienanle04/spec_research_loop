"""Loop persistence models."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.loop.catalog import (
    CardKind,
    DecisionKind,
    NodeHeadStatus,
    WorkflowNode,
)


class LoopSession(Base):
    __tablename__ = "loop_sessions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    account_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accounts.id"),
        nullable=False,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    working_draft_node: Mapped[str] = mapped_column(String(64), nullable=False)
    working_draft_narrative: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    working_draft_narratives: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    produced_spec_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    valid_spec_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
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

    cards: Mapped[list["Card"]] = relationship(back_populates="session")
    node_heads: Mapped[list["NodeHead"]] = relationship(back_populates="session")
    stage_revisions: Mapped[list["StageRevision"]] = relationship(
        back_populates="session"
    )
    decisions: Mapped[list["Decision"]] = relationship(back_populates="session")
    spec_versions: Mapped[list["SpecVersion"]] = relationship(back_populates="session")


class Card(Base):
    __tablename__ = "loop_cards"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
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

    session: Mapped[LoopSession] = relationship(back_populates="cards")

    def kind_enum(self) -> CardKind:
        return CardKind(self.kind)


class StageRevision(Base):
    __tablename__ = "loop_stage_revisions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_n: Mapped[int] = mapped_column(Integer, nullable=False)
    narrative: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    card_snapshot: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    freeze_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped[LoopSession] = relationship(back_populates="stage_revisions")


class NodeHead(Base):
    __tablename__ = "loop_node_heads"
    __table_args__ = (
        UniqueConstraint("session_id", "node", name="uq_loop_node_heads_session_node"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=NodeHeadStatus.EMPTY
    )
    stage_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_stage_revisions.id"),
        nullable=True,
    )
    generated_since_prepare: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    session: Mapped[LoopSession] = relationship(back_populates="node_heads")

    def node_enum(self) -> WorkflowNode:
        return WorkflowNode(self.node)

    def status_enum(self) -> NodeHeadStatus:
        return NodeHeadStatus(self.status)


class Decision(Base):
    __tablename__ = "loop_decisions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default=DecisionKind.CONFIRM
    )
    node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_revision_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped[LoopSession] = relationship(back_populates="decisions")


class SpecVersion(Base):
    __tablename__ = "loop_spec_versions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("loop_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    session: Mapped[LoopSession] = relationship(back_populates="spec_versions")
