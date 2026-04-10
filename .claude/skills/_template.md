---
# Skill Template — copy this file to create a new skill
name: skill-name                        # Slash command: /skill-name
description: >
  One-sentence description of what this skill does.
category: engineering                   # engineering | analysis | architecture | research | zetetic | genius | compose
trigger: >
  When to invoke this skill — concrete situations, not abstractions.
agents:                                 # Agents this skill invokes (in order)
  - agent-name
shapes: []                              # Problem shapes from INDEX.md (genius skills only)
input: >
  What the user provides.
output: >
  What the skill produces.
zetetic_gate:
  logical: "Is it consistent? — the specific check for this skill"
  critical: "Is it true? — the specific check for this skill"
  rational: "Is it useful? — the specific check for this skill"
  essential: "Is it necessary? — the specific check for this skill"
composes: []                            # Other skills this skill may invoke
aliases: []                             # Alternative names for this skill
hand_off: {}                            # Conditions → next skill/agent
---

## Purpose

One paragraph: what this skill does and why it exists.

## When to Use

- Bullet list of concrete trigger situations.

## Procedure

Numbered steps. Each step names the agent it delegates to and what that agent does.

## Zetetic Gates

| Pillar | Gate | Failure action |
|--------|------|----------------|
| Logical | [...] | [...] |
| Critical | [...] | [...] |
| Rational | [...] | [...] |
| Essential | [...] | [...] |

## Output Format

The expected structure of the skill's output.

## Hand-offs

| Condition | Next skill | Reason |
|-----------|------------|--------|

## Anti-patterns

- What this skill refuses to do.

## Examples

Brief concrete examples.
