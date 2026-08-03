"""Active cost-gate token passed to low-level external API clients."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.services.cost_control.types import ExternalApiProvider

_active_gate: ContextVar["ActiveCostGate | None"] = ContextVar("cost_control_active_gate", default=None)


@dataclass
class ActiveCostGate:
  user_id: int
  provider: ExternalApiProvider
  action: str
  token: str = field(default_factory=lambda: uuid.uuid4().hex)
  cache_hit: bool = False
  cached_value: Any = None


def get_active_cost_gate() -> ActiveCostGate | None:
  return _active_gate.get()


def set_active_cost_gate(gate: ActiveCostGate | None) -> object:
  return _active_gate.set(gate)


def reset_active_cost_gate(token: object) -> None:
  try:
    _active_gate.reset(token)
  except ValueError:
    _active_gate.set(None)
