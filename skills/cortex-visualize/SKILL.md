---
name: cortex-visualize
description: "Launch interactive visualizations — 3D neural graph of methodology profiles and memories, real-time memory dashboard with heatmaps and entity graphs. Use when the user says 'show visualization', 'open dashboard', 'show me the graph', 'visualize memories', 'show memory map', 'open neural graph', 'memory dashboard', 'show heatmap', or when a visual overview of the memory system or cognitive profile would be helpful."
---

# Visualize — Interactive Dashboards and Graphs

## Keywords
visualize, dashboard, graph, heatmap, neural graph, 3D, memory map, show memories, visual overview, open dashboard, entity graph, methodology graph, show profile, interactive, brain map

## Overview

Launch interactive browser-based visualizations of Cortex's memory system and cognitive profiles. The 3D neural graph shows methodology profiles, memories, and knowledge graph connections. The memory dashboard shows real-time heatmaps, entity networks, activity timelines, and domain distribution.

**Use this skill when:** The user wants a visual overview, is exploring the knowledge graph, or needs to present/screenshot Cortex's state.

## Workflow

### Option A: Unified Neural Graph

Launch the 3D interactive visualization combining methodology profiles, memories, and knowledge graph:

```
cortex:open_visualization({})
```

Or filter to a specific domain:
```
cortex:open_visualization({
  "domain": "cortex"
})
```

Opens in the browser at `http://127.0.0.1:3458`. Features:
- **3D force-directed graph** with methodology nodes, memory nodes, and entity nodes
- **Color coding** by domain, heat level, and memory type
- **Interactive** — click nodes for details, drag to explore, scroll to zoom
- **Auto-shutdown** after 10 minutes idle

### Option B: Memory Dashboard

Launch the real-time memory system dashboard:

```
cortex:open_memory_dashboard({})
```

Opens in the browser at `http://127.0.0.1:3457`. Features:
- **Memory heatmap** — visual grid of all memories colored by heat level
- **Entity network** — interactive graph of entities and relationships
- **Activity timeline** — when memories were created, accessed, consolidated
- **Domain distribution** — breakdown of memories across project domains
- **Real-time updates** — auto-refreshes as memories change

### Option C: Get Graph Data (Programmatic)

For custom visualization or analysis:

```
cortex:get_methodology_graph({
  "domain": "<optional filter>"
})
```

Returns raw graph data (nodes + edges) that can be processed or exported.

## Tips

- **Servers auto-shutdown**: Both visualization servers stop after 10 minutes of no browser activity
- **Bookmark the URLs**: `http://127.0.0.1:3458` (neural graph) and `http://127.0.0.1:3457` (dashboard) stay consistent across launches
- **Screenshots**: The Cyber Obsidian theme is designed to look great in dark mode screenshots
- **Large datasets**: For 1000+ memories, the visualization batches data loading for performance
