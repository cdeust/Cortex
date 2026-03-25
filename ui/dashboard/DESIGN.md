# Cortex Memory Dashboard - Design System

## Design Reference: Cyber Obsidian

A professional neural graph dashboard inspired by Stitch-generated reference designs, combining Obsidian-style force-directed graph interaction with a dark IDE-like chrome.

---

## Layout Architecture

```
+--[SIDEBAR 200px]--+--[MAIN AREA]--------------------------------------+
|                    | [TOP NAV BAR - tabs + search + status]            |
| Cortex             |                                                   |
| v4.0               | [KPI STRIP - 4 metric cards]                     |
|                    |                                                   |
| > Home             |                                                   |
| > Nodes            |            [3D FORCE GRAPH]                      |
| > Threads          |            Obsidian-style                        |
| > Archive          |            Force-directed                        |
| > Trash            |                                                   |
|                    |                                                   |
| [NEW MEMORY]       | [BOTTOM BAR - legend + status]                   |
|                    |                                                   |
| Settings  Status   |                                                   |
+--------------------+---[DETAIL PANEL 400px]---------------------------+
                     | Type badge | Close                                |
                     | Title                                             |
                     | Content                                           |
                     | Properties grid                                   |
                     | Classifiers (tags)                                |
                     | Proximal Links (connections)                      |
                     | Saturation Bar (heat)                             |
                     +---------------------------------------------------+
```

### Breakpoints
- Desktop: Full layout with sidebar + graph + detail panel
- No responsive breakpoints needed (this is a dev tool, desktop-only)

---

## Color System

### Base Palette

| Token               | Value              | Usage                        |
|---------------------|--------------------|------------------------------|
| `--bg-base`         | `#0a0a0a`          | App background               |
| `--bg-surface`      | `#111111`          | Sidebar, panels              |
| `--bg-elevated`     | `#1a1a1a`          | Cards, KPI boxes             |
| `--bg-hover`        | `#222222`          | Hover states                 |
| `--border-subtle`   | `rgba(255,255,255,0.06)` | Card borders          |
| `--border-active`   | `#4ade80`          | Active nav, focus states     |

### Accent Colors

| Token               | Value              | Usage                        |
|---------------------|--------------------|------------------------------|
| `--accent-primary`  | `#4ade80`          | Primary actions, active nav  |
| `--accent-cyan`     | `#00d2ff`          | Entities, KPI values         |
| `--accent-magenta`  | `#d946ef`          | Semantic memories            |
| `--accent-green`    | `#26de81`          | Episodic memories            |
| `--accent-red`      | `#ff4444`          | Causal edges, errors         |
| `--accent-amber`    | `#f59e0b`          | Hover highlight, warnings    |

### Text Colors

| Token               | Value              | Usage                        |
|---------------------|--------------------|------------------------------|
| `--text-primary`    | `rgba(255,255,255,0.87)` | Headings, values     |
| `--text-secondary`  | `rgba(255,255,255,0.55)` | Body text, labels    |
| `--text-tertiary`   | `rgba(255,255,255,0.25)` | Hints, inactive      |
| `--text-accent`     | `#4ade80`          | Active labels, links         |

---

## Typography

### Font Stack
- **Display**: `'Orbitron', sans-serif` - Logo, KPI values, section headers
- **Body**: `'JetBrains Mono', monospace` - All other text

### Scale

| Element          | Font       | Size  | Weight | Letter-spacing | Case      |
|-----------------|------------|-------|--------|----------------|-----------|
| Logo            | Orbitron   | 13px  | 800    | 4px            | UPPERCASE |
| KPI Value       | Orbitron   | 22px  | 700    | 0              | -         |
| KPI Label       | JetBrains  | 8px   | 400    | 2px            | UPPERCASE |
| Nav Item        | JetBrains  | 11px  | 500    | 0              | Sentence  |
| Section Header  | Orbitron   | 8px   | 600    | 3px            | UPPERCASE |
| Body Text       | JetBrains  | 11px  | 400    | 0              | Sentence  |
| Badge           | Orbitron   | 8px   | 600    | 2px            | UPPERCASE |
| Meta Label      | JetBrains  | 9px   | 400    | 1px            | UPPERCASE |
| Meta Value      | JetBrains  | 11px  | 400    | 0              | -         |
| Tooltip         | JetBrains  | 10px  | 400    | 0              | -         |

---

## Components

### Sidebar Navigation
- Fixed left, 200px wide
- Logo at top with version badge
- Icon + label nav items
- Active state: green left border + green text + subtle green bg
- "New Memory" CTA button at bottom
- Footer: settings gear + status indicator

### KPI Strip
- 4 cards in a horizontal row below the top nav
- Each card: large Orbitron number + small uppercase label
- Background: `--bg-elevated`
- Border: `--border-subtle`
- Value color: `--accent-primary`

### Top Navigation Bar
- Horizontal tab strip
- Tabs: Neural Graph, Memory Logs, Pattern Analysis, Vector Search
- Search input right-aligned
- Active tab: underline accent

### Neural Graph (3D)
- Three.js force-directed simulation
- Memory nodes: spheres (episodic green, semantic magenta)
- Entity nodes: octahedrons (cyan)
- Edge styles:
  - Default: `#5a6a7a` at 0.3 opacity
  - Causal: `#ff4444`
  - Co-occurrence: `#d946ef`
  - Virtual (memory-entity): `#3a4a5a` at 0.15 opacity
- Node labels: pipe separator style (`| LABEL_TEXT`), shown on hover or zoom
- Selective bloom on node cores
- Ambient dust particles (subtle)
- Auto-fit camera after simulation settles
- Auto-rotate when idle > 4s

### Detail Panel (Right Slide-in)
- 400px wide, slide from right
- Sections:
  1. **Type Badge** - SEMANTIC / EPISODIC / ENTITY with colored border
  2. **Title** - Node name or content excerpt
  3. **Content** - Full content text (memories only)
  4. **Properties** - 2-column grid (Heat, Importance, Domain, Source, Created, etc.)
  5. **Classifiers** - Tag pills with colored borders
  6. **Proximal Links** - Connection list sorted by weight, clickable
  7. **Saturation Bar** - Heat visualization bar at bottom
- Close button: top-right, styled X

### Bottom Status Bar
- Legend: colored dots with labels
- Right side: node count, edge count, latency
- Status: "SYNCHRONIZED" indicator

### Analytics Panel (Left slide-over)
- Slides over sidebar on toggle
- KPI overview strip
- Bar charts: Memory Types, Heat Distribution, Domain Breakdown, Tag Frequency
- Clickable bars filter the graph view

---

## Interaction Patterns

### Node Hover
- Highlight mesh (wireframe) appears around node
- Connected edges turn amber (#f59e0b)
- Tooltip shows: content, type badge, meta (time, heat, domain)
- Label becomes visible

### Node Click
- Detail panel opens from right
- Non-connected nodes fade to 12% opacity
- Connected edges highlight
- No zoom-to-node (preserves spatial context)

### Panel Close
- ESC key or close button
- All nodes restore full opacity
- Camera stays in current position

### Search
- Real-time filtering of visible nodes
- Matches against content, tags, domain, entity name
- Triggers graph rebuild with force simulation reheat

### Type Filter
- All / Episodic / Semantic / Entity buttons
- Triggers full graph rebuild
- Force simulation reheats on filter change

---

## Animation

| Element          | Property        | Duration | Easing                          |
|-----------------|-----------------|----------|---------------------------------|
| Panel slide     | transform       | 450ms    | cubic-bezier(0.16, 1, 0.3, 1)  |
| Camera fly      | position        | 1000ms   | ease-out cubic                  |
| Node opacity    | opacity         | 300ms    | linear                         |
| Tooltip         | display         | instant  | -                               |
| Filter button   | background      | 300ms    | ease                           |
| Loading fade    | opacity         | 1000ms   | linear                         |
| Auto-rotate     | orbit            | continuous | 0.15 deg/frame               |
| Entity spin     | rotation.y      | continuous | 0.004 rad/frame              |
| Dust drift      | position        | continuous | linear                       |
| Flow particles  | position        | continuous | linear along edge            |
| Force sim       | node positions  | ~660 frames | alpha decay 0.0015           |

---

## Node Sizing

| Node Type | Base Scale | Scale Factors                     | Range     |
|-----------|-----------|-----------------------------------|-----------|
| Memory    | 1.2       | + importance * 1.0 + heat * 0.6  | 1.2 - 2.8 |
| Entity    | 1.8       | + heat * 1.2                     | 1.8 - 3.0 |

---

## Edge Rendering

| Edge Type       | Color     | Opacity Factor           |
|----------------|-----------|--------------------------|
| Default        | `#90a4ae` | 0.15 + weight * 0.35    |
| Causal         | `#ff4444` | 0.15 + weight * 0.35    |
| Co-occurrence  | `#d946ef` | 0.15 + weight * 0.35    |
| Virtual        | `#556677` | 0.06 + weight * 0.12    |
| Highlighted    | `#f59e0b` | 0.9                     |

---

## Post-Processing

- **Selective Bloom**: 2-pass compositing
  - Bloom strength: 0.8
  - Bloom radius: 0.5
  - Bloom threshold: 0.35
- **Vignette**: darkness 1.2, factor 0.3
- **Film Grain**: intensity 0.03

---

## File Structure

```
ui/dashboard/
  DESIGN.md          # This file
  theme.css          # All styles
  js/
    config.js        # Colors, categories, utilities
    state.js         # Reactive state + event bus
    scene.js         # Three.js setup, bloom, camera
    nodes.js         # Memory + entity node builders
    edges.js         # Edge lines, fiber tracts, flow particles
    effects.js       # Ambient dust
    graph.js         # Force simulation, raycasting, animation loop
    interaction.js   # Tooltip, detail panel, keyboard shortcuts
    timeline.js      # Timeline overlay view
    categories.js    # Categories overlay view
    analytics.js     # Analytics panel charts
    controls.js      # UI button handlers
    polling.js       # API polling
    stats.js         # Header stats bar
```

---

## API Contract

**Endpoint**: `GET /api/dashboard`

**Response**:
```json
{
  "stats": {
    "total": 87,
    "active": 26,
    "episodic": 14,
    "semantic": 12,
    "entities": 61,
    "relationships": 212,
    "avg_heat": 0.342,
    "engram_total_slots": 128,
    "engram_occupied_slots": 26,
    "triggers": 5,
    "protected": 3
  },
  "hot_memories": [...],
  "entities": [...],
  "relationships": [...],
  "domain_counts": {...},
  "recent_memories": [...]
}
```
