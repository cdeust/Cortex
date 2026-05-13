#!/usr/bin/env python3
"""Pilot migration analyzer — Phase 2 of ADR-2244.

Walks the methodology wiki, runs each page's body through the new
data-driven classifier (``mcp_server.core.wiki_classifier.classify_memory``,
post-#27/#28), and produces a Markdown report showing the proposed
modern 4-tuple (kind, lifecycle, audience, provenance) for each page
alongside its current legacy ``kind``.

Goal: human-reviewable accuracy check before any bulk re-bucketing
(Phase 4). The ADR-2244 acceptance criterion is ≥ 90% kind agreement
with human judgment on a ~100-page representative sample.

Usage
-----

    uv run scripts/wiki_pilot_migration.py \\
        --wiki ~/.claude/methodology/wiki \\
        --sample-size 100 \\
        --out scripts/wiki-pilot-report.md

By default samples are stratified across the current ``kind`` directories
so the report exercises ADRs, specs, lessons, notes, references, etc.
without being swamped by the 7,820 file-doc notes.

Read-only. The script never writes to the wiki itself.
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Ensure mcp_server is importable when run from the Cortex repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_server.core.wiki_classifier import classify_memory  # noqa: E402


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<fm>.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True)
class PageRecord:
    """One row of the migration report."""

    path: str
    legacy_kind: str
    title: str
    content_length: int
    proposed_kind: str | None
    proposed_lifecycle: str | None
    proposed_audience: tuple[str, ...]
    proposed_provenance: str | None
    rejected: bool
    rejection_reason: str
    kind_agreement: str  # "kept" | "changed" | "n/a"


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Cheap YAML-ish parser; returns (frontmatter_dict, body).

    Handles three patterns observed in the wiki:
      1. ``key: value`` scalars.
      2. ``key: [a, b, c]`` inline lists.
      3. ``key:`` followed by indented ``  - item`` block lists.

    Lists land as Python ``list[str]``; scalars as ``str``. Indentation
    inside multi-line scalars (folded blocks etc.) is not preserved —
    sufficient for the pilot since we only care about ``tags``, ``kind``,
    and ``title``.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text

    fm: dict[str, object] = {}
    current_list_key: str | None = None
    current_list: list[str] = []

    def _close_list() -> None:
        nonlocal current_list_key, current_list
        if current_list_key is not None:
            fm[current_list_key] = current_list
            current_list_key = None
            current_list = []

    for raw in m.group("fm").splitlines():
        stripped = raw.strip()
        if not stripped:
            _close_list()
            continue
        # Block-list item: indented, starts with `-`.
        if (
            current_list_key is not None
            and raw.startswith(" ")
            and stripped.startswith("- ")
        ):
            current_list.append(stripped[2:].strip().strip("'\""))
            continue
        # Otherwise this line ends any open list.
        _close_list()
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            # Empty value → either a block list follows, or scalar with no value.
            current_list_key = key
            current_list = []
            continue
        if value.startswith("[") and value.endswith("]"):
            fm[key] = [
                t.strip().strip("'\"") for t in value[1:-1].split(",") if t.strip()
            ]
            continue
        fm[key] = value.strip("'\"")

    _close_list()
    return fm, text[m.end() :]


def _extract_tags(fm: dict[str, object]) -> list[str]:
    """Pull tags from frontmatter.

    Accepts the value as ``list[str]`` (block list, inline list) or
    ``str`` (comma-separated scalar). Empty/missing → ``[]``.
    """
    raw = fm.get("tags", "")
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    if isinstance(raw, str) and raw:
        return [t.strip() for t in raw.split(",") if t.strip()]
    return []


def _legacy_kind_from_path(rel_path: str) -> str:
    """First path component is the legacy kind directory."""
    return rel_path.split("/", 1)[0]


def _strip_h1(body: str) -> str:
    """Drop a leading H1 heading if present (it's usually the title)."""
    lines = body.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        return "\n".join(lines[1:]).strip()
    return body.strip()


def _evaluate(
    path: str,
    text: str,
) -> PageRecord:
    fm, body = _parse_frontmatter(text)
    tags = _extract_tags(fm)
    title = str(fm.get("title", "")).strip()
    content = _strip_h1(body)
    if not content:
        content = title  # use the title for nearly-empty pages
    legacy_kind = _legacy_kind_from_path(path)

    try:
        verdict = classify_memory(content, tags)
    except Exception as exc:  # noqa: BLE001
        return PageRecord(
            path=path,
            legacy_kind=legacy_kind,
            title=title,
            content_length=len(content),
            proposed_kind=None,
            proposed_lifecycle=None,
            proposed_audience=(),
            proposed_provenance=None,
            rejected=True,
            rejection_reason=f"classifier raised: {type(exc).__name__}: {exc}",
            kind_agreement="n/a",
        )

    if verdict is None:
        return PageRecord(
            path=path,
            legacy_kind=legacy_kind,
            title=title,
            content_length=len(content),
            proposed_kind=None,
            proposed_lifecycle=None,
            proposed_audience=(),
            proposed_provenance=None,
            rejected=True,
            rejection_reason="admission gate rejected (audit-tag, noise, or low score)",
            kind_agreement="n/a",
        )

    # Map legacy directory name → modern kind for the "kept vs changed" view.
    from mcp_server.shared.wiki_classification import normalize_legacy_kind

    normalized_legacy = normalize_legacy_kind(legacy_kind)
    agreement = "kept" if verdict.kind == normalized_legacy else "changed"

    return PageRecord(
        path=path,
        legacy_kind=legacy_kind,
        title=title,
        content_length=len(content),
        proposed_kind=verdict.kind,
        proposed_lifecycle=verdict.lifecycle,
        proposed_audience=tuple(verdict.audience),
        proposed_provenance=verdict.provenance,
        rejected=False,
        rejection_reason="",
        kind_agreement=agreement,
    )


def _collect_pages(wiki_root: Path) -> list[Path]:
    """All .md pages under wiki_root excluding ``.generated/``."""
    out: list[Path] = []
    for md in wiki_root.rglob("*.md"):
        rel = md.relative_to(wiki_root)
        if rel.parts and rel.parts[0].startswith("."):
            continue
        out.append(md)
    return out


def _stratified_sample(
    pages: list[Path],
    wiki_root: Path,
    sample_size: int,
    rng: random.Random,
) -> list[Path]:
    """Sample evenly across the legacy ``kind`` directories.

    Each kind contributes up to ``sample_size / N_kinds`` pages. Kinds
    with fewer pages contribute everything they have; the remainder is
    redistributed so the total approaches ``sample_size``.
    """
    by_kind: dict[str, list[Path]] = defaultdict(list)
    for p in pages:
        rel = p.relative_to(wiki_root)
        by_kind[rel.parts[0]].append(p)

    n_kinds = len(by_kind)
    if n_kinds == 0:
        return []

    per_kind = max(sample_size // n_kinds, 1)
    sampled: list[Path] = []
    leftover_quota = sample_size
    for kind, files in by_kind.items():
        take = min(per_kind, len(files), leftover_quota)
        sampled.extend(rng.sample(files, take))
        leftover_quota -= take

    if leftover_quota > 0:
        remaining = [p for p in pages if p not in set(sampled)]
        rng.shuffle(remaining)
        sampled.extend(remaining[:leftover_quota])

    return sampled


def _format_report(records: list[PageRecord], wiki_root: Path) -> str:
    """Render the migration report as Markdown."""
    n = len(records)
    n_rejected = sum(1 for r in records if r.rejected)
    n_admitted = n - n_rejected
    n_kept = sum(1 for r in records if r.kind_agreement == "kept")
    n_changed = sum(1 for r in records if r.kind_agreement == "changed")

    by_legacy: dict[str, int] = defaultdict(int)
    by_proposed: dict[str, int] = defaultdict(int)
    by_transition: dict[tuple[str, str | None], int] = defaultdict(int)
    by_lifecycle: dict[str | None, int] = defaultdict(int)
    by_audience: dict[str, int] = defaultdict(int)
    by_provenance: dict[str | None, int] = defaultdict(int)
    rejection_reasons: dict[str, int] = defaultdict(int)

    for r in records:
        by_legacy[r.legacy_kind] += 1
        by_proposed[r.proposed_kind or "<rejected>"] += 1
        by_transition[(r.legacy_kind, r.proposed_kind)] += 1
        if not r.rejected:
            by_lifecycle[r.proposed_lifecycle] += 1
            for a in r.proposed_audience:
                by_audience[a] += 1
            by_provenance[r.proposed_provenance] += 1
        else:
            rejection_reasons[r.rejection_reason] += 1

    lines: list[str] = []
    lines.append("# ADR-2244 Phase 2 — Pilot migration report")
    lines.append("")
    lines.append(f"Wiki root: `{wiki_root}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Sample size:** {n}")
    lines.append(
        f"- **Admitted by new classifier:** {n_admitted} ({_pct(n_admitted, n)})"
    )
    lines.append(
        f"- **Rejected (admission gate):** {n_rejected} ({_pct(n_rejected, n)})"
    )
    lines.append(
        f"- **Kind kept (legacy → modern direct map):** {n_kept} ({_pct(n_kept, n_admitted)} of admitted)"
    )
    lines.append(
        f"- **Kind changed:** {n_changed} ({_pct(n_changed, n_admitted)} of admitted)"
    )
    lines.append("")
    lines.append("## Distribution — legacy kinds in the sample")
    lines.append("")
    lines.append("| Legacy kind | Pages |")
    lines.append("|---|---:|")
    for k, c in sorted(by_legacy.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {c} |")
    lines.append("")
    lines.append("## Distribution — proposed modern kinds")
    lines.append("")
    lines.append("| Proposed kind | Pages |")
    lines.append("|---|---:|")
    for k, c in sorted(by_proposed.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {c} |")
    lines.append("")
    lines.append("## Transition matrix (legacy → proposed)")
    lines.append("")
    lines.append("| From | To | Count |")
    lines.append("|---|---|---:|")
    for (frm, to), c in sorted(by_transition.items(), key=lambda kv: -kv[1]):
        to_str = to if to is not None else "<rejected>"
        lines.append(f"| `{frm}` | `{to_str}` | {c} |")
    lines.append("")
    lines.append("## Proposed facet distributions (admitted pages only)")
    lines.append("")
    lines.append("### Lifecycle")
    lines.append("")
    lines.append("| Value | Pages |")
    lines.append("|---|---:|")
    for k, c in sorted(by_lifecycle.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {c} |")
    lines.append("")
    lines.append("### Audience (multi-valued — counted per occurrence)")
    lines.append("")
    lines.append("| Value | Pages |")
    lines.append("|---|---:|")
    for k, c in sorted(by_audience.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {c} |")
    lines.append("")
    lines.append("### Provenance")
    lines.append("")
    lines.append("| Value | Pages |")
    lines.append("|---|---:|")
    for k, c in sorted(by_provenance.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{k}` | {c} |")
    lines.append("")
    if rejection_reasons:
        lines.append("## Rejection reasons")
        lines.append("")
        lines.append("| Reason | Pages |")
        lines.append("|---|---:|")
        for reason, c in sorted(rejection_reasons.items(), key=lambda kv: -kv[1]):
            lines.append(f"| {reason} | {c} |")
        lines.append("")

    lines.append("## Per-page proposals")
    lines.append("")
    lines.append(
        "| Path | Legacy → Proposed | Lifecycle | Audience | Provenance | Status |"
    )
    lines.append("|---|---|---|---|---|---|")
    for r in records:
        if r.rejected:
            status = f"❌ {r.rejection_reason}"
            transition = f"`{r.legacy_kind}` → —"
            lifecycle = "—"
            audience = "—"
            provenance = "—"
        else:
            status = "✅ kept" if r.kind_agreement == "kept" else "🔁 changed"
            transition = f"`{r.legacy_kind}` → `{r.proposed_kind}`"
            lifecycle = f"`{r.proposed_lifecycle}`"
            audience = ", ".join(f"`{a}`" for a in r.proposed_audience)
            provenance = f"`{r.proposed_provenance}`"
        lines.append(
            f"| `{r.path}` | {transition} | {lifecycle} | {audience} | {provenance} | {status} |"
        )
    lines.append("")
    return "\n".join(lines)


def _pct(num: int, denom: int) -> str:
    if denom == 0:
        return "0.0%"
    return f"{num / denom * 100:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--wiki",
        type=Path,
        default=Path.home() / ".claude" / "methodology" / "wiki",
        help="Wiki root directory.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=100,
        help="Pages to sample. Stratified by legacy kind directory.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "wiki-pilot-report.md",
        help="Path to write the Markdown report.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260512,
        help="RNG seed for the sample (deterministic by default).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate every page (ignores --sample-size).",
    )
    args = parser.parse_args()

    wiki_root: Path = args.wiki.expanduser().resolve()
    if not wiki_root.is_dir():
        print(f"error: wiki root not found: {wiki_root}", file=sys.stderr)
        return 2

    print(f"scanning {wiki_root}", file=sys.stderr)
    pages = _collect_pages(wiki_root)
    print(f"found {len(pages)} pages", file=sys.stderr)

    if args.all:
        sampled = pages
    else:
        rng = random.Random(args.seed)
        sampled = _stratified_sample(pages, wiki_root, args.sample_size, rng)
    print(f"evaluating {len(sampled)} pages", file=sys.stderr)

    records: list[PageRecord] = []
    for p in sampled:
        rel = p.relative_to(wiki_root)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"  skip {rel}: {exc}", file=sys.stderr)
            continue
        records.append(_evaluate(str(rel), text))

    report = _format_report(records, wiki_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"wrote report: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
