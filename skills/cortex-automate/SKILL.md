---
name: cortex-automate
description: "Set up automation — prospective memory triggers, neuro-symbolic rules, and CLAUDE.md sync. Use when the user says 'remind me when', 'trigger when', 'create a rule', 'auto-remember', 'sync to CLAUDE.md', 'push insights', 'set up trigger', 'when I open this file', 'when this keyword appears', or when you want to automate memory behavior based on conditions."
---

# Automate — Triggers, Rules, and Sync

## Keywords
trigger, rule, automate, remind me when, auto-remember, sync instructions, push to CLAUDE.md, prospective memory, keyword trigger, file trigger, domain trigger, time trigger, filter rule, boost rule

## Overview

Set up proactive automation in Cortex — triggers that fire when conditions are met (like opening a specific file or entering a domain), rules that filter or boost memories during recall, and syncing top insights back into CLAUDE.md for persistent project instructions.

**Use this skill when:** You want Cortex to proactively surface information based on context, filter out noise during recall, or keep CLAUDE.md updated with memory-derived insights.

## Workflow

### Triggers — Proactive Memory Recall

Create triggers that fire automatically when conditions match:

**Keyword trigger** — fires when a query/context contains specific words:
```
cortex:create_trigger({
  "type": "keyword",
  "pattern": "authentication",
  "memory_id": <id>,
  "message": "Remember: we decided to use JWT with refresh tokens, not sessions"
})
```

**File trigger** — fires when a specific file is being worked on:
```
cortex:create_trigger({
  "type": "file",
  "pattern": "pg_store.py",
  "memory_id": <id>,
  "message": "This file has a known issue with connection pooling under load"
})
```

**Domain trigger** — fires when entering a specific project domain:
```
cortex:create_trigger({
  "type": "domain",
  "pattern": "cortex",
  "memory_id": <id>,
  "message": "Priority: finish the refactoring plan before adding new features"
})
```

**Time trigger** — fires after a time condition:
```
cortex:create_trigger({
  "type": "time",
  "pattern": "7d",
  "memory_id": <id>,
  "message": "It's been a week — run consolidation"
})
```

Triggers fire up to 5 times by default, then deactivate. They appear in the `query_methodology` response at session start.

### Rules — Filter and Boost During Recall

Add rules that modify recall behavior:

**Soft rule** (boost/penalize score):
```
cortex:add_rule({
  "type": "soft",
  "scope": "domain:cortex",
  "condition": "tag:architecture",
  "weight": 1.5,
  "description": "Boost architecture memories in Cortex domain"
})
```

**Hard rule** (include/exclude):
```
cortex:add_rule({
  "type": "hard",
  "scope": "global",
  "condition": "tag:deprecated",
  "action": "exclude",
  "description": "Never surface deprecated memories"
})
```

**Tag rule** (auto-tag on store):
```
cortex:add_rule({
  "type": "tag",
  "scope": "domain:cortex",
  "condition": "content_match:refactor",
  "tag": "refactoring",
  "description": "Auto-tag refactoring memories"
})
```

**List active rules:**
```
cortex:get_rules({
  "scope": "domain:cortex"
})
```

### Sync to CLAUDE.md

Push top memory insights into project CLAUDE.md for persistent context:

```
cortex:sync_instructions({
  "directory": "<project root>",
  "max_insights": 10
})
```

This extracts the most important, high-confidence memories and formats them as project instructions in CLAUDE.md. Useful for keeping the project-level instructions file updated with lessons and patterns discovered across sessions.

## Tips

- **Triggers are personal reminders**: Think of them as "note to future self" tied to a context
- **Rules shape retrieval**: Soft rules are preferred over hard rules — they influence ranking without hiding potentially useful memories
- **Sync periodically**: Run `sync_instructions` after significant sessions to keep CLAUDE.md current
- **Don't over-trigger**: Too many triggers create noise. Use them for genuinely important context-dependent reminders
