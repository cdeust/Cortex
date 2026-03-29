---
name: cortex-remember-global
description: "Store a global memory that is visible across all projects. Use when the user shares architecture rules, coding conventions, infrastructure facts, security policies, team agreements, or any knowledge that applies beyond a single project. Triggers on 'remember this everywhere', 'this applies to all projects', 'global rule', 'shared convention', 'infrastructure note', 'cross-project', or when the content is clearly universal (clean architecture, SOLID, deployment configs, server addresses)."
---

# Remember Global — Store Cross-Project Knowledge

## Keywords
global, everywhere, all projects, cross-project, shared, universal, convention, standard, rule, infrastructure, policy, team agreement, always, never, architecture rule, coding standard

## Overview

Store knowledge that transcends any single project into Cortex's global memory. Global memories bypass domain filtering during recall — they're visible from every project you work on. Use this for architecture rules, coding conventions, infrastructure facts, security policies, and team agreements.

**Cortex auto-detects many global patterns** (clean architecture, dependency injection, server addresses, etc.), but use this skill explicitly when you want to guarantee cross-project visibility.

## Workflow

### Step 1: Identify Cross-Project Knowledge

Good candidates for global memory:
- **Architecture rules**: "Always follow clean architecture — inner layers never import outer layers"
- **Coding conventions**: "Use UTC timestamps in all database layers"
- **Infrastructure**: "Production database at db.internal:5432, daily backups at 3AM UTC"
- **Security policies**: "Rotate API keys every 90 days, store in 1Password vault"
- **Team agreements**: "PRs must be under 300 lines, always include tests"
- **Reusable patterns**: "Use factory injection for all handler composition roots"

**Not global** (project-specific): bug fixes, feature decisions for one project, file-specific notes.

### Step 2: Store as Global

```
cortex:remember({
  "content": "<clear, self-contained knowledge that applies across projects>",
  "tags": ["<category>", "<topic>"],
  "is_global": true,
  "force": true
})
```

**Content guidelines:**
- Write as a rule or fact, not a narrative: "Always use UTC" not "Today we decided to use UTC in the auth service"
- Include the *why* when it's a rule: "Use dependency injection because it enables testing and follows SOLID"
- Keep it universal — no project-specific file paths, PR numbers, or branch names

### Step 3: Verify Global Status

The response includes:
- `is_global: true` — confirms cross-project visibility
- `global_reason: "explicit"` — stored because you explicitly requested it

### Step 4: Anchor for Permanence (Optional)

Global memories are already high-value, but if they must never decay:

```
cortex:anchor({
  "memory_id": <id>,
  "reason": "Core architecture rule — permanent"
})
```

## Auto-Detection

Even without `is_global: true`, Cortex automatically detects global content using a weighted signal classifier across 6 categories:

| Category | Example signals |
|---|---|
| **Architecture** | clean architecture, SOLID, dependency injection, composition root |
| **Convention** | coding standard, naming convention, best practice, team agreement |
| **Infrastructure** | server at, database URL, Docker compose, CI/CD pipeline |
| **Security** | API key rotation, credential policy, authentication, encryption |
| **Cross-project** | all projects, shared across, universal, applies everywhere |
| **Knowledge** | UTC timestamps, WAL mode, connection pools, idempotency |

If the weighted score exceeds threshold 3.0, the memory is automatically global — no explicit flag needed.

## Tips

- **Be declarative**: "Inner layers never import outer layers" is better than "We should probably avoid importing infrastructure in core"
- **One rule per memory**: Don't bundle 5 conventions into one memory — store each separately for better retrieval
- **Tag consistently**: Use `architecture`, `convention`, `infrastructure`, `security`, `policy` tags for easy filtering
- **Review with visualization**: Use `cortex:open_visualization` and click the "Global" filter to see all cross-project knowledge
