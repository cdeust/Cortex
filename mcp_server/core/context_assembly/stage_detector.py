"""Pluggable stage detection for structured context assembly.

A "stage" is a **distinct subject with its own context** — the unit of
topical locality that the StageAwareContextAssembler operates on. In
the original Swift PRD pipeline (Clément Deust), stages are explicit:
Impact, Integration, PRD, Implementation. Each is a different task with
its own vocabulary and its own relevance.

For Cortex, free-form conversations don't come with explicit stage
labels. This module provides pluggable detectors so stage boundary
strategies can be A/B tested empirically rather than hard-coded.

Ships two detectors in v1:
  - `ExplicitStageDetector` — stage = an explicit field on the memory
    (e.g. "plan_id" for BEAM, "agent_topic" for production)
  - `TemporalStageDetector` — stage = contiguous block of memories with
    inter-memory time gaps below a threshold

Future (A/B candidates): semantic clustering, LLM topic-shift detection,
hybrid explicit+temporal fallback.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any


class StageDetector(ABC):
    """Assigns each memory to a stage ID.

    Stage IDs are stable strings per memory. The assembler uses them
    to partition candidates into own-stage vs adjacent-stage pools.
    """

    @abstractmethod
    def stage_of(self, memory: dict[str, Any]) -> str:
        """Return the stage ID for a single memory."""

    @abstractmethod
    def all_stages(self, corpus: list[dict[str, Any]]) -> list[str]:
        """Return all distinct stage IDs across a corpus, in a stable order."""


# ── Explicit field detector ─────────────────────────────────────────────


class ExplicitStageDetector(StageDetector):
    """Stage = value of an explicit field on the memory.

    Examples:
      - BEAM benchmark: field="plan_id" (the BEAM-10M dataset has a
        plan index per turn, tagged at ingest).
      - Production Cortex: field="agent_topic" or "directory_context".

    When the field is missing from a memory, the fallback value is
    used — defaults to "default".
    """

    def __init__(self, field: str = "plan_id", fallback: str = "default") -> None:
        self._field = field
        self._fallback = fallback

    def stage_of(self, memory: dict[str, Any]) -> str:
        value = memory.get(self._field)
        if value is None or value == "":
            return self._fallback
        return str(value)

    def all_stages(self, corpus: list[dict[str, Any]]) -> list[str]:
        seen: list[str] = []
        seen_set: set[str] = set()
        for m in corpus:
            stage = self.stage_of(m)
            if stage not in seen_set:
                seen.append(stage)
                seen_set.add(stage)
        return seen


# ── Temporal gap detector ───────────────────────────────────────────────


class TemporalStageDetector(StageDetector):
    """Stage = contiguous block of memories separated by <gap_hours>.

    Useful when memories lack explicit stage labels but have reliable
    timestamps. A gap larger than the threshold starts a new stage.

    Args:
        gap_hours: inter-memory gap above which a new stage begins.
            Default 4h matches a typical work-session boundary.
        time_field: name of the timestamp field. Accepts ISO strings
            or datetime objects.
    """

    def __init__(
        self,
        gap_hours: float = 4.0,
        time_field: str = "created_at",
    ) -> None:
        self._gap = timedelta(hours=gap_hours)
        self._time_field = time_field
        # Cache: memory_id → stage_id after first pass
        self._cache: dict[Any, str] = {}

    def stage_of(self, memory: dict[str, Any]) -> str:
        mid = memory.get("memory_id") or memory.get("id") or id(memory)
        if mid in self._cache:
            return self._cache[mid]
        # Temporal detection requires knowledge of neighbors; if called
        # without pre-computation, fall back to the timestamp bucket.
        ts = self._parse_ts(memory.get(self._time_field))
        if ts is None:
            return "default"
        # Bucket by day as a reasonable standalone fallback
        return f"day-{ts.date().isoformat()}"

    def all_stages(self, corpus: list[dict[str, Any]]) -> list[str]:
        # Sort by timestamp, walk linearly, emit a new stage when gap exceeded
        timed: list[tuple[datetime, dict[str, Any]]] = []
        for m in corpus:
            ts = self._parse_ts(m.get(self._time_field))
            if ts is not None:
                timed.append((ts, m))
        timed.sort(key=lambda x: x[0])

        stages: list[str] = []
        current_stage: str | None = None
        last_ts: datetime | None = None
        counter = 0
        for ts, m in timed:
            if last_ts is None or (ts - last_ts) > self._gap:
                counter += 1
                current_stage = f"stage-{counter}"
                stages.append(current_stage)
            assert current_stage is not None
            mid = m.get("memory_id") or m.get("id") or id(m)
            self._cache[mid] = current_stage
            last_ts = ts
        return stages

    @staticmethod
    def _parse_ts(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            # Try ISO format first (2024-03-15, 2024-03-15T10:00:00Z)
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
            # Try BEAM's "Month-DD-YYYY" format (March-15-2024)
            import calendar

            try:
                parts = value.split("-")
                if len(parts) == 3 and parts[0].isalpha():
                    month_name = parts[0]
                    day = int(parts[1])
                    year = int(parts[2])
                    month_abbrs = {
                        m.lower(): i for i, m in enumerate(calendar.month_name) if m
                    }
                    month_num = month_abbrs.get(month_name.lower())
                    if month_num:
                        return datetime(year, month_num, day)
            except (ValueError, IndexError):
                pass
        return None


# ── Composite fallback detector ─────────────────────────────────────────


class CompositeStageDetector(StageDetector):
    """Try detectors in order until one returns a non-fallback stage.

    Useful for production: try explicit labels first, fall back to
    temporal detection if no explicit label exists.
    """

    def __init__(
        self,
        detectors: list[StageDetector],
        fallback: str = "default",
    ) -> None:
        if not detectors:
            raise ValueError("CompositeStageDetector requires at least one detector")
        self._detectors = detectors
        self._fallback = fallback

    def stage_of(self, memory: dict[str, Any]) -> str:
        for det in self._detectors:
            stage = det.stage_of(memory)
            if stage and stage != self._fallback and not stage.startswith("day-"):
                return stage
        # Last resort: first detector's output (may be fallback)
        return self._detectors[0].stage_of(memory)

    def all_stages(self, corpus: list[dict[str, Any]]) -> list[str]:
        # Use the union across detectors, de-duplicated in seen order
        seen: list[str] = []
        seen_set: set[str] = set()
        for det in self._detectors:
            for s in det.all_stages(corpus):
                if s not in seen_set:
                    seen.append(s)
                    seen_set.add(s)
        return seen
