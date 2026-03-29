---
name: cortex-recall-global
description: "Search and retrieve global memories — knowledge that applies across all projects. Use when the user asks 'what are our coding standards', 'what conventions do we follow', 'what's our infrastructure setup', 'do we have a rule about', 'what applies to all projects', 'shared knowledge', 'global rules', or when you need cross-project context like architecture decisions, server configs, or team policies."
---

# Recall Global — Retrieve Cross-Project Knowledge

## Keywords
global, convention, standard, rule, infrastructure, policy, all projects, shared, universal, what's our rule, coding standard, architecture rule, team agreement, cross-project, server config, deployment

## Overview

Retrieve global memories — knowledge stored as cross-project that's visible regardless of which project you're currently working in. Global memories include architecture rules, coding conventions, infrastructure facts, security policies, and team agreements.

**Note:** Regular `cortex:recall` already surfaces global memories automatically. This skill is for when you specifically want to focus on cross-project knowledge.

## Workflow

### Step 1: Recall Global Knowledge

Query with any domain — global memories appear alongside domain-specific results:

```
cortex:recall({
  "query": "<topic to search for>",
  "max_results": 10
})
```

Global memories are included in results regardless of the current project domain.

### Step 2: Filter to Global Only

To see only global cross-project knowledge, use the unified neural graph:

```
cortex:open_visualization()
```

Click the **Global** filter button (pink) to isolate all global memories.

Click the **Global** filter — global memories appear as pink nodes connected to all project domains.

### Step 3: Explore by Category

Common global recall patterns:

**Architecture rules:**
```
cortex:recall({ "query": "architecture rules and principles" })
```

**Infrastructure:**
```
cortex:recall({ "query": "server addresses and database connections" })
```

**Coding conventions:**
```
cortex:recall({ "query": "coding standards and naming conventions" })
```

**Security policies:**
```
cortex:recall({ "query": "security policies and credential management" })
```

### Step 4: Navigate Connections

After finding a global memory, explore what it connects to across projects:

```
cortex:navigate_memory({
  "memory_id": <id>,
  "depth": 2
})
```

Global memories link to all domain hubs in the knowledge graph — following connections shows which projects reference similar concepts.

## How Global Recall Works

Global memories have `is_global = TRUE` in the database. During recall, every retrieval signal (vector, FTS, trigram, heat, recency) includes the clause:

```sql
WHERE (domain = current_domain OR is_global = TRUE)
```

This means global memories compete on relevance alongside domain-specific ones — they're not artificially boosted, just not filtered out.

## Tips

- **Global memories compete on merit**: They appear in results only when relevant to the query, not automatically at the top
- **Use the visualization**: The unified graph shows global memories (pink) with edges to every project — a visual map of shared knowledge
- **Rate for quality**: Use `cortex:rate_memory` on global memories that were helpful to improve future retrieval confidence
- **Assess coverage**: Use `cortex:assess_coverage` to see if any project domain is missing shared knowledge
