"""scripts/lib/precache_embedding_model.sh must never label a failed
pre-cache [ok] — issue #537.

Source: issue #537. Step 5/7 of scripts/setup.sh printed
"[ok] Embedding model cached" even when the pre-cache raised, because the
inline python one-liner caught the exception, printed a warning to a
stream the shell never inspected, and then exited 0 by falling off the
end of the try/except — reaching the end of the step, not succeeding at
it, was what drove the label. The fix removes the swallow so the outcome
is derived from the subprocess exit code, and extracts the step into
scripts/lib/precache_embedding_model.sh so both outcomes are drivable
here without running the rest of scripts/setup.sh (no PostgreSQL, no
brew, no real ~100MB download).

Each test sources the real library file and defines the same three
helper functions scripts/setup.sh defines before sourcing it
(ok/warn/spinner) — the production strings, not reimplementations of the
label logic. A shadow ``sentence_transformers`` module on PYTHONPATH
forces the real failure this issue observed (an import raising inside
the pre-cache) without mocking python3 itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_PATH = REPO_ROOT / "scripts" / "lib" / "precache_embedding_model.sh"

_HARNESS = """
set -euo pipefail
GREEN='\\033[0;32m'
YELLOW='\\033[1;33m'
NC='\\033[0m'
ok()   {{ echo -e "${{GREEN}}[ok]${{NC}} $1"; }}
warn() {{ echo -e "${{YELLOW}}[!!]${{NC}} $1"; }}
spinner() {{
    local pid=$1
    wait "$pid"
    spin_exit=$?
    return $spin_exit
}}
source "{lib_path}"
precache_embedding_model_step "{project_dir}" "{deps_dir}"
"""


def _run_step(
    tmp_path: Path, shadow_pythonpath: str | None
) -> subprocess.CompletedProcess:
    script = _HARNESS.format(
        lib_path=LIB_PATH, project_dir=REPO_ROOT, deps_dir=tmp_path / "deps"
    )
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
    if shadow_pythonpath is not None:
        env["PYTHONPATH"] = shadow_pythonpath
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_forced_failure_prints_warn_not_ok(tmp_path):
    """A real exception inside the pre-cache must yield [!!], never [ok]."""
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "sentence_transformers.py").write_text(
        "raise ModuleNotFoundError("
        "\"No module named 'numpy._core._multiarray_umath'\")\n"
    )

    result = _run_step(tmp_path, str(shadow_dir))

    print("--- forced-failure stdout ---")
    print(result.stdout)
    print("--- forced-failure stderr ---")
    print(result.stderr)

    assert "[ok]" not in result.stdout
    assert "[!!]" in result.stdout
    assert result.returncode == 1


def test_forced_success_prints_ok_not_warn(tmp_path):
    """A pre-cache that actually loads the model must yield [ok]."""
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "sentence_transformers.py").write_text(
        "class SentenceTransformer:\n"
        "    def __init__(self, *a, **k):\n"
        "        pass\n"
        "\n"
        "    def encode(self, texts):\n"
        "        class _Shape:\n"
        "            shape = (len(texts), 384)\n"
        "        return _Shape()\n"
    )

    result = _run_step(tmp_path, str(shadow_dir))

    print("--- forced-success stdout ---")
    print(result.stdout)
    print("--- forced-success stderr ---")
    print(result.stderr)

    assert "[ok]" in result.stdout
    assert "[!!]" not in result.stdout
    assert result.returncode == 0
