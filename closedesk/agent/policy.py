"""Policy gate: allow / escalate / block. No I/O."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Policy:
    auto_propose_max_inr: float
    escalate_above_inr: float
    allowed_actions: tuple[str, ...]


def load_policy(path: Path | None = None) -> Policy:
    path = path or Path("config/policy.yaml")
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    return Policy(
        auto_propose_max_inr=float(raw["auto_propose_max_inr"]),
        escalate_above_inr=float(raw["escalate_above_inr"]),
        allowed_actions=tuple(raw["allowed_actions"]),
    )


def gate(action: str, amount_inr: float, policy: Policy) -> str:
    """Return allow | escalate | block."""
    if action not in policy.allowed_actions:
        return "block"
    if amount_inr > policy.escalate_above_inr:
        return "block"
    if amount_inr > policy.auto_propose_max_inr:
        return "escalate"
    return "allow"
