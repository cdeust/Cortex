"""Deterministic gap-fix: tested_by edges from scripts/* to the tests that load them at
runtime.

Evidence accepted (AST only, never docstrings/comments):
  1. import statements naming a scripts module: `from scripts.X import`, `from scripts
  import X`, `import scripts.X`
  2. bare `import X` / `from X import` where X is a scripts/ module AND the test inserts
  a scripts dir on sys.path
  3. a non-docstring string constant equal to `scripts/X.py|sh` or to `X.py|sh` (X in
  scripts/) in a file that
     references a scripts directory (load via path: importlib, subprocess, runpy)
Each added edge carries `evidence: "<test path>:<line>"`.
"""

import ast
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
graph_path = Path(sys.argv[2])
g = json.loads(graph_path.read_text())
ids = {n["id"] for n in g["nodes"]}
existing = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
scripts = {
    p.stem: p for p in (root / "scripts").iterdir() if p.suffix in (".py", ".sh")
}


def docstring_nodes(tree):
    out = set()
    for n in ast.walk(tree):
        if (
            isinstance(
                n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            and n.body
        ):
            b = n.body[0]
            if (
                isinstance(b, ast.Expr)
                and isinstance(b.value, ast.Constant)
                and isinstance(b.value.value, str)
            ):
                out.add(id(b.value))
    return out


added, report = [], []
for test in sorted((root / "tests_py").rglob("*.py")):
    rel = test.relative_to(root).as_posix()
    if f"file:{rel}" not in ids:
        continue
    src = test.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        continue
    docs = docstring_nodes(tree)
    mentions_scripts_dir = "scripts" in src
    hits = {}

    def hit(stem, line, why, hits=hits):
        hits.setdefault(stem, (line, why))

    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            parts = n.module.split(".")
            if parts[0] == "scripts" and len(parts) > 1 and parts[1] in scripts:
                hit(parts[1], n.lineno, "import")
            elif parts[0] == "scripts":
                for a in n.names:
                    if a.name in scripts:
                        hit(a.name, n.lineno, "import")
            elif parts[0] in scripts and mentions_scripts_dir and "sys.path" in src:
                hit(parts[0], n.lineno, "sys.path import")
        elif isinstance(n, ast.Import):
            for a in n.names:
                p = a.name.split(".")
                if p[0] == "scripts" and len(p) > 1 and p[1] in scripts:
                    hit(p[1], n.lineno, "import")
                elif p[0] in scripts and mentions_scripts_dir and "sys.path" in src:
                    hit(p[0], n.lineno, "sys.path import")
        elif (
            isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and id(n) not in docs
        ):
            v = n.value.strip()
            name = v[len("scripts/") :] if v.startswith("scripts/") else v
            stem, dot, ext = name.rpartition(".")
            if (
                dot
                and ext in ("py", "sh")
                and "/" not in stem
                and stem in scripts
                and (v.startswith("scripts/") or mentions_scripts_dir)
            ):
                hit(stem, n.lineno, "path literal")
    for stem, (line, why) in hits.items():
        src_id = f"file:scripts/{scripts[stem].name}"
        tgt_id = f"file:{rel}"
        if src_id not in ids:
            report.append(f"SKIP no node {src_id}")
            continue
        key = (src_id, tgt_id, "tested_by")
        if key in existing:
            continue
        existing.add(key)
        added.append(
            {
                "source": src_id,
                "target": tgt_id,
                "type": "tested_by",
                "direction": "forward",
                "weight": 0.5,
                "evidence": f"{rel}:{line}",
                "provenance": f"gapfix/link_runtime_tested_by.py ({why})",
            }
        )

g["edges"].extend(added)
tagged = 0
for n in g["nodes"]:
    if any(e["source"] == n["id"] for e in added) and "tested" not in n.get("tags", []):
        n.setdefault("tags", []).append("tested")
        tagged += 1
graph_path.write_text(json.dumps(g))
json.dump(
    added, open(graph_path.parent / "gapfix" / "added_tested_by.json", "w"), indent=1
)
print(f"added {len(added)} tested_by edges; tagged {tagged} nodes; {len(report)} skips")
for r in report[:10]:
    print(r)
