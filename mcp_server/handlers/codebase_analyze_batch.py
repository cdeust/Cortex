"""Prepare independent codebase inputs without importing the caller handler."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from mcp_server.handlers.remember_bulk import file_reads_are_independent, prepare_bulk
from mcp_server.handlers.remember_prepared import InputFailure


@dataclass
class FileOperations:
    relative: Callable
    read: Callable
    parse: Callable
    args: Callable


def prepare_file_jobs(
    paths: list[Path], context: dict, operations: FileOperations
) -> Iterable[dict | InputFailure]:
    jobs = _file_jobs(paths, context, operations)
    if not file_reads_are_independent(paths):
        return jobs
    prepared = list(jobs)
    _attach_file_embeddings(prepared)
    return prepared


def _file_job(path: Path, context: dict, operations: FileOperations) -> dict:
    relative = operations.relative(path, context["root"])
    content = operations.read(path)
    job = {"relative": relative, "content": content}
    if content is None:
        return job
    analysis = operations.parse(relative, content)
    existing = context["existing"]
    unchanged = (
        context["incremental"]
        and relative in existing
        and existing[relative][1] == analysis.content_hash
    )
    job.update(analysis=analysis, unchanged=unchanged)
    if not unchanged:
        job["args"] = operations.args(
            context["root"], relative, analysis, context["domain"]
        )
    return job


def _file_jobs(
    paths: list[Path], context: dict, operations: FileOperations
) -> Iterator[dict | InputFailure]:
    for path in paths:
        try:
            yield _file_job(path, context, operations)
        except Exception as exc:  # noqa: BLE001 — defer fatal parse/preparation error until preceding writes finish
            yield InputFailure(exc)
            return


def _attach_file_embeddings(jobs: list[dict | InputFailure]) -> None:
    eligible = [job for job in jobs if isinstance(job, dict) and "args" in job]
    pending = prepare_bulk((job["args"] for job in eligible), stop_on_error=True)
    # source: ADR-0339
    for job, prepared in zip(eligible, pending, strict=False):
        job["prepared"] = prepared
