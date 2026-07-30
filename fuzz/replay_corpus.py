#!/usr/bin/env python3
"""Replay every committed fuzz corpus input through its harness.

Why this exists
---------------
The fuzzers themselves are CI-only: atheris publishes manylinux x86_64
wheels for cpython 3.12-3.14 and nothing else, so a contributor on a Mac
cannot run them at all. That would leave the harnesses' properties unchecked
on every machine except one CI job — and a property nobody can run locally
is one that rots.

This replayer needs no atheris. It imports each harness's `consume` and
feeds it the committed corpus, so:

  * every crash the fuzzer ever found stays fixed (the corpus is the
    regression suite — a reproducer is committed, not just described);
  * the harnesses stay importable and their assertions stay meaningful,
    rather than silently breaking against a renamed field and only failing
    the next time someone runs a fuzz campaign;
  * the properties run in the normal test suite, on every platform.

It is wired into pytest via tests_py/fuzz/test_corpus_replay.py, so this is
executed by the same `pytest` run as everything else.

Usage:
    python3 fuzz/replay_corpus.py            # replay all corpora
    python3 fuzz/replay_corpus.py --list     # show harnesses and counts
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

FUZZ_DIR = Path(__file__).resolve().parent
CORPUS_DIR = FUZZ_DIR / "corpus"


@dataclass(frozen=True)
class Harness:
    """One fuzz harness and the corpus directory that feeds it.

    Data only — deliberately no methods. mutmut's mutation generator
    categorically excludes the body of any `@dataclass`-decorated class
    (`mutmut/mutation/file_mutation.py:236`), so logic placed on methods
    here would carry zero mutation coverage no matter how the test loader
    names the module (issue #262 3rd pass; issue #282).
    `harness_module_path` / `harness_corpus_path` / `harness_consume` /
    `harness_inputs` below carry the same logic as free functions instead.
    """

    name: str


def harness_module_path(harness: "Harness") -> Path:
    return FUZZ_DIR / f"{harness.name}.py"


def harness_corpus_path(harness: "Harness") -> Path:
    return CORPUS_DIR / harness.name


def harness_consume(harness: "Harness") -> Callable[[bytes], None]:
    """Import the harness and hand back its single-iteration entry point."""
    module_path = harness_module_path(harness)
    spec = importlib.util.spec_from_file_location(harness.name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{module_path}: not importable")
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass (and typing constructs
    # generally) resolve annotations via sys.modules[cls.__module__],
    # which is None for a module loaded from a path and never inserted.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    consume = getattr(module, "consume", None)
    if consume is None:
        raise RuntimeError(
            f"{module_path}: no consume(data: bytes) —"
            " every harness must expose one so its property is runnable"
            " without atheris"
        )
    return consume


def harness_inputs(harness: "Harness") -> Iterator[tuple[Path, bytes]]:
    directory = harness_corpus_path(harness)
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if path.is_file():
            yield path, path.read_bytes()


def discover() -> list[Harness]:
    """Every fuzz_*.py beside this file.

    Discovered rather than listed so a new harness is picked up by adding
    the file — and so a harness cannot be added without its property being
    replayed (§1.2: no edit here to extend the set).
    """
    return [
        Harness(name=path.stem)
        for path in sorted(FUZZ_DIR.glob("fuzz_*.py"))
        if path.is_file()
    ]


def replay(harness: Harness) -> int:
    """Run one harness over its corpus. Returns the number of inputs run."""
    consume = harness_consume(harness)
    count = 0
    for path, data in harness_inputs(harness):
        try:
            consume(data)
        except Exception as error:
            raise AssertionError(
                f"{harness.name} failed on committed corpus input {path.name}:"
                f" {type(error).__name__}: {error}"
            ) from error
        count += 1
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="list harnesses and corpus sizes"
    )
    args = parser.parse_args(argv)

    harnesses = discover()
    if not harnesses:
        print("no fuzz_*.py harnesses found", file=sys.stderr)
        return 1

    if args.list:
        for harness in harnesses:
            print(f"{harness.name}: {sum(1 for _ in harness_inputs(harness))} input(s)")
        return 0

    total = 0
    for harness in harnesses:
        ran = replay(harness)
        total += ran
        print(f"{harness.name}: {ran} corpus input(s) replayed")
    print(f"{total} input(s) across {len(harnesses)} harness(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
