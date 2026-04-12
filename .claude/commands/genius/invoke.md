# Invoke Genius Agent

Load a genius agent by name and apply its reasoning pattern to a problem inline.

## Instructions

1. Parse $ARGUMENTS: the first word is the agent name, the rest is the problem description.
   Example: `/genius-invoke darwin "Our metrics show a slow decline but we keep theorizing before we have enough data"`

2. Run `tools/genius-invoker.sh invoke <agent-name> "<problem>"` to validate the agent exists and load its content.

3. Read the full agent file at `agents/genius/<name>.md`. Pay attention to:
   - The `<identity>` section for the reasoning pattern
   - The `<workflow>` section for the step-by-step procedure
   - The `<output-format>` section for how to structure the response

4. Apply the agent's workflow to the problem. Work through each step of the agent's procedure, applying it to the specific problem described. Do not skip steps.

5. Produce output in the agent's `output-format`. If the agent defines a specific structure (sections, tables, verdicts), follow it exactly.

6. If the agent's workflow calls for tools (difficulty books, provenance files, estimates), use the corresponding tools from `tools/`.

7. End with a "Next step" recommendation: what the user should do next, and whether another genius agent should be consulted (check the agent's `pairs_well_with` frontmatter field).

$ARGUMENTS
