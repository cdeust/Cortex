"""Cycle 1: add every top-level function/class and method missing from the graph, from
the AST.

Summary = first docstring line when present, else an explicit "No docstring; <kind>
<name> (lines a-b)" —
never invented. Each node carries provenance "ast" so LLM-written and AST-derived
summaries stay distinguishable.
"""

import ast
import json
import sys
from pathlib import Path

# source: reading threshold for the `complexity` label (lines of body), not measured
SIMPLE_MAX_LINES = 20

root = Path(sys.argv[1])
gp = Path(sys.argv[2])
g = json.loads(gp.read_text())
ids = {n["id"] for n in g["nodes"]}
scan = json.load(open(root / ".ua/intermediate/scan-result.json"))["files"]
fid = {
    n["filePath"]: n["id"]
    for n in g["nodes"]
    if n.get("filePath") and n["type"] not in ("function", "class")
}
nodes, edges = [], []


def symbol_node(p, kind, n, nid):
    """The graph node of AST definition `n` (summary = first docstring line)."""
    doc = (ast.get_docstring(n) or "").strip().splitlines()
    summary = (
        doc[0]
        if doc
        else f"No docstring; {kind} {n.name} (lines {n.lineno}-{n.end_lineno})."
    )
    area = (
        "test"
        if p.startswith(("tests_py/", "fuzz/"))
        else ("benchmark" if p.startswith("benchmarks/") else "production")
    )
    tags = [area, kind] + (["private"] if n.name.startswith("_") else [])
    return {
        "id": nid,
        "type": kind,
        "name": n.name,
        "filePath": p,
        "lineRange": [n.lineno, n.end_lineno],
        "summary": summary,
        "tags": tags,
        "complexity": "simple"
        if (n.end_lineno - n.lineno) < SIMPLE_MAX_LINES
        else "moderate",
        "provenance": "gapfix/add_ast_symbols.py",
    }


def add(p, kind, n, parent_id):
    nid = f"{kind}:{p}:{n.name}"
    if nid in ids:
        return nid
    nodes.append(symbol_node(p, kind, n, nid))
    ids.add(nid)
    edges.append(
        {
            "source": parent_id,
            "target": nid,
            "type": "contains",
            "direction": "forward",
            "weight": 1.0,
            "evidence": f"{p}:{n.lineno}",
            "provenance": "gapfix/add_ast_symbols.py",
        }
    )
    return nid


for f in scan:
    p = f["path"]
    if not p.endswith(".py") or p not in fid:
        continue
    try:
        t = ast.parse((root / p).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        continue
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(p, "function", n, fid[p])
        elif isinstance(n, ast.ClassDef):
            cid = add(p, "class", n, fid[p])
            for m in n.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    mid = f"function:{p}:{m.name}"
                    if mid not in ids:
                        add(
                            p, "function", m, cid
                        )  # method; id collides by name across classes -> first wins
g["nodes"] += nodes
g["edges"] += edges
gp.write_text(json.dumps(g))
print(f"added {len(nodes)} symbol nodes, {len(edges)} contains edges")
