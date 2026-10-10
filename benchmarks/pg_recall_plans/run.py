"""Plan-only experiment in a retained reproduce.sh container; no model or host URL."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

from benchmarks.pg_recall_plans.fixture import MIN_ROWS
from benchmarks.pg_recall_plans.evidence import write_summary
from benchmarks.pg_recall_plans.sql import experiment_sql


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--container-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rows", type=int, default=MIN_ROWS)
    args = parser.parse_args()
    if args.rows < MIN_ROWS:
        parser.error(f"--rows must be at least {MIN_ROWS} (W4-1)")
    if not re.fullmatch(r"cortex-bench-pg-\d+-[0-9a-f]+", args.container):
        parser.error("--container must name the retained reproduce.sh container")
    return args


def command(
    argv: list[str], sql: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, input=sql, text=True, capture_output=True, check=True)


def validate_container(name: str, expected_id: str) -> dict[str, object]:
    result = command(["docker", "inspect", name])
    info = json.loads(result.stdout)[0]
    driver = Path(__file__).parents[1] / "reproduce.sh"
    match = re.search(
        r'^PG_IMAGE="([^"]+)"$', driver.read_text(encoding="utf-8"), re.MULTILINE
    )
    if match is None:
        raise RuntimeError("cannot verify reproduce.sh image")
    config = info["Config"]
    if config["Image"] != match[1] or not info["State"]["Running"]:
        raise RuntimeError("refusing a stopped container or a different image")
    if "POSTGRES_DB=cortex_bench" not in config["Env"]:
        raise RuntimeError("container lacks reproduce.sh database identity")
    if info["Id"] != expected_id:
        raise RuntimeError("container ID does not match the chosen reproduce.sh run")
    return {
        "container": name,
        "container_id": info["Id"],
        "image": info["Image"],
        "image_ref": config["Image"],
    }


def host_evidence() -> dict[str, str]:
    return {
        "git_sha": command(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "uptime": command(["uptime"]).stdout.strip(),
        "df": command(["df", "-h", "/"]).stdout,
    }


def run_experiment(args: argparse.Namespace, database: str) -> None:
    script = experiment_sql(args.rows)
    (args.output / "experiment.sql").write_text(script, encoding="utf-8")
    argv = [
        "docker",
        "exec",
        "-i",
        args.container,
        "psql",
        "-X",
        "-qAt",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        database,
    ]
    result = subprocess.run(argv, input=script, text=True, capture_output=True)
    (args.output / "results.jsonl").write_text(result.stdout, encoding="utf-8")
    (args.output / "nested-plans.log").write_text(result.stderr, encoding="utf-8")
    (args.output / "command.json").write_text(json.dumps(argv), encoding="utf-8")
    result.check_returncode()


def main() -> None:
    args = arguments()
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = validate_container(args.container, args.container_id)
    # Immutable identity for every subsequent command.
    args.container = args.container_id
    metadata.update({"before": host_evidence(), "rows": args.rows})
    database = "cortex_w4_" + uuid.uuid4().hex
    command(["docker", "exec", args.container, "createdb", "-U", "postgres", database])
    try:
        run_experiment(args, database)
        if not write_summary(args.output):
            raise RuntimeError("W4-1 plan/equivalence gate failed; see summary.json")
    finally:
        command(
            ["docker", "exec", args.container, "dropdb", "-U", "postgres", database]
        )
        metadata["after"] = host_evidence()
        script = args.output / "experiment.sql"
        if script.exists():
            metadata["script_sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
        (args.output / "manifest.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
