"""The mutation gate judges only the mutants on changed lines (ADR-1122).

Owner decision 2026-11-06: a one-line change no longer pays for every mutant of
the function it touches (#865: 102 survivors in `_construct_store`; #878: 273).
The cases build a `mutants/` directory in mutmut 3.8.1's layout: the generated
module, with an unmutated copy and the mutants of each function, and its `.spans`
index. The mapping was also checked against `mutmut show` on every mutant of
`core/telemetry.py` (245) and `core/wiki_identity.py` (35, methods included).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import ci_mutation_lines as cml  # noqa: E402

PATH = "mcp_server/m.py"
SOURCE = (
    "def f(a, b=1):\n"  # 1
    "    c = a + b\n"  # 2
    "    return c * 2\n"  # 3
    "\n"  # 4
    "\n"  # 5
    "class K:\n"  # 6
    "    def m(self, x):\n"  # 7
    "        y = x - 1\n"  # 8
    "        return y\n"  # 9
)
# name -> body of the generated function after its `def` line
GENERATED = {
    "x_f__mutmut_orig": (
        "def x_f__mutmut_orig(a, b=1):",
        ["c = a + b", "return c * 2"],
    ),
    "x_f__mutmut_1": ("def x_f__mutmut_1(a, b=2):", ["c = a + b", "return c * 2"]),
    "x_f__mutmut_2": ("def x_f__mutmut_2(a, b=1):", ["c = a - b", "return c * 2"]),
    "x_f__mutmut_3": ("def x_f__mutmut_3(a, b=1):", ["c = a + b", "return c * 3"]),
    "xǁKǁm__mutmut_orig": (
        "def xǁKǁm__mutmut_orig(self, x):",
        ["y = x - 1", "return y"],
    ),
    "xǁKǁm__mutmut_1": ("def xǁKǁm__mutmut_1(self, x):", ["y = x + 1", "return y"]),
}


def _tree(tmp_path: Path, generated=GENERATED, version=cml.SPANS_VERSION) -> Path:
    (tmp_path / PATH).parent.mkdir(parents=True)
    (tmp_path / PATH).write_text(SOURCE, encoding="utf-8")
    lines, spans = ["import os", ""], {}
    for key, (header, body) in generated.items():
        start = len(lines)
        lines += ["", header, *(f"    {b}" for b in body)]
        spans[key] = [start, len(lines)]
    mutants = tmp_path / "mutants" / PATH
    mutants.parent.mkdir(parents=True)
    mutants.write_text("\n".join(lines) + "\n", encoding="utf-8")
    index = {"version": version, "spans": spans}
    Path(f"{mutants}.spans").write_text(json.dumps(index), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("mutant", "lines"),
    [("x_f__mutmut_1", {1}), ("x_f__mutmut_2", {2}), ("x_f__mutmut_3", {3})],
)
def test_a_function_mutant_lands_on_its_source_line(tmp_path, mutant, lines):
    root = _tree(tmp_path)
    assert cml.mutated_lines(root, PATH, f"mcp_server.m.{mutant}") == lines


def test_a_method_mutant_lands_on_its_source_line(tmp_path):
    root = _tree(tmp_path)
    assert cml.mutated_lines(root, PATH, "mcp_server.m.xǁKǁm__mutmut_1") == {8}


def test_only_mutants_on_changed_lines_are_judged(tmp_path):
    root = _tree(tmp_path)
    env = {cml.LINES_ENV: f"{PATH}=2,9"}
    names = [f"mcp_server.m.x_f__mutmut_{n}" for n in (1, 2, 3)]
    assert cml.judged(names, root, env) == ["mcp_server.m.x_f__mutmut_2"]
    assert not cml.keeps("mcp_server.m.xǁKǁm__mutmut_1", root, env)


def test_without_a_line_scope_every_mutant_is_judged(tmp_path):
    root = _tree(tmp_path)
    assert cml.keeps("mcp_server.m.x_f__mutmut_1", root, {})


def test_a_mutant_mutmut_did_not_generate_is_kept_for_the_stale_check(tmp_path):
    root = _tree(tmp_path)
    env = {cml.LINES_ENV: f"{PATH}=2"}
    assert cml.keeps("mcp_server.m.x_f__mutmut_99", root, env)


def test_a_copy_that_differs_from_the_source_stops_the_gate(tmp_path):
    drifted = {**GENERATED}
    drifted["x_f__mutmut_orig"] = (
        "def x_f__mutmut_orig(a, b=1):",
        ["c = 0", "return c"],
    )
    root = _tree(tmp_path, drifted)
    with pytest.raises(cml.LineMapError, match="differs from source"):
        cml.mutated_lines(root, PATH, "mcp_server.m.x_f__mutmut_2")


def test_an_unknown_spans_version_stops_the_gate(tmp_path):
    root = _tree(tmp_path, version=2)
    with pytest.raises(cml.LineMapError, match="spans version"):
        cml.keeps("mcp_server.m.x_f__mutmut_2", root, {cml.LINES_ENV: f"{PATH}=2"})


def test_a_malformed_scope_stops_the_gate():
    with pytest.raises(cml.LineMapError):
        cml.parse_scope("12,13")


def test_a_cut_is_judged_on_its_anchor_and_the_next_line():
    assert cml.job_lines({4}, {(10, 4)}) == [4, 10, 11]
    assert cml.scope_value(PATH, [4, 10]) == f"{PATH}=4,10"
