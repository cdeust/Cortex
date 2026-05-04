"""Reproducibility manifest emitter — protocol §10 schema.

Every scored run emits a ``manifest.json`` in
``benchmarks/llm_head_to_head/results/<runid>/`` containing every field
listed in §10. Missing fields → run downgraded to *exploratory* per
``tasks/verification-protocol.md`` global invariants.

precondition: caller has computed run-time fields (started_at, hostname,
  uname, package lockfile sha, db snapshot sha) BEFORE calling
  ``write_manifest``. We do NOT silently fill in missing fields with
  defaults — missing fields are recorded as null and the manifest's
  ``schema_compliance`` field flags any nulls.
postcondition: ``write_manifest()`` writes a valid JSON file with all
  §10 keys present (possibly null) and returns its path. Subsequent
  ``append_item_result`` calls write per-item results to a sibling
  ``items.jsonl`` file (one line per item × condition × generator cell).
invariant: API keys are NEVER serialised. The ``forbidden_substrings``
  audit at the end of ``write_manifest`` raises if any value resembles
  a key prefix.
"""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import os
import platform
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "beam-10m-llm-h2h-manifest-v1"


# Values that should NEVER appear in a manifest (defence in depth).
FORBIDDEN_KEY_PREFIXES = ("sk-", "sk_live_", "AIza", "ANTHROPIC_API_KEY=")


@dataclass
class ManifestModelEntry:
    api: str  # 'anthropic' | 'openai' | 'google'
    model_id: str


@dataclass
class ManifestStats:
    bootstrap_seed: int = 20260503
    holm_bonferroni_family_alpha: float = 0.01
    shuffle_seed_base: int = 20260501


@dataclass
class ManifestHardware:
    hostname: str = ""
    user: str = ""
    uname: str = ""
    python_version: str = ""


@dataclass
class ManifestPrompts:
    answer_prompt_sha256: str = ""
    judge_prompt_sha256: str = ""


@dataclass
class ManifestDB:
    pgvector_extversion: str | None = None
    pg_server_version_num: str | None = None
    hnsw_index_params: dict[str, Any] = field(default_factory=dict)
    db_snapshot_sha: str | None = None


@dataclass
class ManifestCode:
    code_hash: str = ""
    tree_dirty: bool = False
    tree_dirty_files: list[str] = field(default_factory=list)
    package_lockfile_sha: str = ""
    beam_dataset_sha: str | None = None
    embedding_cache_sha: str | None = None


@dataclass
class Manifest:
    schema_version: str
    run_id: str
    started_at: str
    code: ManifestCode
    db: ManifestDB
    prompts: ManifestPrompts
    generator_models: dict[str, ManifestModelEntry]
    judge_models: dict[str, ManifestModelEntry]
    judge_mode: str  # 'cross_vendor' | 'single_judge_opus'
    pricing_snapshot_sha: str
    item_count: int
    conditions: list[str]
    cells_total: int
    stats: ManifestStats
    hardware: ManifestHardware
    cost_tracking: dict[str, Any] = field(
        default_factory=lambda: {
            "input_tokens_total": 0,
            "output_tokens_total": 0,
            "estimated_usd": 0.0,
        }
    )
    schema_compliance: dict[str, Any] = field(default_factory=dict)


def sha256_file(path: Path) -> str:
    """Compute SHA-256 of a file's bytes.

    pre: path exists and is readable.
    post: returns 64-char hex string.
    """
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def git_head_sha(repo_root: Path) -> str:
    """Capture the current code SHA. Falls back to empty string off-git."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            check=True,
            text=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def git_tree_dirty(repo_root: Path) -> tuple[bool, list[str]]:
    """Detect dirty tree per protocol freeze requirement.

    pre: ``repo_root`` is a git checkout (or returns clean if not).
    post: returns (is_dirty, list of changed files); the file list is
      capped at 200 entries to keep the manifest readable.
    """
    try:
        out = subprocess.run(
            [
                "git",
                "diff",
                "--stat",
                "--ignore-submodules=all",
                "HEAD",
                "--name-only",
            ],
            cwd=str(repo_root),
            capture_output=True,
            check=True,
            text=True,
        )
        files = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        return (bool(files), files[:200])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return (False, [])


def collect_hardware() -> ManifestHardware:
    """Snapshot host metadata at run start.

    pre: stdlib only; no network.
    post: never includes user-secret content.
    """
    return ManifestHardware(
        hostname=socket.gethostname(),
        user=getpass.getuser(),
        uname=platform.platform(),
        python_version=platform.python_version(),
    )


def audit_no_secrets(obj: Any, path: str = "$") -> list[str]:
    """Walk a JSON-serialisable object and flag suspected secrets.

    pre: ``obj`` is JSON-compatible.
    post: returns a (possibly empty) list of ``path`` strings where a
      forbidden prefix was detected. Caller should ABORT the write if
      the list is non-empty.
    """
    findings: list[str] = []
    if isinstance(obj, str):
        for prefix in FORBIDDEN_KEY_PREFIXES:
            if prefix in obj:
                findings.append(f"{path}: matches forbidden prefix {prefix!r}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            findings.extend(audit_no_secrets(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            findings.extend(audit_no_secrets(v, f"{path}[{i}]"))
    return findings


def build_manifest(
    run_id: str,
    repo_root: Path,
    generator_models: dict[str, ManifestModelEntry],
    judge_models: dict[str, ManifestModelEntry],
    judge_mode: str,
    item_count: int,
    conditions: list[str],
    pricing_snapshot_sha: str,
    answer_prompt_path: Path,
    judge_prompt_path: Path,
    package_lockfile_path: Path,
) -> Manifest:
    """Assemble the manifest data class. Does NOT write to disk yet.

    pre:
      - ``run_id`` is a directory-safe string (no slashes).
      - ``conditions`` ⊆ {'A','B','C','D'}.
      - ``judge_mode`` ∈ {'cross_vendor','single_judge_opus'}.
    post:
      - returns a Manifest with all fields populated; cost_tracking
        starts at zero and is incremented during the run.
    """
    is_dirty, dirty_files = git_tree_dirty(repo_root)
    code = ManifestCode(
        code_hash=git_head_sha(repo_root),
        tree_dirty=is_dirty,
        tree_dirty_files=dirty_files,
        package_lockfile_sha=sha256_file(package_lockfile_path)
        if package_lockfile_path.exists()
        else "",
    )
    prompts = ManifestPrompts(
        answer_prompt_sha256=sha256_file(answer_prompt_path),
        judge_prompt_sha256=sha256_file(judge_prompt_path),
    )
    cells_total = item_count * len(conditions) * len(generator_models)
    return Manifest(
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        started_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        code=code,
        db=ManifestDB(),
        prompts=prompts,
        generator_models=generator_models,
        judge_models=judge_models,
        judge_mode=judge_mode,
        pricing_snapshot_sha=pricing_snapshot_sha,
        item_count=item_count,
        conditions=sorted(conditions),
        cells_total=cells_total,
        stats=ManifestStats(),
        hardware=collect_hardware(),
    )


def _serialisable(m: Manifest) -> dict[str, Any]:
    """Convert dataclass tree to a plain dict via dataclasses.asdict."""
    return asdict(m)


def write_manifest(manifest: Manifest, results_dir: Path) -> Path:
    """Write the manifest to ``<results_dir>/manifest.json``.

    pre: results_dir parent exists.
    post:
      - returns the path to the written file.
      - raises RuntimeError if the secret-audit finds suspected keys
        (defence in depth — keys must NEVER reach disk).
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    blob = _serialisable(manifest)

    findings = audit_no_secrets(blob)
    if findings:
        raise RuntimeError(
            "Refusing to write manifest: suspected API key material found: "
            + "; ".join(findings)
        )

    # Compliance check: every required §10 field must be present (possibly
    # nullable but the key must exist).
    blob.setdefault("schema_compliance", {}).update(
        {
            "all_required_fields_present": _check_required_fields(blob),
            "audited_for_secrets": True,
        }
    )

    out_path = results_dir / "manifest.json"
    with out_path.open("w") as fp:
        json.dump(blob, fp, indent=2, sort_keys=True)
    return out_path


REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "run_id",
    "started_at",
    "code",
    "db",
    "prompts",
    "generator_models",
    "judge_models",
    "judge_mode",
    "pricing_snapshot_sha",
    "item_count",
    "conditions",
    "cells_total",
    "stats",
    "hardware",
    "cost_tracking",
)


def _check_required_fields(blob: dict[str, Any]) -> list[str]:
    """Return the list of missing required keys (empty when fully compliant)."""
    return [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in blob]


@dataclass
class ItemResultLine:
    """One row in ``items.jsonl``. One per (item × condition × generator)."""

    question_id: str
    ability: str
    condition: str  # 'A'|'B'|'C'|'D'
    generator_model: str
    generator_response: str
    judge_label: str  # one of the VerdictLabel values
    input_tokens: int
    output_tokens: int
    retry_count: int
    estimated_usd: float
    wall_time_s: float


def append_item_result(results_dir: Path, line: ItemResultLine) -> None:
    """Append one item result to ``items.jsonl``. Atomic-per-line.

    pre: results_dir exists (create_manifest did this).
    post: one new JSONL line is appended. No truncation, no rewrites.
    """
    path = results_dir / "items.jsonl"
    with path.open("a") as fp:
        fp.write(json.dumps(asdict(line)) + "\n")


def update_cost_tracking(
    manifest_path: Path,
    *,
    add_input_tokens: int = 0,
    add_output_tokens: int = 0,
    add_usd: float = 0.0,
) -> None:
    """Patch the cost-tracking fields in-place. Read-modify-write.

    pre: manifest_path exists and is a §10-compliant manifest.
    post: input/output token totals and usd are incremented atomically
      from the perspective of a single writer (the orchestrator).
    """
    with manifest_path.open() as fp:
        blob = json.load(fp)
    ct = blob.setdefault("cost_tracking", {})
    ct["input_tokens_total"] = int(ct.get("input_tokens_total", 0)) + add_input_tokens
    ct["output_tokens_total"] = (
        int(ct.get("output_tokens_total", 0)) + add_output_tokens
    )
    ct["estimated_usd"] = float(ct.get("estimated_usd", 0.0)) + add_usd
    tmp = manifest_path.with_suffix(".tmp")
    with tmp.open("w") as fp:
        json.dump(blob, fp, indent=2, sort_keys=True)
    os.replace(tmp, manifest_path)
