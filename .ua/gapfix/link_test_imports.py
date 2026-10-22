"""Cycle 1: tested_by edges from production modules to test files that import them (AST
import evidence)."""

import ast
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
gp = Path(sys.argv[2])
g = json.loads(gp.read_text())
fid = {
    n["filePath"]: n["id"]
    for n in g["nodes"]
    if n.get("filePath") and n["type"] not in ("function", "class")
}
have = {(e["source"], e["target"], e["type"]) for e in g["edges"]}


def mod_path(m):
    b = root / Path(*m.split("."))
    for c in (b.with_suffix(".py"), b / "__init__.py"):
        if c.is_file():
            return c.relative_to(root).as_posix()
    return None


added = []
for t in sorted((root / "tests_py").rglob("test_*.py")):
    rel = t.relative_to(root).as_posix()
    if rel not in fid:
        continue
    try:
        tree = ast.parse(t.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        continue
    for n in ast.walk(tree):
        mods = []
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods = [f"{n.module}.{a.name}" for a in n.names] + [n.module]
        elif isinstance(n, ast.Import):
            mods = [a.name for a in n.names]
        for m in mods:
            if not m.startswith(("mcp_server", "scripts")):
                continue
            p = mod_path(m)
            if not p or p.endswith("__init__.py") or p not in fid:
                continue
            k = (fid[p], fid[rel], "tested_by")
            if k in have:
                continue
            have.add(k)
            added.append(
                {
                    "source": fid[p],
                    "target": fid[rel],
                    "type": "tested_by",
                    "direction": "forward",
                    "weight": 0.5,
                    "evidence": f"{rel}:{n.lineno}",
                    "provenance": "gapfix/link_test_imports.py",
                }
            )
            break
g["edges"] += added
src = {e["source"] for e in added}
for n in g["nodes"]:
    if n["id"] in src and "tested" not in n.setdefault("tags", []):
        n["tags"].append("tested")
gp.write_text(json.dumps(g))
print(f"added {len(added)} tested_by edges")
