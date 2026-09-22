"""Handler: wiki_purge — remove wiki pages that fail the current classifier.

Re-evaluates every authored wiki page against the current classifier rules
and deletes the ones that would no longer be admitted. Memories in the
PostgreSQL/SQLite store are left untouched — only the markdown files in
~/.claude/methodology/wiki/ are removed.

source: ADR-0465"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_server.core.wiki_stub_detector import (
    DEFAULT_SHALLOW_THRESHOLD,
    DEFAULT_STUB_THRESHOLD,
    placeholder_count,
)
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.shared.wiki_layout import PAGE_KINDS
from mcp_server.handlers._tool_meta import DESTRUCTIVE
from mcp_server.handlers.wiki_purge_scan import (
    PAGE_DIRS,
    RejectAxes,
    candidate_pages,
    evaluate_page,
)

# ── Schema ─────────────────────────────────────────────────────────────

schema = {
    "title": "Wiki — purge stale",
    "annotations": DESTRUCTIVE,
    "description": (
        "Purge wiki pages that no longer earn their place. Two reject "
        "axes: (1) the page no longer passes the current classifier "
        "(`core/wiki_classifier`) — used after tightening rules or a "
        "polluting backfill; (2) the page is a stub — body is majority "
        "placeholder markers (_(to be filled)_ / _To be written._ / "
        "_(none identified)_), produced by the groomer or by "
        "template_v1 synthesis. Stubs masquerade as content but carry "
        "none. Memories remain in the store (still surface via "
        "`recall`); only the wiki markdown files are removed from "
        "disk. Distinct from `wiki_consolidate` (heat decay + "
        "lifecycle, doesn't delete based on classifier), `forget` "
        "(deletes a memory, not a wiki page), and `wiki_compile` "
        "(publishes drafts, doesn't purge). Defaults to dry-run; pass "
        "apply=true to actually delete. Latency ~200-500ms. Returns "
        "{kept, purged, purged_paths, purged_reasons, dry_run} plus the "
        "scan accounting — {wiki_pages_total, scanned, unscanned, "
        "errored, unrecognised_dirs} — so a caller can tell a full sweep "
        "from one that reached only part of the wiki. A page that failed "
        "to read counts as scanned, not unscanned: an I/O fault shows up "
        "in `errored`, never as a coverage gap."
    ),
    "inputSchema": {
        "type": "object",
        "required": [],
        "properties": {
            "apply": {
                "type": "boolean",
                "description": (
                    "If true, actually delete the files. If false (default), "
                    "only report what would be purged."
                ),
                "default": False,
            },
            "kind": {
                "type": "string",
                "description": (
                    "Restrict the purge to a single page-kind directory. "
                    "Omit to scan all page kinds."
                ),
                "enum": sorted(PAGE_KINDS),
                "examples": ["notes", "lessons"],
            },
            "purge_stubs": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Purge pages whose body is majority placeholder "
                    "markers. The dominant noise source today — disable "
                    "only when you want to inspect classifier-purges in "
                    "isolation."
                ),
            },
            "purge_classifier_rejects": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Purge pages that the current classifier no longer "
                    "admits. Set false when you only want to clean stubs "
                    "without re-running the classifier."
                ),
            },
            "stub_threshold": {
                "type": "number",
                "default": DEFAULT_STUB_THRESHOLD,
                "minimum": 0.0,
                "maximum": 1.0,
                "description": (
                    # source: ADR-0465
                    "Fraction of content lines that must be placeholder markers for "
                    "stub classification. Default 0.5; lower values also match "
                    "mixed-content pages."
                ),
            },
            "max_purges": {
                "type": "integer",
                "minimum": 0,
                "description": (
                    "Cap on how many pages this invocation may delete. "
                    "Acts as a safety rail against a buggy classifier "
                    "change wiping the whole wiki in one shot — pages "
                    "beyond the cap stay on disk and surface again on "
                    "the next call so cleanup proceeds gradually. Omit "
                    "(or pass 0) to disable the cap; callers in "
                    "autonomous mode (`consolidate`) supply a small "
                    "value, one-shot human sweeps pass 0 to remove all."
                ),
            },
            "purge_shallow": {
                "type": "boolean",
                "default": True,
                "description": (
                    "Purge pages whose body has fewer than "
                    "`shallow_threshold` prose chars — typically "
                    "auto-generated file-doc dumps that carry only "
                    "metadata and import lists, no actual "
                    "explanation. These take space and mislead readers."
                ),
            },
            "shallow_threshold": {
                "type": "integer",
                "default": DEFAULT_SHALLOW_THRESHOLD,
                "minimum": 0,
                "description": (
                    "Minimum prose-char count a page must carry to "
                    "escape the shallow filter. Default 500; pages "
                    "below this are flagged."
                ),
            },
        },
    },
}


@dataclass
class _Sweep:
    """Running tally of one purge pass over the pages in scope."""

    apply: bool
    max_purges: int | None
    kept: list[str] = field(default_factory=list)
    purged: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    errored: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reasons: dict[str, int] = field(
        default_factory=lambda: {"stub": 0, "shallow": 0, "classifier_reject": 0}
    )
    placeholder_lines: int = 0
    cap_reached: bool = False

    @property
    def scanned(self) -> int:
        """Pages this pass actually looked at, failures included.

        A page that raised was visited, not missed; folding it into
        ``unscanned`` would hide an I/O fault inside the coverage gap
        that number exists to expose (issue #622).
        """
        return (
            len(self.kept) + len(self.purged) + len(self.deferred) + len(self.errored)
        )

    def _reject(self, md: Path, rel: str, reason: str) -> None:
        # Cap applies only when ``apply`` is True — dry-run reports the
        # full count so operators see the actual backlog.
        if self.apply and self.max_purges is not None:
            if len(self.purged) >= self.max_purges:
                self.deferred.append(rel)
                self.cap_reached = True
                return
        self.purged.append(rel)
        self.reasons[reason] = self.reasons.get(reason, 0) + 1
        if reason == "stub":
            self.placeholder_lines += placeholder_count(
                md.read_text(encoding="utf-8", errors="ignore")
            )
        if self.apply:
            md.unlink()

    def visit(self, md: Path, rel: str, axes: RejectAxes) -> None:
        """Evaluate one in-scope page and record what happened to it."""
        try:
            _kind, _tags, reason, _score = evaluate_page(md, axes)
            if reason is None:
                self.kept.append(rel)
            else:
                self._reject(md, rel, reason)
        except (OSError, ValueError) as exc:
            self.errored.append(rel)
            self.errors.append(f"{rel}: {exc}")


def _prune_empty_dirs(root: Path) -> None:
    """Drop directories an apply emptied so the tree stays tidy."""
    for dir_path in sorted(root.rglob("*"), key=lambda p: -len(p.parts)):
        if (
            dir_path.is_dir()
            and not any(dir_path.iterdir())
            and not dir_path.name.startswith("_")
            and dir_path != root
        ):
            try:
                dir_path.rmdir()
            except OSError:
                pass


def _axes_from_args(args: dict[str, Any]) -> RejectAxes:
    return RejectAxes(
        check_stub=bool(args.get("purge_stubs", True)),
        check_shallow=bool(args.get("purge_shallow", True)),
        check_classifier=bool(args.get("purge_classifier_rejects", True)),
        stub_threshold=float(args.get("stub_threshold") or DEFAULT_STUB_THRESHOLD),
        shallow_threshold=int(
            args.get("shallow_threshold") or DEFAULT_SHALLOW_THRESHOLD
        ),
    )


def _max_purges_from_args(args: dict[str, Any]) -> int | None:
    raw = args.get("max_purges")
    return int(raw) if raw is not None and int(raw) > 0 else None


def _report(sweep: _Sweep, census, root: Path) -> dict[str, Any]:
    scanned = sweep.scanned
    return {
        "applied": sweep.apply,
        "scanned": scanned,
        # The denominator ``scanned`` has to be read against: how many
        # pages the wiki holds, and how many this sweep never looked at.
        "wiki_pages_total": census.pages_total,
        "unscanned": max(census.pages_total - scanned, 0),
        "unrecognised_dirs": sorted(census.unrecognised),
        "errored": len(sweep.errored),
        "kept": len(sweep.kept),
        "purged": len(sweep.purged),
        "purged_paths": sweep.purged,
        "purged_reasons": sweep.reasons,
        "deferred": len(sweep.deferred),
        # Sample only — the full count is the metric.
        "deferred_paths": sweep.deferred[:50],
        "cap_reached": sweep.cap_reached,
        "max_purges": sweep.max_purges,
        "placeholder_lines_purged": sweep.placeholder_lines,
        "errors": sweep.errors,
        "root": str(root),
    }


async def handler(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Purge wiki pages that no longer earn their place."""
    args = args or {}
    root = Path(WIKI_ROOT).expanduser()
    if not root.exists():
        return {"error": f"wiki root does not exist: {root}"}

    kind_filter = args.get("kind")
    target_dirs = {str(kind_filter)} if kind_filter else set(PAGE_DIRS)
    in_scope, census = candidate_pages(root, target_dirs)

    axes = _axes_from_args(args)
    sweep = _Sweep(
        apply=bool(args.get("apply", False)),
        max_purges=_max_purges_from_args(args),
    )
    for md in in_scope:
        sweep.visit(md, str(md.relative_to(root)), axes)

    if sweep.apply and sweep.purged:
        _prune_empty_dirs(root)

    return _report(sweep, census, root)
