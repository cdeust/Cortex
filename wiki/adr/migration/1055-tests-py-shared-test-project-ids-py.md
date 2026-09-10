# ADR-1055: tests_py/shared/test_project_ids.py design and historical evidence

Status: accepted; existing test/harness evidence preserved during issue #514.

Source `tests_py/shared/test_project_ids.py`, original SHA-256 `b51f3f0d461fe6e73ee32ac149773b42ed360e7fc1e60b5347d5f0931596873c`.
Assertions and runtime fixture literals remain unchanged.

## Original comment, lines 115–118

````text
# Documented tradeoff (see project_ids.py docstring): on a
# case-sensitive filesystem two distinct sibling directories
# differing only by case would fold to the same normalized id.
# Accepted — see rationale in normalize_project_id's docstring.
````

