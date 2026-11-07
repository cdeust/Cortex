"""Check that Cortex's redaction engine finds exactly what gitleaks finds.

The engine (``mcp_server/shared/redaction_engine.py``) ports gitleaks' rule
decision procedure to Python; this compares the two on the same files, as
sets of ``(file, line, rule id)``:

- ``--corpus``: the generated real-format fake credentials and negatives of
  ``scripts/secret_corpus.py``, written to a temporary directory;
- ``--tree DIR``: any directory (CI passes the checkout).

Usage: ``python scripts/redaction_parity.py --gitleaks /path/to/gitleaks
[--corpus] [--tree DIR]``. Exit 0 when the sets are equal, 1 otherwise; the
report names rule ids, files and lines, never secret values.

source: ADR-1110"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from mcp_server.shared.redaction_engine import redaction_spans  # noqa: E402
from mcp_server.shared.redaction_gate import rule_set  # noqa: E402
from scripts.secret_corpus import NEGATIVES, samples  # noqa: E402

Finding = tuple[str, int, str]


VENDORED_CONFIG = REPO_ROOT / "third_party" / "gitleaks" / "v8.30.1" / "gitleaks.toml"
RULES_JSON = REPO_ROOT / "mcp_server" / "shared" / "redaction_rules" / "gitleaks.json"


def _global_path_allowlist() -> list[re.Pattern[str]]:
    block = VENDORED_CONFIG.read_text(encoding="utf-8").split("[[rules]]", 1)[0]
    paths = block.split("paths = [", 1)[1].split("]\nregexes", 1)[0]
    return [re.compile(p) for p in re.findall(r"'''(.*?)'''", paths)]


def port_findings(root: Path) -> set[Finding]:
    skip = _global_path_allowlist()
    found: set[Finding] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            if any(p.search(rel) for p in skip):
                continue
            try:
                text = Path(dirpath, name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for start, _end, rule_id in redaction_spans(text, rule_set()):
                found.add((rel, text.count("\n", 0, start) + 1, rule_id))
    return found


def gitleaks_findings(binary: str, root: Path) -> set[Finding]:
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        subprocess.run(  # noqa: S603 — caller-pinned binary
            [
                binary,
                "dir",
                str(root),
                # the pinned default rules, never a .gitleaks.toml found in root
                "--config",
                str(VENDORED_CONFIG),
                "--no-banner",
                "--redact=100",
                "-f",
                "json",
                "-r",
                str(report),
                "--exit-code",
                "0",
            ],
            check=True,
            capture_output=True,
        )
        rows = json.loads(report.read_text(encoding="utf-8"))
    prefix = str(root).rstrip("/") + "/"
    # rules the port skips by design (they need a file name) are out of scope
    skipped = {r["id"] for r in json.loads(RULES_JSON.read_text())["skipped"]}
    return {
        (r["File"].removeprefix(prefix), r["StartLine"], r["RuleID"])
        for r in rows
        if r["RuleID"] not in skipped
    }


def write_corpus(root: Path) -> None:
    for rule_id, (text, _fake) in samples().items():
        (root / f"{rule_id}.txt").write_text(text + "\n", encoding="utf-8")
    (root / "negatives.txt").write_text("\n".join(NEGATIVES) + "\n", encoding="utf-8")


def compare(binary: str, root: Path) -> int:
    ours, theirs = port_findings(root), gitleaks_findings(binary, root)
    print(f"{root}: gitleaks={len(theirs)} port={len(ours)} both={len(ours & theirs)}")
    for row in sorted(theirs - ours):
        print("  only gitleaks:", *row)
    for row in sorted(ours - theirs):
        print("  only port:   ", *row)
    return 0 if ours == theirs else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gitleaks", required=True)
    parser.add_argument("--corpus", action="store_true")
    parser.add_argument("--tree", type=Path)
    args = parser.parse_args(argv)
    status = 0
    if args.corpus:
        with tempfile.TemporaryDirectory() as tmp:
            write_corpus(Path(tmp))
            status |= compare(args.gitleaks, Path(tmp))
    if args.tree:
        status |= compare(args.gitleaks, args.tree.resolve())
    return status


if __name__ == "__main__":
    sys.exit(main())
