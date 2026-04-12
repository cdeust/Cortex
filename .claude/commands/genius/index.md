# Genius Agent Index

Display the genius agent index in a navigable format. Filter by category, show pairings, or browse the full shape-to-agent lookup.

## Instructions

1. Parse $ARGUMENTS for optional filters:
   - No arguments: show all categories with agent counts
   - `index <category>` — show shapes for a specific category (fuzzy match on category name)
   - `index --agents` — list all agents with their descriptions
   - `index --pairs <agent>` — show what pairs well with a given agent
   - `index --search <term>` — search shapes, triggers, and agents by keyword

2. **Category overview** (no args): Read `agents/genius/INDEX.md`. Extract all `### ` category headers. For each category, count the shapes (table rows). Display as a numbered list:
   ```
   1. Measurement, Signal, and Isolation (5 shapes) — curie
   2. Estimation and Bounding (5 shapes) — fermi
   ...
   ```
   Tell the user they can drill into any category by number or name.

3. **Category detail**: Find the matching `### ` section in INDEX.md (case-insensitive partial match). Display the full shape table for that category. Include the trigger and key move columns for each shape.

4. **Agent list**: Run `tools/genius-invoker.sh list --shapes`. Format as a clean table with agent name, description, and shapes.

5. **Pairs**: Read the specified agent file at `agents/genius/<agent>.md`. Extract the `pairs_well_with` frontmatter field. For each paired agent, show its description. Suggest composition patterns using `/genius-compose`.

6. **Search**: Run `tools/genius-invoker.sh list --search "<term>"`. Also search INDEX.md for matching shapes. Combine results, deduplicating by agent name.

7. Always end with a usage hint: how to invoke an agent (`/genius-invoke <name> "<problem>"`), how to compose agents (`/genius-compose`), or how to let the router pick (`/genius-route`).

$ARGUMENTS
