"""Replay the committed fuzz corpora in the normal test suite.

The fuzzers need atheris, which publishes manylinux x86_64 wheels for
cpython 3.12-3.14 and nothing else — so no contributor on a Mac, and no
Windows CI leg, can run a campaign. Without this file the harnesses'
properties would be checked on exactly one job, and every crash the fuzzer
has ever found would be recorded only in a directory nothing reads.

Replaying needs no atheris: each harness exposes `consume(data: bytes)`.
"""

from pathlib import Path

import pytest

from fuzz import replay_corpus as _replay_corpus_module

_REPLAYER = Path(__file__).resolve().parents[2] / "fuzz" / "replay_corpus.py"


def _replayer():
    # A normal package-qualified import (not importlib.util.spec_from_file_
    # location, which registered this module as bare "replay_corpus" instead
    # of "fuzz.replay_corpus" -- mutmut's trampoline dispatch keys mutants by
    # the latter, so the file-path import made every mutant in this module
    # unreachable by mutmut's coverage tracking: "tests recorded trampoline
    # hits but none match any mutant key" (issue #282 sweep, reproduced via
    # `mutmut run` on this file). Package-qualified import fixes both the
    # test (unchanged behavior) and the mutation-testing blind spot.
    return _replay_corpus_module


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
    corpus = list(module.harness_inputs(target))
    assert corpus, (
        f"{harness} has an empty corpus — a harness with no inputs asserts"
        " nothing, and every crash it once found would be unpinned"
    )
    assert module.replay(target) == len(corpus)


# --- harness_consume error paths (issue #282: dataclass mutation blindspot)
#
# harness_consume is a free function carrying logic that used to live on
# Harness methods; @dataclass-decorated classes are excluded from mutmut's
# mutation generator entirely, so these error paths need direct negative-
# case tests or they carry zero mutation coverage no matter how the
# happy-path replay test above is parametrized (real harnesses always
# import cleanly and always expose consume()).


def test_harness_consume_missing_consume_raises_exact_message(tmp_path, monkeypatch):
    """A harness module that fails to expose `consume(data: bytes)` must
    raise RuntimeError with the exact diagnostic message, not a bare
    AttributeError from an unguarded getattr — and the message content
    (not just its type) is what tells a contributor what to fix."""
    monkeypatch.setattr(_replay_corpus_module, "FUZZ_DIR", tmp_path)
    harness_name = "fuzz_missing_consume"
    module_path = tmp_path / f"{harness_name}.py"
    module_path.write_text("VALUE = 1\n")
    harness = _replay_corpus_module.Harness(name=harness_name)
    with pytest.raises(RuntimeError) as excinfo:
        _replay_corpus_module.harness_consume(harness)
    assert str(excinfo.value) == (
        f"{module_path}: no consume(data: bytes) —"
        " every harness must expose one so its property is runnable"
        " without atheris"
    )


def test_harness_consume_preregisters_module_before_exec(tmp_path, monkeypatch):
    """harness_consume must insert the freshly-created module into
    sys.modules[spec.name] BEFORE calling exec_module on it (see the
    function's own docstring: @dataclass and other typing constructs
    resolve annotations via sys.modules[cls.__module__], which would be
    absent for a module loaded from a bare file path). A harness whose
    top level checks `sys.modules[__name__]` observes itself, not None,
    only if that ordering holds."""
    monkeypatch.setattr(_replay_corpus_module, "FUZZ_DIR", tmp_path)
    harness_name = "fuzz_selfcheck"
    (tmp_path / f"{harness_name}.py").write_text(
        "import sys\n"
        "assert sys.modules[__name__] is not None, (\n"
        "    'harness module must be pre-registered in sys.modules before exec'\n"
        ")\n"
        "def consume(data: bytes) -> None:\n"
        "    pass\n"
    )
    harness = _replay_corpus_module.Harness(name=harness_name)
    consume = _replay_corpus_module.harness_consume(harness)
    consume(b"")


def test_replay_wraps_consume_failure_with_input_context(tmp_path, monkeypatch):
    """`replay()`'s try/except re-raises with which corpus input and which
    original exception caused the failure -- the diagnostic context, not
    just the fact that something in the corpus failed."""
    monkeypatch.setattr(_replay_corpus_module, "FUZZ_DIR", tmp_path)
    monkeypatch.setattr(_replay_corpus_module, "CORPUS_DIR", tmp_path / "corpus")
    harness_name = "fuzz_always_raises"
    (tmp_path / f"{harness_name}.py").write_text(
        "def consume(data: bytes) -> None:\n    raise ValueError('boom')\n"
    )
    corpus_dir = tmp_path / "corpus" / harness_name
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "seed-1").write_bytes(b"x")
    harness = _replay_corpus_module.Harness(name=harness_name)
    with pytest.raises(AssertionError) as excinfo:
        _replay_corpus_module.replay(harness)
    assert str(excinfo.value) == (
        f"{harness_name} failed on committed corpus input seed-1: ValueError: boom"
    )
    assert excinfo.value.__cause__ is not None
    assert isinstance(excinfo.value.__cause__, ValueError)
