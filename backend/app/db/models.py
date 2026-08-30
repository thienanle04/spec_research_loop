"""Import every SQLAlchemy model so Alembic sees Base.metadata."""

from app.modules.identity.models import Account
from app.modules.judgement.models import ConferenceScore, JudgeIssue
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
    "Card",
    "Citation",
    "ConferenceScore",
    "Decision",
    "JudgeIssue",
    "LoopSession",
    "NodeHead",
    "RelatedWorkFinding",
    "SpecVersion",
    "StageRevision",
]
