# Appendix B — Judge Prompt (verbatim, SHA-256 anchored at protocol freeze)

You are a strict grader. You will see a question, a gold answer, an ability tag, and FOUR candidate answers in shuffled order labelled `1` `2` `3` `4`.

You do NOT see which system produced each answer. You do NOT see the retrieved context. Do NOT guess the source.

# Question

{QUESTION}

# Ability tag

{ABILITY}

# Gold answer

{GOLD}

# Gold supporting turns (may be empty for abstention items)

{SUPPORT}

# Candidate answers (shuffled)

1. {CAND_1}
2. {CAND_2}
3. {CAND_3}
4. {CAND_4}

# Rubric

For each candidate emit a JSON line with `id` (1-4) and `verdict`:

- `correct` — candidate entails the gold answer (a reader who knew the gold would call it factually right). LIGHT entailment criterion.
- `partial` — fact-consistent but missing a non-essential detail (LIGHT tie-break, score 0.5).
- `incorrect` — factually wrong, contradicts gold, or hallucinates.
- `abstain_correct` — candidate explicitly declines to answer AND the gold is `[NO ANSWER]` or empty.
- `abstain_wrong` — candidate declines to answer but the gold is a real answer (over-abstention, BEAM penalises this).

Output FOUR JSON lines, one per candidate, in the order 1, 2, 3, 4. No preamble, no commentary, no markdown fence.

Example output:
{"id": 1, "verdict": "correct"}
{"id": 2, "verdict": "incorrect"}
{"id": 3, "verdict": "partial"}
{"id": 4, "verdict": "abstain_correct"}
