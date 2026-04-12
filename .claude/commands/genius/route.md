# Route Problem to Genius Agents

Analyze a problem description, find matching genius agent shapes, and recommend agents.

## Instructions

1. Take the problem description from $ARGUMENTS.

2. Run `tools/genius-invoker.sh route "$ARGUMENTS"` to search INDEX.md for matching shapes.

3. Read `agents/genius/INDEX.md` directly. For each keyword in the problem description, scan the Shape tables for matching triggers. Look for:
   - Exact shape name matches
   - Trigger condition matches (the "Trigger" column describes when the shape activates)
   - Semantic matches where the problem structure fits a shape even without keyword overlap

4. Rank recommendations by match quality. For each recommended agent (1-3 max), output:
   - **Agent name** and link to its file
   - **Matching shape(s)** with the trigger text from INDEX.md
   - **Why it matches** — connect the problem's structure to the shape's trigger
   - **Key move** — what the agent will do first

5. If multiple agents match, suggest a **composition sequence**: which agent to run first and why, what its output feeds into the next agent, and the expected combined insight. Reference `tools/genius-invoker.sh compose` for execution.

6. If no shapes match, say so clearly. Suggest the user try a standard team agent instead or rephrase the problem to expose its structural shape.

$ARGUMENTS
