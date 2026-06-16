"""User-facing CLI for Cortex codebase ingest with rich progress display.

Usage (exact form referenced in docs):
    uv run python scripts/cortex_ingest.py <path> [--force] [--output-dir DIR] [--language LANG]

Implements CliProgress backed by rich.progress for a live progress bar.
rich is already a dependency (rich==15.0.0 in uv.lock); no new deps added.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from mcp_server.handlers.ingest_codebase import handler

_console = Console()


class CliProgress:
    """ProgressReporter backed by rich.progress for terminal display.

    Precondition (constructor): called from the main thread before asyncio.run.
    Postcondition (stage):      the rich Progress bar advances to the new stage.
    Postcondition (advance):    the task total is updated dynamically; spinner
                                shows running symbol count when total is unknown.
    Postcondition (close):      the rich Progress context manager is stopped,
                                leaving the final state visible in the terminal.
    """

    def __init__(self) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=_console,
            transient=False,
        )
        self._task_id: TaskID | None = None
        self._stage_label: str = ""
        self._started = False

    def _ensure_started(self) -> None:
        if not self._started:
            self._progress.start()
            self._started = True

    def stage(self, name: str, index: int, total: int) -> None:
        """Advance to a named stage; create or update the rich task."""
        self._ensure_started()
        self._stage_label = name
        label = f"[{index + 1}/{total}] {name}"
        if self._task_id is None:
            self._task_id = self._progress.add_task(label, total=None)
        else:
            self._progress.update(
                self._task_id, description=label, completed=0, total=None
            )

    def advance(self, done: int, total: int | None = None) -> None:
        """Update within-stage progress; sets task total dynamically."""
        if self._task_id is None:
            return
        if total and total > 0:
            self._progress.update(self._task_id, completed=done, total=total)
        else:
            # Indeterminate: show running count in description.
            label = f"[?] {self._stage_label} ({done} symbols)"
            self._progress.update(self._task_id, description=label)

    def log(self, message: str) -> None:
        """Print a log line above the progress bar."""
        if self._started:
            self._progress.print(message)
        else:
            _console.print(message)

    def close(self) -> None:
        """Stop the rich progress display."""
        if self._started:
            self._progress.stop()
            self._started = False


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cortex_ingest",
        description="Ingest a codebase into Cortex's knowledge graph.",
    )
    p.add_argument("project_path", help="Path to the codebase root to ingest.")
    p.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force re-analysis even if a cached graph exists.",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        metavar="DIR",
        help="Override the default graph output directory.",
    )
    p.add_argument(
        "--language",
        default="auto",
        metavar="LANG",
        help="Language hint for the upstream analyser (default: auto).",
    )
    return p


def _print_summary(result: dict) -> None:
    """Print a rich summary table of the ingest result."""
    if not result.get("ingested"):
        _console.print(
            f"[bold red]Ingest failed:[/bold red] {result.get('reason', 'unknown')}",
        )
        detail = result.get("error") or result.get("message")
        if detail:
            _console.print(f"  {detail}")
        return

    _console.print("\n[bold green]Ingest complete.[/bold green]")
    rows = [
        ("Graph path", result.get("graph_path", "—")),
        ("Symbols seen", result.get("symbol_count_seen", 0)),
        ("Files seen", result.get("file_count_seen", 0)),
        ("Entities written", result.get("entities_written", 0)),
        ("Edges written", result.get("edges_written", 0)),
        ("Processes seen", result.get("process_count_seen", 0)),
        ("Wiki pages", len(result.get("wiki_pages_written") or [])),
    ]
    for label, value in rows:
        _console.print(f"  [cyan]{label:<22}[/cyan] {value}")

    diagnostics = result.get("diagnostics")
    if diagnostics:
        _console.print(f"\n[yellow]Diagnostics ({len(diagnostics)}):[/yellow]")
        for d in diagnostics[:5]:
            _console.print(f"  {d}")
        if len(diagnostics) > 5:
            _console.print(f"  … and {len(diagnostics) - 5} more.")


async def _run(args: argparse.Namespace) -> int:
    """Async entry point: build progress, call handler, print summary."""
    progress = CliProgress()
    result = await handler(
        {
            "project_path": args.project_path,
            "force_reindex": args.force,
            "output_dir": args.output_dir,
            "language": args.language,
        },
        progress=progress,
    )
    _print_summary(result)
    return 0 if result.get("ingested") else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
