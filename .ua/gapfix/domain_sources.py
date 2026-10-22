"""Readers of the sources build_domain_graph.py turns into domains, flows and hooks.

Each reader parses one documented source of the repository: the tool catalogue
(docs/mcp-tools.md), the tool registries (mcp_server/tool_registry_*.py), the
handler modules, and the Claude Code hook wiring (.claude-plugin/plugin.json).
"""

import ast
import glob
import json
import os
import re

# source: how far after `@mcp.tool(name=...)` the registry's safe_handler call is
# looked for (characters); the longest registration in the registries is shorter
REGISTRATION_WINDOW = 2500


def read_catalogue(repo):
    """(tool -> tier heading, tool -> Purpose cell) from docs/mcp-tools.md."""
    tier, tool_tier, purpose = None, {}, {}
    for line in open(f"{repo}/docs/mcp-tools.md", encoding="utf-8"):
        h = re.match(r"^## (.+)", line)
        if h:
            tier = re.sub(r"\s*\(\d+.*\)$", "", h.group(1)).strip()
            continue
        row = re.match(r"^\| `([a-z_]+)` \| (.+?) \|", line)
        if row and tier:
            tool_tier[row.group(1)] = tier
            purpose[row.group(1)] = row.group(2).strip()
    return tool_tier, purpose


def registered_tools(repo, tool_tier):
    """tool -> (handler path, entry function name, registry group).

    `@mcp.tool(name="T")` followed by `safe_handler(<module>.<fn>)` in a registry;
    catalogue tools registered another way fall back to mcp_server/handlers/<T>.py.
    """
    tools = {}
    for p in sorted(glob.glob(f"{repo}/mcp_server/tool_registry_*.py")):
        src = open(p, encoding="utf-8").read()
        gname = os.path.basename(p)[len("tool_registry_") : -3]
        for m in re.finditer(r'@mcp\.tool\(\s*name="([a-z_]+)"', src):
            window = src[m.end() : m.end() + REGISTRATION_WINDOW]
            h = re.search(r"safe_handler\(\s*([a-z_]+)\.([a-z_]+)", window)
            if h and m.group(1) not in tools:
                path = f"mcp_server/handlers/{h.group(1)}.py"
                if os.path.exists(f"{repo}/{path}"):
                    tools[m.group(1)] = (path, h.group(2), gname)
    for t in tool_tier:
        if t not in tools and os.path.exists(f"{repo}/mcp_server/handlers/{t}.py"):
            tools[t] = (f"mcp_server/handlers/{t}.py", "handler", "other")
    return tools


def entry_function(repo, path, name):
    """`name` itself when defined; the wrapped implementation for
    `name = instrument(n, impl, ...)`."""
    tree = ast.parse(open(f"{repo}/{path}", encoding="utf-8").read())
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return name
        if (
            isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
            and isinstance(n.value, ast.Call)
        ):
            for a in n.value.args:
                if isinstance(a, ast.Name):
                    return a.id
    return name


def plugin_hooks(repo):
    """[(hook module, event, matcher)] wired in .claude-plugin/plugin.json."""
    hooks = []
    plugin = json.load(open(f"{repo}/.claude-plugin/plugin.json"))
    for event, matchers in plugin.get("hooks", {}).items():
        for m in matchers:
            for h in m.get("hooks", []):
                mm = re.search(r"mcp_server\.hooks\.([a-z_]+)", h.get("command", ""))
                if mm:
                    hooks.append((mm.group(1), event, m.get("matcher", "")))
    return hooks
