"""Per-query JSONL journal written beside a benchmark's ``--results-out``.

The benchmark runners score retrieval and keep only ranks. Token and energy
accounting need what each query actually retrieved and when each phase ran,
without re-running the benchmark. This module records both, after
``db.recall`` has returned, so retrieval and scores are unchanged.

Two files are written next to ``<stem>.json``:

- ``<stem>.queries.jsonl``: one line per scored query, with the ids,
  sources, byte and code-point sizes and sha256 of every retrieved item
  (and the item text itself when ``include_content`` is set).
- ``<stem>.phases.jsonl``: one line per timed phase (``ingest`` or
  ``recall``), with wall-clock start and end in Unix seconds, the clock the
  macOS ``powermetrics`` sample timestamps use, so ``benchmarks/energy`` can
  attribute power samples to phases.

source: Cortex benchmark refresh plan, step 1 (2026-09-30), items (d) and (e).
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any

QUERIES_SUFFIX = ".queries.jsonl"
PHASES_SUFFIX = ".phases.jsonl"


def sidecar_paths(results_out: str | Path) -> tuple[Path, Path]:
    """Return ``(queries_path, phases_path)`` beside ``results_out``."""
    out = Path(results_out)
    stem = out.with_suffix("")
    return (
        stem.with_name(stem.name + QUERIES_SUFFIX),
        stem.with_name(stem.name + PHASES_SUFFIX),
    )


def text_stats(text: str) -> dict[str, Any]:
    """UTF-8 byte count, code-point count and sha256 of ``text``."""
    raw = text.encode("utf-8")
    return {
        "bytes": len(raw),
        "codepoints": len(text),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def item_record(
    result: dict, source_map: dict | None, include_content: bool
) -> dict[str, Any]:
    """One retrieved item as the journal stores it."""
    content = str(result.get("content") or "")
    record: dict[str, Any] = {
        "memory_id": result.get("memory_id"),
        "source": (source_map or {}).get(result.get("memory_id")),
        "score": result.get("score"),
        **text_stats(content),
    }
    if include_content:
        record["content"] = content
    return record


class QueryLog:
    """Append-only journal of retrieved items and timed phases.

    A log built with ``results_out=None`` is disabled: every method is a
    no-op, so runners call it unconditionally.
    """

    def __init__(
        self, results_out: str | Path | None, *, include_content: bool = False
    ) -> None:
        self.include_content = include_content
        self._queries: IO[str] | None = None
        self._phases: IO[str] | None = None
        if results_out is not None:
            queries_path, phases_path = sidecar_paths(results_out)
            queries_path.parent.mkdir(parents=True, exist_ok=True)
            self._queries = queries_path.open("w", encoding="utf-8")
            self._phases = phases_path.open("w", encoding="utf-8")

    @property
    def enabled(self) -> bool:
        return self._queries is not None

    def _write(self, stream: IO[str] | None, payload: dict[str, Any]) -> None:
        if stream is not None:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    @contextmanager
    def phase(self, name: str, unit: str) -> Iterator[None]:
        """Time the enclosed block as phase ``name`` of unit ``unit``."""
        start = time.time()
        try:
            yield
        finally:
            end = time.time()
            self._write(
                self._phases,
                {"phase": name, "unit": unit, "wall_start": start, "wall_end": end},
            )

    def record(
        self,
        question_id: str,
        results: list[dict],
        *,
        source_map: dict | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Write one scored query and the items it retrieved."""
        items = [item_record(r, source_map, self.include_content) for r in results]
        self._write(
            self._queries,
            {
                "question_id": question_id,
                "items": items,
                "retrieved_bytes": sum(i["bytes"] for i in items),
                **(extra or {}),
            },
        )

    def close(self) -> None:
        for stream in (self._queries, self._phases):
            if stream is not None:
                stream.close()
        self._queries = self._phases = None

    def __enter__(self) -> QueryLog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
