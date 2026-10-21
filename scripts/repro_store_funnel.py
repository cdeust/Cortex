#!/usr/bin/env python3
"""ADR-1112 increment 2 acceptance: database access outside the store.

One command, no database:

    python scripts/repro_store_funnel.py [--base-ref main]

Counts, for the base ref (extracted with ``git archive``) and for the working
tree, the two quantities ``tests_py/architecture/test_store_funnel.py`` pins
to zero: lines outside ``mcp_server/infrastructure/`` that reach a store's
connection or pools, and modules there that import the PostgreSQL driver
(minus the listed diagnostics). Prints a JSON summary and appends an entry to
the append-only experiment log.

source: ADR-1112 (increment 2, research protocol)
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests_py.architecture.test_store_funnel import (  # noqa: E402
    _DRIVER_ALLOWED,
    connection_offenders,
    driver_importers,
)

LOG = ROOT / "docs" / "verification" / "connection-broker" / "experiment-log.md"


def _measure(package: Path) -> dict:
    offenders = connection_offenders(package)
    importers = sorted(driver_importers(package) - set(_DRIVER_ALLOWED))
    files = sorted({line.rsplit(":", 1)[0] for line in offenders})
    return {
        "connection_access_lines": len(offenders),
        "connection_access_files": len(files),
        "driver_importers_outside_diagnostics": len(importers),
        "files": files,
        "importers": importers,
    }


def _extract(ref: str, into: Path) -> Path:
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", ref, "mcp_server"],
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(into, filter="data")
    return into / "mcp_server"


def _append(base_ref: str, before: dict, after: dict) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    lines = [
        "",
        f"### store funnel census {stamp} (`python scripts/repro_store_funnel.py`)",
        "",
        f"- Variable: the code tree ({base_ref} vs working tree); no database.",
    ]
    for label, data in ((base_ref, before), ("working tree", after)):
        summary = {k: v for k, v in data.items() if k not in ("files", "importers")}
        lines.append(f"- {label}: `{json.dumps(summary)}`")
    if before["files"]:
        lines.append(f"- {base_ref} files: {', '.join(before['files'])}")
    if before["importers"]:
        lines.append(f"- {base_ref} driver importers: {', '.join(before['importers'])}")
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="main")
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cortex-funnel-") as scratch:
        before = _measure(_extract(args.base_ref, Path(scratch)))
    after = _measure(ROOT / "mcp_server")
    print(json.dumps({args.base_ref: before, "working tree": after}, indent=2))
    if not args.no_log:
        _append(args.base_ref, before, after)
    clean = after["connection_access_lines"] == 0
    return 0 if clean and not after["driver_importers_outside_diagnostics"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
