"""Replay the committed fuzz corpora in the normal test suite.

The fuzzers need atheris, which publishes manylinux x86_64 wheels for
cpython 3.12-3.14 and nothing else — so no contributor on a Mac, and no
Windows CI leg, can run a campaign. Without this file the harnesses'
properties would be checked on exactly one job, and every crash the fuzzer
has ever found would be recorded only in a directory nothing reads.

Replaying needs no atheris: each harness exposes `consume(data: bytes)`.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

_REPLAYER = Path(__file__).resolve().parents[2] / "fuzz" / "replay_corpus.py"


def _replayer():
    spec = importlib.util.spec_from_file_location("replay_corpus", _REPLAYER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_the_replayer_is_present():
    assert _REPLAYER.is_file(), f"{_REPLAYER} is missing"


def test_at_least_one_harness_exists():
    """A fuzzing setup that discovers nothing would pass everything."""
    assert _replayer().discover(), "no fuzz_*.py harnesses discovered"


@pytest.mark.parametrize(
    "harness", [h.name for h in _replayer().discover()], ids=lambda n: n
)
def test_harness_holds_on_its_whole_corpus(harness):
    module = _replayer()
    target = next(h for h in module.discover() if h.name == harness)
    corpus = list(target.inputs())
    assert corpus, (
        f"{harness} has an empty corpus — a harness with no inputs asserts"
        " nothing, and every crash it once found would be unpinned"
    )
    assert module.replay(target) == len(corpus)
