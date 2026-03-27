"""Node construction helpers for the unified graph builder.

Builds a 6-level hierarchy: root → category → project → agent → type-group → leaf.
Each function appends nodes (and direct parent-child edges) for one level.
Pure business logic -- no I/O.

Memory and entity node builders live in graph_builder_memory.py.
"""

from __future__ import annotations

import re
from typing import Any

# ── Type aliases ─────────────────────────────────────────────────────

Node = dict[str, Any]
Edge = dict[str, Any]
IdAllocator = Any  # callable(str) -> str

# ── Colors ───────────────────────────────────────────────────────────

ROOT_COLOR = "#FFFFFF"
CATEGORY_COLOR = "#8B5CF6"
DOMAIN_COLOR = "#E8B840"
AGENT_COLOR = "#2DD4BF"
TYPE_GROUP_COLOR = "#64748B"
ENTRY_COLOR = "#60D8F0"
PATTERN_COLOR = "#70D880"
TOOL_COLOR = "#E0A840"
FEATURE_COLOR = "#B088E0"
MEMORY_COLORS = {"episodic": "#58D888", "semantic": "#C070D0"}
ENTITY_COLORS = {
    "function": "#50D0E8",
    "dependency": "#60A0E0",
    "error": "#E07070",
    "decision": "#E0C050",
    "technology": "#9080D0",
    "file": "#7088D0",
    "variable": "#50B8D0",
}

EDGE_COLORS = {
    "has-category": "#B0B0B0",
    "has-project": "#8B5CF6",
    "has-agent": "#2DD4BF",
    "has-group": "#64748B",
    "groups": "#50C8E0",
    "bridge": "#FF00FF",
    "persistent-feature": "#ec4899",
    "memory-entity": "#40A0B8",
    "domain-entity": "#50B0C8",
}

# ── Technology category classification ───────────────────────────────

_TECH_KEYWORDS: dict[str, set[str]] = {
    "Backend": {
        "api",
        "database",
        "server",
        "fastapi",
        "postgresql",
        "auth",
        "migration",
        "backend",
        "endpoint",
        "middleware",
        "sql",
        "redis",
        "graphql",
        "rest",
        "microservice",
        "celery",
        "django",
        "flask",
    },
    "Frontend": {
        "react",
        "typescript",
        "component",
        "ui",
        "android",
        "css",
        "rendering",
        "frontend",
        "html",
        "vue",
        "angular",
        "swift",
        "ios",
        "mobile",
        "widget",
        "layout",
        "animation",
        "navigation",
    },
    "AI/Research": {
        "prd",
        "metaprompting",
        "orchestration",
        "research",
        "prompting",
        "rag",
        "strategy",
        "llm",
        "model",
        "embedding",
        "benchmark",
        "evaluation",
        "thinking",
        "cognitive",
        "neural",
        "memory",
        "thermodynamic",
        "cortex",
        "methodology",
    },
    "DevOps": {
        "deploy",
        "docker",
        "ci",
        "pipeline",
        "git",
        "homebrew",
        "compiler",
        "build",
        "infrastructure",
        "terraform",
        "kubernetes",
        "monitoring",
        "logging",
        "container",
        "certificate",
    },
}


def classify_tech_category(dp: dict) -> str:
    """Classify a domain profile into a technology category.

    Uses topKeywords and tool names for signal. Returns the best-matching
    category or 'General' as fallback.
    """
    keywords = {k.lower() for k in (dp.get("topKeywords") or [])}
    # Add tool names as signal
    for tool_name in dp.get("toolPreferences") or {}:
        keywords.add(tool_name.lower())

    best_cat = "General"
    best_score = 0
    for cat, cat_keywords in _TECH_KEYWORDS.items():
        score = len(keywords & cat_keywords)
        if score > best_score:
            best_score = score
            best_cat = cat
    return best_cat


# ── Level 0: Root node ───────────────────────────────────────────────


def add_root_node(
    next_id: IdAllocator,
    nodes: list[Node],
) -> str:
    """Create the single root node. Returns its id."""
    nid = next_id("root")
    nodes.append(
        {
            "id": nid,
            "type": "root",
            "label": "Cortex",
            "domain": "",
            "color": ROOT_COLOR,
            "size": 30,
            "group": "_root",
            "content": "Cortex — cognitive profiling & persistent memory",
        }
    )
    return nid


# ── Level 1: Category nodes ─────────────────────────────────────────


def add_category_node(
    name: str,
    root_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> str:
    """Create a technology category node linked to root. Returns its id."""
    nid = next_id("cat")
    nodes.append(
        {
            "id": nid,
            "type": "category",
            "label": name,
            "domain": "",
            "color": CATEGORY_COLOR,
            "size": 12,
            "group": "_categories",
            "content": f"Technology category: {name}",
        }
    )
    edges.append(
        {
            "source": root_id,
            "target": nid,
            "type": "has-category",
            "weight": 0.8,
            "color": EDGE_COLORS["has-category"],
        }
    )
    return nid


# ── Level 2: Project (domain) nodes ─────────────────────────────────


def add_domain_hub(
    dp: dict,
    domain_key: str,
    category_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> str:
    """Create a project/domain hub node linked to its category. Returns its id."""
    hub_id = next_id("dom")
    session_count = dp.get("sessionCount") or 0
    nodes.append(
        {
            "id": hub_id,
            "type": "domain",
            "label": dp.get("label") or domain_key,
            "domain": domain_key,
            "color": DOMAIN_COLOR,
            "size": max(6, min(25, (session_count or 1) ** 0.5 * 2)),
            "group": domain_key,
            "sessionCount": session_count,
            "confidence": dp.get("confidence") or 0,
            "content": (
                f"{dp.get('label') or domain_key} — "
                f"{session_count} sessions, confidence {(dp.get('confidence') or 0):.0%}"
            ),
        }
    )
    edges.append(
        {
            "source": category_id,
            "target": hub_id,
            "type": "has-project",
            "weight": 0.7,
            "color": EDGE_COLORS["has-project"],
        }
    )
    return hub_id


# ── Level 3: Agent nodes ────────────────────────────────────────────


def add_agent_node(
    agent: dict,
    domain_key: str,
    hub_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> str:
    """Create an agent node linked to its project. Returns its id."""
    nid = next_id("agent")
    nodes.append(
        {
            "id": nid,
            "type": "agent",
            "label": agent["name"],
            "domain": domain_key,
            "color": AGENT_COLOR,
            "size": 6,
            "group": domain_key,
            "content": agent.get("description", agent["name"]),
            "toolCount": len(agent.get("tools", [])),
        }
    )
    edges.append(
        {
            "source": hub_id,
            "target": nid,
            "type": "has-agent",
            "weight": 0.6,
            "color": EDGE_COLORS["has-agent"],
        }
    )
    return nid


# ── Level 4: Type-group nodes ───────────────────────────────────────

TYPE_GROUP_LABELS = ["Entry Points", "Patterns", "Tools", "Features", "Memories"]


def add_type_group_nodes(
    parent_id: str,
    domain_key: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
    labels: list[str] | None = None,
) -> dict[str, str]:
    """Create type-group nodes under a parent (agent or hub). Returns {label: nid}."""
    labels = labels or TYPE_GROUP_LABELS
    result: dict[str, str] = {}
    for label in labels:
        nid = next_id("tg")
        nodes.append(
            {
                "id": nid,
                "type": "type-group",
                "label": label,
                "domain": domain_key,
                "color": TYPE_GROUP_COLOR,
                "size": 3,
                "group": domain_key,
                "content": f"{label} for {domain_key}",
            }
        )
        edges.append(
            {
                "source": parent_id,
                "target": nid,
                "type": "has-group",
                "weight": 0.5,
                "color": EDGE_COLORS["has-group"],
            }
        )
        result[label] = nid
    return result


# ── Level 5: Leaf node builders ──────────────────────────────────────


def _is_readable_pattern(pattern: str) -> bool:
    """Filter out nonsensical n-gram patterns (hashes, random word combos)."""
    if not pattern or len(pattern) < 3:
        return False
    parts = [p.strip() for p in pattern.replace("/", " ").split()]
    for p in parts:
        if len(p) > 8 and re.fullmatch(r"[0-9a-f]+", p):
            return False
    stopwords = {
        "json",
        "general",
        "against",
        "through",
        "already",
        "instead",
        "context",
        "updates",
        "meaning",
        "continue",
        "connect",
        "acceptable",
        "violating",
        "interactive",
        "verified",
        "updated",
        "internal",
        "background",
    }
    meaningful = [p for p in parts if len(p) > 2 and p.lower() not in stopwords]
    return len(meaningful) >= 1


def add_entry_points(
    dp: dict,
    domain_key: str,
    parent_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add entry-point leaf nodes linked to a type-group parent."""
    for ep in dp.get("entryPoints") or []:
        pattern = ep.get("pattern", "")
        if not _is_readable_pattern(pattern):
            continue
        label = pattern.replace(" / ", ", ")
        nid = next_id("entry")
        freq = ep.get("frequency") or 0
        nodes.append(
            {
                "id": nid,
                "type": "entry-point",
                "label": label,
                "domain": domain_key,
                "color": ENTRY_COLOR,
                "size": max(3, min(12, (freq or 1) * 1.5)),
                "group": domain_key,
                "confidence": ep.get("confidence") or 0,
                "frequency": freq,
                "content": pattern,
            }
        )
        edges.append(
            {
                "source": parent_id,
                "target": nid,
                "type": "groups",
                "weight": ep.get("confidence") or 0.5,
                "color": EDGE_COLORS["groups"],
            }
        )


def add_recurring_patterns(
    dp: dict,
    domain_key: str,
    parent_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add recurring-pattern leaf nodes linked to a type-group parent."""
    for rp in dp.get("recurringPatterns") or []:
        nid = next_id("pat")
        freq = rp.get("frequency") or 0
        nodes.append(
            {
                "id": nid,
                "type": "recurring-pattern",
                "label": rp.get("pattern", ""),
                "domain": domain_key,
                "color": PATTERN_COLOR,
                "size": max(3, min(12, (freq or 1) * 1.2)),
                "group": domain_key,
                "confidence": rp.get("confidence") or 0,
                "frequency": freq,
                "content": rp.get("pattern", ""),
            }
        )
        edges.append(
            {
                "source": parent_id,
                "target": nid,
                "type": "groups",
                "weight": rp.get("confidence") or 0.5,
                "color": EDGE_COLORS["groups"],
            }
        )


def add_tool_preferences(
    dp: dict,
    domain_key: str,
    parent_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add top-5 tool-preference leaf nodes linked to a type-group parent."""
    tool_prefs = dp.get("toolPreferences") or {}
    top_tools = sorted(
        tool_prefs.items(), key=lambda x: x[1].get("ratio", 0), reverse=True
    )[:5]
    for tool_name, pref in top_tools:
        nid = next_id("tool")
        ratio = pref.get("ratio", 0)
        nodes.append(
            {
                "id": nid,
                "type": "tool-preference",
                "label": tool_name,
                "domain": domain_key,
                "color": TOOL_COLOR,
                "size": max(3, min(10, ratio * 10)),
                "group": domain_key,
                "ratio": ratio,
                "avgPerSession": pref.get("avgPerSession", 0),
                "content": (
                    f"{tool_name} (usage: {ratio:.0%}, "
                    f"avg/session: {pref.get('avgPerSession', 0)})"
                ),
            }
        )
        edges.append(
            {
                "source": parent_id,
                "target": nid,
                "type": "groups",
                "weight": ratio,
                "color": EDGE_COLORS["groups"],
            }
        )


def add_behavioral_features(
    dp: dict,
    domain_key: str,
    parent_id: str,
    next_id: IdAllocator,
    nodes: list[Node],
    edges: list[Edge],
) -> None:
    """Add behavioral-feature leaf nodes linked to a type-group parent."""
    for feat_label, weight in (dp.get("featureActivations") or {}).items():
        if abs(weight) < 0.05:
            continue
        nid = next_id("feat")
        nodes.append(
            {
                "id": nid,
                "type": "behavioral-feature",
                "label": feat_label,
                "domain": domain_key,
                "color": FEATURE_COLOR,
                "size": max(2, min(8, abs(weight) * 10)),
                "group": domain_key,
                "activation": weight,
                "content": f"{feat_label} (activation: {weight:+.3f})",
            }
        )
        edges.append(
            {
                "source": parent_id,
                "target": nid,
                "type": "groups",
                "weight": abs(weight),
                "color": EDGE_COLORS["groups"],
            }
        )
