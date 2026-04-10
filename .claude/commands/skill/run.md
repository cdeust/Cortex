# Run Skill

Execute a registered skill by name. The skill's procedure, zetetic gates, and output format guide the execution.

## Instructions

1. Parse: first word is the skill name, rest is the input/arguments.

2. Resolve the skill file: `tools/skill-runner.sh <skill-name>`
   If not found, list available skills and ask the user to choose.

3. Read the resolved skill file. Follow its **Procedure** section step by step.

4. Before delivering output, check every **Zetetic Gate**. If any gate fails, report the failure and stop — do not produce partial output that bypasses a gate.

5. After output, check the **Hand-offs** section. If a hand-off condition is met, suggest the next skill to the user.

$ARGUMENTS
