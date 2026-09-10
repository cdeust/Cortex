---
created: 2026-09-09T11:00:52Z
kind: adr
number: 1060
status: accepted
tags: [hooks, governance, wiki, enforcement]
title: Refuse a decision written into code at edit time, in the distributed hook
---
# ADR-1060: Refuse a decision written into code at edit time, in the distributed hook

## Status

accepted

## Context

The wiki is the only decision index and code carries a pointer, never the decision itself. Nothing enforced it. `scripts/craftsmanship_decisions.py` verifies the converse property, that a `source:` citation resolves to a real decision, so it catches a dangling pointer and never a decision written as prose where a pointer belongs.

The gap was demonstrated, not theorised. While fixing the plugin installer's dependency step (ADR-1059), ten and twelve line comment blocks explaining two flag choices were written into `scripts/setup.sh` and passed every gate. A reviewer caught one; the owner caught the convention breach. Both are after the fact.

CI is the wrong layer. A gate in `ci.yml` reports the violation once it is already written, committed and pushed, so the cost is paid and the fix is a second commit. Hooks exist to refuse the action instead.

Placement matters as much as the rule. `.claude/hooks/` is excluded by `.gitignore` (`.claude/*`, with only `settings.json` excepted), so a hook written there is local configuration on one machine, versioned nowhere and distributed to nobody. Cortex's own hooks are declared in `.claude-plugin/plugin.json` and implemented under `mcp_server/hooks/`, invoked through `scripts/launcher.py`. That is the only placement where the rule ships with the plugin.

Detecting a decision in general is not possible; detecting its shape is. A decision is prose, and prose in code appears as a long run of consecutive comment lines. Measuring the tracked tree gives the threshold rather than taste: excluding headers and tests, only a handful of files reach eight, and the blocks that motivated this were ten and twelve.

Two exemptions are needed or the rule is unusable. A file's opening block orients the reader and is not a decision; defining it as "nothing executable precedes it" avoids a line-number threshold, which would be a number to tune and a place for a decision to hide just inside. Tests narrate scenarios at length, which is why the repository already exempts them from the file-size cap.

## Decision

`mcp_server/hooks/decision_gate.py` runs as a `PreToolUse` hook on `Edit` and `Write`, declared in `.claude-plugin/plugin.json` alongside the other Cortex hooks, and exits 2 to block the call when the edit would introduce a run of eight or more consecutive comment lines into a code file.

A line carrying a `source:` pointer never counts toward a run: that is the sanctioned way to reference a decision, and the refusal message names `wiki_adr` as where the prose belongs and the pointer form to leave behind.

Only what the call introduces is judged: a block already present in the file is grandfathered, so editing an unrelated part of a legacy file is never refused. No path, header block or comment-marker language is exempt. (The first revision exempted the file's header block, defined as a run preceded by nothing executable, and test files; both exemptions were withdrawn on 2026-09-10, see the revision below.)

`CORTEX_DECISION_GATE=off` overrides for a single call, for genuine non-decision prose such as a worked example or a data table, and requires saying why.

### Revision 2026-09-09 — a first review caught three ways the shape heuristic misfired

A review of the first cut found the hook crashing on unreadable input, misreading string and heredoc bodies as comments, and losing grandfathering on a pure reflow. All three are fixed at the source, not patched at the throw site:

**Read failures fail open.** `candidate_content` and `introduced_block` only caught `OSError` around `Path.read_text`; a `UnicodeDecodeError` (a `ValueError`, not an `OSError` — a null byte in the path raises the same way) crashed the hook and, with it, every edit to that file. Both call sites now go through one `_read_text` helper that catches `(OSError, ValueError)` and treats "cannot read" and "does not exist yet" the same way: judge the fragment alone rather than crash.

**Comment detection is lexical, not prefix-matched.** The original scan treated any line whose stripped text started with the marker as a comment, with no notion of string literals or heredocs. Two shapes misfired: a module docstring followed by a licence block was blocked (the docstring disqualified the header scan, even though it isn't code), and a `cat <<'CFG' ... CFG` heredoc body containing commented example lines was blocked (that body is data being written, not prose about the script). Python now scans via `tokenize.COMMENT`, which cannot confuse a string body for a comment, and a leading module docstring is tolerated as header material the same way a shebang or `set` line is. The shell-family scanner (`.sh`/`.bash`/`.zsh`/`.rb`) skips heredoc bodies between a `<<DELIM` opener and the matching closing line.

**Grandfathering compares content, not position.** The original ratchet keyed a run by its exact joined text; inserting or removing a single bare marker line inside an existing block changed the key, so a pure rewrap of a block already in the file was reported as newly introduced. Grandfathering now compares the set of body-comment line texts already in the file against the candidate run's lines: a run is refused only when the count of lines *not* already present anywhere in the file's body prose reaches the threshold, so reflowing an existing block is never treated as new.

**Two further findings changed what's enforced, not just how it's checked** (both withdrawn by the revision of 2026-09-10 below). `is_test_path` recognised only `tests`/`tests_py`/`test`/`fuzz` and the Python `test_*.py`/`*_test.py` shapes; `tests_js` — the repo's actual JS test root — and the `.spec.ts`/`.test.ts` filename shapes were unrecognised, so JS test files were scanned while their Python equivalents were exempt. The test-path check now also matches `tests_js` by name and any `*.test.*`/`*.spec.*` filename, uniformly across languages. Separately, `//` and `/* */` markers were never actually measured: the tracked tree (excluding `deps/`) holds 1418 `.py` files and 18 `.sh` files, but zero non-test files using `//` or `/* */` comments. `COMMENT_MARKERS` now covers only the `#`-comment languages the threshold was measured against — `.py`, `.sh`, `.bash`, `.zsh`, `.rb` — and drops `.js`/`.ts`/`.tsx`/`.jsx`/`.swift`/`.go`/`.rs`/`.java`/`.c`/`.h`/`.cpp` until there is tracked-tree evidence for them. This is a narrowing of enforcement, not a threshold change: `PROSE_RUN_LIMIT` is unchanged, and the hook still refuses the ten- and twelve-line rationale blocks it was built to catch.

### Revision 2026-09-10 — no exception

Owner ruling, verbatim intent: "Révision de l'ADR-1060, pas d'exception". The gate applies to every comment-marker language, to test files and to header blocks alike.

**The leak.** On 2026-09-10 six lines of `///` rationale were written into `ai-architect-mcp-codebase/tests/rust_local_receiver_static_resolution.rs` and the hook allowed the write. Three of its exemptions each sufficed on their own: (1) `COMMENT_MARKERS` covered only the `#` languages (`.py .sh .bash .zsh .rb`) and deferred `//`, `///` and `/* */` "until measured"; (2) `is_test_path` exempted the `tests` directory (with `tests_py`, `tests_js`, `test`, `fuzz`, and the `test_*`, `*_test`, `*.test.*`, `*.spec.*` file shapes); (3) the run was preceded by nothing executable, so it read as the file header. An exemption is a place for a decision to hide, and this one hid in all three at once.

**Removed.** The language deferral: `mcp_server/hooks/_decision_gate_lex.py` now lexes `//` and `/* */` (`.rs .js .jsx .ts .tsx .go .java .c .h .cpp .hpp .cc .swift .kt .kts .cs .scala .m .mm .dart .php`), `--` (`.sql .lua .hs`), `;` (`.el .clj .lisp`) and the full `#` family (`.py .sh .bash .zsh .rb .pl .toml .yaml .yml .r .cfg .ini`). The new families go through one character-level scanner that tracks string literals (Rust raw strings and backtick strings included) and block comments, so a `//` or `/* */` inside a string literal never reads as a comment and every line a block comment crosses does; Python stays on `tokenize` and the shell family keeps its heredoc skip. The test-path exemption (`is_test_path`, `_TEST_DIRS`, `_TEST_FILE_RE`) is deleted. The header exemption (`_is_header_run` and the tokenizer's header boundary) is deleted. The refusal now states that no header, test file or language is exempt, so an agent that remembers the first revision is corrected at the point of refusal.

**Kept, and why.** `PROSE_RUN_LIMIT` stays at 8: the threshold was measured, and the ruling changes where it applies, not what it is. Grandfathering stays: only what the call introduces is judged, so a legacy file with a thirty-line header is still editable, and the measurement below is what shows the ruling breaks nothing. A `source:` pointer line never counts toward a run: it is the sanctioned form. Unreadable or unparsable input still fails open. `CORTEX_DECISION_GATE=off` stays: it is a visible act in the transcript with a stated reason, not a silent exemption, and a gate with no escape hatch gets disabled wholesale.

One narrowing of the Python scanner came with the rewrite: a comment token that follows code on the same line (`x = 1  # note`) no longer counts as a comment line, which is what that scanner's docstring already claimed and what the new scanner does for every other language.

**Measurement.** Tracked tree at `8d71210f` (`origin/main` on 2026-09-10), every file whose suffix the gate now judges, scanned with the revised lexer. A header run is a run of eight or more comment lines preceded only by blank lines, comment lines, a shebang, a shell `set` line or the Python module docstring; test paths are the ones the deleted `is_test_path` used to exempt.

| suffix | tracked files | header run of 8+ (code / test) | body run of 8+ (code / test) |
|---|---|---|---|
| `.py` | 1427 | 0 / 0 | 10 / 33 |
| `.sh` | 20 | 4 / 0 | 1 / 0 |
| `.yml` | 17 | 0 / 0 | 1 / 0 |
| `.sql` | 12 | 5 / 0 | 1 / 0 |
| `.yaml` | 1 | 0 / 0 | 0 / 0 |
| `.toml` | 1 | 0 / 0 | 1 / 0 |
| `.js` | 1 | 0 / 1 | 0 / 0 |
| total | 1479 | 9 / 1 | 14 / 33 |

Ten files carry a header run at or over the threshold, among them `benchmarks/reproduce.sh`, `scripts/install-plugin.sh`, `scripts/phase_0_4_5_backfill.sql` and `tests_js/spatial_hash.test.js`. Every one is grandfathered: editing any of them elsewhere is allowed, and only a new header of eight or more comment lines, or eight new lines added to an existing one, is refused. Nothing in the tree is blocked by the ruling. The number is recorded here so the owner decides on it, not the implementer.

## Consequences

Easier: the convention becomes a processing obligation rather than something a reader must remember. The failure that produced this ADR cannot recur silently, because the write is refused before the file changes.

Easier: the refusal carries its own remedy. It names the tool that records the decision and the pointer to leave, so the correction is mechanical rather than a research task.

Harder: existing files carry blocks over the threshold (at `8d71210f`: 10 with a header run, 47 with a body run, 33 of those under test roots). The ratchet grandfathers them, so nothing breaks, but they are now visibly on the wrong side of a stated rule and are candidates for migration to the wiki.

Harder: a new file cannot open with eight or more comment lines, whatever the language. A licence or orientation header of that length is either shortened, replaced by a `source:` pointer to the page that holds the text, or written under `CORTEX_DECISION_GATE=off` with the reason stated. Since the revision of 2026-09-10 this is the chosen cost: a header exemption is a place for a decision to hide, and it did.

Harder: a test file is judged like any other. A scenario narrated in eight or more comment lines moves into the test's docstring or the wiki; the same override applies.

Risk accepted: the threshold is a shape heuristic. A decision written in seven lines passes, and a long data table written as comments is refused. The override covers the second; the first is a smaller failure than the one this closes.

Risk accepted: an agent can set the override. That is deliberate. A gate with no escape hatch gets disabled wholesale, and requiring a stated reason keeps the choice visible in the transcript.

Risk accepted: grandfathering by line-text set, not exact position, can under-block a new decision that happens to reuse phrasing already present elsewhere in the file. This trade was made deliberately to fix the reflow false-positive; the alternative (position-based keying) is what broke on a pure rewrap.

Risk accepted: the scanner for the `//`, `--` and `;` families is a small state machine, not a parser. It tracks quoted strings (single-line unless the language lets them span lines, backtick and Rust raw strings always), character literals and block comments; it does not know every literal form of every language. Its failure mode is a comment hidden inside what it took for a string, which fails open, never a block refused for a string it took for a comment on a line holding code.
