"""Install everything Cortex needs, in the foreground, once — stdlib only.

This is the plugin's ``Setup`` hook (Claude Code runs it for ``claude --init-only``,
before the first SessionStart) and the program the background pre-install runs
for the next version's set. It installs the base set, the plugin's managed
PostgreSQL server when the store is eligible (ADR-1110), the semantic-search
set from uv.lock, then downloads the pinned embedding model, and it is the
only place besides the MCP server and the two detached jobs that installs.

Outcome: exit 0 and ``{"status": "ready"}`` in ``<set>.setup.json``, or exit 1
with the cause printed and ``{"status": "failed", "error": ...}``. When the
store was eligible for the managed PostgreSQL server but it could not run
here, the outcome also carries ``"sqlite_fallback": <cause>`` and the next
SessionStart shows it (ADR-1110, owner decision D3). The host
discards a Setup hook's output and exit code (measured: Claude Code 2.1.300,
``claude --init-only`` exits 0 whatever the hook did), so everything printed is
also appended to ``<data>/setup.log`` and the outcome file is what a caller
reads (``scripts/init_plugin.py``).

source: ADR-1108
source: ADR-1110
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import launcher_deps
import launcher_gc
import launcher_layout
import launcher_lock
import launcher_logs
import launcher_ml
import launcher_site

SETUP = (
    "--setup"  # source: ADR-1108 (the argument the Setup hook starts the launcher with)
)


def require_host_data() -> None:
    """Exit 1 unless the host's plugin data directory is in the environment.

    ``--setup`` installs into ``<CLAUDE_PLUGIN_DATA>/sets``; the host sets that
    variable for its Setup hook, a user's shell does not, and the launcher then
    falls back to the plugin tree (``launcher._resolve_paths``): an install the
    hooks never look in. Refuse that rather than install in the wrong place.
    """
    if os.environ.get("CLAUDE_PLUGIN_DATA"):
        return
    print(
        "[cortex-setup] refused: CLAUDE_PLUGIN_DATA is not set, so this would "
        "install into the plugin tree, where Cortex's hooks do not look. Run "
        "`claude --init-only` instead: Claude Code sets the directory.",
        file=sys.stderr,
    )
    sys.exit(1)


def job_lock(deps_dir: str) -> str:
    return f"{deps_dir}.setup.lock"


def log_path(deps_dir: str) -> Path:
    """Everything a Setup run printed: the host shows none of it."""
    return launcher_layout.data_dir(deps_dir) / "setup.log"


def status_file(deps_dir: str) -> Path:
    return Path(f"{deps_dir}.setup.json")


def outcome(deps_dir: str) -> dict:
    """The last Setup run's outcome for this set, ``{}`` when none ran."""
    try:
        data = json.loads(status_file(deps_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


FALLBACK = "sqlite_fallback"  # source: ADR-1110 D3 (the outcome field)


def sqlite_fallback(deps_dir: str) -> str:
    """Why the last Setup left an eligible store on SQLite, ``""`` when it did not."""
    return str(outcome(deps_dir).get(FALLBACK) or "")


def _record(
    deps_dir: str, status: str, error: str = "", gc_error: str = "", fallback: str = ""
) -> None:
    """Write the outcome; ``gc_error`` only when the set is ready but the sets
    of earlier versions could not be collected; ``fallback`` only when an
    eligible store stays on SQLite because the managed server cannot run."""
    record = {"status": status, "error": error}
    if gc_error:
        record["gc_error"] = gc_error
    if fallback:
        record[FALLBACK] = fallback
    path = status_file(deps_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


class _Tee:
    """A text stream that also appends to the setup log."""

    def __init__(self, stream, sink) -> None:
        self._stream, self._sink = stream, sink

    def write(self, text: str) -> int:
        self._sink.write(text)
        self._sink.flush()
        return self._stream.write(text)

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def _say(message: str) -> None:
    print(f"[cortex-setup] {message}", flush=True)


def _fail(deps_dir: str, error: str, fallback: str = "") -> int:
    _say(f"FAILED: {error} (log: {log_path(deps_dir)})")
    _record(deps_dir, "failed", error, fallback=fallback)
    return 1


def managed_pg_step(deps_dir: str, say):
    """The managed PostgreSQL step (ADR-1110): a ``StepOutcome``.

    Imported here, after the base set, because it needs psycopg. The import
    system cached the set's directory as it was before the install, so it is
    rescanned first, as ``launcher._ensure_runtime`` does (ADR-1104)."""
    importlib.invalidate_caches()
    launcher_site.isolate_deps(deps_dir)
    import launcher_pg_provision  # noqa: PLC0415 — needs the base set installed

    return launcher_pg_provision.setup_step(
        str(launcher_layout.data_dir(deps_dir)), say
    )


def _warm_model(deps_dir: str, launcher: str, log) -> str:
    """Download the pinned embedding model; the failure's cause, "" on success."""
    env = dict(os.environ)
    env[launcher_ml.STATUS_ENV] = str(launcher_ml.status_file(deps_dir))
    done = subprocess.run(
        [sys.executable, launcher, launcher_ml.WARMUP_MODULE],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
    )
    status, why = launcher_ml.state(deps_dir)
    if done.returncode or status != "ready":
        return why or f"the model download exited {done.returncode}"
    return ""


def _install(deps_dir: str, launcher: str, log) -> int:
    started = time.monotonic()
    _say(f"installing the base dependency set into {deps_dir}")
    launcher_deps.ensure_deps(deps_dir)
    if not launcher_deps.set_ready(deps_dir, "base"):
        return _fail(deps_dir, "the locked base dependency set did not install")
    step = managed_pg_step(deps_dir, _say)
    if step.failed:
        return _fail(deps_dir, step.failed)
    if os.environ.get(launcher_ml.ZERO_DOWNLOAD_ENV, "").lower() in ("1", "true"):
        _say(f"semantic search skipped: {launcher_ml.ZERO_DOWNLOAD_ENV} is set")
    else:
        _say("installing the semantic-search dependency set (about 1 GB)")
        launcher_deps.ensure_all_deps(deps_dir)
        if not launcher_deps.set_ready(deps_dir, "ml"):
            return _fail(
                deps_dir,
                "the locked semantic-search set did not install",
                step.fallback,
            )
        _say("downloading the embedding model")
        cause = _warm_model(deps_dir, launcher, log)
        if cause:
            why = f"the embedding model did not download: {cause}"
            return _fail(deps_dir, why, step.fallback)
    _record(deps_dir, "ready", fallback=step.fallback)
    if step.fallback:
        _say(f"SQLite fallback: {step.fallback}")
    Path(f"{deps_dir}.base-job.failed").unlink(missing_ok=True)
    _say(f"ready in {time.monotonic() - started:.0f} s")
    return 0


def run(deps_dir: str, launcher: str) -> int:
    """Install base + semantic search + model for ``deps_dir``'s lock; exit code.

    Precondition: ``deps_dir`` is ``<data>/sets/<key>``; sys.path already
    carries it (the launcher did that).
    Postcondition: 0 iff both sets are stamped for this uv.lock and the model
    is cached (or the operator opted out of the download); otherwise 1 with the
    cause printed and recorded. A concurrent Setup of the same set is waited
    for as long as it runs (the kernel releases its lock when it exits, so no
    clock decides that it failed), not duplicated. On success the sets no
    installed version references are removed; a path that could not be removed
    is printed and recorded, a collection that raised OSError is printed and
    recorded as ``gc_error`` (``_collect``), and neither changes the exit code.
    Any other exception's traceback is printed while the output still goes to
    ``setup.log``, then raised.
    """
    log_file = launcher_logs.rotate(log_path(deps_dir))
    with log_file.open("a", encoding="utf-8") as log:
        out, err = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = _Tee(out, log), _Tee(err, log)
        try:
            return _run_locked(deps_dir, launcher, log)
        except BaseException:
            traceback.print_exc()  # into setup.log: the host discards stderr
            raise
        finally:
            sys.stdout, sys.stderr = out, err


def _run_locked(deps_dir: str, launcher: str, log) -> int:
    with launcher_lock.held(job_lock(deps_dir), None):
        _record(deps_dir, "installing")
        code = _install(deps_dir, launcher, log)
    if code == 0:
        _collect(deps_dir)
    return code


def _collect(deps_dir: str) -> None:
    """Remove the sets no installed version references, once ``ready`` is recorded.

    The set is ready whatever happens here. ``launcher_gc.collect`` raises
    OSError when a user registry or ``sets/`` cannot be listed or its record
    cannot be written; the cause is printed (so into setup.log) and recorded as
    ``gc_error`` in the outcome file, which ``init_plugin.py`` prints. It is not
    written to ``gc-failed.json``: writing that file can be what failed.
    """
    root = os.environ.get("CORTEX_RUNNING_ROOT") or os.environ.get(
        "CLAUDE_PLUGIN_ROOT", ""
    )
    if not root:
        return
    data = str(launcher_layout.data_dir(deps_dir))
    try:
        removed = launcher_gc.collect(root, data)
    except OSError as exc:
        # str keeps the filename ("[Errno 13] Permission denied: '<path>'");
        # repr of an OSError drops it.
        kind = type(exc).__name__
        cause = f"could not collect the sets of earlier versions: {kind}: {exc}"
        _say(cause)
        _record(deps_dir, "ready", gc_error=cause, fallback=sqlite_fallback(deps_dir))
        return
    if removed:
        _say(f"removed {len(removed)} unreferenced paths of earlier sets")
    left = launcher_gc.failed_removals(data)
    if left:
        _say(
            f"could not remove {len(left)} paths of earlier sets (listed "
            f"above, recorded in {Path(data) / launcher_gc.FAILED})"
        )
