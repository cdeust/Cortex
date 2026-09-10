# ADR-0751: scripts/launcher_pip.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/launcher_pip.py`; original SHA-256 `c0f1a9131e1095abfbd8c48c002f8bc5d0aefee95160b2cf93184685ca7dd13a`.

## Original docstring, lines 1–8

````text
"""Pip resolution before dependency commit; stdlib only.

The CPU torch wheel is staged separately, then participates in the same PyPI
resolution as the requested ML packages. Base constraints retain the launcher's
shared dependency pins. PEP 668 retry remains limited to the private --target.
Sources: https://pip.pypa.io/en/stable/cli/pip_install/
https://pip.pypa.io/en/stable/topics/configuration/#pip-config-file
"""
````

## Original comment, lines 38–38

````text
# source: pip configuration docs — os.devnull disables every config file.
````

