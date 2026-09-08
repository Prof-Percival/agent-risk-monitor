from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

SEVERITIES = ("low", "medium", "high", "critical")


@dataclass(frozen=True)
class Event:
    event_id: str
    agent_id: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Analysis:
    """Everything a rule may read. Rules do no IO, so what they need is loaded before they run."""

    event: Event
    allowed_domains: frozenset[str]
    prior_sensitive_reads: int = 0


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"{self.severity} is not one of {SEVERITIES}")
