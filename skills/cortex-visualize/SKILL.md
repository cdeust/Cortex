---
name: cortex-visualize
description: "Launch the interactive unified neural graph visualization. Use when the user says 'show visualization', 'show me the graph', 'visualize memories', 'show memory map', 'open neural graph', or when a visual overview of the memory system or cognitive profile would be helpful."
---

# Visualize — Interactive Neural Graph

## Keywords
visualize, graph, neural graph, memory map, show memories, visual overview, entity graph, methodology graph, show profile, interactive

## Overview

Launch the interactive browser-based unified neural graph combining methodology profiles, memories, and knowledge graph connections. Features 2D force-directed layout with domain separation, emotional tagging, quality scoring, and global memory visualization.

**Use this skill when:** The user wants a visual overview, is exploring the knowledge graph, or needs to present/screenshot Cortex's state.

## Workflow

### Launch Unified Neural Graph

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
- **2D force-directed graph** with methodology nodes, memory nodes, and entity nodes
- **Color coding** by domain, heat level, memory type, and emotional state
- **Global memories** shown in pink (#FF4081) with double-ring, connected to all domain hubs
- **Quality scoring** with colored arcs (green/amber/red)
- **Interactive** -- click nodes for details, drag to explore, scroll to zoom
- **Filters** -- All, Methodology, Memories, Knowledge, Emotional, Protected, Hot, Global
- **Auto-shutdown** after 10 minutes idle

### Get Graph Data (Programmatic)

For custom visualization or analysis:

```
cortex:get_methodology_graph({
  "domain": "<optional filter>"
})
```

Returns raw graph data (nodes + edges) that can be processed or exported.

## Tips

- **Server auto-shuts down** after 10 minutes of no browser activity
- **Bookmark the URL**: `http://127.0.0.1:3458` stays consistent across launches
- **Screenshots**: The Cyber Obsidian theme is designed to look great in dark mode
- **Large datasets**: The graph handles 1000+ nodes with force-directed layout
