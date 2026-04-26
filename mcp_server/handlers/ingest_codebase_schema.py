"""MCP tool schema for ingest_codebase.

Held separate so the composition root stays under the 300-line cap.
"""

from __future__ import annotations

schema = {
    "description": (
        "Ingest a codebase analysis from the upstream ai-automatised-"
        "pipeline MCP server into Cortex's store. Triggers `analyze_"
        "codebase` upstream (or reuses a cached graph_path memo), pulls "
        "every Function/Method/Struct + every call edge + every File→"
        "symbol containment edge via Cypher, then materialises them as "
        "memories + KG entities + edges, plus a wiki reference page "
        "per detected process entry point. Use this to seed the Wiki / "
        "Board / Knowledge / Graph views from a freshly-indexed or re-"
        "indexed codebase. Distinct from `codebase_analyze` (Cortex's "
        "OWN tree-sitter analyzer, no upstream MCP), `seed_project` "
        "(5-stage shallow sweep, no AST), and `wiki_seed_codebase` "
        "(consumes existing .md docs, not analysis). Mutates wiki/, "
        "memories, entities, relationships. Latency varies (10s-5min "
        "depending on cache hit). Cortex only consumes upstream "
        "analysis — it does not drive the pipeline. Returns counts and "
        "the wiki paths written."
    ),
    "inputSchema": {
        "type": "object",
        "required": ["project_path"],
        "properties": {
            "project_path": {
                "type": "string",
                "description": (
                    "Absolute path to the codebase root to analyse. Used both "
                    "as the pipeline input and to memoise the resulting graph "
                    "path so subsequent ingests are idempotent."
                ),
                "examples": ["/Users/alice/code/cortex"],
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Directory where the code graph is stored. Defaults to "
                    "~/.cache/cortex/code-graphs/<project-key>/."
                ),
                "examples": ["/Users/alice/.cache/cortex/code-graphs/cortex-ab12cd34"],
            },
            "language": {
                "type": "string",
                "description": "Language filter passed to analyze_codebase.",
                "enum": ["auto", "rust", "python", "typescript"],
                "default": "auto",
            },
            "force_reindex": {
                "type": "boolean",
                "description": (
                    "If true, call analyze_codebase even when a cached graph "
                    "path exists for this project."
                ),
                "default": False,
            },
        },
    },
}
