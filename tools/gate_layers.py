"""G4 — the layer gate: every import in the workspace obeys `tools/layers.toml`.

**What it reads.** `tools/layers.toml` (the fourteen rows), every `packages/*/pyproject.toml`
(for the workspace membership and each `[project.entry-points."omniweave.drivers"]` table), every
`packages/*/src/**/*.py` (as source text), and — for each package an entry point names — that
package's `src/<package>/driver.toml`.

**What it asserts.** Four things, in the order 02-architecture.md section 3.3 states them:

1. every `Import` / `ImportFrom` **at module, class and function scope, `TYPE_CHECKING` blocks
   included**, maps to a first-party root that is in that package's row (or is the package
   itself);
2. no source file uses a relative import, because `from . import store` carries no first-party
   root to map and would be a hole in exactly the place a violation would hide
   (`ban-relative-imports = "all"`, 11-repo-layout.md section 8.1);
3. every `[project.entry-points."omniweave.drivers"]` value is a colon-free dotted package that
   exists in that distribution's `src/` (11-repo-layout.md section 1.5 — hatchling writes
   `entry_points.txt` from the table without validating the value's shape at all, so a malformed
   first-party value would ship and fail on a user's machine as a discovery-time refusal);
4. **every row is re-derived** from that distribution's entry points under rules 3 and 4 and
   compared with what `layers.toml` declares, **so no author picks their own row.** The Port is
   read out of each named package's `driver.toml` `[driver] port`, `tomllib` only, **never by
   importing it** (INV-4).

**How the graph is built.** With the stdlib `ast` module, walking source rather than importing it.
That is 02-architecture.md section 3.3's "Extends the charter" note: the charter lists this script
without saying how the graph is built, and `ast` is the answer because the gate has to run on a
package whose dependencies are not installed — which is precisely the condition a layer violation
creates — and because it keeps the dev dependency group exactly as charter D1 prints it, with no
`import-linter` and no `grimp` putting a package's own import graph between HEAD and the gate that
proves HEAD's import graph.

**Why the walk is duplicated in `packages/omniweave-core/tests/test_layers.py`.** It is the same
property asserted from the test tree, on purpose: the gate must run as `uv run tools/gate_layers.py`
with nothing installed and no pytest, and the test must run on every PR. Neither may import the
other — this script imports nothing first-party at all, which is what lets it inspect a broken
tree. The two are held in agreement by
`packages/omniweave-core/tests/unit/test_gates_structural.py`.

Exit 0 clean, 1 with one `G4 FAIL` block per finding naming the file, the line, the import and the
row it violates. Specified in 02-architecture.md section 3.3 (the mechanism table's first row, and
the two worked violations that follow it) and 16-roadmap.md section 4's P1 exit criteria.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CARD_FILENAME",
    "DRIVER_ENTRY_POINT_GROUP",
    "ENTRY_POINT_VALUE",
    "PORTS",
    "ROW_FOR_COMPILE",
    "ROW_FOR_EVERYTHING_ELSE",
    "Distribution",
    "Finding",
    "ImportSite",
    "Workspace",
    "check_entry_points",
    "check_layers_declaration",
    "driver_entry_points",
    "emit",
    "find_layer_violations",
    "find_relative_imports",
    "find_repo_root",
    "first_party_root",
    "import_sites",
    "main",
    "read_card_port",
    "row_for_ports",
]

DRIVER_ENTRY_POINT_GROUP = "omniweave.drivers"
"""The one entry-point group a driver distribution declares.

`omniweave.targets` is the second group 04-driver-system.md section 4.1 names, and it is
deliberately not read here: a target is reached through a `compile` driver id, so rules 3 and 4 are
total over this group alone. Reading a group that does not govern a row would let a distribution
move its row by declaring in the other one.
"""

ENTRY_POINT_VALUE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")
"""The entry-point *value* grammar, verbatim from 11-repo-layout.md section 1.5.

Two grammars that look alike and are not: the value is a **colon-free dotted package path**, while
the card's own `entrypoint` key is `module:attr` — the one place a colon is legal, because
`activate()` must assert the loaded class's `PORT` and `SCHEMA_VERSION` against the card before any
work. The charter justifies the colon-free form by `setuptools._entry_points.validate` raising at
build time on a path-shaped value; that justification does not protect this repository, because all
fourteen distributions build with hatchling, which does not validate the value at all. So G4
asserts the shape directly while it is already reading the table.
"""

PORTS: tuple[str, ...] = ("acquire", "parse", "derive", "embed", "compile")
"""The five Ports, in charter order. The first segment of a driver id **is** the Port.

Declared here rather than imported from `omniweave_ports` because this gate may import nothing
first-party — it has to run on a tree whose dependencies are not installed. The full id grammar
`^(acquire|parse|derive|embed|compile)\\.[a-z0-9_]{1,32}\\.[a-z0-9_]{1,32}$` (04-driver-system.md
section 4.1, section 5 X35) has one home and it is `drivers/card.py`; what this gate needs, and all
it checks, is that a key's first segment names a Port at all — an unrecognised first segment would
otherwise derive rule 3 silently and hand a distribution the narrow row for free.
"""

ROW_FOR_COMPILE: tuple[str, ...] = ("omniweave_core", "omniweave_ports")
"""Rule 4. A distribution declaring a `compile` driver may import the OUT framework.

`CompileV1` lives in `omniweave_core.out` because its signature mixes ports types (`DriverIO`,
`DriverResult`) with the OUT framework types a target is validated by (`Plan`, `ILBundle`,
`AssetLedger`, `RuleSpec`, `CarrierDoc`), and a Protocol has to live in one distribution
(02-architecture.md section 3.2 rule 4). That carve-out is the whole of the exception to "a driver
cannot pin the framework".
"""

ROW_FOR_EVERYTHING_ELSE: tuple[str, ...] = ("omniweave_ports",)
"""Rule 3. `acquire` / `parse` / `derive` / `embed` only, so `["omniweave_ports"]` **exactly**.

Adding `omniweave_core` to such a row fails this gate. A parse driver emits `owdoc-fragment/1`; it
never constructs a `Block` and never holds a `DocSink` (02-architecture.md section 3.3's first
worked violation).
"""

CARD_FILENAME = "driver.toml"
"""The card, read by `tomllib` and never imported (11-repo-layout.md section 1.5, INV-4)."""

_PY = ".py"


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation, carried with everything its failure block prints.

    02-architecture.md section 3.3's worked violations name the file, the line, the offending
    import, the row it violates and the fix, "so the gate's output is predictable rather than a
    puzzle". That shape is the requirement rather than a nicety, so it is a type rather than an
    f-string repeated at every site.
    """

    where: str
    subject: str
    why: str
    fix: str

    def block(self) -> str:
        """The `G4 FAIL` block, indented as the plan prints it."""
        pad = " " * 9
        body = "\n".join(f"{pad}{line}" for line in (self.subject, *self.why.splitlines()))
        return f"G4 FAIL  {self.where}\n{body}\n{pad}fix: {self.fix}"


@dataclass(frozen=True, slots=True)
class ImportSite:
    """One `import` or `from ... import`, with the file and line that wrote it."""

    path: Path
    line: int
    module: str
    level: int
    statement: str


def find_repo_root(start: Path) -> Path:
    """The nearest ancestor carrying the three things only the workspace root carries.

    Walking up rather than counting `parents[n]`, so the script keeps working from a checkout whose
    depth differs and `Path(".")` — banned in library code, and a lie under a hook runner that need
    not chdir — is never consulted.
    """
    for candidate in (start, *start.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "packages").is_dir()
            and (candidate / "tools" / "layers.toml").is_file()
        ):
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


def first_party_root(module: str) -> str | None:
    """The `omniweave*` distribution root a dotted module name belongs to, if any.

    `omniweave` and `omniweave_*` are the fourteen; anything else is somebody else's gate. Purity
    is G1's and G9's, not this one's.
    """
    root = module.split(".", 1)[0]
    return root if root == "omniweave" or root.startswith("omniweave_") else None


def import_sites(path: Path) -> tuple[ImportSite, ...]:
    """Every import in `path`, **at any scope**, `if TYPE_CHECKING:` blocks included.

    `ast.walk` is what makes "module, class and function scope" true without enumerating the
    statement kinds an import can nest inside — and function scope is not hypothetical here:
    `omniweave_core/__init__.py`'s `__getattr__` resolves the nine lazy subpackages with nine
    literal function-scope `import omniweave_core.<name> as module` statements, which a
    module-scope-only walk would not see at all.

    A regex would read an import out of a docstring, miss one indented into a function body and
    could not tell `level` from a dotted name. `TYPE_CHECKING` is included because a layer
    violation is a fact about the *source* — hiding one there would let a driver name a framework
    type it may not depend on. That is exactly where this gate parts company with G17, which
    excludes `TYPE_CHECKING` because it is a statement about the runtime.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: list[ImportSite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            sites.extend(
                ImportSite(
                    path=path,
                    line=node.lineno,
                    module=alias.name,
                    level=0,
                    statement=f"import {alias.name}",
                )
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = ", ".join(alias.name for alias in node.names)
            sites.append(
                ImportSite(
                    path=path,
                    line=node.lineno,
                    module=module,
                    level=node.level,
                    statement=f"from {'.' * node.level}{module} import {names}",
                )
            )
    return tuple(sites)


@dataclass(frozen=True, slots=True)
class Distribution:
    """One workspace member, as the layer gate needs to see it: a directory, never a module."""

    name: str
    directory: Path

    @property
    def layer_key(self) -> str:
        """The `tools/layers.toml` key: the distribution name with `-` as `_`."""
        return self.name.replace("-", "_")

    @property
    def src(self) -> Path:
        return self.directory / "src"

    @property
    def import_roots(self) -> tuple[str, ...]:
        """The top-level package names this distribution ships."""
        if not self.src.is_dir():
            return ()
        return tuple(
            sorted(path.name for path in self.src.iterdir() if (path / "__init__.py").is_file())
        )

    def pyproject(self) -> dict[str, object]:
        return tomllib.loads((self.directory / "pyproject.toml").read_text(encoding="utf-8"))

    def sources(self) -> tuple[Path, ...]:
        """Every `.py` under `src/`, `__pycache__` excluded, in a stable order."""
        if not self.src.is_dir():
            return ()
        return tuple(
            path for path in sorted(self.src.rglob(f"*{_PY}")) if "__pycache__" not in path.parts
        )


@dataclass(frozen=True, slots=True)
class Workspace:
    """`packages/` and `tools/layers.toml`, read off the tree rather than off a list.

    Reading membership off `packages/*/pyproject.toml` is what makes a fifteenth distribution fail
    here on the day it is added rather than on the day someone notices.
    """

    root: Path

    def distributions(self) -> tuple[Distribution, ...]:
        found = (
            Distribution(name=path.parent.name, directory=path.parent)
            for path in (self.root / "packages").glob("*/pyproject.toml")
        )
        return tuple(sorted(found, key=lambda dist: dist.name))

    def layers(self) -> dict[str, tuple[str, ...]]:
        """`tools/layers.toml` — the complete allowed set per package, transitively closed."""
        text = (self.root / "tools" / "layers.toml").read_text(encoding="utf-8")
        parsed = tomllib.loads(text)
        return {key: tuple(str(name) for name in value) for key, value in parsed.items()}

    def relative(self, path: Path) -> str:
        """`path` as a repo-relative POSIX path, which is what a failure block prints."""
        return path.resolve().relative_to(self.root).as_posix()


def check_layers_declaration(workspace: Workspace) -> list[Finding]:
    """The gate validating its own input before it trusts it.

    A row naming a distribution that does not exist is a row nothing can violate, and a member with
    no row is a tree the walk silently skips — either one turns this gate green by accident, which
    is the only failure mode a structural gate has. Rows 1 and 2 (`omniweave_ports = []`,
    `omniweave_core = ["omniweave_ports"]`) are the charter rather than a derivation, so they are
    asserted literally here; rows 3 and 4 are re-derived in `check_entry_points`.
    """
    findings: list[Finding] = []
    rows = workspace.layers()
    members = {dist.layer_key for dist in workspace.distributions()}
    location = "tools/layers.toml"

    findings.extend(
        Finding(
            where=location,
            subject=f"{missing} = ?",
            why=(
                f"packages/{missing.replace('_', '-')}/ is a workspace member with no row, so "
                "every import in it is unchecked."
            ),
            fix="add its row (02-architecture.md section 3.2 rules 3 and 4 derive it).",
        )
        for missing in sorted(members - set(rows))
    )
    findings.extend(
        Finding(
            where=location,
            subject=f"{orphan} = {list(rows[orphan])}",
            why=f"{orphan} names no workspace member, so nothing can violate this row.",
            fix="delete the row, or add the distribution it names.",
        )
        for orphan in sorted(set(rows) - members)
    )
    for package in sorted(set(rows) & members):
        row = rows[package]
        if package in row:
            findings.append(
                Finding(
                    where=location,
                    subject=f"{package} = {list(row)}",
                    why=f"{package} lists itself; a package may always import itself.",
                    fix=f"remove {package} from its own row.",
                )
            )
        findings.extend(
            Finding(
                where=location,
                subject=f"{package} = {list(row)}",
                why=f"{package} may import {unknown}, which is not a declared distribution.",
                fix=f"remove {unknown}, or declare it.",
            )
            for unknown in sorted(set(row) - set(rows))
        )

    for package, expected, rule in (
        ("omniweave_ports", (), "1"),
        ("omniweave_core", ("omniweave_ports",), "2"),
    ):
        actual = rows.get(package)
        if actual is not None and actual != expected:
            findings.append(
                Finding(
                    where=location,
                    subject=f"{package} = {list(actual)}",
                    why=(
                        f"rule {rule} fixes this row at {list(expected)}. It is the charter, not a "
                        "derivation (02-architecture.md section 3.2)."
                    ),
                    fix="restore the row. Changing it is a charter amendment.",
                )
            )
    return findings


def find_layer_violations(
    dist: Distribution, allowed: frozenset[str], workspace: Workspace
) -> list[Finding]:
    """Every import in `dist` naming a first-party root outside its row.

    `allowed` is the row plus the distribution's own import roots, because a package may always
    import itself. A root that is not `omniweave*` is not this gate's business.
    """
    findings: list[Finding] = []
    row = sorted(allowed - set(dist.import_roots))
    for path in dist.sources():
        try:
            sites = import_sites(path)
        except SyntaxError as error:
            findings.append(
                Finding(
                    where=f"{workspace.relative(path)}:{error.lineno or 0}",
                    subject=(error.text or "").strip(),
                    why=f"the file does not parse, so its imports cannot be mapped: {error.msg}",
                    fix="fix the syntax; a file the gate cannot read is a file it cannot gate.",
                )
            )
            continue
        findings.extend(
            Finding(
                where=f"{workspace.relative(site.path)}:{site.line}",
                subject=site.statement,
                why=(
                    f"{dist.name} may import {row} and itself; "
                    f"{first_party_root(site.module)} is outside that row "
                    "(tools/layers.toml, 02-architecture.md section 3.2)."
                ),
                fix=(
                    "move the shared implementation below the row, or reach it through a Port. "
                    "Widening a row is a CONTRACT bump on an announced RELEASE MINOR."
                ),
            )
            for site in sites
            if (root := first_party_root(site.module)) is not None and root not in allowed
        )
    return findings


def find_relative_imports(dist: Distribution, workspace: Workspace) -> list[Finding]:
    """Every `from . import ...` in `dist`.

    A relative import carries no first-party root to map, so a tree that mixes the two spellings
    has a hole in exactly the place a violation would hide. Ruff's `ban-relative-imports = "all"`
    enforces it on a changed file; this enforces it on the tree, and 11-repo-layout.md section 8.1
    names that as the reason the ban exists at all: it "is what makes `tools/gate_layers.py`'s
    `ast` walk able to map every import to a first-party root without resolving anything".
    """
    findings: list[Finding] = []
    for path in dist.sources():
        try:
            sites = import_sites(path)
        except SyntaxError:
            continue  # already reported by find_layer_violations
        findings.extend(
            Finding(
                where=f"{workspace.relative(site.path)}:{site.line}",
                subject=site.statement,
                why=(
                    "a relative import carries no first-party root, so this line is invisible to "
                    "the layer walk (11-repo-layout.md section 8.1)."
                ),
                fix="spell it absolutely.",
            )
            for site in sites
            if site.level > 0
        )
    return findings


def driver_entry_points(dist: Distribution) -> dict[str, str]:
    """That distribution's `[project.entry-points."omniweave.drivers"]` table, as written."""
    project = dist.pyproject().get("project")
    if not isinstance(project, dict):
        return {}
    groups = project.get("entry-points")
    if not isinstance(groups, dict):
        return {}
    table = groups.get(DRIVER_ENTRY_POINT_GROUP)
    if not isinstance(table, dict):
        return {}
    return {str(key): str(value) for key, value in table.items()}


def row_for_ports(ports: frozenset[str]) -> tuple[str, ...]:
    """Rules 3 and 4 as one total function of the Ports a distribution declares.

    One `compile` driver carries the whole distribution to rule 4, because a row is the set of
    roots any module in the distribution may import and a distribution is not partitioned by
    driver.
    """
    return ROW_FOR_COMPILE if "compile" in ports else ROW_FOR_EVERYTHING_ELSE


def read_card_port(card: Path) -> str | None:
    """`[driver] port` out of a `driver.toml` — `"parse/1"` reads as `"parse"`.

    `tomllib`, never an import: INV-4 is that a card is data and reading it must not run the
    driver's module body. That is the whole reason this gate can derive a row from a distribution
    whose dependencies are not installed and whose module body would raise `SystemExit`.
    """
    parsed = tomllib.loads(card.read_text(encoding="utf-8"))
    driver = parsed.get("driver")
    if not isinstance(driver, dict):
        return None
    port = driver.get("port")
    if not isinstance(port, str):
        return None
    return port.split("/", 1)[0]


def check_entry_points(workspace: Workspace) -> tuple[list[Finding], int]:
    """Clause 4 — **no author picks their own row** — plus clause 3's value-shape check.

    Returns the findings and the number of rows actually re-derived, which the summary prints: a
    re-derivation over zero declarations is vacuous, and a gate that reports "ok" without saying it
    checked nothing keeps reporting ok after the data arrives. At P1 no distribution declares a
    driver entry point — the first-party cards land with P3 W3.1-W3.6 (16-roadmap.md section 6) —
    so the count is legitimately 0 and the twelve driver rows are still the hand-written ones
    02-architecture.md section 3.2 prints.
    """
    findings: list[Finding] = []
    rows = workspace.layers()
    derived = 0
    for dist in workspace.distributions():
        table = driver_entry_points(dist)
        if not table:
            continue
        location = f"packages/{dist.name}/pyproject.toml"
        ports: set[str] = set()
        for driver_id, value in sorted(table.items()):
            port = driver_id.split(".", 1)[0]
            if port not in PORTS:
                findings.append(
                    Finding(
                        where=location,
                        subject=f'"{driver_id}" = "{value}"',
                        why=(
                            f"{port!r} is not one of the five Ports {list(PORTS)}, so rules 3 and "
                            "4 cannot derive this distribution's row (04-driver-system.md "
                            "section 4.1)."
                        ),
                        fix="an id is <port>.<family>.<impl>.",
                    )
                )
                continue
            ports.add(port)
            findings.extend(_check_entry_point_value(dist, driver_id, value, location))
            findings.extend(_check_card_port(dist, driver_id, value, port, location))
        if not ports:
            continue
        expected = row_for_ports(frozenset(ports))
        derived += 1
        actual = rows.get(dist.layer_key)
        if actual != expected:
            findings.append(
                Finding(
                    where="tools/layers.toml",
                    subject=f"{dist.layer_key} = {list(actual or ())}",
                    why=(
                        f"{dist.name} declares {sorted(ports)} drivers, so its row must be "
                        f"{list(expected)} exactly (02-architecture.md section 3.2 rule "
                        f"{'4' if 'compile' in ports else '3'}). No author picks their own row."
                    ),
                    fix=f"set the row to {list(expected)}, or change what the distribution ships.",
                )
            )
    return findings, derived


def _check_entry_point_value(
    dist: Distribution, driver_id: str, value: str, location: str
) -> list[Finding]:
    """Clause 3: a colon-free dotted package that exists in this distribution's `src/`."""
    subject = f'"{driver_id}" = "{value}"'
    fix = "the value is a dotted package; module:attr belongs on the card's `entrypoint` key."
    if ":" in value or "/" in value or not ENTRY_POINT_VALUE.match(value):
        return [
            Finding(
                where=location,
                subject=subject,
                why=(
                    f"an entry-point value must match {ENTRY_POINT_VALUE.pattern} with no ':' and "
                    "no '/' (11-repo-layout.md section 1.5). hatchling writes entry_points.txt "
                    "without validating it, so this would ship and fail on a user's machine as a "
                    "discovery-time refusal."
                ),
                fix=fix,
            )
        ]
    package = dist.src / Path(*value.split("."))
    if not package.is_dir() and not package.with_suffix(_PY).is_file():
        return [
            Finding(
                where=location,
                subject=subject,
                why=f"{value} names no package under packages/{dist.name}/src/.",
                fix=fix,
            )
        ]
    return []


def _check_card_port(
    dist: Distribution, driver_id: str, value: str, port: str, location: str
) -> list[Finding]:
    """Clause 4's read: the card's own `[driver] port` must agree with the entry-point key.

    `packages/omniweave-core/tests/test_layers.py` derives the Port from the entry-point key alone
    and says so explicitly — "a card whose `port` contradicts its entry-point key is that gate's
    finding, not this one's". This is that finding.
    """
    subject = f'"{driver_id}" = "{value}"'
    card_path = f"packages/{dist.name}/src/{value.replace('.', '/')}/{CARD_FILENAME}"
    card = dist.src / Path(*value.split(".")) / CARD_FILENAME
    if not card.is_file():
        return [
            Finding(
                where=location,
                subject=subject,
                why=(
                    f"{value} declares a driver but ships no {CARD_FILENAME}, so its Port cannot "
                    "be read without importing it (11-repo-layout.md section 1.5, INV-4)."
                ),
                fix=f"add {card_path}.",
            )
        ]
    declared = read_card_port(card)
    if declared is None:
        return [
            Finding(
                where=card_path,
                subject=subject,
                why=f"{CARD_FILENAME} has no `[driver] port` string, so no row can be derived.",
                fix='add port = "<port>/<major>".',
            )
        ]
    if declared != port:
        return [
            Finding(
                where=card_path,
                subject=f'port = "{declared}/…"   vs   {subject}',
                why=(
                    f"the card says {declared!r} and the entry-point key says {port!r}. The first "
                    "segment of an id IS the Port (04-driver-system.md section 4.1), so the two "
                    "cannot disagree and the row would be derived from a coin toss."
                ),
                fix="make the card and the key agree.",
            )
        ]
    return []


def emit(line: str = "") -> None:
    """Write one line to stdout.

    `print` is banned repo-wide by ruff's `T20` because "a library that prints has no way to be
    quiet inside a hook with a 400 ms deadline" (11-repo-layout.md section 8.1). A gate script is
    not a library and stdout is the whole of its output contract, but the repository declares no
    `tools/*.py` per-file-ignore, so the writer is explicit rather than suppressed.
    """
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run G4 over the workspace containing this file. 0 clean, 1 with one block per finding."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        emit(f"usage: {Path(__file__).name}   (no arguments; the workspace is found by walking up)")
        return 2

    workspace = Workspace(root=find_repo_root(Path(__file__).resolve()))
    rows = workspace.layers()
    findings = check_layers_declaration(workspace)

    walked = 0
    for dist in workspace.distributions():
        allowed = frozenset(rows.get(dist.layer_key, ())) | frozenset(dist.import_roots)
        findings.extend(find_layer_violations(dist, allowed, workspace))
        findings.extend(find_relative_imports(dist, workspace))
        walked += len(dist.sources())

    entry_point_findings, derived = check_entry_points(workspace)
    findings.extend(entry_point_findings)

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G4 FAIL  {len(findings)} finding(s) over {walked} source files, {len(rows)} rows.")
        return 1

    emit(f"G4 ok  {walked} source files, {len(rows)} rows, {derived} row(s) re-derived.")
    if derived == 0:
        emit(
            "       no distribution declares [project.entry-points.'omniweave.drivers'] yet, so "
            "clause 4 is vacuous; the first-party cards land with P3 W3.1-W3.6."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
