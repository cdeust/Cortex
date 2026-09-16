"""Direct MCP startup must honor ADR-0505 before settings bind.

Run in a fresh interpreter with a disposable configuration root. Stop at the
MCP dependency boundary: exercise real entrypoint/settings imports without
starting a server, loading embeddings, or connecting to a database.
"""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

# Test liveness budget only; not a startup performance requirement.
# source: docs/shared-host-memory.md — test liveness budget policy.
PROCESS_TIMEOUT = 30

REPO = Path(__file__).resolve().parents[1]
PROBE = r"""
import importlib.abc
import json
import os
import sys
from types import ModuleType

for name in ("scipy", "scipy.linalg", "scipy.special", "sklearn",
             "sklearn.utils", "sklearn.utils.validation", "anyio"):
    sys.modules[name] = ModuleType(name)

class StopBeforeMCP(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp":
            from mcp_server.infrastructure.memory_config import get_memory_settings
            settings = get_memory_settings()
            print(json.dumps({"backend": settings.STORE_BACKEND,
                              "db_path": settings.DB_PATH,
                              "dsn": os.environ.get("DATABASE_URL"),
                              "settings_dsn": settings.DATABASE_URL}))
            raise SystemExit(0)

sys.meta_path.insert(0, StopBeforeMCP())
import mcp_server.__main__
raise AssertionError("MCP boundary was not reached")
"""


def probe(tmp_path, marker=None, **overrides):
    root = tmp_path / "claude"
    (root / "methodology").mkdir(parents=True)
    if marker is not None:
        (root / "methodology" / "backend.json").write_text(json.dumps(marker))
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("CORTEX_", "CLAUDE_", "PYTHON"))
        and key != "DATABASE_URL"
    }
    env.update(CORTEX_CLAUDE_DIR=str(root), PYTHONPATH=str(REPO), **overrides)
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=PROCESS_TIMEOUT,
    )
    data = json.loads(result.stdout)
    assert data["db_path"] == str(root / "methodology" / "memory.db")
    return data


@pytest.mark.parametrize("backend", ["sqlite", "postgresql"])
def test_direct_entrypoint_applies_saved_backend_before_settings(tmp_path, backend):
    assert probe(tmp_path, {"backend": backend})["backend"] == backend


@pytest.mark.parametrize("variable", ["DATABASE_URL", "CORTEX_MEMORY_DATABASE_URL"])
def test_explicit_dsn_takes_precedence_over_marker(tmp_path, variable):
    dsn = "postgresql://localhost/disposable_bootstrap_probe"
    result = probe(tmp_path, {"backend": "sqlite"}, **{variable: dsn})
    assert result["backend"] == "auto"
    assert result["dsn" if variable == "DATABASE_URL" else "settings_dsn"] == dsn


@pytest.mark.parametrize(
    "overrides",
    [
        {"CORTEX_MEMORY_STORE_BACKEND": "postgresql"},
        {"CORTEX_BACKEND": "postgres"},
    ],
)
def test_explicit_backend_takes_precedence_over_marker(tmp_path, overrides):
    assert (
        probe(tmp_path, {"backend": "sqlite"}, **overrides)["backend"] == "postgresql"
    )


@pytest.mark.parametrize("marker", [None, {"backend": "unknown"}])
def test_no_valid_marker_keeps_existing_auto_behavior(tmp_path, marker):
    assert probe(tmp_path, marker)["backend"] == "auto"


def test_blank_manifest_dsn_does_not_override_marker(tmp_path):
    result = probe(tmp_path, {"backend": "sqlite"}, DATABASE_URL="  ")
    assert result["backend"] == "sqlite"
    assert result["dsn"] is None
