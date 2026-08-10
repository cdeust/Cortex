"""Single-load helper for the four ``scripts/craftsmanship_*.py`` modules.

Every ``test_craftsmanship_*.py`` file imports this module (a genuine
package import, cached by Python's normal import machinery — this file
lives under ``tests_py/scripts/``, a real package via its ``__init__.py``)
instead of each independently calling
``importlib.util.spec_from_file_location`` on ``craftsmanship_rules.py``.

Why that independence was wrong: ``craftsmanship_rules.py`` defines the
frozen dataclass ``Violation``, and its own body imports its two siblings
(``craftsmanship_imports.py`` / ``craftsmanship_constants.py``), each of
which imports ``Violation`` back. Every separate
``spec_from_file_location`` call re-executes the file from scratch,
minting a NEW ``Violation`` class each time — dataclass equality compares
``__class__ is __class__``, so a baseline-diff test comparing a
``Violation`` from one load against one from another silently always
disagrees. Loading once, here, and sharing the result closes that.

The dotted, path-derived module name (``scripts.craftsmanship_rules``, not
a bare name) is preserved for mutmut's trampoline — same idiom as
``check_doc_claims.py``'s sibling loads (see that file's test for the full
rationale).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load_once(dotted_name: str, filename: str):
    bare_name = dotted_name.rsplit(".", 1)[-1]
    if dotted_name in sys.modules:
        return sys.modules[dotted_name]
    if bare_name in sys.modules:
        # craftsmanship_rules.py's own body already loaded this sibling
        # under its bare name — reuse it instead of executing it again.
        return sys.modules[bare_name]
    spec = importlib.util.spec_from_file_location(dotted_name, _SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    # Registered under BOTH names before exec: the dotted name for
    # mutmut/dataclasses (`_process_class` looks up
    # `sys.modules[cls.__module__]`), the bare name because
    # craftsmanship_rules.py's own body does `import craftsmanship_constants`
    # / `import craftsmanship_imports`, each of which does `from
    # craftsmanship_rules import Violation` — that must resolve to THIS
    # in-progress module, not trigger a second recursive load.
    sys.modules[dotted_name] = module
    sys.modules[bare_name] = module
    spec.loader.exec_module(module)
    return module


rules = _load_once("scripts.craftsmanship_rules", "craftsmanship_rules.py")
craftsmanship_imports = _load_once(
    "scripts.craftsmanship_imports", "craftsmanship_imports.py"
)
craftsmanship_constants = _load_once(
    "scripts.craftsmanship_constants", "craftsmanship_constants.py"
)
craftsmanship_layer_table = _load_once(
    "scripts.craftsmanship_layer_table", "craftsmanship_layer_table.py"
)
baseline_mod = _load_once("scripts.craftsmanship_baseline", "craftsmanship_baseline.py")
