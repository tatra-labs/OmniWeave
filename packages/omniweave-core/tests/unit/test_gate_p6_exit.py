"""P6's two runnable exit criteria, and the failures each one exists to catch.

16-roadmap.md:687-695 lists seven commands. Five invoke `ow eval` and `ow query`, which are P7's
CLI and P10's eval harness; two are scripts, and these are their tests:

* `tools/gate_one_absent_site.py` -- SV8's count. It re-implements nothing, so half of what must be
  proven is that it DELEGATES: the site it reports is the site `gate_semgrep`'s own walk finds, and
  a second site anywhere makes both red.
* `tools/gate_no_ellipsis_default.py` -- 16:674's freeze clause, *"**No field in any of these types
  defaults to `...`**"*. Four shapes must be proven red and one proven green, because the green one
  is a `Protocol` method and the whole judgement in that gate is which of the five it is.

Both gates are asserted against the REAL tree in one test each, which is what stops every synthetic
case from being a proof about a temporary directory and nothing else.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from conftest import PlanDocs

ROADMAP = "16-roadmap.md"
STORE_DOC = "07-store-and-retrieval.md"


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())


def _load(name: str) -> object:
    """Load a `tools/` script by path.

    `spec_from_file_location`, the house form: `tools/` is a directory of scripts and not a
    package, `importlib.import_module` is confined to `host/`, and a `sys.path` mutation would
    leak into every later test in the session.
    """
    path = REPO_ROOT / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"omniweave_{name}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - the file is in this repository
        message = f"cannot load {path}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


absent_gate = _load("gate_one_absent_site")
ellipsis_gate = _load("gate_no_ellipsis_default")


# =============================================================================================
# 1. Both scripts exist under the names P6's exit block gives them
# =============================================================================================


@pytest.mark.parametrize(
    "script", ["tools/gate_one_absent_site.py", "tools/gate_no_ellipsis_default.py"]
)
def test_the_exit_block_names_a_script_that_exists(script: str, plan: PlanDocs) -> None:
    """An exit criterion is a COMMAND, and a command that cannot be run is not a criterion."""
    plan.require()
    assert script in plan.text(ROADMAP)
    assert (REPO_ROOT / script).is_file()


# =============================================================================================
# 2. SV8's count, and the delegation that keeps it one implementation
# =============================================================================================


def test_the_real_tree_has_exactly_one_absent_site() -> None:
    """The one assertion that is about this repository rather than about a fixture."""
    assert absent_gate.main() == 0
    sites = absent_gate.sites()
    assert len(sites) == 1
    assert sites[0][0] == absent_gate.HOME


def test_the_reported_site_is_the_one_the_bank_confines_it_to() -> None:
    """`HOME` is read off `gate_semgrep`, not retyped, so the two gates cannot disagree."""
    assert absent_gate.HOME.endswith("omniweave_core/retrieve/verdict.py")
    assert absent_gate.RULE == "omniweave-one-verdict-absent-site"


def test_a_second_site_inside_the_home_file_is_caught(tmp_path: Path) -> None:
    """The half semgrep cannot express.

    The bank's rule confines the return to one FILE; the count rejects a second site inside that
    file, which is the sixteenth-hazard case 16:661 names -- *"what stops a sixteenth hazard from
    becoming a second citability rule"*.
    """
    home = tmp_path / absent_gate.HOME
    home.parent.mkdir(parents=True)
    home.write_text(
        "from omniweave_core.retrieve.verdict import VerdictState\n"
        "def a() -> VerdictState:\n"
        "    return VerdictState.ABSENT\n"
        "def b() -> VerdictState:\n"
        "    return VerdictState.ABSENT\n",
        encoding="utf-8",
    )
    assert len(absent_gate.sites(tmp_path)) == 2


def test_a_site_outside_the_home_file_is_caught(tmp_path: Path) -> None:
    """The half the bank DOES express, asserted here so the runner's report covers both."""
    stray = tmp_path / "packages/omniweave/src/omniweave/route/evidence.py"
    stray.parent.mkdir(parents=True)
    stray.write_text(
        "from omniweave_core.retrieve.verdict import VerdictState\n"
        "def guess() -> VerdictState:\n"
        "    return VerdictState.ABSENT\n",
        encoding="utf-8",
    )
    found = absent_gate.sites(tmp_path)
    assert [rel for rel, _ in found] == ["packages/omniweave/src/omniweave/route/evidence.py"]


def test_the_runner_walks_with_the_banks_own_generator() -> None:
    """One walk, not two. INV-21 allows a fact one home and a second count could disagree.

    Asserted structurally: the runner's source names `_bank._absent_returns` and defines no
    generator of its own, so a future edit that re-implemented the walk fails here.
    """
    source = (REPO_ROOT / "tools" / "gate_one_absent_site.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_absent_returns" not in defined
    assert "_bank._absent_returns" in source
    assert "_bank.ast_findings" in source


# =============================================================================================
# 3. The ellipsis ban: four red shapes, one green, and the real tree
# =============================================================================================


def test_the_real_tree_carries_no_ellipsis_default() -> None:
    """P6 freezes this, so it has to hold now rather than at the freeze."""
    assert ellipsis_gate.main() == 0
    assert ellipsis_gate.findings() == []


def _shipped(tmp_path: Path, source: str) -> Path:
    """Write `source` where the gate's `packages/*/src/**` glob will find it."""
    path = tmp_path / "packages/omniweave-core/src/omniweave_core/shape.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("class S:\n    x: int = ...\n", "field"),
        ("class S:\n    x = ...\n", "assign"),
        ("def f(x: int = ...) -> None:\n    return None\n", "param"),
        ("def f(*, x: int = ...) -> None:\n    return None\n", "param"),
    ],
)
def test_each_banned_shape_is_found(tmp_path: Path, source: str, kind: str) -> None:
    """07:1239's three forms, plus the keyword-only parameter group.

    A keyword-only default lives in `args.kw_defaults` and not in `args.defaults`, so a gate that
    read one list would pass the shape a caller is most likely to omit.
    """
    _shipped(tmp_path, source)
    found = ellipsis_gate.findings(tmp_path)
    assert len(found) == 1
    assert found[0].kind == kind


def test_a_protocol_method_is_not_a_finding(tmp_path: Path) -> None:
    """D290: the declaration form. The framework ships three of these and they are not the defect.

    A body-less method binds no default at any call site -- the call goes to the implementation --
    so 07:1239's stated harm, a consumer type-checking against `EllipsisType`, cannot arise.
    """
    _shipped(
        tmp_path,
        "from typing import Any, Protocol\n"
        "class Cursor(Protocol):\n"
        "    def execute(self, sql: str, parameters: dict[str, object] = ..., /) -> Any: ...\n",
    )
    assert ellipsis_gate.findings(tmp_path) == []


def test_a_docstringed_declaration_is_still_a_declaration(tmp_path: Path) -> None:
    """A `Protocol` method with a docstring above its `...` is the same shape, and this house
    writes one on nearly every method."""
    _shipped(
        tmp_path,
        "from typing import Protocol\n"
        "class P(Protocol):\n"
        "    def f(self, x: int = ...) -> None:\n"
        '        """What it does."""\n'
        "        ...\n",
    )
    assert ellipsis_gate.findings(tmp_path) == []


def test_a_real_body_with_an_ellipsis_default_is_a_finding(tmp_path: Path) -> None:
    """The control for the case above: the same signature with an implementation IS the defect."""
    _shipped(
        tmp_path,
        "class P:\n    def f(self, x: int = ...) -> int:\n        return 1 if x is ... else x\n",
    )
    found = ellipsis_gate.findings(tmp_path)
    assert len(found) == 1
    assert found[0].kind == "param"


def test_a_function_body_that_is_an_ellipsis_is_never_a_finding(tmp_path: Path) -> None:
    """An expression statement is not a default.

    `omniweave_core.store` is built out of four Protocols of exactly this shape.
    """
    _shipped(
        tmp_path, "from typing import Protocol\nclass P(Protocol):\n    def f(self) -> None: ...\n"
    )
    assert ellipsis_gate.findings(tmp_path) == []


def test_a_test_file_is_not_a_shipped_shape(tmp_path: Path) -> None:
    """The glob is `packages/*/src/**`: a fixture may bind `Ellipsis` to prove a refusal."""
    path = tmp_path / "packages/omniweave-core/tests/unit/test_x.py"
    path.parent.mkdir(parents=True)
    path.write_text("class S:\n    x: int = ...\n", encoding="utf-8")
    assert ellipsis_gate.findings(tmp_path) == []


def test_a_stub_is_not_a_shipped_shape(tmp_path: Path) -> None:
    """`.pyi` is where `= ...` is the CORRECT spelling, and `sdk/_generated.pyi` is shipped."""
    path = tmp_path / "packages/omniweave/src/omniweave/sdk/_generated.pyi"
    path.parent.mkdir(parents=True)
    path.write_text("def f(x: int = ...) -> None: ...\n", encoding="utf-8")
    assert ellipsis_gate.findings(tmp_path) == []


def test_a_green_control(tmp_path: Path) -> None:
    """Without it, a gate that found nothing anywhere would pass every red test above."""
    _shipped(tmp_path, "class S:\n    x: int = 0\n    y: str | None = None\n")
    assert ellipsis_gate.findings(tmp_path) == []


def test_the_report_names_the_file_the_line_and_the_shape(tmp_path: Path) -> None:
    """A failure whose message is a count sends the reader looking for the site by hand."""
    _shipped(tmp_path, "class Shape:\n    x: int = ...\n")
    (finding,) = ellipsis_gate.findings(tmp_path)
    rendered = finding.render()
    assert "shape.py:2" in rendered
    assert "Shape" in rendered
    assert "annotated class field" in rendered


def test_the_bans_mechanism_is_the_plans(plan: PlanDocs) -> None:
    """07:1239-1241 states the harm, which is what the gate's D290 reading turns on."""
    plan.require()
    text = plan.text(STORE_DOC)
    assert "No field defaults to `...` anywhere in a shipped shape." in text
    assert "neither required nor defaulted" in text
