"""Benchmark result reporting — shared formatting across all runners."""

from __future__ import annotations


def print_header(title: str):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)
    print()


def print_category_table(
    results: dict[str, dict],
    columns: list[str],
    reference: dict[str, float] | None = None,
    ref_label: str = "Ref",
):
    """Print a per-category results table.

    Args:
        results: {category: {metric: value, ...}}
        columns: which metrics to show as columns
        reference: optional {category: score} for comparison column
    """
    # Header
    header = f"{'Category':<28}"
    for col in columns:
        header += f" {col:>6}"
    if reference:
        header += f"  {ref_label:>8}"
    print(header)
    print("-" * (30 + 7 * len(columns) + (10 if reference else 0)))

    # Rows
    for cat, metrics in sorted(results.items()):
        row = f"{cat:<28}"
        for col in columns:
            val = metrics.get(col, 0.0)
            if col.startswith("r") or col.startswith("R"):
                row += f" {val:>5.1%}"
            else:
                row += f" {val:>6.3f}"
        if reference:
            ref = reference.get(cat)
            row += f"  {ref:>8.3f}" if ref is not None else "       —"
        print(row)


def print_summary_line(
    label: str,
    metrics: dict[str, float],
    columns: list[str],
    reference_value: float | None = None,
):
    """Print a single summary/overall row."""
    row = f"{label:<28}"
    for col in columns:
        val = metrics.get(col, 0.0)
        if col.startswith("r") or col.startswith("R"):
            row += f" {val:>5.1%}"
        else:
            row += f" {val:>6.3f}"
    if reference_value is not None:
        row += f"  {reference_value:>8.3f}"
    print(row)


def print_timing(total_time: float, count: int, unit: str = "questions"):
    """Print timing summary."""
    rate = total_time / max(count, 1)
    print(f"\nTotal time: {total_time:.1f}s ({rate:.1f}s/{unit})")
    print(f"{unit.capitalize()}: {count}")
