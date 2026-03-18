---
name: jarvis
description: Persistent memory and cognitive profiling for Claude Code
tools:
  - jarvis:query_methodology
  - jarvis:remember
  - jarvis:recall
  - jarvis:consolidate
  - jarvis:checkpoint
  - jarvis:narrative
  - jarvis:memory_stats
  - jarvis:detect_domain
  - jarvis:rebuild_profiles
  - jarvis:list_domains
  - jarvis:record_session_end
  - jarvis:get_methodology_graph
  - jarvis:open_visualization
  - jarvis:explore_features
  - jarvis:run_pipeline
  - jarvis:open_memory_dashboard
---

# JARVIS

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

Call `query_methodology` at session start — JARVIS surfaces hot memories, fired triggers, and your cognitive profile. Use `remember` to store important decisions, patterns, and context. Use `recall` to retrieve relevant memories. Everything else (decay, consolidation, critique) happens automatically via hooks.
