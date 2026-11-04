"""Longitudinal outcome benchmark (issue #343).

Measures the behavioural claim — a session with recall reaches a correct,
independently checkable answer in fewer turns and tokens than the same
session without recall — instead of the top-1 retrieval proxy measured by
``benchmarks/lib/longitudinal_runner.py``.

Slice 1 (this package so far): ``paired_delta`` — the scoring core that
pairs the two arms and reports the delta with a variance estimate.
Corpus, task definitions and the two-arm runner are later slices.

source: issue #343"""
