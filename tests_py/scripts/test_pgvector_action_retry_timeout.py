"""Pin the per-attempt timeout contract in the shared CI action."""

from pathlib import Path
import os
import re
import subprocess

from mcp_server.shared.platform import resolve_bash

# A bare "bash" on Windows is the System32 WSL stub. source: ADR-1101
BASH = resolve_bash()

REPO = Path(__file__).resolve().parents[2]
ACTION = REPO / ".github/actions/test-suite/action.yml"


def test_pgvector_apt_attempts_are_bounded_and_report_timeout() -> None:
    action = ACTION.read_text(encoding="utf-8")

    assert "# source: issue #681 (suggested 120-second per-attempt bound)" in action
    timeout_marker = (
        "APT_TIMEOUT=120"  # source: issue #681 (owner-specified example bound)
    )
    assert timeout_marker in action
    assert re.search(
        r'if sudo timeout "\$\{APT_TIMEOUT\}s" apt-get update; then', action
    )
    assert re.search(
        r'if sudo timeout "\$\{APT_TIMEOUT\}s" apt-get install -y '
        r'"postgresql-\$\{PG_VER\}-pgvector"; then',
        action,
    )
    assert "apt_update_timed_out=1" in action
    assert "apt_install_timed_out=1" in action
    assert "apt-get update timed out after 3 attempts" in action
    assert "apt-get install timed out after 3 attempts" in action


def test_timeout_retries_each_command_and_names_final_failure() -> None:
    action = ACTION.read_text(encoding="utf-8")
    start = action.index("        APT_TIMEOUT=")
    end = action.index("        # Role + DB expected by DATABASE_URL", start)
    apt_loops = "\n".join(line[8:] for line in action[start:end].splitlines())
    timeout_status = 124  # source: GNU coreutils timeout(1) exit status
    harness = """\
PG_VER=fixture
sudo() { "$@"; }
timeout() { shift; "$@"; }
apt-get() {
  case "$*" in
    update) command_name=update ;;
    install*) command_name=install ;;
  esac
  printf 'APT_%s\\n' "$command_name"
  # source: timeout status is supplied by the GNU coreutils fixture
  if [ "$FAIL_STAGE" = "$command_name" ]; then return "$TIMEOUT_STATUS"; fi
  return 0
}
sleep() { :; }
"""

    for stage in ("update", "install"):
        result = subprocess.run(
            [BASH, "-c", harness + apt_loops],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "FAIL_STAGE": stage,
                "TIMEOUT_STATUS": str(timeout_status),
            },
        )

        assert result.returncode == 1
        assert result.stdout.splitlines().count(f"APT_{stage}") == 3
        assert f"apt-get {stage} timed out after 3 attempts" in result.stderr


def test_final_message_reports_last_attempt_not_an_earlier_timeout() -> None:
    action = ACTION.read_text(encoding="utf-8")
    start = action.index("        APT_TIMEOUT=")
    end = action.index("        # Role + DB expected by DATABASE_URL", start)
    apt_loops = "\n".join(line[8:] for line in action[start:end].splitlines())
    # Per-attempt exit statuses: one timeout, then two ordinary failures.
    # source: GNU coreutils timeout(1) exits 124 on expiry; 1 is any failure.
    harness = """\
PG_VER=fixture
sudo() { "$@"; }
timeout() { shift; "$@"; }
statuses="124 1 1"
apt-get() {
  case "$*" in
    update) command_name=update ;;
    install*) command_name=install ;;
  esac
  if [ "$command_name" != "$FAIL_STAGE" ]; then return 0; fi
  status="${statuses%% *}"; statuses="${statuses#* }"
  return "$status"
}
sleep() { :; }
"""

    for stage in ("update", "install"):
        result = subprocess.run(
            [BASH, "-c", harness + apt_loops],
            capture_output=True,
            text=True,
            env={**os.environ, "FAIL_STAGE": stage},
        )

        assert result.returncode == 1
        assert "timed out after 3 attempts" not in result.stderr
        assert f"apt-get {stage}" in result.stderr
        assert "failed after 3 attempts" in result.stderr
