"""Call graph v2: `calls` edges resolved through imports, re-exports, classes and known
types.

Resolution rules (no name-similarity guessing; an unresolvable call is skipped):
  f(...)                 -> def in this module, or an imported symbol (followed through
                            re-exporting modules, depth <= 6)
  mod.f(...)             -> symbol f of the module bound to `mod` by an import
  C(...)                 -> class C (and C.__init__ when C defines it)
  C.m(...)               -> method m of class C or of its resolved bases
  self.m / cls.m(...)    -> method m of the enclosing class or its resolved bases
  super().m(...)         -> method m of a resolved base of the enclosing class
  v.m(...)               -> method m of class C when v is a parameter or local annotated
  `C`
                            (or Optional[C] / C | None) or assigned `v = C(...)` in the
                            function
Methods are graph nodes `function:<file>:<name>`; a method edge is added only when that
name is defined in the class body. Evidence = caller file:line.

usage: python3 link_calls_resolved.py <repo root> <knowledge-graph.json>
"""

import ast
import json
import sys
from pathlib import Path

import call_resolution as cr
import call_targets as ct

ROOT = Path(sys.argv[1])
GP = Path(sys.argv[2])
SCAN = ("mcp_server/", "scripts/", "benchmarks/", "plugins/", "tests_py/", "fuzz/")


def add_edge(g, have, src, tid, weight, evidence):
    """Append one `calls` edge unless it already exists; True when added."""
    if (src, tid, "calls") in have:
        return False
    g["edges"].append(
        {
            "source": src,
            "target": tid,
            "type": "calls",
            "direction": "forward",
            "weight": weight,
            "evidence": evidence,
        }
    )
    have.add((src, tid, "calls"))
    return True


def link_function(g, ids, have, m, fn, cls):
    """Edges for one function: its calls, then the callables it passes on."""
    p = m.path
    src = f"function:{p}:{fn.name}"
    if src not in ids:
        return 0
    local_imports = cr.import_table(fn.body, m.pkg)
    types = ct.local_types(m, fn, local_imports)
    added = 0
    for call in (c for c in ast.walk(fn) if isinstance(c, ast.Call)):
        for kind, tp, tn in ct.callee_targets(m, fn, cls, call, local_imports, types):
            tid = f"{kind}:{tp}:{tn}"
            if tid in ids and tid != src:
                ev = f"{p}:{call.lineno} resolved call"
                added += add_edge(g, have, src, tid, 0.8, ev)
    for ref in ct.references(fn):
        as_call = ast.Call(func=ref, args=[], keywords=[])
        for kind, tp, tn in ct.callee_targets(
            m, fn, cls, as_call, local_imports, types
        ):
            tid = f"{kind}:{tp}:{tn}"
            if kind == "function" and tid in ids and tid != src:
                ev = f"{p}:{ref.lineno} passed as a callable reference"
                added += add_edge(g, have, src, tid, 0.6, ev)
    return added


def main():
    cr.configure(ROOT)
    g = json.loads(GP.read_text())
    ids = {n["id"] for n in g["nodes"]}
    have = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
    paths = sorted(
        {
            n["filePath"]
            for n in g["nodes"]
            if n["filePath"].endswith(".py") and n["filePath"].startswith(SCAN)
        }
    )
    ct.index_subclasses(paths)
    added = 0
    for p in paths:
        m = cr.load(p)
        if m:
            for fn, cls in ct.functions(m):
                added += link_function(g, ids, have, m, fn, cls)
    GP.write_text(json.dumps(g, indent=2, ensure_ascii=False))
    print("calls edges added:", added)


main()
