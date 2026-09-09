"""The four structural gates, tested as programs rather than trusted as scripts.

`tools/gate_layers.py` (G4), `tools/gate_core_pure.py` (G1), `tools/gate_importtime.py` (G9 + G23)
and `tools/gate_lazy_core.py` (G17) are the CI half of four properties the test tree already
asserts from the other side — `tests/test_layers.py`, `tests/test_purity.py` and
`tests/test_g17.py`. Two halves of one property is two chances to be subtly different, and the
difference that matters is invisible from either side alone, so this file is where they are made to
meet.

Three kinds of test, and the second is the one that earns the file:

* **the gates are green on HEAD** — each `main()` returns 0 here, which is the same statement
  P1's exit criteria makes at the shell;
* **each gate goes red when it is shown the violation it exists for**, over synthetic trees built
  in `tmp_path`. A gate that has never been shown a red is a gate nobody has tested, and the two
  worked violations 02-architecture.md section 3.3 prints are reproduced literally;
* **the gates agree with the plan and with each other where they must, and differ where the plan
  says they must.** G4 counts a `TYPE_CHECKING` import because a layer violation is a fact about
  the source; G17 excludes one because it is a statement about the runtime. That single deliberate
  disagreement is asserted directly, because it is the kind of thing a later refactor "fixes".

The gates are loaded by file path with `importlib.util`, never by `importlib.import_module` — the
API `tools/semgrep/omniweave.yaml` bans outside `host/` — and never by putting `tools/` on
`sys.path`, which would make the name `gate_layers` importable from anywhere for the rest of the
session.

Specified in 02-architecture.md section 3.3 and 16-roadmap.md section 4 (W1.7 G4, W1.9 G1/G9/G17/
G23).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
import textwrap
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import omniweave_core
import pytest

if TYPE_CHECKING:
    from conftest import SourceIndex

GATES: tuple[str, ...] = ("gate_core_pure", "gate_importtime", "gate_layers", "gate_lazy_core")
"""The four scripts this file owns, as `tools/<name>.py`."""


def _load(repo_root: Path, name: str) -> ModuleType:
    """Load `tools/<name>.py` under a private name, without putting `tools/` on `sys.path`.

    A gate script is a program, and importing one is the only way to test its parts rather than
    only its exit code. `spec_from_file_location` reaches the file directly, so the bare name
    `gate_layers` never becomes importable for the rest of the session.

    The module **is** registered in `sys.modules` under `_owgate_<name>`, and it has to be:
    `@dataclass(frozen=True, slots=True)` re-creates the class to add `__slots__`, and resolving
    the `from __future__ import annotations` string annotations on the way through goes via
    `sys.modules[cls.__module__]`. An unregistered module makes that lookup `None` and every gate
    that declares a value type fails to import at all.
    """
    path = repo_root / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_owgate_{name}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def gates(repo_root: Path) -> dict[str, ModuleType]:
    """The four gate scripts, loaded once."""
    return {name: _load(repo_root, name) for name in GATES}


# ---------------------------------------------------------------------------
# What a gate script may be made of
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", GATES)
def test_a_gate_script_imports_nothing_first_party(repo_root: Path, name: str) -> None:
    """The property that lets G4 and G1 run on a tree whose dependencies are not installed.

    02-architecture.md section 3.3's "Extends the charter" note: the graph is built with the stdlib
    `ast` module, "walking source rather than importing it — which also means the gate runs on a
    package whose dependencies are not installed". A gate that imported `omniweave_core` to inspect
    it would fail on exactly the broken tree it exists to diagnose, and G17's and G9's answers
    would be about this process rather than about a bare interpreter.
    """
    tree = ast.parse((repo_root / "tools" / f"{name}.py").read_text(encoding="utf-8"))
    named: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            named.append(node.module or "")
    first_party = [
        module
        for module in named
        if module.split(".", 1)[0] == "omniweave" or module.startswith("omniweave_")
    ]
    assert first_party == [], f"tools/{name}.py imports {first_party}"


@pytest.mark.parametrize("name", GATES)
def test_a_gate_script_imports_only_the_standard_library(repo_root: Path, name: str) -> None:
    """Stdlib only, so the gate needs nothing installed but an interpreter.

    Introducing a dependency here would put a package's own import graph between HEAD and the gate
    that proves HEAD's import graph, which is the reason charter D1's dev group contains no
    `import-linter` and no `grimp` (02-architecture.md section 3.3).
    """
    tree = ast.parse((repo_root / "tools" / f"{name}.py").read_text(encoding="utf-8"))
    stdlib = frozenset(sys.stdlib_module_names) | {"__future__"}
    outside: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            outside.extend(
                alias.name for alias in node.names if alias.name.split(".", 1)[0] not in stdlib
            )
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            root = (node.module or "").split(".", 1)[0]
            if root and root not in stdlib:
                outside.append(node.module or "")
    assert outside == [], f"tools/{name}.py imports {outside}"


@pytest.mark.parametrize("name", GATES)
def test_a_gate_script_names_its_gate_and_a_plan_locus(
    gates: dict[str, ModuleType], name: str
) -> None:
    """House style, and it is load-bearing for a gate: a failure has to be actionable.

    The module docstring states which gate it is, what it reads, what it asserts and where the plan
    fixes it. Without the locus, a red gate is an argument; with it, it is a citation.
    """
    doc = gates[name].__doc__ or ""
    assert "02-architecture.md section 3.3" in doc, f"tools/{name}.py cites no mechanism table row"
    identifiers = {
        "gate_layers": "G4",
        "gate_core_pure": "G1",
        "gate_importtime": "G9",
        "gate_lazy_core": "G17",
    }
    assert identifiers[name] in doc.splitlines()[0], f"tools/{name}.py does not name its gate"


@pytest.mark.parametrize("name", GATES)
def test_a_gate_refuses_arguments_rather_than_ignoring_them(
    gates: dict[str, ModuleType], name: str
) -> None:
    """Exit 2 on an argument, so a mistyped invocation is never a silent green.

    Distinguished from exit 1: 1 is "the property is false", 2 is "the gate did not run". CI treats
    both as failure and a human needs to know which.
    """
    assert gates[name].main(["--all"]) == 2


# ---------------------------------------------------------------------------
# The gates are green on HEAD
# ---------------------------------------------------------------------------


def test_gate_layers_is_green(gates: dict[str, ModuleType]) -> None:
    """`uv run tools/gate_layers.py`, P1's exit criteria line for G4."""
    assert gates["gate_layers"].main([]) == 0


def test_gate_core_pure_is_green(gates: dict[str, ModuleType]) -> None:
    """`uv run tools/gate_core_pure.py`, P1's exit criteria line for G1.

    It shells out to `uv export --locked`, so a stale `uv.lock` fails here as a resolve failure
    rather than as a purity failure — which is the honest reading of a lock that no longer matches
    the declarations it was made from.
    """
    assert gates["gate_core_pure"].main([]) == 0


def test_gate_importtime_is_green(gates: dict[str, ModuleType]) -> None:
    """G9 + G23. Spawns fresh interpreters, which is the only witness for a cold import."""
    assert gates["gate_importtime"].main([]) == 0


def test_gate_lazy_core_is_green(gates: dict[str, ModuleType]) -> None:
    """G17, all four clauses, including the negative control and "deferred, not absent"."""
    assert gates["gate_lazy_core"].main([]) == 0


# ---------------------------------------------------------------------------
# G4 — the layer gate
# ---------------------------------------------------------------------------


def _workspace(
    module: ModuleType, tmp_path: Path, rows: dict[str, list[str]], trees: dict[str, dict[str, str]]
) -> object:
    """A synthetic workspace: `tools/layers.toml` plus `packages/<dist>/src/<root>/<file>`.

    Built rather than mutated-in-place because a gate that can only be tested by breaking the
    repository is a gate that gets tested once.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'synthetic'\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "tools").mkdir(exist_ok=True)
    (tmp_path / "tools" / "layers.toml").write_text(
        "\n".join(f"{key} = {value!r}".replace("'", '"') for key, value in rows.items()) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    for dist, files in trees.items():
        directory = tmp_path / "packages" / dist
        (directory / "src").mkdir(parents=True, exist_ok=True)
        pyproject = files.pop("pyproject.toml", f'[project]\nname = "{dist}"\n')
        (directory / "pyproject.toml").write_text(pyproject, encoding="utf-8", newline="\n")
        for relative, source in files.items():
            target = directory / "src" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(textwrap.dedent(source), encoding="utf-8", newline="\n")
    return module.Workspace(root=tmp_path.resolve())


def _walk(module: ModuleType, workspace: object) -> list[object]:
    """`main()`'s loop, without `main()`: every layer and relative-import finding."""
    rows = workspace.layers()
    findings: list[object] = []
    for dist in workspace.distributions():
        allowed = frozenset(rows.get(dist.layer_key, ())) | frozenset(dist.import_roots)
        findings.extend(module.find_layer_violations(dist, allowed, workspace))
        findings.extend(module.find_relative_imports(dist, workspace))
    return findings


def test_g4_reproduces_the_plans_two_worked_violations(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """02-architecture.md section 3.3's own worked output, both rows.

    `import omniweave_core.model` under `omniweave-pdf` — a parse driver emits
    `owdoc-fragment/1`, never constructs a `Block` and never holds a `DocSink`. `from
    omniweave.run.supervisor import run` under `omniweave-serve` — which may not import
    `omniweave` and never runs the Supervisor.
    """
    module = gates["gate_layers"]
    workspace = _workspace(
        module,
        tmp_path,
        {
            "omniweave_pdf": ["omniweave_ports"],
            "omniweave_serve": ["omniweave_core", "omniweave_ports"],
            "omniweave_core": ["omniweave_ports"],
            "omniweave_ports": [],
            "omniweave": ["omniweave_core", "omniweave_ports"],
        },
        {
            "omniweave-pdf": {
                "omniweave_pdf/__init__.py": "",
                "omniweave_pdf/driver.py": "import omniweave_ports\nimport omniweave_core.model\n",
            },
            "omniweave-serve": {
                "omniweave_serve/__init__.py": "",
                "omniweave_serve/query.py": "from omniweave.run.supervisor import run\n",
            },
        },
    )
    findings = _walk(module, workspace)
    blocks = [finding.block() for finding in findings]
    assert len(findings) == 2, blocks

    pdf = next(block for block in blocks if "omniweave_pdf/driver.py" in block)
    assert "import omniweave_core.model" in pdf
    assert "driver.py:2" in pdf
    assert "['omniweave_ports']" in pdf

    serve = next(block for block in blocks if "omniweave_serve/query.py" in block)
    assert "from omniweave.run.supervisor import run" in serve
    assert "query.py:1" in serve
    assert "['omniweave_core', 'omniweave_ports']" in serve


def test_g4_sees_an_import_at_every_scope_including_type_checking(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """ "module, class **and function** scope, `TYPE_CHECKING` blocks included".

    Each of the four is a real hiding place. `TYPE_CHECKING` is the subtle one: it never executes,
    so a runtime instrument cannot see it — and a driver that names a framework type there has
    still made its distribution depend on the framework's shape.
    """
    module = gates["gate_layers"]
    workspace = _workspace(
        module,
        tmp_path,
        {"omniweave_pdf": ["omniweave_ports"], "omniweave_core": [], "omniweave_ports": []},
        {
            "omniweave-pdf": {
                "omniweave_pdf/__init__.py": "",
                "omniweave_pdf/hiding.py": """\
                    from typing import TYPE_CHECKING

                    import omniweave_core.model

                    if TYPE_CHECKING:
                        from omniweave_core.out import Plan


                    class Parser:
                        import omniweave_core.store

                        def run(self) -> None:
                            import omniweave_core.retrieve
                    """,
            }
        },
    )
    findings = _walk(module, workspace)
    lines = sorted(int(finding.where.rsplit(":", 1)[1]) for finding in findings)
    assert lines == [3, 6, 10, 13], [finding.block() for finding in findings]


def test_g4_ignores_a_third_party_import_because_purity_is_g1s(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """The layer gate maps first-party roots and stops. Overlap between gates hides a hole.

    A `numpy` import under `omniweave-pdf` is correct — a driver distribution is where a
    third-party dependency belongs — so a layer gate that flagged it would be wrong, not strict.
    """
    module = gates["gate_layers"]
    workspace = _workspace(
        module,
        tmp_path,
        {"omniweave_pdf": ["omniweave_ports"], "omniweave_ports": []},
        {
            "omniweave-pdf": {
                "omniweave_pdf/__init__.py": "",
                "omniweave_pdf/d.py": "import numpy\nimport pypdfium2\nimport omniweave_ports\n",
            }
        },
    )
    assert _walk(module, workspace) == []


def test_g4_flags_a_relative_import_because_it_carries_no_root_to_map(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """`from . import store` is invisible to the walk, so it is a hole rather than a style choice.

    11-repo-layout.md section 8.1: `ban-relative-imports` "is what makes `tools/gate_layers.py`'s
    `ast` walk able to map every import to a first-party root without resolving anything".
    """
    module = gates["gate_layers"]
    workspace = _workspace(
        module,
        tmp_path,
        {"omniweave_core": ["omniweave_ports"], "omniweave_ports": []},
        {
            "omniweave-core": {
                "omniweave_core/__init__.py": "",
                "omniweave_core/a.py": "from . import store\nfrom .out import Plan\n",
            }
        },
    )
    findings = _walk(module, workspace)
    assert len(findings) == 2, [finding.block() for finding in findings]
    assert all("relative import" in finding.why for finding in findings)


def test_g4_allows_the_nine_function_scope_self_imports_core_actually_ships(
    gates: dict[str, ModuleType], repo_root: Path
) -> None:
    """`omniweave_core/__init__.py`'s `__getattr__` is the repo's own function-scope test case.

    It resolves the nine lazy subpackages with nine literal `import omniweave_core.<name> as
    module` statements rather than one `importlib.import_module(f"omniweave_core.{name}")`, because
    that API is banned outside `host/`. The walk must **see** all nine — a module-scope-only walk
    would see none — and must **allow** all nine, because a package may always import itself.
    """
    module = gates["gate_layers"]
    path = repo_root / "packages" / "omniweave-core" / "src" / "omniweave_core" / "__init__.py"
    sites = module.import_sites(path)
    lazy_self_imports = [
        site
        for site in sites
        if site.module.startswith("omniweave_core.")
        and site.module.split(".")[1] in omniweave_core.LAZY
    ]
    assert len(lazy_self_imports) == len(omniweave_core.LAZY) == 9, [
        site.statement for site in sites
    ]

    workspace = module.Workspace(root=repo_root)
    dist = next(d for d in workspace.distributions() if d.name == "omniweave-core")
    allowed = frozenset(workspace.layers()["omniweave_core"]) | frozenset(dist.import_roots)
    assert module.find_layer_violations(dist, allowed, workspace) == []


def test_g4_derives_rows_3_and_4_from_the_ports_a_distribution_declares(
    gates: dict[str, ModuleType],
) -> None:
    """The derivation itself, against the two shapes the plan already fixes.

    `omniweave-pdf` is 11-repo-layout.md section 1.5's worked non-`compile` shape and
    `omniweave-target-pptx` is 02-architecture.md section 3.2's worked `compile` one.
    """
    module = gates["gate_layers"]
    assert module.row_for_ports(frozenset({"parse"})) == module.ROW_FOR_EVERYTHING_ELSE
    assert module.row_for_ports(frozenset({"acquire", "derive", "embed"})) == (
        module.ROW_FOR_EVERYTHING_ELSE
    )
    assert module.row_for_ports(frozenset({"compile"})) == module.ROW_FOR_COMPILE
    assert module.row_for_ports(frozenset({"parse", "compile"})) == module.ROW_FOR_COMPILE
    assert module.ROW_FOR_EVERYTHING_ELSE == ("omniweave_ports",)
    assert module.ROW_FOR_COMPILE == ("omniweave_core", "omniweave_ports")


def _driver_distribution(driver_id: str, port: str, row: list[str]) -> dict[str, object]:
    """A synthetic driver distribution: an entry point, a package and a card."""
    return {
        "rows": {
            "omniweave_pdf": row,
            "omniweave_core": ["omniweave_ports"],
            "omniweave_ports": [],
        },
        "tree": {
            "omniweave-pdf": {
                "pyproject.toml": (
                    "[project]\n"
                    'name = "omniweave-pdf"\n'
                    '[project.entry-points."omniweave.drivers"]\n'
                    f'"{driver_id}" = "omniweave_pdf"\n'
                ),
                "omniweave_pdf/__init__.py": "",
                "omniweave_pdf/driver.toml": f'[driver]\nid = "{driver_id}"\nport = "{port}"\n',
            }
        },
    }


def test_g4_re_derivation_accepts_a_row_that_matches_the_card(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """The happy path of clause 4, and the proof the re-derivation is not vacuously green.

    On HEAD the count of re-derived rows is 0 — no distribution declares a driver entry point until
    P3 W3.1-W3.6 — so without this test the clause would be untested code until then.
    """
    module = gates["gate_layers"]
    shape = _driver_distribution("parse.pdf.pdfium", "parse/1", ["omniweave_ports"])
    workspace = _workspace(module, tmp_path, shape["rows"], shape["tree"])
    findings, derived = module.check_entry_points(workspace)
    assert findings == []
    assert derived == 1


def test_g4_refuses_a_parse_driver_that_widened_its_own_row(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """ "NO AUTHOR PICKS THEIR OWN ROW", stated as the failure it exists to produce.

    "Adding `omniweave_core` to such a row fails the gate" (02-architecture.md section 3.2 rule 3).
    A driver cannot pin the framework, and a widened row is exactly how it would.
    """
    module = gates["gate_layers"]
    shape = _driver_distribution(
        "parse.pdf.pdfium", "parse/1", ["omniweave_core", "omniweave_ports"]
    )
    workspace = _workspace(module, tmp_path, shape["rows"], shape["tree"])
    findings, derived = module.check_entry_points(workspace)
    assert derived == 1
    assert len(findings) == 1, [finding.block() for finding in findings]
    block = findings[0].block()
    assert "rule 3" in block
    assert "['omniweave_ports']" in block
    assert "No author picks their own row" in block


def test_g4_requires_a_compile_driver_to_carry_the_out_framework_row(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """Rule 4 in the other direction: a `compile` driver narrowed to rule 3's row fails too.

    `CompileV1` lives in `omniweave_core.out`, so a target that could not import it would not
    build. The gate is an equality, not a ceiling.
    """
    module = gates["gate_layers"]
    shape = _driver_distribution("compile.pptx.oxml", "compile/1", ["omniweave_ports"])
    workspace = _workspace(module, tmp_path, shape["rows"], shape["tree"])
    findings, _ = module.check_entry_points(workspace)
    assert len(findings) == 1, [finding.block() for finding in findings]
    assert "rule 4" in findings[0].block()
    assert "['omniweave_core', 'omniweave_ports']" in findings[0].block()


def test_g4_finds_a_card_whose_port_contradicts_its_entry_point_key(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """The finding `tests/test_layers.py` explicitly assigns to this gate.

    That file derives the Port from the entry-point key alone and says so: "a card whose `port`
    contradicts its entry-point key is that gate's finding, not this one's". The row would
    otherwise be derived from a coin toss.
    """
    module = gates["gate_layers"]
    shape = _driver_distribution("parse.pdf.pdfium", "compile/1", ["omniweave_ports"])
    workspace = _workspace(module, tmp_path, shape["rows"], shape["tree"])
    findings, _ = module.check_entry_points(workspace)
    assert any("cannot disagree" in finding.why for finding in findings), [
        finding.block() for finding in findings
    ]


def test_g4_reads_the_card_with_tomllib_and_never_by_importing_it(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """INV-4: a card is data. The gate must derive a row from a package that cannot be imported.

    The synthetic package's `__init__.py` raises `SystemExit` at module scope — the rogue-driver
    shape P1's demo installs — so an implementation that imported to read `port` would take the
    process down instead of reporting a row.
    """
    module = gates["gate_layers"]
    shape = _driver_distribution("parse.pdf.pdfium", "parse/1", ["omniweave_ports"])
    shape["tree"]["omniweave-pdf"]["omniweave_pdf/__init__.py"] = (
        "import sys\nsys.exit('a rogue driver body')\n"
    )
    workspace = _workspace(module, tmp_path, shape["rows"], shape["tree"])
    findings, derived = module.check_entry_points(workspace)
    assert (findings, derived) == ([], 1)


@pytest.mark.parametrize(
    "value",
    ["omniweave_pdf.driver:PdfParser", "omniweave_pdf/driver", "Omniweave_Pdf", "1pdf"],
)
def test_g4_rejects_an_entry_point_value_that_is_not_a_dotted_package(
    gates: dict[str, ModuleType], tmp_path: Path, value: str
) -> None:
    """11-repo-layout.md section 1.5's shape check, and why this gate owns it.

    hatchling writes `entry_points.txt` from the table "without validating the value's shape at
    all", so a malformed first-party value ships and fails on a user's machine as a discovery-time
    refusal. `module:attr` is the near-miss that matters: it is the grammar of the card's own
    `entrypoint` key, the one place a colon is legal.
    """
    module = gates["gate_layers"]
    tree = {
        "omniweave-pdf": {
            "pyproject.toml": (
                "[project]\n"
                'name = "omniweave-pdf"\n'
                '[project.entry-points."omniweave.drivers"]\n'
                f'"parse.pdf.pdfium" = "{value}"\n'
            ),
            "omniweave_pdf/__init__.py": "",
            "omniweave_pdf/driver.toml": '[driver]\nport = "parse/1"\n',
        }
    }
    workspace = _workspace(
        module, tmp_path, {"omniweave_pdf": ["omniweave_ports"], "omniweave_ports": []}, tree
    )
    findings, _ = module.check_entry_points(workspace)
    assert any("entry-point value" in finding.why for finding in findings), [
        finding.block() for finding in findings
    ]


def test_g4_validates_its_own_input_before_it_trusts_it(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """A member with no row is a tree the walk silently skips, which is a green by accident.

    The only failure mode a structural gate has is passing for the wrong reason, so the rows are
    checked against the workspace membership before a single import is mapped.
    """
    module = gates["gate_layers"]
    workspace = _workspace(
        module,
        tmp_path,
        {"omniweave_ports": [], "omniweave_ghost": ["omniweave_ports"]},
        {"omniweave-pdf": {"omniweave_pdf/__init__.py": ""}, "omniweave-ports": {}},
    )
    reasons = [finding.why for finding in module.check_layers_declaration(workspace)]
    assert any("workspace member with no row" in reason for reason in reasons), reasons
    assert any("names no workspace member" in reason for reason in reasons), reasons


def test_g4_holds_rows_1_and_2_as_the_charter_rather_than_a_derivation(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """Rules 1 and 2 are not derived from anything — they are the charter.

    They are the two rows P1 freezes (16-roadmap.md section 4, "Frozen at the end of P1"); the
    other twelve come from entry points that do not exist yet.
    """
    module = gates["gate_layers"]
    workspace = _workspace(
        module,
        tmp_path,
        {"omniweave_ports": ["omniweave_core"], "omniweave_core": []},
        {"omniweave-ports": {}, "omniweave-core": {}},
    )
    reasons = [finding.why for finding in module.check_layers_declaration(workspace)]
    assert any("rule 1 fixes this row at []" in reason for reason in reasons), reasons
    assert any("rule 2 fixes this row at ['omniweave_ports']" in reason for reason in reasons)


def test_g4_agrees_with_the_layers_toml_the_repository_ships(
    gates: dict[str, ModuleType], sources: SourceIndex, repo_root: Path
) -> None:
    """The gate and `tests/test_layers.py` read the same fourteen rows the same way.

    Two readers of one declaration is one chance for them to disagree about it; this is where that
    would surface, rather than as a green gate beside a red test.
    """
    workspace = gates["gate_layers"].Workspace(root=repo_root)
    assert workspace.layers() == sources.layers()
    assert len(workspace.layers()) == 14


# ---------------------------------------------------------------------------
# G1 — the purity gate
# ---------------------------------------------------------------------------


def test_g1_parses_the_shape_uv_export_actually_writes(gates: dict[str, ModuleType]) -> None:
    """`-e ./packages/<name>` for a workspace member, PEP 508 for everything else.

    The `# via` provenance is indented under each requirement and must not be read as a
    distribution; a parser that took every non-blank line would classify `# via omniweave-core` as
    a third-party dependency named `#`.
    """
    module = gates["gate_core_pure"]
    exported = (
        "# This file was autogenerated by uv\n"
        "-e ./packages/omniweave-core\n"
        "-e ./packages/omniweave-ports\n"
        "    # via omniweave-core\n"
        "pydantic==2.9.2\n"
        "    # via omniweave-core\n"
        "torch==2.4.0 ; sys_platform == 'linux'\n"
    )
    assert module.parse_requirements(exported) == (
        "omniweave-core",
        "omniweave-ports",
        "pydantic",
        "torch",
    )


def test_g1_declared_closure_refuses_a_third_party_dependency(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """INV-2's negative evidence, in miniature.

    `torch` and `torchvision` are **base** requirements of docling, so its DOCX reader costs
    ~2.5-3.5 GB installed with CUDA wheels. One line in one `pyproject.toml` is all that costs.
    """
    module = gates["gate_core_pure"]
    for name, dependencies in (
        ("omniweave-core", '["omniweave-ports >=1,<2", "torch>=2.4"]'),
        ("omniweave-ports", "[]"),
    ):
        directory = tmp_path / "packages" / name
        directory.mkdir(parents=True)
        (directory / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\ndependencies = {dependencies}\n',
            encoding="utf-8",
            newline="\n",
        )
    findings = module.check_declared_closure(tmp_path)
    assert any("torch" in finding.subject for finding in findings), [
        finding.block() for finding in findings
    ]
    assert any("Amending this amends the CHARTER" in finding.why for finding in findings)


def test_g1_declared_closure_refuses_a_dependency_ports_grew(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """The shape a closure catches and a single `dependencies` read does not.

    Core stays clean, `omniweave-ports` grows one dependency, and every consumer of core inherits
    it — which is why rule 1 is "`omniweave-ports` depends on nothing" rather than "on nothing
    third-party".
    """
    module = gates["gate_core_pure"]
    for name, dependencies in (
        ("omniweave-core", '["omniweave-ports >=1,<2"]'),
        ("omniweave-ports", '["attrs>=24"]'),
    ):
        directory = tmp_path / "packages" / name
        directory.mkdir(parents=True)
        (directory / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\ndependencies = {dependencies}\n',
            encoding="utf-8",
            newline="\n",
        )
    findings = module.check_declared_closure(tmp_path)
    assert any("rule 1" in finding.why for finding in findings), [
        finding.block() for finding in findings
    ]


def test_g1_source_walk_sees_the_import_inv_2_names(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """The instrument neither the declarations nor the resolve can have: an *undeclared* import.

    INV-2's violation example is "a `from pydantic import` inside `omniweave_core/model/`", and
    that line is a defect the moment it is written, whether or not pydantic is in the venv.
    """
    module = gates["gate_core_pure"]
    src = tmp_path / "omniweave_core" / "model"
    src.mkdir(parents=True)
    (src / "block.py").write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "import omniweave_ports\n"
        "from pydantic import BaseModel\n"
        "import numpy as np\n"
        "from . import sibling\n",
        encoding="utf-8",
        newline="\n",
    )
    offences = module.third_party_imports(tmp_path)
    assert [name for _, _, name in offences] == ["pydantic", "numpy"], offences
    assert [line for _, line, _ in offences] == [4, 5]


def test_g1_extras_are_a_remedy_and_never_a_capability(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """ "No other core extra may exist, because an extra that adds a capability makes INV-2
    conditional" (11-repo-layout.md section 2.1)."""
    module = gates["gate_core_pure"]
    directory = tmp_path / "packages" / "omniweave-core"
    directory.mkdir(parents=True)
    (directory / "pyproject.toml").write_text(
        '[project]\nname = "omniweave-core"\n'
        "[project.optional-dependencies]\n"
        'sqlite = ["pysqlite3-binary>=0.5"]\n'
        'vision = ["torch>=2.4"]\n',
        encoding="utf-8",
        newline="\n",
    )
    findings = module.check_extras(tmp_path)
    assert len(findings) == 1, [finding.block() for finding in findings]
    assert "capability REMEDY rather than a capability" in findings[0].why


def test_g1_and_the_purity_test_agree_on_what_core_may_declare(
    gates: dict[str, ModuleType], repo_root: Path
) -> None:
    """The gate's own reading of HEAD, with the two halves of G1 checked separately.

    `tests/test_purity.py` asserts the declared closure; this asserts that the gate reading it
    agrees, so a change to one instrument cannot pass while the other fails.
    """
    module = gates["gate_core_pure"]
    assert module.check_declared_closure(repo_root) == []
    assert module.check_extras(repo_root) == []
    assert module.check_source_imports(repo_root) == []
    assert module.EXPECTED_CLOSURE == ("omniweave-core", "omniweave-ports")
    assert module.PERMITTED_EXTRAS == ("sqlite",)


# ---------------------------------------------------------------------------
# G9 / G23 — the import trace
# ---------------------------------------------------------------------------


def test_g9_classifier_keeps_stdlib_and_first_party_and_nothing_else(
    gates: dict[str, ModuleType],
) -> None:
    """The classifier, over the four cases a trace actually contains.

    `sys.stdlib_module_names` is the membership test rather than a hand list precisely because it
    is frozen per version and already includes the private accelerators.
    """
    module = gates["gate_importtime"]
    trace = frozenset(
        {
            "json",
            "json.decoder",
            "zipfile",
            "omniweave_core",
            "omniweave_core.canonical",
            "omniweave_ports",
            "_virtualenv",
            "pydantic",
            "torch.nn",
        }
    )
    assert module.third_party(trace) == ("pydantic", "torch.nn")


def test_g9_names_asyncio_and_selectors_explicitly_because_they_are_stdlib(
    gates: dict[str, ModuleType],
) -> None:
    """G23's two names would pass the third-party check, which is the whole reason G23 exists.

    The single event loop in the framework lives in `omniweave/run/`, in the CLI distribution, so
    core pays no loop-import tax (INV-3).
    """
    module = gates["gate_importtime"]
    assert module.FORBIDDEN_EAGER_MODULES == ("asyncio", "selectors")
    assert module.third_party(frozenset(module.FORBIDDEN_EAGER_MODULES)) == ()


def test_g9_instrument_sees_a_third_party_module_when_shown_one(
    gates: dict[str, ModuleType],
) -> None:
    """The gate's own negative control, run as a test.

    It synthesises a module into `tmp_path` rather than importing one from the dev group, because
    the environment G9 is designed for is the one with nothing installed — and a control that
    needs a dependency cannot run there.
    """
    module = gates["gate_importtime"]
    interpreter = module.Interpreter(executable=sys.executable)
    assert module.check_negative_control(interpreter) == []


def test_g9_covers_ports_as_well_as_core(gates: dict[str, ModuleType]) -> None:
    """`omniweave_ports` is stdlib-only by row as well as by declaration.

    Which is exactly why leaving it unchecked would be the cheap place for a third-party import to
    appear: it is the distribution nobody looks at.
    """
    assert gates["gate_importtime"].SUBJECTS == ("omniweave_core", "omniweave_ports")


# ---------------------------------------------------------------------------
# G17 — the lazy-core gate
# ---------------------------------------------------------------------------


def test_g17_gates_the_same_nine_the_package_itself_declares(gates: dict[str, ModuleType]) -> None:
    """The gate's tuple against `omniweave_core.LAZY`, which is `__init__.__all__`.

    `tests/test_g17.py` checks the nine against the six plan documents that print the braced set;
    this checks them against the code they gate. A rename that updated the module and not the gate
    would pass that test and fail here.
    """
    module = gates["gate_lazy_core"]
    assert module.LAZY == (
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
    assert len(module.LAZY) == len(set(module.LAZY)) == 9
    assert frozenset(module.LAZY) == omniweave_core.LAZY
    assert sorted(module.LAZY) == sorted(omniweave_core.__all__)
    assert "drivers" not in module.LAZY


def test_g17_static_walk_finds_the_violation_inv_3_names(
    gates: dict[str, ModuleType],
) -> None:
    """ "a module-level `from .store import Store` added to make a type annotation resolve at
    runtime instead of under `TYPE_CHECKING`" — INV-3's own words, spelled absolutely.

    Both spellings are covered: `from omniweave_core.store import Store` and the near-miss
    `from omniweave_core import store`, which names the same module and which a check that looked
    only at `node.module` would miss.
    """
    module = gates["gate_lazy_core"]
    tree = ast.parse(
        textwrap.dedent("""\
            from omniweave_core.store import Store
            from omniweave_core import store, canonical
            import omniweave_core.out
            import json
            """)
    )
    named = [
        name
        for node in module.module_scope_runtime_imports(tree)
        for name in module._named_modules(node)
    ]
    forbidden = {f"omniweave_core.{name}" for name in module.LAZY}
    assert sorted(set(named) & forbidden) == [
        "omniweave_core.out",
        "omniweave_core.store",
    ]


def test_g17_excludes_type_checking_and_function_scope_where_g4_does_not(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """The one place the two gates must disagree, asserted so a refactor cannot "fix" it.

    G4 counts a `TYPE_CHECKING` import because a layer violation is a fact about the source. G17
    excludes it because the block never executes, so it costs the 250 ms hook path nothing — and
    excludes a function-scope import because deferring is the *fix* for a G17 violation, not an
    instance of one. `omniweave_core/__init__.py`'s `__getattr__` is nine deferred imports of the
    nine lazy names, and a G17 that flagged them would flag the mechanism that makes it pass.
    """
    lazy, layers = gates["gate_lazy_core"], gates["gate_layers"]
    source = textwrap.dedent("""\
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from omniweave_core.store import Store


        def load() -> None:
            import omniweave_core.model
        """)

    tree = ast.parse(source)
    named = [
        name
        for node in lazy.module_scope_runtime_imports(tree)
        for name in lazy._named_modules(node)
    ]
    assert not [name for name in named if name.startswith("omniweave_core.")], named

    path = tmp_path / "eager.py"
    path.write_text(source, encoding="utf-8", newline="\n")
    seen = sorted(
        site.module for site in layers.import_sites(path) if site.module.startswith("omniweave_")
    )
    assert seen == ["omniweave_core.model", "omniweave_core.store"]


def test_g17_instrument_sees_a_lazy_name_when_it_really_is_imported(
    gates: dict[str, ModuleType],
) -> None:
    """The gate's negative control, run as a test. A `sys.modules` assertion that can only pass is
    not a gate.

    `store` is the name used because it is the largest of the nine and the only site that may call
    `sqlite3.connect` (INV-17), so if any name is going to arrive through a convenience re-export
    it is this one.
    """
    module = gates["gate_lazy_core"]
    interpreter = module.Interpreter(executable=sys.executable)
    assert module.check_negative_control(interpreter) == []


def test_g17_requires_the_nine_to_be_deferred_rather_than_absent(
    gates: dict[str, ModuleType], repo_root: Path
) -> None:
    """Clause 4, and the reason G17 is not satisfiable by deletion.

    A lazy name that is *absent* rather than deferred passes the absence assertion and breaks every
    caller, so the gate asserts both halves. Asserted over the homes on disk because
    `modelserver.py` lands at P4 W4.9; `toolchain.py` landed with W1.6, so eight of the
    nine have a home on disk and only `modelserver` is still absent.
    """
    module = gates["gate_lazy_core"]
    src = module.core_src(repo_root)
    homes = tuple(
        name for name in module.LAZY if (src / name).is_dir() or (src / f"{name}.py").is_file()
    )
    assert homes == (
        "model",
        "store",
        "archive",
        "retrieve",
        "answer",
        "out",
        "host",
        "toolchain",
    ), homes
    interpreter = module.Interpreter(executable=sys.executable)
    assert module.check_reachable(repo_root, interpreter) == []


# ---------------------------------------------------------------------------
# The red path of the two runtime gates, without breaking the repository
# ---------------------------------------------------------------------------


class _StubInterpreter:
    """An `Interpreter` that reports what it is told to report.

    G17 and G9 read a fresh interpreter, so their red path cannot be reached from a green tree
    without editing the tree — and a gate whose failure branch is only exercised by a broken
    checkout is a failure branch nobody has read. The instrument is the seam, so the instrument is
    what is replaced; the classification logic under test is untouched.
    """

    def __init__(self, loaded: set[str], executed: set[str] | None = None) -> None:
        self._loaded = frozenset(loaded)
        self._executed = frozenset(loaded if executed is None else executed)

    def modules_after(self, statement: str) -> frozenset[str]:
        return frozenset() if statement == "" else self._loaded

    def trace(self, statement: str) -> frozenset[str]:
        return frozenset() if statement == "" else self._executed

    def attributed(self, statement: str) -> frozenset[str]:
        return self.trace(statement) - self.trace("")


def test_g17_goes_red_when_a_lazy_name_is_eagerly_loaded(gates: dict[str, ModuleType]) -> None:
    """Clause 1's failure, through both instruments.

    The message has to say *why* a lazy name matters, because the cost is invisible at the call
    site: `ow hook prompt` has a 250 ms warm p95 budget (G26) and every failure on that hook is a
    silent exit 0, so a deadline breach turns the adoption lever off with no symptom.
    """
    module = gates["gate_lazy_core"]
    interpreter = _StubInterpreter({"omniweave_core", "omniweave_core.store", "sqlite3"})
    findings = module.check_absence(interpreter)
    assert len(findings) == 2, [finding.block() for finding in findings]
    assert all("store" in finding.subject for finding in findings)
    assert all("250 ms" in finding.why for finding in findings)


def test_g17_static_half_names_the_file_and_the_line(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """Clause 2 is the half that turns "something loaded store" into "this line loaded store"."""
    module = gates["gate_lazy_core"]
    src = tmp_path / "packages" / "omniweave-core" / "src" / "omniweave_core"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    (src / "resolve.py").write_text(
        "from __future__ import annotations\n\nfrom omniweave_core.store import Store\n",
        encoding="utf-8",
        newline="\n",
    )
    interpreter = _StubInterpreter({"omniweave_core", "omniweave_core.resolve"})
    findings = module.check_static(tmp_path.resolve(), interpreter)
    assert len(findings) == 1, [finding.block() for finding in findings]
    assert findings[0].subject.endswith("omniweave_core/resolve.py:3: omniweave_core.store")
    assert "TYPE_CHECKING" in findings[0].fix


def test_g17_static_half_ignores_a_module_the_eager_import_never_loaded(
    gates: dict[str, ModuleType], tmp_path: Path
) -> None:
    """`store/sqlite.py` importing `omniweave_core.store` is not a G17 violation.

    The clause is scoped to the modules a bare `import omniweave_core` actually loaded, because a
    lazy subpackage importing its own siblings is what a lazy subpackage is for.
    """
    module = gates["gate_lazy_core"]
    src = tmp_path / "packages" / "omniweave-core" / "src" / "omniweave_core" / "store"
    src.mkdir(parents=True)
    (src.parent / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    (src / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    (src / "sqlite.py").write_text("import omniweave_core.store\n", encoding="utf-8", newline="\n")
    interpreter = _StubInterpreter({"omniweave_core"})
    assert module.check_static(tmp_path.resolve(), interpreter) == []


def test_g23_goes_red_when_core_loads_an_event_loop(gates: dict[str, ModuleType]) -> None:
    """G23's failure, and the two stdlib names the third-party check would never catch.

    The single event loop in the framework lives in `omniweave/run/`, in the CLI distribution,
    precisely so core pays no loop-import tax (INV-3).
    """
    module = gates["gate_importtime"]
    interpreter = _StubInterpreter({"omniweave_core", "asyncio", "selectors"})
    findings = module.check_no_event_loop(interpreter)
    assert len(findings) == 2, [finding.block() for finding in findings]
    for finding in findings:
        assert "asyncio" in finding.subject and "selectors" in finding.subject
        assert "omniweave/run/" in finding.fix


def test_g23_says_so_when_the_baseline_interpreter_makes_it_unmeasurable(
    gates: dict[str, ModuleType],
) -> None:
    """A bare `python -c ''` that already loaded a loop makes G23 unmeasurable, not green.

    Reporting the environment rather than the tree is the honest answer: the difference-based
    reading that G9 uses would cancel the contamination and print a pass that means nothing.
    """
    module = gates["gate_importtime"]

    class _ContaminatedBaseline(_StubInterpreter):
        def modules_after(self, statement: str) -> frozenset[str]:  # noqa: ARG002
            return frozenset({"asyncio"})

    findings = module.check_no_event_loop(_ContaminatedBaseline(set()))
    assert len(findings) == 1
    assert "unmeasurable" in findings[0].why


def test_g9_goes_red_when_a_third_party_module_is_attributed_to_core(
    gates: dict[str, ModuleType],
) -> None:
    """G9's failure, with INV-2's own evidence in the message.

    `torch` and `torchvision` are **base** requirements of docling, so its DOCX reader costs
    ~2.5-3.5 GB installed with CUDA wheels. The gate exists so that arriving here is loud.
    """
    module = gates["gate_importtime"]
    interpreter = _StubInterpreter({"omniweave_core", "omniweave_ports", "torch", "json"})
    findings = module.check_no_third_party(interpreter)
    assert findings, "the classifier saw torch and reported nothing"
    assert any("torch" in finding.subject for finding in findings)
    assert any("2.5-3.5 GB" in finding.why for finding in findings)


def test_g9_reports_the_two_instruments_disagreeing_as_the_finding(
    gates: dict[str, ModuleType],
) -> None:
    """A module reachable through `sys.modules` but absent from the trace was re-exported.

    `-X importtime` sees what was *executed*; `sys.modules` sees what is *reachable*. That is the
    shape that is free on a warm interpreter and expensive on a cold one, which is the only kind
    that matters for INV-3.
    """
    module = gates["gate_importtime"]
    interpreter = _StubInterpreter(
        loaded={"omniweave_core", "omniweave_ports", "pydantic"}, executed={"omniweave_core"}
    )
    reasons = [finding.why for finding in module.check_no_third_party(interpreter)]
    assert any("the two instruments disagree" in reason for reason in reasons), reasons
