# Research Session

Start, resume, or close a research session. Manages research context: question, hypotheses, evidence state, and lab notebook.

## Instructions

1. Parse $ARGUMENTS for the subcommand:
   - `session start "<research question>"` — create a new session
   - `session resume` — load previous session state
   - `session close` — produce summary and archive

2. **Start**: Run `tools/research-session-manager.sh start "<question>"`. This creates `research/`, initializes `NOTEBOOK.md`, and writes `.session.json`. Confirm the research question back to the user and suggest formulating initial hypotheses with `session hypothesis add`.

3. **Resume**: Run `tools/research-session-manager.sh resume`. Display the current research question, active hypotheses, and notebook entry count. If Cortex is available, call `cortex:recall` with the research question to load prior context. Summarize what was found and suggest next steps.

4. **Close**: Run `tools/research-session-manager.sh status` first to show final state. Then run `tools/research-session-manager.sh close`. Produce a structured summary:
   - Research question
   - Hypotheses and their final status (confirmed / rejected / open)
   - Key findings from notebook entries
   - Open questions for future sessions

   If Cortex is available, call `cortex:remember` with the summary tagged `["research", "session-close"]`.

5. If no subcommand is given, run `tools/research-session-manager.sh status` to show current state.

6. For hypothesis management, delegate to:
   - `tools/research-session-manager.sh hypothesis add "<hypothesis>"`
   - `tools/research-session-manager.sh hypothesis list`

7. All notebook entries during a session should reference the active research question. Remind the user to use `/research-notebook add` for detailed entries.

8. During an active session, the following compute and preview tools are available:
   - `tools/docker-runner.sh` — run experiments in isolated Docker containers
   - `tools/mlx-compute.sh` — run ML experiments on Apple Silicon with MLX
   - `tools/live-preview.sh` — preview research documents (Markdown, LaTeX, HTML)
   All three tools auto-log to the lab notebook when a session is active.

$ARGUMENTS
