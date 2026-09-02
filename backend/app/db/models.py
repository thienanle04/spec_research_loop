"""Import every SQLAlchemy model so Alembic sees Base.metadata."""

from app.modules.identity.models import Account
from app.modules.judgement.models import (
    AggregatorIssue,
    AggregatorScore,
    ConferenceScore,
    HandlingOption,
    JudgeIssue,
)
from app.modules.loop.models import (
    Card,
    Decision,
    LoopSession,
    NodeHead,
    SpecVersion,
    StageRevision,
)
from app.modules.research.models import Citation, RelatedWorkFinding

__all__ = [
    "Account",
    "AggregatorIssue",
    "AggregatorScore",
    "Card",
    "Citation",
    "ConferenceScore",
    "Decision",
    "HandlingOption",
    "JudgeIssue",
    "LoopSession",
    "NodeHead",
    "RelatedWorkFinding",
    "SpecVersion",
    "StageRevision",
]
