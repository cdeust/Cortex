# Compose Multiple Genius Agents

Load multiple genius agents in sequence, apply each to the problem, and pass output forward.

## Instructions

1. Parse $ARGUMENTS: agent names separated by spaces, then `--`, then the problem description.
   Example: `/genius-compose curie fermi -- "We see 3x more latency than our model predicts but have no measurement of where it goes"`

2. Run `tools/genius-invoker.sh compose <agent1> <agent2> ... -- "<problem>"` to validate all agents exist and load their content.

3. For each agent in sequence:
   a. Read the full agent file at `agents/genius/<name>.md`
   b. Apply that agent's complete workflow to the problem (or to the accumulated output from prior agents)
   c. Produce the output in that agent's `output-format`
   d. Label the output clearly: "=== Output from <agent> ==="

4. **Chain rule**: each agent after the first receives:
   - The original problem description
   - The full output from all previous agents
   - An instruction to build on, refine, or challenge the prior output using its own method

5. After all agents have run, produce a **Synthesis** section that:
   - Identifies where the agents agree (convergent insights)
   - Identifies where they disagree or see different aspects (complementary insights)
   - Proposes concrete next actions that combine the strongest outputs
   - Notes any gaps that no agent addressed

6. If any agent's workflow calls for artifacts (difficulty books, provenance files, estimates), create them using the corresponding tools.

$ARGUMENTS
