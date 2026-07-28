#!/usr/bin/env python3
"""Fuzz the wiki source-path canonicaliser against its own post-condition.

Why this target
---------------
`normalize_source_path` is a path canonicaliser, and canonicalisers are a
classic source of security defects: everything downstream compares, dedupes
or resolves the string it returns, so any input that survives normalisation
in two different spellings defeats whatever the comparison was protecting.

This harness asserts the post-condition the function's own docstring states,
which is exactly the check that was missing. Writing it found a live bug:
the original stripped "./" in a loop and then "/" once, so ".//./x" came out
as "./x" — still carrying the prefix the function exists to remove. Two
spellings of one document therefore normalised to two different strings, and
`extract_document_paths` dedupes on that result. Fixed in the same change;
this harness is what keeps it fixed.

Property: for ANY input the result is None, or a string with no leading "/"
and no leading "./" — idempotent under a second application.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.shared.wiki_source_paths import normalize_source_path  # noqa: E402


def consume(data: bytes) -> None:
    """One fuzz iteration. Shared by atheris and by replay_corpus.py."""
    raw = data.decode("utf-8", errors="surrogateescape")

    result = normalize_source_path(raw)

    if result is None:
        return
    if not isinstance(result, str):
        raise AssertionError(f"returned {type(result).__name__}, not str | None")
    if result.startswith("/"):
        raise AssertionError(f"leading slash survived: {result!r} (from {raw!r})")
    if result.startswith("./"):
        raise AssertionError(f"leading './' survived: {result!r} (from {raw!r})")
    if not result:
        raise AssertionError("returned empty string; the contract says None")
    # Idempotence is the property that makes the result usable as a dedup and
    # comparison key at all: normalising an already-normalised path must be a
    # no-op. The original defect was precisely a non-idempotent result.
    again = normalize_source_path(result)
    if again != result:
        raise AssertionError(f"not idempotent: {result!r} -> {again!r}")


def main() -> None:
    # Deferred deliberately, not for load time: atheris publishes no wheel for
    # macOS or aarch64, so a module-level import would make this harness
    # unimportable there — and replay_corpus.py imports it to run the property
    # without a fuzzer. Only main() needs the engine.
    import atheris  # noqa: PLC0415

    atheris.Setup(sys.argv, consume)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
