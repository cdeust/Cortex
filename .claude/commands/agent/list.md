# List Available Agents

List all zetetic agents with their types, roles, and trigger conditions.

## Instructions

1. Run the agent catalog tool to list agents. Apply filters if the user specified any:
   - All agents: `tools/agent-catalog.sh --all`
   - Team only: `tools/agent-catalog.sh --team`
   - Genius only: `tools/agent-catalog.sh --genius`
   - By shape: `tools/agent-catalog.sh --genius --shape "$ARGUMENTS"`
   - By keyword: `tools/agent-catalog.sh --search "$ARGUMENTS"`

2. If the user asked about a specific problem (not an agent name), run `tools/shape-router.sh "$ARGUMENTS"` to find the matching genius agent(s) by problem shape.

3. Present results as a clean table. For genius agents, include the problem shapes they serve.

$ARGUMENTS
