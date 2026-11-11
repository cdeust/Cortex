"""Receipt of memory operations run with networking disabled (issue #734).

Issue #734, slice 6: "Demonstrate memory operations with networking disabled
after provisioning and label fallback behavior." This entry point starts
``offline_receipt_ops`` in a fresh interpreter, with the network guard
installed before ``mcp_server`` is imported, against a throwaway SQLite store,
then writes one receipt:

- ``operations``: each ``remember`` and the ``recall``, with its outcome, the
  embedding mode (``neural`` or ``fallback``) and ``ModelState``, the reranker
  state, and the network attempts it made;
- ``network_attempts``: every refused connection or lookup, host and port;
- ``runtime_manifest``: ``effective_manifest`` with what the engines served;
- ``verdict``: ``offline`` when every operation succeeded and nothing tried
  the network, ``network_attempted`` when something did, ``failed`` when an
  operation failed; ``fallback`` lists the operations served by the
  algorithmic embedding or without the reranker, so a fallback result is
  never read as a full-model one.

The environment is the caller's except for the store, which is redirected so
the receipt never writes to the user's memories, the variables that would
select another store (``DATABASE_URL``, ``PG*``), and the proxy variables
(``*_proxy``, any case): without them a client connects to the real host, and
the receipt names it rather than the proxy (the guard refuses a configured
proxy all the same, ``network_guard.py``). The model caches and the
offline switches (``CORTEX_RERANKER_OFFLINE``, ``HF_HUB_OFFLINE``,
``CORTEX_EMBEDDING_ZERO_DOWNLOAD``) are passed through as they are: a
provisioned machine is measured as configured.

Usage: ``python -m benchmarks.lib.offline_receipt --out receipt.json``.
Exit status 0 for ``offline``, 1 otherwise.

source: issue #734, acceptance item 4;
docs/audits/model-identity-inventory-2026-11-06.md,
remaining slice 4
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# source: issue #734; bumped when a key of the receipt changes meaning.
SCHEMA = 1
_REPO = Path(__file__).resolve().parents[2]
# source: tests_py/conftest.py ``_redirect_real_data_roots`` (the variables
# that place the store); tests_py/integration/test_fresh_mcp_sqlite.py (the
# variables that would select PostgreSQL).
_STORE_SELECTORS = ("DATABASE_URL", "CORTEX_DATABASE_URL", "CORTEX_TEST_DATABASE_URL")
# source: test_fresh_mcp_sqlite.py (a fresh SQLite run); a cold import of the
# models on CPU fits well inside it.
_TIMEOUT_S = 600
LIMITS = (
    "The guard covers Python code that goes through the socket module; a "
    "native extension opening its own sockets, or a child process, is not "
    "covered. Loopback and Unix sockets are allowed, except a configured "
    "proxy's address."
)


def child_env(root: Path) -> dict[str, str]:
    """The caller's environment with the store moved under ``root``.

    postcondition: no variable selects PostgreSQL or names a proxy; the
    SQLite store, the Claude directory and ``CODEX_HOME`` are under ``root``."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _STORE_SELECTORS
        and not key.startswith("PG")
        and not key.lower().endswith("_proxy")
    }
    methodology = root / "methodology"
    methodology.mkdir(parents=True, exist_ok=True)
    sqlite_path = str(methodology / "memory.db")
    env.update(
        CORTEX_CLAUDE_DIR=str(root),
        CODEX_HOME=str(root / "codex"),
        CORTEX_MEMORY_STORE_BACKEND="sqlite",
        CORTEX_MEMORY_DB_PATH=sqlite_path,
        CORTEX_MEMORY_SQLITE_FALLBACK_PATH=sqlite_path,
        PYTHONPATH=os.pathsep.join(
            p for p in (str(_REPO), env.get("PYTHONPATH", "")) if p
        ),
    )
    return env


def verdict(document: dict[str, Any]) -> dict[str, Any]:
    """``verdict`` and ``fallback`` of a child document (module docstring)."""
    operations = document["operations"]
    if not all(op["ok"] for op in operations):
        state = "failed"
    elif document["network_attempts"]:
        state = "network_attempted"
    else:
        state = "offline"
    fallback = [
        {"index": i, "operation": op["operation"]}
        for i, op in enumerate(operations)
        if op["embedding_mode"] != "neural" or op["reranker_state"] != "loaded"
    ]
    return {"verdict": state, "fallback": fallback}


def run_child(root: Path) -> dict[str, Any]:
    """Run ``offline_receipt_ops`` once under ``root``; its JSON document.

    raises: ``RuntimeError`` naming the exit status when the child fails
    before writing its document (its stderr is left on the caller's)."""
    output = root / "child.json"
    completed = subprocess.run(
        [sys.executable, "-m", "benchmarks.lib.offline_receipt_ops", str(output)],
        cwd=_REPO,
        env=child_env(root),
        timeout=_TIMEOUT_S,
        stdout=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0 or not output.exists():
        raise RuntimeError(f"offline receipt child exited {completed.returncode}")
    return json.loads(output.read_text(encoding="utf-8"))


def build_receipt() -> dict[str, Any]:
    """One receipt, from a child run in a throwaway directory."""
    with tempfile.TemporaryDirectory(prefix="cortex_offline_receipt_") as tmp:
        document = run_child(Path(tmp))
    return {"schema": SCHEMA, **document, **verdict(document), "limits": LIMITS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    receipt = build_receipt()
    args.out.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"{receipt['verdict']}: {args.out}")
    return 0 if receipt["verdict"] == "offline" else 1


if __name__ == "__main__":
    sys.exit(main())
