#!/usr/bin/env python3
"""Collect genuine registered-handler SDK responses from an isolated fixture.

Run later, sequentially, after seeding the throwaway SQLite/profile fixture.
Cases are JSONL {"tool": "query_methodology"|"recall", "arguments": {...}}.
This uses MCPServer.call_tool and the actual registry wrappers, without a
transport, CLI/model API call, or production database. Normal recall may load
the existing local embedding model; this collector is not a lightweight test.
Token counts are optional external evidence, never produced by an estimator.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.response_budget_measurements import (
    read_jsonl,
    summarize,
    token_observations,
)  # noqa: E402 — direct script execution

# source: ADR-0718
CALIBRATION_RESPONSES = 100
ALLOWED_TOOLS = frozenset({"query_methodology", "recall"})


def validate_environment(root: Path) -> None:
    root = root.resolve(strict=True)
    configured = os.environ.get("CORTEX_CLAUDE_DIR")
    if not configured or Path(configured).resolve() != root / "claude":
        raise ValueError(
            "CORTEX_CLAUDE_DIR must be the isolated root's claude directory"
        )
    if root == Path.home() or root.is_relative_to(Path.home() / ".claude"):
        raise ValueError("The calibration root must not be the production Claude tree")
    socket = root / "no-postgres"
    expected_dsn = f"postgresql://{quote(str(socket), safe='')}/cortex_budget_fixture"
    if socket.exists() or any(
        os.environ.get(name) != expected_dsn
        for name in ("DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL")
    ):
        raise ValueError(
            "DATABASE_URL must name the prescribed nonexistent Unix socket"
        )
    if os.environ.get("CORTEX_MEMORY_STORE_BACKEND") != "sqlite":
        raise ValueError("Explicit isolated SQLite backend required")
    if os.environ.get("CORTEX_EMBEDDING_ZERO_DOWNLOAD") != "1":
        raise ValueError("CORTEX_EMBEDDING_ZERO_DOWNLOAD=1 required")
    if any(os.environ.get(name) for name in ("PGHOSTADDR", "PGSERVICE")):
        raise ValueError("Remove inherited PostgreSQL connection overrides")


def validate_cases(cases: list[dict], expected: int = CALIBRATION_RESPONSES) -> None:
    if len(cases) != expected:
        raise ValueError(f"Expected {expected} runtime cases, received {len(cases)}")
    for case in cases:
        if case.get("tool") not in ALLOWED_TOOLS or not isinstance(
            case.get("arguments"), dict
        ):
            raise ValueError("Each case must name an allowed tool and arguments object")
    if (
        expected == CALIBRATION_RESPONSES
        and {case["tool"] for case in cases} != ALLOWED_TOOLS
    ):
        raise ValueError("Calibration must cover both query_methodology and recall")


def request_digest(case: dict) -> str:
    data = json.dumps(case, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def validate_captures(cases: list[dict], records: list[dict]) -> None:
    for case, record in zip(cases, records, strict=True):
        if record.get("tool") != case["tool"] or record.get(
            "request_sha256"
        ) != request_digest(case):
            raise ValueError("Captured response does not match its case digest/tool")


def load_runtime(root: Path):
    # Delayed imports: CLI help, parsing and guard tests never load Cortex/ML.
    from mcp.server.mcpserver import MCPServer  # noqa: PLC0415 — explicit measurement entrypoint
    from mcp_server.infrastructure import config  # noqa: PLC0415 — validate paths before handler imports
    from mcp_server.infrastructure.memory_config import get_memory_settings  # noqa: PLC0415 — explicit measurement entrypoint
    from mcp_server.infrastructure.memory_store import reset_shared_store  # noqa: PLC0415 — cleanup owned isolated stores

    settings = get_memory_settings()
    paths = (settings.DB_PATH, settings.SQLITE_FALLBACK_PATH, config.PROFILES_PATH)
    if settings.STORE_BACKEND != "sqlite" or any(
        not Path(path).resolve().is_relative_to(root / "claude") for path in paths
    ):
        raise ValueError("Resolved data paths/backend escape the isolated fixture")
    from mcp_server import tool_registry_core, tool_registry_memory  # noqa: PLC0415 — import handlers only after guard
    from mcp_server.handlers._tool_meta import apply_output_schemas, apply_param_docs  # noqa: PLC0415 — same registration finalization as __main__

    server = MCPServer(name="cortex-response-budget-fixture")
    tool_registry_core._register_query_methodology(server)
    tool_registry_memory._register_recall(server)
    schemas = {
        "query_methodology": tool_registry_core.SCHEMAS["query_methodology"],
        "recall": tool_registry_memory.SCHEMAS["recall"],
    }
    apply_output_schemas(server, schemas)
    apply_param_docs(server, schemas)
    return server, reset_shared_store


async def capture(
    server, cases: list[dict], output: Path, metadata: dict
) -> list[dict]:
    records = []
    with output.open("x", encoding="utf-8") as stream:
        for index, case in enumerate(cases):
            result = await server.call_tool(case["tool"], case["arguments"])
            wire = result.model_dump(mode="json", by_alias=True, exclude_none=True)
            if wire.get("isError"):
                raise RuntimeError(f"Tool returned an error at case {index}")
            record = {
                "case": index,
                "tool": case["tool"],
                "request_sha256": request_digest(case),
                "capture_provenance": metadata,
                "result": wire,
            }
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            records.append(record)
    return records


async def collect(
    root: Path, cases: list[dict], output: Path, metadata: dict
) -> list[dict]:
    server, close = load_runtime(root)
    try:
        return await capture(server, cases, output, metadata)
    finally:
        close()


def provenance(cases: Path) -> dict:
    root = Path(__file__).resolve().parents[1]
    paths = (
        "mcp_server/core/response_budget.py",
        "mcp_server/handlers/query_methodology.py",
        "mcp_server/handlers/recall.py",
        "mcp_server/tool_registry_memory.py",
        "uv.lock",
    )
    sdk = importlib.metadata.distribution("mcp").locate_file(
        "mcp/server/mcpserver/utilities/func_metadata.py"
    )
    return {
        "python": sys.version,
        "mcp_version": importlib.metadata.version("mcp"),
        "sdk_serializer_sha256": hashlib.sha256(sdk.read_bytes()).hexdigest(),
        "source_sha256": {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in paths
        },
        "entrypoint": "registry + MCPServer.call_tool; no transport/Claude call",
        "cases_sha256": hashlib.sha256(cases.read_bytes()).hexdigest(),
    }


def capture_provenance(records: list[dict]) -> dict:
    metadata = records[0].get("capture_provenance")
    if not isinstance(metadata, dict) or not metadata:
        raise ValueError("Captured source/SDK provenance is required")
    if any(record.get("capture_provenance") != metadata for record in records):
        raise ValueError("Do not pool captures from different runtime sources")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--isolated-root", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--counts", type=Path)
    parser.add_argument("--existing-captures", type=Path)
    args = parser.parse_args()
    root = args.isolated_root.resolve(strict=True)
    validate_environment(root)
    cases = read_jsonl(args.cases)
    validate_cases(cases)
    analysis_metadata = provenance(args.cases)
    records = (
        read_jsonl(args.existing_captures)
        if args.existing_captures
        else asyncio.run(collect(root, cases, args.output, analysis_metadata))
    )
    validate_captures(cases, records)
    counts = token_observations(read_jsonl(args.counts)) if args.counts else {}
    report = summarize(records, counts)
    report["capture_provenance"] = capture_provenance(records)
    report["analysis_provenance"] = analysis_metadata
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
