"""G17 — the lazy-core gate.

`import omniweave_core` imports none of
`{model, store, archive, retrieve, answer, out, host, toolchain, modelserver}`.

The reason is the per-turn hook path. `ow hook prompt` has a p95 budget of 250 ms warm
(G26) and every failure on that hook is a silent exit 0, so a deadline breach turns the
adoption lever off with no symptom — the worst failure shape available on the agent path
(01-principles.md, INV-3). Core pays for every module this import touches, and the nine
names are the nine largest things it could touch.

Three properties, and the third is what makes the first two trustworthy: the gate
asserts the nine are absent, asserts each is still *reachable*, and asserts by
**negative control** that the same instrument sees one of them when it really is
imported. A `sys.modules` assertion that can only pass is not a gate.

Specified in charter.md section D1 gate G17 and 11-repo-layout.md section 1.3 ("The nine
LAZY names are a STRUCTURAL property, not a convention"). Enforced in CI by
`tools/gate_lazy_core.py` (02-architecture.md section 3.3), which W1.9 owns; this is the
same assertion in the test tree, where it runs on every PR from P1 onward.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the fixtures deliver these; the names are here for the annotations
    from pathlib import Path

    from conftest import Interpreter, PlanDocs, SourceIndex

# The nine, verbatim from charter.md section D1 gate G17.
# `test_the_nine_names_are_the_plans_nine` asserts this tuple against every document
# that prints the set, so the literal here cannot drift away from the charter row that
# fixes it.
LAZY: tuple[str, ...] = (
    "model",
    "store",
    "archive",
    "retrieve",
    "answer",
    "out",
    "host",
    "toolchain",
    "modelserver",
)

# The seven of the nine that are packages. `toolchain` and `modelserver` are single
# modules (11-repo-layout.md section 1.3's tree marks both `LAZY` on a `.py` line), which
# is why the count of subpackage homes P1 creates is not nine.
LAZY_PACKAGES: tuple[str, ...] = tuple(
    name for name in LAZY if name not in {"toolchain", "modelserver"}
)

# Every plan site that prints the braced set. Cross-document agreement over six
# independent statements of one list is worth more than any one of them being right.
LAZY_SET_SITES: tuple[str, ...] = (
    "00-vision.md",
    "02-architecture.md",
    "10-interfaces.md",
    "11-repo-layout.md",
    "12-performance.md",
    "_notes/charter.md",
)

# `{model, store, ...}` as the documents write it, tolerating the `**bold**`, backtick and
# line-wrap decoration a markdown table cell puts around the names.
_BRACED_SET = re.compile(r"\{(model[^{}]*modelserver)\}")
_NAME = re.compile(r"[a-z_]+")


def _named_sets(plan: PlanDocs) -> dict[str, tuple[str, ...]]:
    """The braced nine-name set as each document prints it, keyed by document."""
    found: dict[str, tuple[str, ...]] = {}
    for document in LAZY_SET_SITES:
        flattened = plan.text(document).replace("\n", " ")
        match = _BRACED_SET.search(flattened)
        if match is not None:
            found[document] = tuple(_NAME.findall(match.group(1)))
    return found


def _core_src(repo_root: Path) -> Path:
    return repo_root / "packages" / "omniweave-core" / "src" / "omniweave_core"


def _module_name(repo_root: Path, path: Path) -> str:
    """`.../src/omniweave_core/a/b.py` -> `omniweave_core.a.b`."""
    src = repo_root / "packages" / "omniweave-core" / "src"
    parts = path.relative_to(src).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _runtime_module_scope_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """Imports that run when the module is imported.

    Module scope, plus `try:`/`else:`/`finally:` at module scope, which is how a stdlib
    fallback is spelled. `if TYPE_CHECKING:` bodies are excluded on purpose: they never
    execute, so an annotation resolved there costs the hook path nothing. That exclusion
    is the difference between this gate and G4, which counts `TYPE_CHECKING` imports
    because a layer violation is a fact about the source and not about the runtime.
    """
    found: list[ast.Import | ast.ImportFrom] = []

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                found.append(node)
            elif isinstance(node, ast.Try):
                visit(node.body)
                visit(node.orelse)
                visit(node.finalbody)
            elif isinstance(node, ast.If) and not _is_type_checking(node.test):
                visit(node.body)
                visit(node.orelse)

    visit(tree.body)
    return found


def _is_type_checking(test: ast.expr) -> bool:
    match test:
        case ast.Name(id="TYPE_CHECKING"):
            return True
        case ast.Attribute(attr="TYPE_CHECKING"):
            return True
        case _:
            return False


# ---------------------------------------------------------------------------
# The list itself
# ---------------------------------------------------------------------------


def test_the_nine_names_are_the_plans_nine(plan: PlanDocs) -> None:
    """Every document that prints the set prints the same set, and it is `LAZY`.

    Six statements of one list is six chances for a rename to land in five of them.
    `drivers` is deliberately **not** among them: 11-repo-layout.md section 1.3's tree
    marks `drivers/` `T-CONTRACT` with no `LAZY`, because `DriverCard` and `resolve()`
    are on the discovery path `ow doctor` and `ow drivers list` already take.
    """
    plan.require()
    printed = _named_sets(plan)
    missing = sorted(set(LAZY_SET_SITES) - set(printed))
    assert missing == [], f"documents that no longer print the lazy set: {missing}"
    for document, names in sorted(printed.items()):
        assert names == LAZY, f"_plan/{document} prints {names}, not {LAZY}"


def test_the_lazy_set_has_exactly_nine_members() -> None:
    """ "the nine lazy subpackages" is a literal in 11-repo-layout.md sections 1.3 and 3,
    in 12-performance.md's G17 row and in charter.md D1. Nine is what those say."""
    assert len(LAZY) == len(set(LAZY)) == 9
    assert len(LAZY_PACKAGES) == 7


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def test_a_bare_import_of_core_loads_none_of_the_nine(interpreter: Interpreter) -> None:
    """G17, from a fresh interpreter.

    This session has already imported half the tree for its own reasons, so its own
    `sys.modules` cannot answer the question at all.
    """
    loaded = interpreter.modules_after("import omniweave_core")
    eager = sorted(name for name in LAZY if f"omniweave_core.{name}" in loaded)
    assert eager == [], f"import omniweave_core eagerly loaded {eager}"


def test_g17_also_holds_under_importtime(interpreter: Interpreter) -> None:
    """The same statement through G9's instrument rather than G17's.

    `-X importtime` reports what was *executed*, so it is the trace
    `tools/gate_importtime.py` reads and the one 02-architecture.md section 3.3 names.
    Two instruments disagreeing is itself the finding.
    """
    executed = interpreter.importtime_modules("import omniweave_core")
    eager = sorted(name for name in LAZY if f"omniweave_core.{name}" in executed)
    assert eager == [], f"-X importtime attributes {eager} to import omniweave_core"


def test_the_instrument_sees_a_lazy_name_when_it_really_is_imported(
    interpreter: Interpreter,
) -> None:
    """The negative control for the two assertions above.

    `store` is the one used because it is the largest of the nine and the only site that
    may call `sqlite3.connect` (INV-17), so if any name is going to arrive through a
    convenience re-export it is this one. A gate whose instrument is silently broken
    reports green forever.
    """
    loaded = interpreter.modules_after("import omniweave_core.store")
    assert "omniweave_core.store" in loaded
    assert "omniweave_core" in loaded


def test_no_eagerly_loaded_core_module_names_a_lazy_submodule_at_module_scope(
    repo_root: Path, interpreter: Interpreter, sources: SourceIndex
) -> None:
    """The static half of G17 — the half that says *which line* broke it.

    `test_a_bare_import_of_core_loads_none_of_the_nine` reports that something pulled a
    lazy name in. This reports the file and the line, and it finds exactly the violation
    INV-3 names: "a module-level `from .store import Store` added to make a type
    annotation resolve at runtime instead of under `TYPE_CHECKING`".
    """
    eager = {
        name
        for name in interpreter.modules_after("import omniweave_core")
        if name == "omniweave_core" or name.startswith("omniweave_core.")
    }
    forbidden = {f"omniweave_core.{name}" for name in LAZY}
    violations: list[str] = []
    for path in sources.files(_core_src(repo_root)):
        if _module_name(repo_root, path) not in eager:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _runtime_module_scope_imports(tree):
            named = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            for name in named:
                if name in forbidden or name.split(".")[:2] in [
                    module.split(".") for module in forbidden
                ]:
                    violations.append(f"{path.as_posix()}:{node.lineno}: {name}")
    report = "\n".join(violations)
    assert violations == [], f"an eagerly imported core module names a lazy submodule:\n{report}"


# ---------------------------------------------------------------------------
# The complement: the nine are deferred, not absent
# ---------------------------------------------------------------------------


def test_the_seven_lazy_subpackages_p1_creates_are_importable_on_demand(
    repo_root: Path, interpreter: Interpreter
) -> None:
    """Importing each one directly is what proves the eager import's silence is laziness
    and not absence. `toolchain` and `modelserver` are modules rather than packages and
    arrive with W1.6 and W4.9, so P1's tree has seven homes and not nine."""
    present = tuple(name for name in LAZY if (_core_src(repo_root) / name).is_dir())
    assert present == LAZY_PACKAGES, f"P1's subpackage homes are {present}"
    for name in present:
        loaded = interpreter.modules_after(f"import omniweave_core.{name}")
        assert f"omniweave_core.{name}" in loaded, f"omniweave_core.{name} is not importable"


def test_every_lazy_name_is_reachable_through_getattr(interpreter: Interpreter) -> None:
    """The complement of G17, and the reason G17 is not satisfiable by deletion.

    11-repo-layout.md section 1.3: "`__init__.py` exposes them through `__getattr__`".
    A lazy name that is *absent* rather than deferred passes the absence assertion and
    breaks every caller, so the gate has to assert both halves.

    **This carried a strict xfail from P1 until P4 W4.9b**, whose reason read: "modelserver.py
    lands at P4 W4.9, so `__init__`'s `__getattr__` cannot expose all nine before then. G17's
    absence half above is asserted unconditionally and does not wait for this." The marker said
    what would end it -- "the day this starts passing is the day the substrate is complete, and a
    skip would say nothing at all on that day" -- and `strict=True` is what made the day arrive as
    a failure rather than as silence. `modelserver.py` landed; the ninth name resolves; the marker
    is gone and the assertion is unconditional.
    """
    program = "import omniweave_core\n" + "\n".join(
        f"getattr(omniweave_core, {name!r})" for name in LAZY
    )
    interpreter.run(program)
