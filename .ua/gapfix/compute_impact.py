"""Impact (blast radius) per function and per change set, from the graph's edges.

For every production function/class X (not under tests_py/):
  callers     = reverse transitive closure of `calls` (production code only)
  entryPoints = callers ∪ {X} that are MCP tool handlers
  (mcp_server/handlers/*:handler),
                hook entry points (mcp_server/hooks/*:main) or CLI mains
                (scripts/*:main)
  tests       = test functions with a static `calls` path into {X} ∪ callers
  measured    = number of tests whose execution covered X (coverage.py contexts,
                `exercisedByTests`), when present
Written to node['impact'] and as tags `blast:<low|medium|high>` (callers <5 / <50 /
>=50:
quartile-free thresholds chosen for reading, not for scoring) and `entry:<n>`.

For each change set (git ref vs base), changed = functions/classes whose line range
intersects a changed hunk (and files touched); affected = their callers, entry points,
tests, documenting docs and the files containing them. Written as
diff-overlay-<label>.json in the dashboard's overlay format.

usage: python3 compute_impact.py <repo> <graph> <base> <out_dir> [label=ref ...]
"""

import collections
import json
import re
import subprocess
import sys

# source: reading thresholds for the blast tags (callers), stated in the docstring
BLAST_LOW_MAX = 5
# source: reading threshold for the blast tags (callers), stated in the docstring
BLAST_MEDIUM_MAX = 50

REPO, GP, BASE, OUT = sys.argv[1:5]
CHANGESETS = [a.split("=", 1) for a in sys.argv[5:]]
g = json.load(open(GP))
nodes = {n["id"]: n for n in g["nodes"]}
callers = collections.defaultdict(set)
contains = collections.defaultdict(set)
documents = collections.defaultdict(set)
for e in g["edges"]:
    if e["type"] == "calls":
        callers[e["target"]].add(e["source"])
    elif e["type"] == "contains":
        contains[e["source"]].add(e["target"])
    elif e["type"] == "documents":
        documents[e["target"]].add(e["source"])
file_of = {n["id"]: n["filePath"] for n in g["nodes"]}
file_node = {
    n["filePath"]: n["id"] for n in g["nodes"] if n["type"] not in ("function", "class")
}


def is_test(nid):
    return file_of.get(nid, "").startswith("tests_py/")


def entry(nid):
    n = nodes.get(nid)
    p = file_of.get(nid, "")
    if not n or n["type"] != "function":
        return None
    if p.startswith("mcp_server/handlers/") and n["name"] == "handler":
        return "tool:" + p.rsplit("/", 1)[1][:-3]
    if p.startswith("mcp_server/hooks/") and n["name"] == "main":
        return "hook:" + p.rsplit("/", 1)[1][:-3]
    if p.startswith("scripts/") and n["name"] == "main":
        return "cli:" + p.rsplit("/", 1)[1][:-3]
    return None


def closure(start):
    """(production callers, tests) reachable backwards from the ids in `start`."""
    seen, tests, stack = set(), set(), list(start)
    while stack:
        cur = stack.pop()
        for c in callers.get(cur, ()):
            if is_test(c):
                tests.add(c)
                continue
            if c not in seen and c not in start:
                seen.add(c)
                stack.append(c)
    return seen, tests


def per_function():
    for n in g["nodes"]:
        if n["type"] not in ("function", "class") or is_test(n["id"]):
            continue
        cs, ts = closure({n["id"]})
        eps = sorted({e for e in (entry(x) for x in cs | {n["id"]}) if e})
        n["impact"] = {
            "callers": len(cs),
            "callerFiles": len({file_of[c] for c in cs}),
            "entryPoints": eps,
            "tests": len(ts),
            "measuredTests": n.get("exercisedByTests") or 0,
        }
        tags = [t for t in n.get("tags", []) if not t.startswith(("blast:", "entry:"))]
        tags.append(
            "blast:"
            + (
                "low"
                if len(cs) < BLAST_LOW_MAX
                else "medium"
                if len(cs) < BLAST_MEDIUM_MAX
                else "high"
            )
        )
        tags.append(f"entry:{len(eps)}")
        n["tags"] = tags


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", re.M)


def changed_ranges(ref):
    out = subprocess.run(
        ["git", "-C", REPO, "diff", "-U0", f"{BASE}...{ref}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    ranges = collections.defaultdict(list)
    cur = None
    for line in out.splitlines():
        if line.startswith("--- "):
            cur = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("+++ ") and cur is None and line.startswith("+++ b/"):
            cur = line[6:]
            ranges[cur].append((0, 0))  # new file: file-level change only
        elif line.startswith("@@") and cur:
            m = HUNK.match(line)
            start = int(m.group(1))
            length = int(m.group(2) or 1)
            ranges[cur].append((start, start + max(length, 1) - 1))
    return ranges


def overlay(label, ref):
    ranges = changed_ranges(ref)
    changed = set()
    for path, rs in ranges.items():
        if path in file_node:
            changed.add(file_node[path])
        for n in g["nodes"]:
            if (
                n["type"] in ("function", "class")
                and n["filePath"] == path
                and n.get("lineRange")
            ):
                a, b = n["lineRange"]
                if any(s <= b and e >= a for s, e in rs if s):
                    changed.add(n["id"])
    fn_changed = {c for c in changed if nodes[c]["type"] in ("function", "class")}
    cs, ts = closure(fn_changed)
    affected = cs | ts
    affected |= {file_node[file_of[x]] for x in affected if file_of.get(x) in file_node}
    for c in changed:
        affected |= documents.get(c, set())
    affected -= changed
    doc = {
        "label": label,
        "ref": ref,
        "base": BASE,
        "changedNodeIds": sorted(changed),
        "affectedNodeIds": sorted(affected),
        "entryPoints": sorted({e for e in (entry(x) for x in cs | fn_changed) if e}),
        "summary": {
            "changed": len(changed),
            "affected": len(affected),
            "tests": len(ts),
            "files_in_diff": len(ranges),
            "files_not_in_graph": sorted(p for p in ranges if p not in file_node),
        },
    }
    json.dump(doc, open(f"{OUT}/diff-overlay-{label}.json", "w"), indent=1)
    print(
        label, json.dumps(doc["summary"])[:300], "entry points:", doc["entryPoints"][:8]
    )


per_function()
json.dump(g, open(GP, "w"), indent=2, ensure_ascii=False)
for label, ref in CHANGESETS:
    overlay(label, ref)
blast = collections.Counter(
    t for n in g["nodes"] for t in n.get("tags", []) if t.startswith("blast:")
)
print("blast tags:", dict(blast))
