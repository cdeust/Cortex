"""The no-deps gate refuses a hashed requirements install missing --no-deps.

The reproduction case is the exact one issue #536 names: PR #332 fixed this
failure everywhere it then knew to look and recorded it in ADR-0800, but
missed ``scripts/setup.sh``, which stayed broken until the plugin installer
failed on it (fixed in PR #539, ADR-1059). Each test states the shape it
protects.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mcp_server.hooks import no_deps_gate as gate

ALLOW, BLOCK = 0, 2

# The broken scripts/setup.sh:225 invocation before PR #539 — --require-hashes
# and -r requirements/setup.txt with no --no-deps anywhere in the command.
BROKEN_SETUP_SH = (
    'python3 -m pip install -q --target "$DEPS_DIR" \\\n'
    '    --require-hashes -r "$PROJECT_DIR/requirements/setup.txt"\n'
)

# The PR #539 fix: the same command with --no-deps added.
FIXED_SETUP_SH = (
    'python3 -m pip install -q --target "$DEPS_DIR" \\\n'
    '    --no-deps --require-hashes -r "$PROJECT_DIR/requirements/setup.txt"\n'
)

UNRELATED_INSTALL = "pip install --no-deps -e .\n"


def _write(tmp_path: Path, rel: str, body: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, "utf-8")
    return path


def _write_event(path: Path, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": str(path), "content": content},
    }


def test_refuses_the_exact_invocation_that_broke_setup_sh(tmp_path: Path) -> None:
    path = _write(tmp_path, "scripts/setup.sh", "")
    assert gate.evaluate(_write_event(path, BROKEN_SETUP_SH)) == BLOCK


def test_allows_the_pr_539_fixed_form(tmp_path: Path) -> None:
    path = _write(tmp_path, "scripts/setup.sh", "")
    assert gate.evaluate(_write_event(path, FIXED_SETUP_SH)) == ALLOW


def test_an_unrelated_pip_invocation_is_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path, "scripts/setup.sh", "")
    assert gate.evaluate(_write_event(path, UNRELATED_INSTALL)) == ALLOW


def test_a_mix_of_related_and_unrelated_commands_still_blocks(tmp_path: Path) -> None:
    """The unrelated command in the same file must not mask the violation."""
    path = _write(tmp_path, "scripts/setup.sh", "")
    body = UNRELATED_INSTALL + BROKEN_SETUP_SH
    assert gate.evaluate(_write_event(path, body)) == BLOCK


def test_out_of_scope_paths_are_never_scanned(tmp_path: Path) -> None:
    """The same broken command outside ADR-1062's scope (scripts/,
    .github/workflows/, .github/actions/, Dockerfile*, .devcontainer/) is
    not this gate's business."""
    path = _write(tmp_path, "docs/example.sh", "")
    assert gate.evaluate(_write_event(path, BROKEN_SETUP_SH)) == ALLOW


def test_github_workflow_yaml_is_in_scope(tmp_path: Path) -> None:
    path = _write(tmp_path, ".github/workflows/ci.yml", "")
    body = "      - run: pip install --require-hashes -r requirements/ci-sqlite.txt\n"
    assert gate.evaluate(_write_event(path, body)) == BLOCK


def test_github_actions_composite_is_in_scope(tmp_path: Path) -> None:
    path = _write(tmp_path, ".github/actions/test-suite/action.yml", "")
    body = "        pip install --require-hashes -r requirements/ci-postgresql.txt\n"
    assert gate.evaluate(_write_event(path, body)) == BLOCK


def test_dockerfile_is_in_scope_by_name_not_extension(tmp_path: Path) -> None:
    path = _write(tmp_path, "Dockerfile", "")
    body = "RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt\n"
    assert gate.evaluate(_write_event(path, body)) == BLOCK


def test_devcontainer_dockerfile_is_in_scope(tmp_path: Path) -> None:
    path = _write(tmp_path, ".devcontainer/Dockerfile", "")
    body = "RUN pip install --require-hashes -r /tmp/requirements.txt\n"
    assert gate.evaluate(_write_event(path, body)) == BLOCK


def test_override_env_var_allows_the_call(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CORTEX_NO_DEPS_GATE", "off")
    path = _write(tmp_path, "scripts/setup.sh", "")
    assert gate.evaluate(_write_event(path, BROKEN_SETUP_SH)) == ALLOW


def test_entrypoint_exits_two_on_a_blocked_write(tmp_path: Path) -> None:
    """The exit code is the contract with Claude Code, not an internal detail."""
    path = _write(tmp_path, "scripts/setup.sh", "")
    event = _write_event(path, BROKEN_SETUP_SH)
    done = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.no_deps_gate"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert done.returncode == BLOCK
    assert "no-deps-gate" in done.stderr


def test_entrypoint_never_crashes_on_an_unreadable_file(tmp_path: Path) -> None:
    """Fail-open contract: a binary file under a scoped path must exit 0,
    never a traceback exit code."""
    path = tmp_path / "scripts" / "blob.sh"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00\x01")
    event = {
        "tool_name": "Edit",
        "tool_input": {"file_path": str(path), "old_string": "x", "new_string": "y"},
    }
    done = subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.no_deps_gate"],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert done.returncode == ALLOW
    assert done.stderr == ""


def test_missing_tool_input_fields_fail_open() -> None:
    assert gate.evaluate({"tool_name": "Write", "tool_input": {}}) == ALLOW
    assert gate.evaluate({}) == ALLOW
