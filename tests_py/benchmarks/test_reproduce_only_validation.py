"""`--only` fails closed: an unknown selector must never yield an empty run.

Observed on 2026-09-09: `reproduce.sh --only longmemeval-s` (the artifact
name the script itself prints) matched nothing, started and stopped a
container, wrote MANIFEST.json and START_SNAPSHOT.json, measured nothing and
exited 0. These tests pin the library that now validates the flag, and the
script's behaviour end to end.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "benchmarks/lib/bench_only.sh"
SCRIPT = REPO / "benchmarks/reproduce.sh"


def _validate(only: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; ONLY="$2"; validate_only && printf "%s" "$ONLY"',
            "bash",
            str(LIBRARY),
            only,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("longmemeval", "longmemeval"),
        ("longmemeval-s", "longmemeval"),
        ("beam-100K", "beam"),
        ("longmemeval-s,beam-100K,locomo", "longmemeval,beam,locomo"),
        ("decision-ids", "decision-ids"),
    ],
)
def test_aliases_normalise_to_the_tokens_want_bench_matches(
    given: str, expected: str
) -> None:
    done = _validate(given)
    assert done.returncode == 0, done.stderr
    assert done.stdout == expected


@pytest.mark.parametrize(
    "given", ["bogus", "longmemeval,bogus", "longmemeval,", ",locomo"]
)
def test_unknown_or_empty_token_fails_closed_naming_the_accepted_values(
    given: str,
) -> None:
    done = _validate(given)
    assert done.returncode == 2
    assert "accepted:" in done.stderr
    for token in ("longmemeval", "locomo", "beam", "decision-ids"):
        assert token in done.stderr


def test_empty_only_means_every_benchmark() -> None:
    done = _validate("")
    assert done.returncode == 0
    assert done.stdout == ""


def test_script_rejects_an_unknown_selector_before_doing_anything(
    tmp_path: Path,
) -> None:
    """End to end on the real script: exit 2, the message, and no artifact.

    Validation runs before any `uv run` or container start, so this test
    needs neither Docker nor a synced environment and returns in well under a
    second. The pre-fix script instead built the package, started a container
    and wrote MANIFEST.json for an empty run.
    """
    out = tmp_path / "out"
    done = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--only",
            "bogus",
            "--no-ablation",
            "--results-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert done.returncode == 2, done.stdout + done.stderr
    assert "selects no benchmark" in done.stderr
    assert not out.exists() or not any(out.iterdir())
