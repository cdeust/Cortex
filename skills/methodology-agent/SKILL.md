---
name: cortex
description: Persistent memory and cognitive profiling for Claude Code
tools:
  - cortex:query_methodology
  - cortex:remember
  - cortex:recall
  - cortex:consolidate
  - cortex:checkpoint
  - cortex:narrative
  - cortex:memory_stats
  - cortex:detect_domain
  - cortex:rebuild_profiles
  - cortex:list_domains
  - cortex:record_session_end
  - cortex:get_methodology_graph
  - cortex:open_visualization
  - cortex:explore_features
  - cortex:run_pipeline
  - cortex:open_memory_dashboard
---

# Cortex

Persistent memory and cognitive profiling for Claude Code.

## Memory Tools

- **remember** — Store a memory (predictive coding gate filters noise automatically)
- **recall** — Retrieve memories via 4-signal fusion (vector + FTS5 + heat + Hopfield) with intent-aware routing
- **consolidate** — Run maintenance: heat decay, compression, CLS consolidation, causal discovery
- **checkpoint** — Save/restore working state across context compaction
- **narrative** — Generate project story from stored memories
- **memory_stats** — Memory system diagnostics

## Profiling Tools

- **query_methodology** — Load cognitive profile + hot memories at session start
- **detect_domain** — Classify current domain from cwd/project
- **rebuild_profiles** — Full rescan of session history
- **list_domains** — Overview of all cognitive domains
- **record_session_end** — Incremental profile update + session self-critique
- **get_methodology_graph** — Graph data for visualization
- **open_visualization** — Launch 3D methodology map in browser
- **explore_features** — Interpretability: features, attribution, persona, crosscoder

## Visualization

- **open_memory_dashboard** — Launch real-time dashboard showing heat map, entity graph, activity feed, and domain distribution

## Pipeline

- **run_pipeline** — Drive ai-architect pipeline end-to-end (PRD to PR)

## Usage

Call `query_methodology` at session start — Cortex surfaces hot memories, fired triggers, and your cognitive profile. Use `remember` to store important decisions, patterns, and context. Use `recall` to retrieve relevant memories. Everything else (decay, consolidation, critique) happens automatically via hooks.
