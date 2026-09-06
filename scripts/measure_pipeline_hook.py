"""Measure the pipeline hook directly in fresh processes and isolated paths.

Run only when the shared host is idle, once per before/after checkout:
python scripts/measure_pipeline_hook.py --repo /path/to/checkout \
    --python /path/to/prepared/venv/bin/python --output /tmp/hook-before

This measures ``python -m``, not launcher dependency bootstrap. It never
installs dependencies. Read and Bash are both rejected by this hook; an
Edit with no graph still needs the canonical store lookup and is outside
this probe. Import traces are separate from CPU samples.

source: tasks/codex-green-remediation-plan.md §3, W2-1: four repetitions,
discard the first; retain user+system CPU, wall time, and peak RSS.
Measurement APIs: https://docs.python.org/3/library/os.html#os.wait4 and
https://docs.python.org/3/library/resource.html#resource.getrusage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

_MODULE = "mcp_server.hooks.pipeline_impact_bump"
# source: remediation plan §3 — four repetitions, first discarded.
_REPETITIONS = 4
_SOURCES = (
    "mcp_server/hooks/pipeline_impact_bump.py",
    "mcp_server/hooks/_store_lifecycle.py",
    "mcp_server/handlers/ingest_helpers.py",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _environment(repo: Path, sandbox: Path) -> dict[str, str]:
    env = {
        key: os.environ[key]
        for key in ("HOME", "PATH", "SYSTEMROOT", "WINDIR")
        if key in os.environ
    }
    project = sandbox / "project"
    project.mkdir()
    socket_dir = sandbox.resolve() / "no-postgres"
    if socket_dir.exists():
        raise ValueError("The probe requires a nonexistent PostgreSQL socket directory")
    # libpq accepts a percent-encoded Unix socket directory in the URI authority.
    # An empty DSN would instead select the user's default database connection.
    dsn = f"postgresql://{quote(str(socket_dir), safe='')}/cortex_hook_probe"
    env.update(
        {
            "PYTHONPATH": str(repo),
            "PYTHONNOUSERSITE": "1",
            "CLAUDE_PROJECT_ROOT": str(project),
            "CORTEX_CLAUDE_DIR": str(sandbox / "claude"),
            "CORTEX_MEMORY_STORE_BACKEND": "sqlite",
            "CORTEX_MEMORY_DB_PATH": str(sandbox / "memory.db"),
            "CORTEX_MEMORY_SQLITE_FALLBACK_PATH": str(sandbox / "memory.db"),
            "CORTEX_MEMORY_DATABASE_URL": dsn,
            "CORTEX_TEST_DATABASE_URL": dsn,
            "DATABASE_URL": dsn,
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "CORTEX_RERANKER_OFFLINE": "1",
            "CORTEX_EMBEDDING_ZERO_DOWNLOAD": "1",
        }
    )
    return env


def _run_sample(command: list[str], payload: str, env: dict, log: Path) -> dict:
    """wait4 returns per-child usage; cumulative RUSAGE_CHILDREN would skew RSS."""
    with (
        log.with_suffix(".stdout").open("w") as out,
        log.with_suffix(".stderr").open("w") as err,
    ):
        started = time.perf_counter()
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=out,
            stderr=err,
            text=True,
            cwd=env["CLAUDE_PROJECT_ROOT"],
            env=env,
        ) as child:
            assert child.stdin is not None
            child.stdin.write(payload)
            child.stdin.close()
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        wall_seconds = time.perf_counter() - started
    if child.returncode:
        raise RuntimeError(f"Hook exited {child.returncode}; inspect {log}.stderr")
    return {
        "command": command,
        "wall_seconds": wall_seconds,
        "user_seconds": usage.ru_utime,
        "system_seconds": usage.ru_stime,
        "cpu_seconds": usage.ru_utime + usage.ru_stime,
        "max_rss_native": usage.ru_maxrss,
        "stdout": str(log.with_suffix(".stdout")),
        "stderr": str(log.with_suffix(".stderr")),
    }


def _host_state() -> dict:
    return {
        "load_average": os.getloadavg(),
        "logical_cpus": os.cpu_count(),
        "root_disk_bytes": dict(shutil.disk_usage("/")._asdict()),
    }


def _measure_case(name: str, args: argparse.Namespace, env: dict) -> dict:
    payload = json.dumps({"tool_name": name, "tool_input": {}})
    command = [args.python, "-m", _MODULE]
    samples = []
    for index in range(_REPETITIONS):
        sample = _run_sample(command, payload, env, args.output / f"{name}-{index}")
        sample["discarded"] = index == 0
        samples.append(sample)
    trace = _run_sample(
        [args.python, "-X", "importtime", "-m", _MODULE],
        payload,
        env,
        args.output / f"{name}-importtime",
    )
    return {"payload": payload, "samples": samples, "import_trace": trace["stderr"]}


def main() -> None:
    args = _parse_args()
    if not hasattr(os, "wait4"):
        raise SystemExit(
            "This per-child resource probe requires a Unix host with wait4."
        )
    args.repo = args.repo.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "entrypoint": "module (launcher bootstrap excluded)",
        "platform": platform.platform(),
        "python": subprocess.check_output([args.python, "-VV"], text=True).strip(),
        "rss_note": "Native getrusage ru_maxrss units; compare on the same OS.",
        "repo": str(args.repo),
        "source_sha256": {
            path: hashlib.sha256((args.repo / path).read_bytes()).hexdigest()
            for path in _SOURCES
        },
        "host_before": _host_state(),
    }
    with tempfile.TemporaryDirectory(prefix="cortex-hook-probe-") as temporary:
        env = _environment(args.repo, Path(temporary))
        report["cases"] = {
            name: _measure_case(name, args, env) for name in ("Read", "Bash")
        }
    report["host_after"] = _host_state()
    destination = args.output / "report.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(destination)


if __name__ == "__main__":
    main()
