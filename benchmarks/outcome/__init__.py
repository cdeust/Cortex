"""Longitudinal outcome benchmark (issue #343).

Measures the behavioural claim — a session with recall reaches a correct,
independently checkable answer in fewer turns and tokens than the same
session without recall — instead of the top-1 retrieval proxy measured by
``benchmarks/lib/longitudinal_runner.py``.

Slice 1: ``paired_delta`` — the scoring core that pairs the two arms and
reports the delta with a variance estimate.
Slice 2: ``answer_key`` — task definitions for the three task families and
a verifier that checks an answer without Cortex; ``commit_resolver`` — the
git lookup that resolves commit answers against the corpus repository.
Slice 3: ``cortex_corpus`` — the corpus (this repository's history, pinned
at ``CORPUS_PIN``) and ``cortex_tasks.json``, whose every key is checked
against that history by ``check_evidence``.
Slice 4: ``two_arm_runner`` — the read-only corpus snapshot and the runner
that sweeps both arms over the same tasks, in the same order, with the same
model and effort, into the trials ``paired_delta`` scores.
The real agent driver is a later slice.

source: issue #343"""
