---
title: "ADR-0660 — mcp_server/shared/platform.py rationale"
status: accepted
source: mcp_server/shared/platform.py
---

# ADR-0660 — mcp_server/shared/platform.py

Migrated source rationale. The excerpts below are preserved verbatim from the source snapshot; historical identifiers inside quotations are not current identities.

## module — original line 3 (docstring)

````text
Centralizes the three portability hazards that silently broke Cortex on
Windows (each previously open-coded at several call sites):
````

## module — original line 6 (docstring)

````text
  1. ``python3`` on the Windows PATH resolves to the Microsoft Store stub —
     it does not run an interpreter, it prints a message and exits 9009.
     Shelling out to a Python interpreter by name is therefore unsafe.
  2. ``Path.home()`` and ``Path.expanduser()`` consult USERPROFILE /
     HOMEDRIVE+HOMEPATH on Windows and silently ignore ``$HOME``. Tests that
     ``monkeypatch.setenv("HOME", ...)`` and admin setups that point HOME at
     a network share both observe the wrong directory as a result.
  3. ``str(Path(...))`` and ``os.path.relpath`` emit backslash separators on
     Windows, which fail regex matches and string comparisons authored for
     forward slashes.
````

## module — original line 17 (docstring)

````text
These are one-liners, but they were duplicated and each duplication was a
fresh place to forget the Windows branch. Three+ call sites each → extract
(coding-standards §3.3).
````

## module — original line 21 (docstring)

````text
source: RAPPORT_INSTALLATION_CORTEX_WINDOWS.md §5.1, §5.2, §5.3

````

## home_dir — original line 37 (docstring)

````text
    ``Path.home()`` ignores ``$HOME`` on Windows. We prefer ``$HOME`` when it
    is set so test fixtures and admin overrides behave identically across
    platforms, and fall back to the OS default otherwise.
    
````

## cache_dir — original line 48 (docstring)

````text
    Follows the freedesktop.org XDG Base Directory spec's XDG_CACHE_HOME
    override (respected by many CLI tools including uv, pip, npm)
    uniformly across platforms; falls back to ``~/.cache`` (via
    ``home_dir()`` so an explicit ``$HOME`` override composes correctly)
    otherwise.
````

## cache_dir — original line 54 (docstring)

````text
    source: https://specifications.freedesktop.org/basedir-spec/latest/
    
````

## python_executable — original line 63 (docstring)

````text
    Always use this instead of ``shutil.which("python3")`` /
    ``shutil.which("python")`` when spawning a Python subprocess: on Windows
    those resolve to the Microsoft Store stub before the real interpreter.
    ``sys.executable`` is, by definition, the interpreter running this code.
    
````
