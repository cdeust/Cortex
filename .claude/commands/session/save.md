# Save Session Context

Save the current session's context for future recall.

## Instructions

1. Summarize the current session: decisions made, files changed, open questions, difficulty-book state.

2. If Cortex is available, call `cortex:remember` with the summary, tagged with the project name.

3. Also save locally: `tools/session-store.sh save "<summary>"`

4. Confirm to the user what was saved.

$ARGUMENTS
