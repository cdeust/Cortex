# Lab Notebook

Add entries to the lab notebook, view recent entries, or search by tag or keyword.

## Instructions

1. Parse $ARGUMENTS for the subcommand:
   - `notebook add "<entry>" [--tag <tag>] [--commit <sha>]` — add a timestamped entry
   - `notebook show [--last <n>]` — display entries (default: all; --last N for recent)
   - `notebook search "<term>"` — find entries matching a keyword or tag
   - `notebook timeline` — show chronological overview of all entries

2. **Add**: Run `tools/lab-notebook-manager.sh add "<entry>"` with any provided flags. If a research session is active (check `research/.session.json` exists), include the current research question as context. Confirm the entry was added with its timestamp.

3. **Show**: Run `tools/lab-notebook-manager.sh show` with optional `--last <n>`. Format the output for readability. If no notebook exists, suggest starting a research session first with `/research-session start`.

4. **Search**: Run `tools/lab-notebook-manager.sh search "<term>"`. Present matching entries clearly. If no matches, suggest alternative search terms or checking the timeline.

5. **Timeline**: Run `tools/lab-notebook-manager.sh timeline`. Display the chronological list with entry count. Useful for getting an overview of research progression.

6. If no subcommand given, run `notebook show --last 5` as a sensible default.

7. Entries should follow good lab notebook practice:
   - State what was done, not just what was found
   - Include the hypothesis being tested when relevant
   - Tag entries for later retrieval (e.g., --tag hypothesis, --tag result, --tag method)
   - Link commits when the entry corresponds to a code change

$ARGUMENTS
