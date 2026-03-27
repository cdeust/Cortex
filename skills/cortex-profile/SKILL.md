---
name: cortex-profile
description: "View and manage your cognitive profile — how you think, work patterns, blind spots, and cross-domain connections. Use when the user says 'show my profile', 'how do I work', 'what are my patterns', 'cognitive style', 'blind spots', 'methodology', or at the start of a session to load context. Also use 'rebuild profile' to rescan all session history, or 'list domains' to see all tracked project domains."
---

# Profile — Cognitive Profiling and Methodology

## Keywords
profile, methodology, cognitive style, work patterns, blind spots, how do I work, thinking style, domains, rebuild profile, my patterns, session history, cognitive, behavioral, persona

## Overview

Cortex builds a cognitive profile from your Claude Code session history — how you explore code, which tools you prefer, what patterns you repeat, where you have blind spots, and how your style connects across different project domains. This profile is used to calibrate responses and surface relevant context.

**Use this skill when:** Starting a session (auto-injected via hook), wanting to understand your work patterns, or needing to rebuild profiles after significant new work.

## Workflow

### Step 1: Load Current Profile

```
cortex:query_methodology({
  "cwd": "<current working directory>",
  "first_message": "<what the user is working on>"
})
```

Returns:
- **Cognitive style** — Felder-Silverman dimensions (active/reflective, sensing/intuitive, visual/verbal, sequential/global)
- **Entry patterns** — How you typically start work in this domain
- **Recurring patterns** — Behavioral patterns that repeat across sessions
- **Blind spots** — Categories, tools, or patterns you tend to miss
- **Connection bridges** — Cross-domain analogies and structural similarities
- **Hot memories** — Most relevant active memories for this context
- **Fired triggers** — Prospective memories activated by the current context

### Step 2: Explore Behavioral Features

Dive deeper into your behavioral profile:

```
cortex:explore_features({ "mode": "persona" })
```

Returns your 12-dimensional persona vector: exploration depth, tool diversity, session persistence, abstraction level, error recovery, etc.

Other exploration modes:
- `"mode": "features"` — What behavioral dictionary features activate for this domain
- `"mode": "attribution"` — How the pipeline traces decisions back to behavioral signals
- `"mode": "crosscoder"` — Behavioral patterns that persist across different project domains

### Step 3: View All Domains

```
cortex:list_domains({})
```

Shows all detected project domains with session counts, cognitive style per domain, and last activity timestamps.

### Step 4: Rebuild Profiles

When profiles seem stale or after significant new work:

```
cortex:rebuild_profiles({})
```

Full rescan of `~/.claude/projects/` session history. Rebuilds all domain profiles, re-extracts patterns, re-classifies cognitive styles, and re-learns behavioral features.

### Step 5: Record Session End

Normally automatic via hook, but can be called manually:

```
cortex:record_session_end({
  "domain": "<current domain>",
  "summary": "<what was accomplished>"
})
```

Updates profiles incrementally via EMA (Exponential Moving Average) — no full rebuild needed.

## Tips

- **Profiles improve over time**: The more sessions you have, the more accurate the cognitive profiling becomes
- **Cross-domain bridges are powerful**: If Cortex detects you use similar patterns in different projects, it surfaces those connections
- **Blind spots are actionable**: If Cortex says you under-use certain tools or miss certain categories, consider addressing those gaps
- **Domain detection is automatic**: `cortex:detect_domain` classifies the current working directory into a known domain — no manual tagging needed
