"""Explicit internal preparation values; no global rendezvous or engine proxy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mcp_server.handlers.remember_preflight import GateObservation, GateRequest
from mcp_server.infrastructure.embedding_batch import EncodedItem
from mcp_server.shared.memory_rows import MemoryRows


@dataclass(frozen=True)
class ObservedNeighbors:
    """Vector hits and rows observed by the gate, reused before insertion."""

    similarities: list[float]
    hits: list[tuple]
    rows: MemoryRows


@dataclass
class PreparedWrite:
    parsed: tuple
    request: GateRequest
    observed: GateObservation | None
    supersedes_id: int | None


@dataclass(frozen=True)
class InputFailure:
    error: Exception


@dataclass
class EncodingOutcome:
    engine: Any = None
    encoded: EncodedItem | None = None


@dataclass
class PreparedEncoding:
    input: dict | InputFailure
    prepared: PreparedWrite | dict | None
    outcome: EncodingOutcome = field(default_factory=EncodingOutcome)
    started_at: float | None = None

    @property
    def args(self) -> dict | None:
        return self.input if isinstance(self.input, dict) else None

    def checked(self) -> PreparedWrite | dict:
        if self.prepared is not None:
            return self.prepared
        if self.outcome.encoded is not None:
            self.outcome.encoded.value()
        raise ValueError("Missing prepared write or deferred preparation error")

    def encoding_input(self) -> dict:
        if not isinstance(self.prepared, PreparedWrite):
            raise ValueError("Only validated writes have encoding inputs")
        return {"content": self.prepared.request.content}
