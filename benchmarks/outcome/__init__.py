"""Longitudinal outcome benchmark (issue #343).

Measures the behavioural claim — a session with recall reaches a correct,
independently checkable answer in fewer turns and tokens than the same
session without recall — instead of the top-1 retrieval proxy measured by
``benchmarks/lib/longitudinal_runner.py``.

Slice 1: ``paired_delta`` — the scoring core that pairs the two arms and
reports the delta with a variance estimate.
Slice 2: ``answer_key`` — task definitions for the three task families and
a verifier that checks an answer without Cortex.
The corpus and the two-arm runner are later slices.

source: issue #343"""
