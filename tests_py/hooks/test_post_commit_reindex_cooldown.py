"""The post-commit cooldown file: its encoding, its window and its pruning (#692).

``gated_files.write_json`` encodes the cooldown JSON as UTF-8, and the hook read it
back with a bare ``read_text()``, which uses the locale code page (cp1252 on
Windows). ``-X warn_default_encoding`` turns each default-encoding file open into an
``EncodingWarning``, made an error in the subprocess test, so that proof holds on
any platform. The in-process tests pin the rest of ``_check_cooldown`` and
``_update_cooldown``, which the diff-scoped mutation gate (ADR-1122) mutates whole.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_server.hooks import post_commit_reindex as hook

ROOT = Path(__file__).resolve().parents[2]
REPO = "C:/Users/Clément/projets/日本語"
CHILD = f"""
import sys
from pathlib import Path
from mcp_server.hooks import post_commit_reindex as hook

hook._COOLDOWN_FILE = Path(sys.argv[1]) / "cooldown.json"
hook._update_cooldown({REPO!r})
hook._update_cooldown("/second/repo")
assert hook._check_cooldown({REPO!r}), "the cooldown entry was not read back"
"""
# source: CORTEX_REINDEX_COOLDOWN_SECONDS, set by each test to a round window.
WINDOW = 10


class _RecordingPath(type(Path())):
    """A real path that records the encoding of every ``read_text`` call."""

    encodings: list[str | None] = []

    def read_text(self, encoding=None, errors=None, **kwargs):
        type(self).encodings.append(encoding)
        return super().read_text(encoding=encoding, errors=errors, **kwargs)


@pytest.fixture
def cooldown(tmp_path, monkeypatch):
    path = _RecordingPath(tmp_path / "cooldown.json")
    _RecordingPath.encodings = []
    monkeypatch.setattr(hook, "_COOLDOWN_FILE", path)
    monkeypatch.setenv("CORTEX_REINDEX_COOLDOWN_SECONDS", str(WINDOW))
    return path


def _at(monkeypatch, now: float) -> None:
    monkeypatch.setattr(hook.time, "time", lambda: now)


def test_cooldown_round_trip_does_no_default_encoding_io(tmp_path: Path) -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-X",
            "warn_default_encoding",
            "-W",
            "error::EncodingWarning",
            "-c",
            CHILD,
            str(tmp_path),
        ],
        capture_output=True,
        env={"CORTEX_CLAUDE_DIR": str(tmp_path / "claude"), "PYTHONPATH": str(ROOT)},
        cwd=ROOT,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "backslashreplace")
    stored = (tmp_path / "cooldown.json").read_bytes().decode("utf-8")
    assert "/second/repo" in stored


def test_both_reads_name_utf8(cooldown, monkeypatch) -> None:
    _at(monkeypatch, 100.0)
    cooldown.write_text(json.dumps({"/a": 100.0}), encoding="utf-8")
    hook._update_cooldown("/b")
    assert hook._check_cooldown("/a")
    assert _RecordingPath.encodings == ["utf-8", "utf-8"]


def test_an_unknown_root_counts_from_the_epoch(cooldown, monkeypatch) -> None:
    cooldown.write_text(json.dumps({"/other": 1.0}), encoding="utf-8")
    _at(monkeypatch, WINDOW - 5)
    assert hook._check_cooldown("/unknown")
    _at(monkeypatch, WINDOW)
    assert not hook._check_cooldown("/unknown")


def test_the_window_end_is_outside_the_cooldown(cooldown, monkeypatch) -> None:
    cooldown.write_text(json.dumps({"/a": 50.0}), encoding="utf-8")
    _at(monkeypatch, 50.0 + WINDOW - 1)
    assert hook._check_cooldown("/a")
    _at(monkeypatch, 50.0 + WINDOW)
    assert not hook._check_cooldown("/a")


def test_an_update_keeps_the_other_repositories(cooldown, monkeypatch) -> None:
    cooldown.write_text(json.dumps({"/a": 1.0}), encoding="utf-8")
    _at(monkeypatch, 2.0)
    hook._update_cooldown("/b")
    assert json.loads(cooldown.read_text(encoding="utf-8")) == {"/a": 1.0, "/b": 2.0}


def _full_history(count: int) -> dict[str, float]:
    # The oldest entry has the lexically largest name, so neither a sort by name
    # nor insertion order agrees with a sort by time.
    return {f"/r{count - 1 - i:02d}": float(i + 1) for i in range(count)}


def test_a_full_file_drops_only_the_oldest_entry(cooldown, monkeypatch) -> None:
    cap = hook._MAX_COOLDOWN_ENTRIES
    history = _full_history(cap)
    cooldown.write_text(json.dumps(history), encoding="utf-8")
    _at(monkeypatch, 1000.0)
    hook._update_cooldown("/new")
    stored = json.loads(cooldown.read_text(encoding="utf-8"))
    oldest = min(history, key=history.__getitem__)
    assert len(stored) == cap
    assert "/new" in stored and oldest not in stored


def test_a_file_at_the_cap_is_not_pruned(cooldown, monkeypatch) -> None:
    history = _full_history(hook._MAX_COOLDOWN_ENTRIES - 1)
    cooldown.write_text(json.dumps(history), encoding="utf-8")
    _at(monkeypatch, 1000.0)
    hook._update_cooldown("/new")
    stored = json.loads(cooldown.read_text(encoding="utf-8"))
    assert list(stored) == [*history, "/new"]
