"""Batch raw vectors only for prevalidated, store-independent bypass writes.

source: ADR-0437"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Iterator
from pathlib import Path

from mcp_server.handlers import remember
from mcp_server.infrastructure.config import CLAUDE_DIR
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.handlers.remember_prepared import (
    EncodingOutcome,
    InputFailure,
    PreparedEncoding,
    PreparedWrite,
)
from mcp_server.infrastructure.embedding_batch import EncodedItem, encode_items

logger = logging.getLogger(__name__)


def _inputs(inputs: Iterable[dict | InputFailure]) -> Iterator[dict | InputFailure]:
    iterator = iter(inputs)
    while True:
        try:
            item = next(iterator)
        except StopIteration:
            return
        except Exception as exc:  # noqa: BLE001 — defer caller preparation failure until preceding writes finish
            yield InputFailure(exc, abort=True)
            return
        yield item


def _prepare_one(args: dict | InputFailure) -> PreparedEncoding:
    if isinstance(args, InputFailure):
        return PreparedEncoding(
            args, None, EncodingOutcome(encoded=EncodedItem({}, error=args.error))
        )
    started_at = time.perf_counter()
    try:
        # Bulk callers explicitly identify bypasses; never speculate on a gate.
        if not (args.get("force") or args.get("write_class") == "deliberate"):
            raise ValueError("Bulk preparation requires an explicit bypass write")
        if args.get("supersedes_id") is not None:
            raise ValueError("Supersession validation must remain sequential")
        prepared = remember.prepare_write(args)
        if isinstance(prepared, PreparedWrite) and prepared.observed is not None:
            raise ValueError("Bulk preparation cannot freeze gate observations")
        return PreparedEncoding(args, prepared, started_at=started_at)
    except Exception as exc:  # noqa: BLE001 — the original handler/caller receives this validation error at its item
        return PreparedEncoding(
            args,
            None,
            EncodingOutcome(encoded=EncodedItem(args, error=exc)),
            started_at,
        )


def prepare_bulk(
    inputs: Iterable[dict | InputFailure], *, stop_on_error: bool = False
) -> list[PreparedEncoding]:
    """Finish validation before the model; retain responses/errors in input order."""
    pending = []
    for args in _inputs(inputs):
        item = _prepare_one(args)
        pending.append(item)
        if stop_on_error and item.prepared is None:
            break
    eligible = [item for item in pending if isinstance(item.prepared, PreparedWrite)]
    if not eligible:
        return pending
    try:
        engine = remember.get_embedding_engine()
    except Exception as exc:  # noqa: BLE001 — first lookup fails at its original item; later items retry sequentially
        eligible[0].outcome.encoded = EncodedItem(
            eligible[0].encoding_input(), error=exc
        )
        return pending
    encoded = encode_items(
        [item.encoding_input() for item in eligible], "content", engine
    )
    for item, result in zip(eligible, encoded, strict=True):
        item.outcome = EncodingOutcome(engine, result)
    logger.debug("Prepared remember raw-vector batch: %d items", len(eligible))
    return pending


async def store_prepared(item: PreparedEncoding) -> dict:
    """Record elapsed entry latency, including preparation/batch/prior continuations.

    Latencies overlap; they are not additive CPU times. Caller input construction
    remains outside remember. Abandoned entries never reach this sample boundary.
    """
    if item.args is None:
        item.checked()  # caller preparation failure happened outside remember

    async def run(args):
        return await remember._handler_impl(args, prepared_encoding=item)

    return await instrument(
        "remember", run, result_count_key=None, started_at=item.started_at
    )(item.args)


def file_reads_are_independent(paths: list[Path]) -> bool:
    """Keep live reads scalar if a preceding remember can replace their target.

    source: ADR-0437"""
    try:
        settings = remember.get_memory_settings()
        roots = [
            CLAUDE_DIR,
            remember.WIKI_ROOT,
            Path(settings.DB_PATH).expanduser().parent,
            Path(settings.SQLITE_FALLBACK_PATH).expanduser().parent,
        ]
        resolved_roots = [Path(root).expanduser().resolve() for root in roots]
        for path in paths:
            resolved = path.expanduser().resolve()
            if any(resolved.is_relative_to(root) for root in resolved_roots):
                return False
            if resolved.exists() and resolved.stat().st_nlink > 1:
                # source: ADR-0437
                return False
        return True
    except Exception as exc:  # noqa: BLE001 — preserve original scalar path when disjointness cannot be established
        logger.debug("Keeping live file reads sequential: %s", exc)
        return False
