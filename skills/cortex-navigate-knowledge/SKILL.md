---
name: cortex-navigate-knowledge
description: "Navigate the knowledge graph — trace entity relationships, explore causal chains, drill into memory clusters, and traverse co-access paths. Use when the user asks 'how are these related', 'what connects X to Y', 'show me the knowledge graph', 'trace the relationship', 'what caused X', 'drill down into', 'explore connections', or when you need to understand the web of relationships between concepts, entities, and memories."
---

# Navigate Knowledge — Graph Exploration and Causal Chains

## Keywords
knowledge graph, relationships, connections, causal chain, how are these related, what connects, drill down, explore, navigate, entity graph, trace, cause and effect, related to, linked to, co-access, cluster

## Overview

Cortex maintains a knowledge graph of entities (people, technologies, concepts, files) and their relationships extracted from memories. This skill lets you traverse that graph — follow causal chains, explore co-access patterns, drill into fractal memory clusters, and understand how different pieces of knowledge connect.

**Use this skill when:** You need to understand relationships between concepts, trace cause-and-effect chains, or explore a topic area systematically.

## Workflow

### Step 1: Trace Causal Chains

Follow entity relationships through the knowledge graph:

```
cortex:get_causal_chain({
  "entity": "PostgreSQL",
  "direction": "both",
  "max_depth": 3
})
```

Returns a chain of entities connected by typed relationships (causes, uses, depends_on, related_to, etc.). Direction can be `"forward"` (effects), `"backward"` (causes), or `"both"`.

### Step 2: Navigate Co-Access Paths

Find memories frequently accessed together using Successor Representation:

```
cortex:navigate_memory({
  "memory_id": <starting_memory_id>,
  "depth": 2,
  "max_nodes": 20
})
```

Returns a graph of memories connected by co-access frequency — revealing implicit relationships that aren't in the explicit knowledge graph.

### Step 3: Hierarchical Exploration

Browse memories through fractal clusters (L0 = broad, L1 = mid, L2 = specific):

```
cortex:recall_hierarchical({
  "query": "authentication system",
  "levels": 3
})
```

Then drill into any interesting cluster:

```
cortex:drill_down({
  "cluster_id": "<cluster from hierarchical recall>",
  "level": "L1"
})
```

### Step 4: Detect Structural Gaps

Find disconnected or under-connected areas:

```
cortex:detect_gaps({
  "domain": "<optional>"
})
```

Returns isolated entities, sparse domains, and temporal drift — areas where your knowledge graph has holes.

## Use Cases

**Understanding a new codebase:**
1. Recall hierarchical to get broad topic clusters
2. Drill down into the most relevant cluster
3. Navigate co-access paths from key memories
4. Trace causal chains for core entities

**Debugging with context:**
1. Recall memories about the error/module
2. Get causal chain for the affected entity
3. Navigate to co-accessed memories (past fixes, related patterns)

**Architecture review:**
1. Get causal chains for key components
2. Detect gaps in architectural documentation
3. Assess coverage for each module

## Tips

- **Start broad, go narrow**: Use hierarchical recall first, then drill down and navigate from specific memories
- **Causal chains reveal architecture**: The knowledge graph captures how components depend on each other — useful for impact analysis
- **Co-access reveals workflow**: Memories accessed together often represent a workflow or related concern, even if they're not explicitly linked
