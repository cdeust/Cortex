"""domain-graph.json for the Understand-Anything domain view, built from sources.

Domains  = the tool tiers of docs/mcp-tools.md (their headings), plus "Session
           lifecycle hooks" (.claude-plugin/plugin.json) and, for handlers the
           catalogue does not list, the tool_registry_<group>.py that registers them.
Flows    = one per MCP tool handler (mcp_server/handlers/<tool>.py: handler) and per
           hook module wired in plugin.json; summary = the catalogue's Purpose cell,
           else the handler's/hook's own summary; entryPoint = "MCP tool <name>" or
           "<Event>[matcher] hook".
Steps    = the project functions the entry function calls, in source order (calls
           edges of the graph, ordered by their evidence line); when the entry calls
           at most two project functions, the steps come from the one it delegates to.
           Each step points at the callee's file and line range.
cross_domain = domain A -> B when a step of A is the entry function of a flow of B.
usage: python3 build_domain_graph.py <repo> <knowledge-graph.json> <out domain-
graph.json>
"""

import collections
import datetime
import json
import re
import sys

from domain_sources import (
    entry_function,
    plugin_hooks,
    read_catalogue,
    registered_tools,
)

# source: below this many direct project calls an entry only delegates;
# its steps are taken from the function it delegates to (see module docstring)
DELEGATION_MAX_CALLS = 2

REPO, GP, OUT = sys.argv[1:4]
g = json.load(open(GP))
nodes = {n["id"]: n for n in g["nodes"]}
calls = collections.defaultdict(list)
for e in g["edges"]:
    if (
        e["type"] == "calls"
        and e["target"] in nodes
        and nodes[e["target"]]["type"] == "function"
    ):
        m = re.search(r":(\d+) ", e.get("evidence", "") + " ")
        calls[e["source"]].append((int(m.group(1)) if m else 10**6, e["target"]))


def kebab(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


tool_tier, purpose = read_catalogue(REPO)
tools = registered_tools(REPO, tool_tier)
hooks = plugin_hooks(REPO)

D, E = [], []
domains = {}


def domain(name, summary, tags):
    did = f"domain:{kebab(name)}"
    if did not in domains:
        domains[did] = {
            "id": did,
            "type": "domain",
            "name": name,
            "summary": summary,
            "tags": tags,
            "complexity": "complex",
            "domainMeta": {
                "entities": [],
                "businessRules": [],
                "crossDomainInteractions": [],
            },
        }
    return did


def steps_for(entry_id):
    direct = [t for _, t in sorted(calls.get(entry_id, []))]
    seq = list(dict.fromkeys(direct))
    if len(seq) <= DELEGATION_MAX_CALLS:
        for t in list(seq):
            deeper = list(dict.fromkeys(x for _, x in sorted(calls.get(t, []))))
            if len(deeper) > len(seq):
                seq = deeper
                break
    return seq[:8]


flow_entry = {}


def flow(fid, name, summary, entry_point, entry_type, entry_id, did, path):
    n = nodes.get(entry_id, {})
    D.append(
        {
            "id": fid,
            "type": "flow",
            "name": name,
            "summary": summary,
            "tags": [entry_type, "flow"],
            "complexity": n.get("complexity", "moderate"),
            "filePath": path,
            "lineRange": n.get("lineRange", [0, 0]),
            "domainMeta": {"entryPoint": entry_point, "entryType": entry_type},
        }
    )
    E.append(
        {
            "source": did,
            "target": fid,
            "type": "contains_flow",
            "direction": "forward",
            "weight": 1.0,
        }
    )
    flow_entry[entry_id] = (fid, did)
    add_steps(fid, entry_id)


def add_steps(fid, entry_id):
    """The flow's steps: the entry's project callees in source order (steps_for)."""
    seq = steps_for(entry_id)
    k = len(seq)
    for i, t in enumerate(seq, 1):
        c = nodes[t]
        sid = f"step:{fid[5:]}:{kebab(c['name'])}-{i}"
        D.append(
            {
                "id": sid,
                "type": "step",
                "name": c["name"],
                "summary": c.get("summary") or c["name"],
                "tags": ["step"],
                "complexity": c.get("complexity", "simple"),
                "filePath": c["filePath"],
                "lineRange": c.get("lineRange", [0, 0]),
                "implementedBy": t,
            }
        )
        E.append(
            {
                "source": fid,
                "target": sid,
                "type": "flow_step",
                "direction": "forward",
                "weight": round(max(0.0, min(1.0, i / max(k, 1))), 3),
            }
        )


for tool, (path, fn, gname) in sorted(tools.items()):
    tier_name = tool_tier.get(tool) or f"Tools registered by tool_registry_{gname}"
    did = domain(
        tier_name,
        f"{tier_name}: MCP tools of Cortex grouped as in docs/mcp-tools.md."
        if tool in tool_tier
        else (
            f"MCP tools registered by mcp_server/tool_registry_{gname}.py "
            "and not listed in docs/mcp-tools.md."
        ),
        ["mcp-tools"],
    )
    entry = f"function:{path}:{entry_function(REPO, path, fn)}"
    flow(
        f"flow:{kebab(tool)}",
        tool,
        purpose.get(tool) or nodes.get(entry, {}).get("summary", tool),
        f"MCP tool {tool}",
        "manual",
        entry,
        did,
        path,
    )

hdid = domain(
    "Session lifecycle hooks",
    "Claude Code hooks wired in .claude-plugin/plugin.json: they inject memory "
    "into sessions and capture what happens in them.",
    ["hooks"],
)
for mod, event, matcher in hooks:
    path = f"mcp_server/hooks/{mod}.py"
    entry = f"function:{path}:main"
    fid = f"flow:hook-{kebab(mod)}"
    if any(d["id"] == fid for d in D):
        continue
    summ = nodes.get(f"file:{path}", {}).get("summary") or nodes.get(entry, {}).get(
        "summary", mod
    )
    flow(
        fid,
        f"{event} hook: {mod}",
        summ,
        f"{event}{'[' + matcher + ']' if matcher else ''} hook",
        "event",
        entry,
        hdid,
        path,
    )

# cross-domain: a step that is another flow's entry function
cross = collections.Counter()
for d in D:
    if d["type"] == "step" and d.get("implementedBy") in flow_entry:
        owner = next(
            e["source"]
            for e in E
            if e["type"] == "flow_step" and e["target"] == d["id"]
        )
        a = next(
            e["source"]
            for e in E
            if e["type"] == "contains_flow" and e["target"] == owner
        )
        b = flow_entry[d["implementedBy"]][1]
        if a != b:
            cross[(a, b)] += 1
for (a, b), c in cross.items():
    E.append(
        {
            "source": a,
            "target": b,
            "type": "cross_domain",
            "direction": "forward",
            "weight": 0.6,
            "description": f"{c} step(s) of {a} run a flow of {b}",
        }
    )

out = {
    "version": "1.0.0",
    "project": {
        **g["project"],
        "analyzedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    },
    "nodes": list(domains.values()) + D,
    "edges": E,
    "layers": [],
    "tour": [],
}
json.dump(out, open(OUT, "w"), indent=2, ensure_ascii=False)
c = collections.Counter(n["type"] for n in out["nodes"])
print(
    dict(c),
    "edges",
    len(E),
    "cross_domain",
    len(cross),
    "| flows without steps:",
    sum(
        1
        for n in D
        if n["type"] == "flow"
        and not any(e["source"] == n["id"] and e["type"] == "flow_step" for e in E)
    ),
)
