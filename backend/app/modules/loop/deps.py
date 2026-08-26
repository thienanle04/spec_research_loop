"""Loop FastAPI / composition-root helpers."""

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.loop.catalog import WORKFLOW_NODES
from app.ports.stage import NoOpStagePort, StagePort

StagePortFactory = Callable[[AsyncSession], StagePort]

_stage_port_factories: dict[str, StagePortFactory] | None = None


def _noop_stage_port(_db: AsyncSession) -> StagePort:
    return NoOpStagePort()


def default_stage_port_factories() -> dict[str, StagePortFactory]:
    return {node.value: _noop_stage_port for node in WORKFLOW_NODES}


def bind_stage_port_factories(factories: dict[str, StagePortFactory]) -> None:
    global _stage_port_factories
    _stage_port_factories = factories


def get_stage_ports(db: AsyncSession) -> dict[str, StagePort]:
    factories = _stage_port_factories or default_stage_port_factories()
    return {node: factory(db) for node, factory in factories.items()}
