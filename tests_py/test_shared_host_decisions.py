"""Independent MCP processes share explicit project decisions, not host context.

source: docs/shared-host-memory.md; project mode's files-only ADR-0056 contract.
These are server handoff tests, not a claim of Claude/Codex hook equivalence.
"""

import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


# Test liveness budget for two local MCP processes; not a latency assertion.
# source: docs/shared-host-memory.md — test liveness budget policy.
SCENARIO_TIMEOUT = 90

REPO = Path(__file__).resolve().parents[1]


def _project(path):
    (path / "wiki").mkdir(parents=True)
    (path / "wiki/manifest.json").write_text(
        json.dumps({"version": 1, "project": "handoff", "pages": {}})
    )
    return str(path)


def _server(root, profile):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CORTEX_")}
    env.pop("DATABASE_URL", None)
    env.update(
        CORTEX_CLAUDE_DIR=str(root),
        CORTEX_RUNTIME="cowork",
        CORTEX_MEMORY_STORE_BACKEND="sqlite",
        CORTEX_MEMORY_AP_ENABLED="0",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server", "--profile", profile],
        cwd=str(REPO),
        env=env,
    )


async def _call(client, tool, args):
    response = await client.call_tool(tool, args)
    assert not response.is_error, response
    result = json.loads(response.content[0].text)
    assert "error" not in result, result
    return result


def _decision(project, title, context="Observed test requirement"):
    return dict(
        project_root=project,
        title=title,
        context=context,
        decision="Use one canonical decision record",
        consequences="Both hosts can cite the same rationale",
    )


async def _recall(client, project, record):
    return await _call(
        client,
        "recall",
        {
            "project_root": project,
            "query": f"ADR-{record['number']:04d}",
            "format": "json",
        },
    )


def test_full_writer_and_lean_reader_share_exact_decision(tmp_path):
    project = _project(tmp_path / "project")

    async def scenario():
        async with Client(_server(tmp_path / "data", "full")) as author:
            async with Client(_server(tmp_path / "data", "lean")) as reader:
                created = await _call(
                    author, "wiki_adr", _decision(project, "Shared decision")
                )
                recalled = await _recall(reader, project, created)
                assert recalled["status"] == "ok"
                assert recalled["memories"][0]["path"] == created["path"]
                assert (
                    "Use one canonical decision record"
                    in recalled["memories"][0]["content"]
                )
                denied = await reader.call_tool(
                    "wiki_adr", _decision(project, "Blocked")
                )
                assert denied.is_error
                assert len(list((Path(project) / "wiki/adr").rglob("*.md"))) == 1

    asyncio.run(asyncio.wait_for(scenario(), timeout=SCENARIO_TIMEOUT))


def test_two_authors_link_outcome_and_allocate_distinct_decisions(tmp_path):
    project = _project(tmp_path / "project")
    other = _project(tmp_path / "other")

    async def scenario():
        async with Client(_server(tmp_path / "data", "full")) as claude:
            async with Client(_server(tmp_path / "data", "full")) as codex:
                first = await _call(
                    claude, "wiki_adr", _decision(project, "Initial choice")
                )
                reference = f"ADR-{first['number']:04d}"
                followup = await _call(
                    codex,
                    "wiki_adr",
                    _decision(
                        project,
                        "Revise after evaluation",
                        f"{reference}: observed outcome requires revision",
                    ),
                )
                recalled = await _recall(claude, project, followup)
                assert reference in recalled["memories"][0]["content"]
                concurrent = await asyncio.gather(
                    _call(
                        claude, "wiki_adr", _decision(project, "Claude contribution")
                    ),
                    _call(codex, "wiki_adr", _decision(project, "Codex contribution")),
                )
                assert len({r["number"] for r in [first, followup, *concurrent]}) == 4
                for record in concurrent:
                    assert (await _recall(claude, project, record))["status"] == "ok"
                    assert (await _recall(codex, project, record))["status"] == "ok"
                await _call(claude, "wiki_reindex", {"project_root": other})
                isolated = await _recall(codex, other, first)
                assert isolated["status"] == "not_found", isolated
                assert all(r["memory_sync"] == "project-files-only" for r in concurrent)

    asyncio.run(asyncio.wait_for(scenario(), timeout=SCENARIO_TIMEOUT))
