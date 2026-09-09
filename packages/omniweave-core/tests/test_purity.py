"""D1 / INV-2 — `omniweave-core` and `omniweave-ports` have zero third-party runtime
dependencies, and `omniweave_ports` has no behaviour at all.

The negative evidence the invariant was written against is unambiguous: `torch` and
`torchvision` are **base** requirements of docling, so its DOCX reader costs ~2.5-3.5 GB
installed with CUDA wheels; `leann-core` requires torch and AGPL PyMuPDF and four PDF
libraries including archived `PyPDF2` (01-principles.md, INV-2). Core being the host,
and being written in the driver-facing vocabulary, is why its single first-party edge
points at `omniweave-ports` rather than duplicating six types.

Four instruments, because one would be a single point of failure:

* the **declarations** — what the two `pyproject.toml` files say they depend on (G1's
  subject);
* the **source** — every import in both `src/` trees, resolved against
  `sys.stdlib_module_names`, which is exactly what that set is for;
* the **import trace** — `python -X importtime -c "import omniweave_core"` (G9), plus
  `asyncio` and `selectors` by name (G23);
* the **audit hook** — what importing each distribution actually opens, connects,
  spawns and starts, which is the only one of the four that can see a side effect.

Enforced in CI by `tools/gate_core_pure.py` and `tools/gate_importtime.py`
(02-architecture.md section 3.3), which W1.9 owns. The clean-environment *resolve* half
of G1 needs a resolver and a network and is that script's; what is asserted here is the
declared closure, which is the thing the resolve resolves.
"""

from __future__ import annotations

import ast
import re
import socket
import subprocess  # noqa: TID251 — the fixture patches it; nothing here spawns one.
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:  # the fixtures deliver these; the names are here for the annotations
    from pathlib import Path

    from conftest import Distribution, Interpreter, SourceIndex

PURE = ("omniweave-ports", "omniweave-core")

# The one dependency core is permitted, verbatim from packages/omniweave-core/
# pyproject.toml's comment: "THE ONLY dependency ... Amending this amends the CHARTER."
CORE_DEPENDENCIES = ("omniweave-ports >=1,<2",)

# G23. The single event loop in the framework lives in `omniweave/run/`, in the CLI
# distribution, precisely so core pays no loop-import tax (charter INV-3).
FORBIDDEN_EAGER_MODULES = ("asyncio", "selectors")

# Names that are importable but are not modules a distribution depends on.
_ALWAYS_AVAILABLE = frozenset({"__future__", "__main__"})

# PEP 508: the distribution name is the leading run of name characters.
_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _dependencies(dist: Distribution) -> tuple[str, ...]:
    """`[project] dependencies` as written, in declaration order."""
    project = dist.pyproject()["project"]
    assert isinstance(project, dict)
    declared = project.get("dependencies", [])
    assert isinstance(declared, list)
    return tuple(str(requirement) for requirement in declared)


def _stdlib() -> frozenset[str]:
    """The standard library of the running interpreter.

    `sys.stdlib_module_names` is frozen per version and includes the private `_`-prefixed
    accelerators, which is what makes it usable as a membership test rather than as a
    heuristic. A hand-maintained list is the thing it exists to replace.
    """
    return frozenset(sys.stdlib_module_names) | _ALWAYS_AVAILABLE


def _third_party_imports(sources: SourceIndex, dist: Distribution) -> list[str]:
    """Every import in `dist`'s `src/` that is neither stdlib nor first-party."""
    stdlib = _stdlib()
    offences: list[str] = []
    for root in dist.import_roots:
        for path in sources.files(dist.src / root):
            for site in sources.imports(path):
                name = site.module.split(".", 1)[0]
                if site.level > 0 or not name:
                    continue  # a relative import; test_layers.py owns that failure
                if name in stdlib or sources.first_party_root(name) is not None:
                    continue
                offences.append(str(site))
    return offences


def _third_party_modules(loaded: frozenset[str], first_party: str) -> list[str]:
    """`loaded` minus the standard library minus the first-party package."""
    stdlib = _stdlib()
    return sorted(
        name
        for name in loaded
        if not name.startswith("_")
        and name.split(".", 1)[0] not in stdlib
        and not name.startswith(("omniweave_core", "omniweave_ports", first_party))
    )


# ---------------------------------------------------------------------------
# The declarations
# ---------------------------------------------------------------------------


def test_core_declares_omniweave_ports_and_nothing_else(sources: SourceIndex) -> None:
    """G1's subject. One line, first-party, stdlib-only on the other side."""
    assert _dependencies(sources.distribution("omniweave-core")) == CORE_DEPENDENCIES


def test_ports_declares_nothing(sources: SourceIndex) -> None:
    """Rule 1. The only distribution in the workspace with an empty `dependencies`."""
    assert _dependencies(sources.distribution("omniweave-ports")) == ()


def test_the_declared_closure_of_core_is_exactly_two_first_party_distributions(
    sources: SourceIndex,
) -> None:
    """G1 stated as a closure over the declarations rather than as a resolve.

    "`omniweave-core` resolves to exactly TWO first-party distributions, `omniweave-core`
    + `omniweave-ports`, and zero third-party ones" (charter D1, G1). The clean-
    environment resolve that proves it against a real index is
    `tools/gate_core_pure.py`'s; the closure that resolve walks is this.
    """
    closure: set[str] = set()
    frontier = ["omniweave-core"]
    while frontier:
        name = frontier.pop()
        if name in closure:
            continue
        closure.add(name)
        for requirement in _dependencies(sources.distribution(name)):
            required = _REQUIREMENT_NAME.match(requirement)
            assert required is not None, requirement
            distribution = required.group(0)
            assert distribution.startswith("omniweave-"), f"{name} depends on {distribution}"
            frontier.append(distribution)
    assert sorted(closure) == sorted(PURE)


def test_cores_only_extra_is_a_capability_remedy(sources: SourceIndex) -> None:
    """ "No other core extra may exist, because an extra that adds a capability makes
    INV-2 conditional" (11-repo-layout.md section 2.1).

    `[sqlite]` is permitted because it is not a capability: `store/sqlite.py` refuses at
    open below `MIN_SQLITE = (3, 42, 0)` and names the extra as the remedy the probe that
    failed prints. An extra that made something newly *possible* would be a dependency
    with a flag in front of it, and INV-2 would hold only for the users who did not set
    the flag.
    """
    project = sources.distribution("omniweave-core").pyproject()["project"]
    assert isinstance(project, dict)
    optional = project.get("optional-dependencies", {})
    assert isinstance(optional, dict)
    assert sorted(optional) == ["sqlite"]


# ---------------------------------------------------------------------------
# The source
# ---------------------------------------------------------------------------


def test_no_source_file_in_core_or_ports_imports_a_third_party_module(
    sources: SourceIndex,
) -> None:
    """D1, resolved against `sys.stdlib_module_names` rather than against a hand list.

    Walking source rather than the installed environment is deliberate: the violation
    INV-2 names is "a `from pydantic import` inside `omniweave_core/model/`", and that
    line is a defect the moment it is written, whether or not pydantic happens to be in
    the venv that runs the gate.
    """
    for name in PURE:
        offences = _third_party_imports(sources, sources.distribution(name))
        assert offences == [], f"{name} imports a third party:\n" + "\n".join(offences)


def test_ports_imports_no_first_party_package_at_all(sources: SourceIndex) -> None:
    """Rule 1 at the source level: `omniweave_ports`' row is `[]`, so it may not import
    even `omniweave_core`. This is what makes a third-party driver's whole omniweave
    surface ~40 KB with an empty `dependencies` list (02-architecture.md row 1)."""
    dist = sources.distribution("omniweave-ports")
    offences: list[str] = []
    for root in dist.import_roots:
        for path in sources.files(dist.src / root):
            for site in sources.imports(path):
                first_party = sources.first_party_root(site.module)
                if first_party is not None and first_party != "omniweave_ports":
                    offences.append(str(site))
    assert offences == [], "omniweave_ports reaches the framework:\n" + "\n".join(offences)


def test_the_purity_walk_detects_a_third_party_import_it_is_shown(
    sources: SourceIndex, tmp_path: Path
) -> None:
    """The negative control. `pydantic` is the import INV-2's violation section names."""
    offender = tmp_path / "model.py"
    offender.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "import omniweave_ports\n"
        "from pydantic import BaseModel\n"
        "import numpy as np\n",
        encoding="utf-8",
    )
    stdlib = _stdlib()
    third_party = [
        str(site)
        for site in sources.imports(offender)
        if site.module.split(".", 1)[0] not in stdlib
        and sources.first_party_root(site.module) is None
    ]
    assert len(third_party) == 2, third_party
    assert "pydantic" in third_party[0]
    assert "numpy" in third_party[1]


# ---------------------------------------------------------------------------
# The import trace
# ---------------------------------------------------------------------------


def test_g9_importtime_attributes_zero_third_party_modules_to_core(
    interpreter: Interpreter,
) -> None:
    """G9, through the instrument the charter names for it.

    Measured as a difference against a bare interpreter, because a virtualenv injects
    `_virtualenv`, `_distutils_hack`, `sitecustomize` and — on Windows —
    `pywin32_bootstrap` under `site` before any user code runs. Read absolutely those
    are third-party modules in the trace; read as a difference they cancel, and what is
    left is what `import omniweave_core` actually cost.
    """
    executed = interpreter.importtime_modules("import omniweave_core")
    assert _third_party_modules(executed, "omniweave_core") == []


def test_g9_importtime_attributes_zero_third_party_modules_to_ports(
    interpreter: Interpreter,
) -> None:
    """The same for the leaf. `omniweave_ports` is stdlib-only by row as well as by
    declaration, so a third-party module here would be unspellable twice over."""
    executed = interpreter.importtime_modules("import omniweave_ports")
    assert _third_party_modules(executed, "omniweave_ports") == []


def test_g23_core_imports_neither_asyncio_nor_selectors(interpreter: Interpreter) -> None:
    """G23. `asyncio` is banned repo-wide by the ruff `banned-api` block and permitted
    only under `omniweave/run/`, the one event loop in the framework. Naming both
    modules explicitly rather than letting the third-party check catch them is the
    point: they are stdlib, so nothing else would."""
    loaded = interpreter.modules_after("import omniweave_core")
    present = sorted(name for name in FORBIDDEN_EAGER_MODULES if name in loaded)
    assert present == [], f"import omniweave_core loaded {present}"


def test_a_bare_import_of_either_adds_only_stdlib_and_first_party_modules(
    interpreter: Interpreter,
) -> None:
    """The `sys.modules` reading of D1, complementary to the `-X importtime` one.

    `-X importtime` sees what was executed; `sys.modules` sees what is reachable. A
    module that was already loaded for another reason appears in the second and not the
    first, so a re-export that is free on a warm interpreter and expensive on a cold one
    shows up here.
    """
    for statement, first_party in (
        ("import omniweave_core", "omniweave_core"),
        ("import omniweave_ports", "omniweave_ports"),
    ):
        added = interpreter.modules_added_by(statement)
        assert _third_party_modules(added, first_party) == [], f"{statement} pulled in a dependency"


# ---------------------------------------------------------------------------
# No behaviour: `omniweave_ports` declares and does not execute
# ---------------------------------------------------------------------------

# Module-scope statements a pure type surface is made of. Everything else — a `with`, a
# `for`, a `try`, a bare call, an `assert` — is the module doing something at import
# time, which is what "not one function here has a side effect" forbids.
_DECLARATIVE = (
    ast.Import,
    ast.ImportFrom,
    ast.ClassDef,
    ast.FunctionDef,
    ast.Assign,
    ast.AnnAssign,
    ast.If,  # `if TYPE_CHECKING:` and `if sys.version_info >= (...)`
    ast.Pass,
)


def _module_scope_offences(path: Path) -> list[str]:
    """Module-level statements in `path` that are not declarations.

    A bare string literal is a declaration here: the module docstring is one, and so is
    the PEP 258 attribute docstring that follows a module constant — `INLINE_MAX = ...`
    followed by the paragraph naming charter D3 as its home. Both evaluate to a string
    that is immediately discarded, which is the whole of their runtime effect. Any other
    bare expression is a call, and a call at module scope is the thing being forbidden.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offences: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Expr):
            if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                offences.append(f"{path.as_posix()}:{node.lineno}: {type(node.value).__name__}")
        elif not isinstance(node, _DECLARATIVE):
            offences.append(f"{path.as_posix()}:{node.lineno}: {type(node).__name__}")
    return offences


def test_every_module_in_ports_is_declarations_and_nothing_else(sources: SourceIndex) -> None:
    """02-architecture.md row 1: `omniweave_ports` is responsible for the driver-facing
    vocabulary and explicitly **not** for "any behaviour — it has no function with a side
    effect".

    Asserted mechanically at module scope, where an effect would actually happen on
    import. What a `Protocol` method body says is a different question and the Port
    contract's, not this gate's.
    """
    dist = sources.distribution("omniweave-ports")
    offences: list[str] = []
    for root in dist.import_roots:
        for path in sources.files(dist.src / root):
            offences.extend(_module_scope_offences(path))
    assert offences == [], "omniweave_ports executes at import time:\n" + "\n".join(offences)


def test_importing_ports_opens_no_file_starts_no_thread_and_makes_no_connection(
    interpreter: Interpreter,
) -> None:
    """The runtime half of "no behaviour", observed with `sys.addaudithook`.

    The hook is armed immediately before the import and disarmed immediately after, so
    interpreter startup is outside the window. Reading its own `.py`/`.pyc` is what
    importing *is*; opening anything else is the module reading data at import time.
    """
    report = interpreter.audit("import omniweave_ports")
    assert report.non_python_files == (), f"opened {report.non_python_files}"
    assert report.sockets == 0
    assert report.subprocesses == 0
    assert report.threads_started == 0


def test_importing_core_opens_no_file_starts_no_thread_and_makes_no_connection(
    interpreter: Interpreter,
) -> None:
    """The same for core, which is INV-3's other half.

    A module that reads a config file, a lock file or `first_party.toml` at import time
    pays for it on every `ow hook prompt`, and `omniweave_core.drivers`' generated
    package data is exactly the file most likely to be read one refactor too early
    (11-repo-layout.md section 7.2).
    """
    report = interpreter.audit("import omniweave_core")
    assert report.non_python_files == (), f"opened {report.non_python_files}"
    assert report.sockets == 0
    assert report.subprocesses == 0
    assert report.threads_started == 0


def test_the_audit_instrument_sees_a_side_effect_when_there_is_one(
    interpreter: Interpreter, tmp_path: Path
) -> None:
    """The negative control for the two audit assertions above."""
    target = tmp_path / "witness.txt"
    target.write_text("x", encoding="utf-8")
    report = interpreter.audit(f"open({str(target)!r}, encoding='utf-8').close()")
    assert report.non_python_files != ()


# ---------------------------------------------------------------------------
# The T1 purity guard the conftest offers
# ---------------------------------------------------------------------------


def test_the_t1_purity_guard_turns_each_side_effect_into_a_failure(
    pure_unit: None, tmp_path: Path
) -> None:
    """`pure_unit` is 13-quality.md section 2.7's row 1 fixture, exercised.

    "an autouse fixture patches `socket.socket`, `subprocess.Popen`, `time.time` and
    `open` outside `tmp_path` to raise". A fixture nothing runs is a fixture that has
    never been shown to raise, so this is the test that makes it real; the reason it is
    opt-in rather than autouse is in its own docstring.
    """
    assert pure_unit is None
    inside = tmp_path / "allowed.txt"
    with open(inside, "w", encoding="utf-8") as handle:  # noqa: PTH123 — the patched builtin
        handle.write("a store under tmp_path is the one file a T1 test may open")
    for effect in (
        lambda: open(__file__, encoding="utf-8"),  # noqa: PTH123 — the patched builtin
        lambda: socket.socket(),
        lambda: subprocess.Popen(["true"]),  # noqa: S607
        lambda: subprocess.run(["true"], check=False),  # noqa: S607
        time.time,
    ):
        with pytest.raises(AssertionError, match=r"13-quality.md"):
            effect()
