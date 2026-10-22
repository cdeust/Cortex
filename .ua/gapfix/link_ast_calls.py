"""Deterministic gap-fix: `calls` edges recovered from the AST, incl. function-local
(deferred) imports.

For every function/method node already in the graph, resolve each call `name(...)` /
`mod.name(...)` to
  - a function defined in the same file, or
  - a function imported (module-level OR inside the function body) from a project
  module,
and add `calls` source->target when both nodes exist and the edge is absent. Evidence =
caller file:line.
Only resolution through explicit imports/defs; no name-similarity guessing.
"""

import ast
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
gp = Path(sys.argv[2])
g = json.loads(gp.read_text())
ids = {n["id"] for n in g["nodes"]}
have = {(e["source"], e["target"], e["type"]) for e in g["edges"]}


def mod_to_path(mod):
    p = root / Path(*mod.split("."))
    if (p.with_suffix(".py")).is_file():
        return p.with_suffix(".py").relative_to(root).as_posix()
    if (p / "__init__.py").is_file():
        return (p / "__init__.py").relative_to(root).as_posix()
    return None


def fnode(path, name):
    for kind in ("function", "class"):
        nid = f"{kind}:{path}:{name}"
        if nid in ids:
            return nid
    return None


def imports_in(body_nodes, here_pkg):
    table = {}
    for n in body_nodes:
        if isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            if n.level:
                base = here_pkg.split(".")[: len(here_pkg.split(".")) - (n.level - 1)]
                mod = ".".join(base + ([mod] if mod else []))
            for a in n.names:
                sub = mod_to_path(f"{mod}.{a.name}") if mod else None
                if sub:
                    table[a.asname or a.name] = ("module", sub)
                else:
                    p = mod_to_path(mod) if mod else None
                    if p:
                        table[a.asname or a.name] = ("symbol", p, a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                p = mod_to_path(a.name)
                if p:
                    table[a.asname or a.name.split(".")[0]] = (
                        ("module", p)
                        if a.asname or "." not in a.name
                        else ("pkg", a.name)
                    )
    return table


added = []
files = [p for d in ("mcp_server", "scripts") for p in (root / d).rglob("*.py")]
for f in files:
    rel = f.relative_to(root).as_posix()
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        continue
    pkg = ".".join(Path(rel).with_suffix("").parts[:-1])
    top = imports_in(
        [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))], pkg
    )
    local_defs = {
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for fn in [
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]:
        caller = fnode(rel, fn.name)
        if not caller:
            continue
        table = {
            **top,
            **imports_in(
                [
                    n
                    for n in ast.walk(fn)
                    if isinstance(n, (ast.Import, ast.ImportFrom))
                ],
                pkg,
            ),
        }
        for c in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
            tgt = None
            if isinstance(c.func, ast.Name):
                nm = c.func.id
                if nm in table and table[nm][0] == "symbol":
                    tgt = fnode(table[nm][1], table[nm][2])
                elif nm in local_defs:
                    tgt = fnode(rel, nm)
            elif isinstance(c.func, ast.Attribute) and isinstance(
                c.func.value, ast.Name
            ):
                ent = table.get(c.func.value.id)
                if ent and ent[0] == "module":
                    tgt = fnode(ent[1], c.func.attr)
            if tgt and tgt != caller and (caller, tgt, "calls") not in have:
                have.add((caller, tgt, "calls"))
                added.append(
                    {
                        "source": caller,
                        "target": tgt,
                        "type": "calls",
                        "direction": "forward",
                        "weight": 0.8,
                        "evidence": f"{rel}:{c.lineno}",
                        "provenance": "gapfix/link_ast_calls.py",
                    }
                )
g["edges"].extend(added)
gp.write_text(json.dumps(g))
json.dump(added, open(gp.parent / "gapfix" / "added_calls.json", "w"), indent=1)
print(f"added {len(added)} calls edges from {len(files)} files")
