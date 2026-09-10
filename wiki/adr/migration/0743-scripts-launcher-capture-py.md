# ADR-0743: scripts/launcher_capture.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/launcher_capture.py`; original SHA-256 `dd19d7038804321dc2b69a577d0ea1cbc378814124b14cedc0b1155bdbe474ba`.

## Original docstring, lines 1–7

````text
"""Exclude disabled captures before backend resolution and dependency bootstrap.

The hook retains the exact decoded stdin text for admitted/invalid events.
Reading a pipe consumes its OS descriptor: bootstrap children then see EOF,
not the hook's JSON payload. StringIO intentionally restores the hook's text
interface only; it does not claim to restore the original file descriptor.
"""
````

