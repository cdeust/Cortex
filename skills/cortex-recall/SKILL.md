---
name: cortex-recall
description: "Search and retrieve memories from Cortex persistent memory. Use when the user asks 'what did we decide about X', 'do you remember', 'what was the fix for', 'find that thing about', 'search memories', 'what do we know about', 'have we seen this before', or when you need context about past decisions, patterns, bugs, or architecture choices. Also use proactively when working on something that likely has relevant historical context."
---

# Recall — Retrieve from Persistent Memory

## Keywords
recall, remember, search, find, what did we, do you remember, what was, have we seen, look up, retrieve, past decision, previous fix, history, what do we know, search memory, find memory, related memories

## Overview

Retrieve relevant memories using Cortex's 6-signal WRRF (Weighted Reciprocal Rank Fusion) retrieval engine. The system automatically classifies your query intent and adjusts retrieval weights — semantic queries emphasize vector similarity, temporal queries emphasize recency, causal queries traverse the knowledge graph.

**Use this skill when:** You need context about past work, decisions, patterns, or fixes. Also use proactively when starting work on a topic that likely has stored context.

## Workflow

### Step 1: Formulate the Query

Write a natural language query. The intent classifier handles routing:

- **Semantic**: "How does the authentication system work?"
- **Temporal**: "What did we work on last week?"
- **Causal**: "What caused the deployment failure?"
- **Entity**: "Everything about PostgreSQL in this project"
- **Multi-hop**: "How does the memory gate relate to consolidation?"

### Step 2: Basic Recall

```
cortex:recall({
  "query": "<natural language question or topic>",
  "limit": 10
})
```

**Optional filters:**
- `"domain"`: Filter to specific project domain
- `"tags"`: Filter by tags (e.g. `["bug-fix", "authentication"]`)
- `"min_heat"`: Only hot/active memories (0.0-1.0)
- `"time_range"`: Temporal filter (e.g. `"last_7_days"`, `"last_30_days"`)
- `"store_type"`: `"episodic"` (specific events) or `"semantic"` (consolidated knowledge)

### Step 3: Hierarchical Recall (For Broad Topics)

When exploring a large topic area, use fractal hierarchical recall:

```
cortex:recall_hierarchical({
  "query": "<broad topic>",
  "levels": 3
})
```

This returns memories organized in L0 (broad clusters) > L1 (sub-topics) > L2 (specific memories). Use `cortex:drill_down` to navigate deeper into any cluster.

### Step 4: Navigate Related Knowledge

After finding relevant memories, explore connections:

```
cortex:navigate_memory({
  "memory_id": <id>,
  "depth": 2
})
```

This uses Successor Representation (co-access graph) to find memories frequently accessed together — surfacing implicit connections the user may not have queried for.

### Step 5: Trace Causal Chains

For understanding cause-and-effect relationships:

```
cortex:get_causal_chain({
  "entity": "<entity name>",
  "direction": "both"
})
```

This traverses the knowledge graph to show how entities relate through causal, temporal, and semantic relationships.

## Tips

- **Be specific**: "PostgreSQL index performance on memories table" retrieves better than "database stuff"
- **Use proactively**: Before making a decision, recall if there's prior context — "have we made decisions about X before?"
- **Recall at session start**: The SessionStart hook auto-injects hot memories, but explicit recall for your current task adds focused context
- **Rate results**: After recall, use `cortex:rate_memory` on results that were useful/not-useful to improve future retrieval
