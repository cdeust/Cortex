#!/usr/bin/env python3
"""Fuzz the hand-rolled YAML frontmatter parser.

Why this target
---------------
`parse_yaml_frontmatter` is a hand-written parser — not a hardened library —
and it reads the front matter of memory and wiki documents. Those documents
carry LLM output and anything else that reaches the ingest path, so its input
is untrusted by the standard's own rule (§13.1 D2). A parser over untrusted
text with no fuzzing is exactly where crash-on-input bugs outlive a green
unit suite, because tests encode the shapes the author thought of.

It is also regex-driven (`^---\\s*\\n([\\s\\S]*?)\\n---\\s*\\n([\\s\\S]*)$`
over the whole document), which puts pathological backtracking on the table
for a document a user can supply. libFuzzer's own timeout is what surfaces
that; it is not something an assertion can express.

Properties asserted (all total-function properties, not parse correctness):
  * returns a FrontmatterResult for ANY input, never raises;
  * `meta` is always a dict — callers index it without a None check;
  * every key is lowercased, which is the documented contract;
  * `body` is a substring of the input — the parser must not invent text.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Anchored to this file: the harness runs from the repo root in CI and from
# an arbitrary working directory inside a ClusterFuzzLite container.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_server.shared.yaml_parser import (  # noqa: E402
    FrontmatterResult,
    parse_yaml_frontmatter,
)


def consume(data: bytes) -> None:
    """One fuzz iteration. Shared by atheris and by replay_corpus.py."""
    # The function is typed `str | None`; the fuzzer speaks bytes. Decoding
    # with surrogateescape rather than errors="ignore" keeps lone surrogates
    # and other ill-formed sequences in play, instead of sanitising away the
    # inputs most likely to break a hand-rolled parser.
    text = data.decode("utf-8", errors="surrogateescape")

    result = parse_yaml_frontmatter(text)

    if not isinstance(result, FrontmatterResult):
        raise AssertionError(f"returned {type(result).__name__}, not FrontmatterResult")
    if not isinstance(result.meta, dict):
        raise AssertionError(f"meta is {type(result.meta).__name__}, not dict")
    if not isinstance(result.body, str):
        raise AssertionError(f"body is {type(result.body).__name__}, not str")
    for key, value in result.meta.items():
        if key != key.lower():
            raise AssertionError(f"meta key {key!r} is not lowercased")
        if not isinstance(value, str):
            raise AssertionError(f"meta[{key!r}] is {type(value).__name__}, not str")
    # The parser only ever slices and strips, so the body it returns must be
    # text that was already present. A violation would mean it fabricated or
    # duplicated document content — which a type check alone cannot see.
    if result.body and result.body not in text:
        raise AssertionError("body is not a substring of the input")


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
