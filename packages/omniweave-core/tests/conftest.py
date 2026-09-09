"""What every test under `packages/omniweave-core/tests/` shares.

Three things, and deliberately only three:

* `repo_root` — the workspace root, found by walking up rather than by counting
  `parents[n]`, so a test that moves between `tests/` and `tests/unit/` does not
  silently start reading the wrong tree.
* `plan` — a reader over `_plan/`, because several constants in this substrate are
  *quoted* from a plan document and a test that asserts the constant against the
  document is the only thing that stops the two drifting. `_plan/` is `.gitignore`d,
  so every such test asks `plan.available` first and skips with a reason when the
  design tree is not in the checkout.
* `interpreter` — a fresh-interpreter helper. G17, G23 and G9 are statements about
  what a *bare* `import omniweave_core` does, and once a pytest session has imported
  half the tree for its own reasons `sys.modules` can no longer answer that question.
  A subprocess is not an optimisation here; it is the only witness.

Plus `pure_unit`, the T1 side-effect guard of 13-quality.md section 2.7. It is
**opt-in** rather than autouse — see its docstring for why, and for what owns making
it autouse.

Specified in 13-quality.md sections 2.2 and 2.7, and 02-architecture.md section 3.3
("the purity gates ... a fresh interpreter").
"""

from __future__ import annotations

import ast
import builtins
import json
import re
import socket
import subprocess  # noqa: TID251 — a fresh interpreter is the only witness for G9/G17/G23.
import sys
import time
import tomllib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# The repository root
# ---------------------------------------------------------------------------


def _find_repo_root(start: Path) -> Path:
    """The nearest ancestor that carries the three things only the root carries."""
    for candidate in (start, *start.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "packages").is_dir()
            and (candidate / "tools" / "layers.toml").is_file()
        ):
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT: Path = _find_repo_root(Path(__file__).resolve())


# ---------------------------------------------------------------------------
# The migration set — ONE home for the path
# ---------------------------------------------------------------------------

# The DDL is package data of `omniweave-core`, not a repo-root directory, and this constant is the
# single place the workspace path is written.
#
# WHY IT IS HERE AND NOT AT THE REPO ROOT. 11-repo-layout.md:1186 -- "`schema/migrations/*.sql` is
# packaged with `omniweave-core` as package data, read through `importlib.resources` at use time
# (section 2.6)". `importlib.resources.files()` takes a PACKAGE, so a repo-root `schema/` cannot
# satisfy that mechanism, and section 2.6 rule 1 bans the `__file__` / `__path__` workaround
# outright. 11-repo-layout.md:205's tree diagram draws these files as a child of
# `omniweave_core/store/` and :793 spells the path in full. Root `schema/` is a different thing
# entirely -- :346 describes it as "GENERATED from Python, committed, byte-diff gated (G6)", which
# hand-written DDL is not.
#
# A build-time copy from a root location was tried and is worse than the move: a hatchling
# `force-include` whose source escapes the project directory takes `omniweave-core`'s sdist from 34
# members to three -- **no `src/` at all** -- while still reporting `Successfully built`, and adding
# it to both targets then makes `sdist` -> `wheel` fail outright. At this path both artefacts carry
# the four files with ZERO build configuration. The finding is `_plan/_notes/build-defects.md` D12
# and `tests/unit/test_sdist_shape.py` is the check that would have caught it.
#
# One consequence for `_plan/`, recorded in D12: 11-repo-layout.md:2304's CODEOWNERS line reads
# `/schema/migrations/`, anchored at the repo root, and should name this path instead. The intent --
# contract review on every DDL change -- is unaffected.
MIGRATIONS_DIR: Path = (
    REPO_ROOT
    / "packages"
    / "omniweave-core"
    / "src"
    / "omniweave_core"
    / "store"
    / "schema"
    / "migrations"
)

# `NNNN_<slug>.sql`, four digits (11-repo-layout.md:1188). Sorting four-digit prefixes as text IS
# numeric order, which is the order 11-repo-layout.md:1188 makes load-bearing.
MIGRATION_GLOB = "[0-9][0-9][0-9][0-9]_*.sql"


def migration_files() -> tuple[Path, ...]:
    """The migration set in the numeric order it must be applied in."""
    return tuple(sorted(MIGRATIONS_DIR.glob(MIGRATION_GLOB)))


# ---------------------------------------------------------------------------
# The plan reader
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanCitation:
    """One line of one plan document, carried with enough to cite it in a failure."""

    document: str
    line: int
    text: str

    def __str__(self) -> str:
        return f"_plan/{self.document}:{self.line}: {self.text.strip()}"


@dataclass(frozen=True, slots=True)
class PlanDocs:
    """A read-only view over `_plan/`.

    `documents()` deliberately excludes `_notes/.snapshots/`: those are frozen copies
    of earlier verification passes, and a test that greps them is asserting against a
    superseded document rather than the current one.
    """

    root: Path

    @property
    def available(self) -> bool:
        """`_plan/` is `.gitignore`d, so a clean clone has no design tree."""
        return self.root.is_dir()

    def require(self) -> None:
        """Skip the calling test when the design tree is not in this checkout."""
        if not self.available:
            pytest.skip("_plan/ is .gitignore'd and absent from this checkout")

    def documents(self) -> tuple[str, ...]:
        """Every current plan document, as a `_plan/`-relative POSIX path."""
        found = (
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*.md")
            if ".snapshots" not in path.parts
        )
        return tuple(sorted(found))

    def text(self, document: str) -> str:
        return (self.root / document).read_text(encoding="utf-8")

    def lines(self, document: str) -> tuple[str, ...]:
        return tuple(self.text(document).splitlines())

    def grep(
        self, pattern: str, *, documents: Sequence[str] | None = None
    ) -> tuple[PlanCitation, ...]:
        """Every line matching `pattern`, across `documents` or the whole plan."""
        compiled = re.compile(pattern)
        names = tuple(documents) if documents is not None else self.documents()
        hits: list[PlanCitation] = []
        for name in names:
            for number, line in enumerate(self.lines(name), start=1):
                if compiled.search(line):
                    hits.append(PlanCitation(document=name, line=number, text=line))
        return tuple(hits)

    def fences(self, document: str, language: str) -> tuple[str, ...]:
        """The body of every ```<language> fence in `document`, in order.

        The fence scanner is line-oriented and closes on the first ``` at the same
        indentation, which is the shape G27 clause (a) reads the same corpus with.
        """
        bodies: list[str] = []
        body: list[str] | None = None
        for line in self.lines(document):
            stripped = line.strip()
            if body is None:
                if stripped == f"```{language}":
                    body = []
            elif stripped == "```":
                bodies.append("\n".join(body))
                body = None
            else:
                body.append(line)
        return tuple(bodies)

    def toml_fences(self, document: str) -> tuple[dict[str, object], ...]:
        """Every ```toml fence in `document`, parsed. G27 clause (a) in miniature."""
        return tuple(tomllib.loads(body) for body in self.fences(document, "toml"))


PLAN: PlanDocs = PlanDocs(root=REPO_ROOT / "_plan")


# ---------------------------------------------------------------------------
# The fresh-interpreter helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuditReport:
    """What a statement did to the outside world, observed with `sys.addaudithook`.

    `opened` holds only the paths opened *while the statement ran* — the hook is armed
    immediately before it and disarmed immediately after, so interpreter startup and
    whatever a virtualenv `.pth` does are outside the window by construction.
    """

    opened: tuple[str, ...]
    sockets: int
    subprocesses: int
    threads_started: int

    @property
    def non_python_files(self) -> tuple[str, ...]:
        """Opened paths that are not a Python source, bytecode or extension file.

        Importing a module necessarily opens its own `.py`/`.pyc`. Opening anything
        else is the module reading data at import time, which is what INV-3 forbids.
        """
        suffixes = (".py", ".pyc", ".pyd", ".pyi", ".so", ".dll", ".dylib")
        return tuple(path for path in self.opened if not path.lower().endswith(suffixes))


_MODULES_PROGRAM = """
{statement}
import json as _json, sys as _sys
print(_json.dumps(sorted(_sys.modules)))
"""

_AUDIT_PROGRAM = """
import json as _json, sys as _sys, threading as _threading
_opened = []
_counts = {{"sockets": 0, "subprocesses": 0}}
_armed = [False]
def _hook(event, args):
    if not _armed[0]:
        return
    if event == "open":
        _opened.append(str(args[0])[:400] if args else "")
    elif event == "socket.__new__":
        _counts["sockets"] += 1
    elif event in ("subprocess.Popen", "os.system", "os.exec", "os.spawn"):
        _counts["subprocesses"] += 1
_sys.addaudithook(_hook)
_threads_before = _threading.active_count()
_armed[0] = True
{statement}
_armed[0] = False
print(_json.dumps({{
    "opened": _opened,
    "sockets": _counts["sockets"],
    "subprocesses": _counts["subprocesses"],
    "threads_started": _threading.active_count() - _threads_before,
}}))
"""

_IMPORTTIME_LINE = re.compile(r"^import time:\s+[\d-]+\s*\|\s+[\d-]+\s*\|\s*(?P<module>\S+)\s*$")


@cache
def _run(executable: str, flags: tuple[str, ...], source: str, timeout_s: float) -> tuple[str, str]:
    proc = subprocess.run(  # noqa: S603 — a fixed argv, no shell, first element sys.executable.
        [executable, *flags, "-c", source],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        message = (
            f"fresh interpreter exited {proc.returncode}\n"
            f"--- source ---\n{source}\n--- stderr ---\n{proc.stderr}"
        )
        raise AssertionError(message)
    return proc.stdout, proc.stderr


@dataclass(frozen=True, slots=True)
class Interpreter:
    """Runs a statement in a fresh interpreter and reports what it did.

    Every result is memoised on `(executable, flags, source)`. The statements these
    gates run are pure observations of an import graph, so a second identical spawn
    would return an identical answer and cost another ~120 ms nine times over.
    """

    executable: str
    timeout_s: float = 120.0

    def run(self, source: str, *, flags: Sequence[str] = ()) -> str:
        """stdout of `python <flags> -c <source>`. A non-zero exit is a failure."""
        stdout, _ = _run(self.executable, tuple(flags), source, self.timeout_s)
        return stdout

    def modules_after(self, statement: str) -> frozenset[str]:
        """`sys.modules` after `statement` has run — an empty statement is the baseline."""
        stdout = self.run(_MODULES_PROGRAM.format(statement=statement))
        names: list[str] = json.loads(stdout.strip().splitlines()[-1])
        return frozenset(names)

    def modules_added_by(self, statement: str) -> frozenset[str]:
        """`modules_after(statement)` minus the baseline.

        The difference matters: a virtualenv injects a `.pth` finder, `sitecustomize`
        and — on Windows — `pywin32_bootstrap` before any user code runs. Measured as
        an absolute set those read as third-party dependencies of whatever is imported
        next; measured as a difference they cancel.
        """
        return self.modules_after(statement) - self.modules_after("")

    def importtime_modules(self, statement: str) -> frozenset[str]:
        """The module names `-X importtime` attributes to `statement`, baseline removed.

        This is G9's instrument rather than G17's: `-X importtime` reports what was
        *executed*, so a module already in `sys.modules` for another reason does not
        appear, and the trace is the artefact 02-architecture.md section 3.3 names.
        """
        return self._importtime(statement) - self._importtime("")

    def _importtime(self, statement: str) -> frozenset[str]:
        _, stderr = _run(self.executable, ("-X", "importtime"), statement, self.timeout_s)
        found: set[str] = set()
        for line in stderr.splitlines():
            match = _IMPORTTIME_LINE.match(line)
            if match is not None:
                found.add(match.group("module"))
        return frozenset(found)

    def audit(self, statement: str) -> AuditReport:
        """What `statement` opened, connected, spawned and started, via an audit hook."""
        stdout = self.run(_AUDIT_PROGRAM.format(statement=statement))
        payload: dict[str, object] = json.loads(stdout.strip().splitlines()[-1])
        opened = payload["opened"]
        assert isinstance(opened, list)
        return AuditReport(
            opened=tuple(str(path) for path in opened),
            sockets=int(str(payload["sockets"])),
            subprocesses=int(str(payload["subprocesses"])),
            threads_started=int(str(payload["threads_started"])),
        )


INTERPRETER: Interpreter = Interpreter(executable=sys.executable)


# ---------------------------------------------------------------------------
# Source walking, shared by the layer gate and the purity gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImportSite:
    """One `import` or `from ... import`, with the file and line that wrote it."""

    path: Path
    line: int
    module: str
    level: int
    statement: str

    def __str__(self) -> str:
        return f"{self.path.as_posix()}:{self.line}: {self.statement}"


def import_sites(path: Path) -> tuple[ImportSite, ...]:
    """Every import in `path`, at any scope, `if TYPE_CHECKING:` blocks included.

    Built with `ast`, not a regex: a regex sees an import inside a docstring, misses
    one inside a function body and cannot tell `level` from a dotted name. The gate
    also runs on a package whose dependencies are not installed, which is why it walks
    source rather than importing it (02-architecture.md section 3.3, "Extends the
    charter").
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: list[ImportSite] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                sites.append(
                    ImportSite(
                        path=path,
                        line=node.lineno,
                        module=alias.name,
                        level=0,
                        statement=f"import {alias.name}",
                    )
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


def source_files(root: Path) -> Iterator[Path]:
    """Every `.py` under `root`, `__pycache__` excluded, in a stable order."""
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


@dataclass(frozen=True, slots=True)
class Distribution:
    """One workspace member, as the layer gate needs to see it."""

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
        return tuple(
            sorted(path.name for path in self.src.iterdir() if (path / "__init__.py").is_file())
        )

    def pyproject(self) -> dict[str, object]:
        text = (self.directory / "pyproject.toml").read_text(encoding="utf-8")
        return tomllib.loads(text)

    def sources(self) -> Iterator[Path]:
        return source_files(self.src)


def distributions(repo_root: Path) -> tuple[Distribution, ...]:
    """The workspace members, read off the tree rather than off a list."""
    found = (
        Distribution(name=path.parent.name, directory=path.parent)
        for path in (repo_root / "packages").glob("*/pyproject.toml")
    )
    return tuple(sorted(found, key=lambda dist: dist.name))


def first_party_root(module: str) -> str | None:
    """The `omniweave*` distribution root a dotted module name belongs to, if any."""
    root = module.split(".", 1)[0]
    return root if root == "omniweave" or root.startswith("omniweave_") else None


@dataclass(frozen=True, slots=True)
class SourceIndex:
    """The workspace seen as source text rather than as importable modules.

    The layer gate and the purity gate both need "every `.py` under every
    `packages/*/src/`, with every import in it and the line that wrote it", and neither
    may get it by importing: the gate has to run on a package whose dependencies are
    not installed, and an import that fails tells you nothing about the import graph
    (02-architecture.md section 3.3, "Extends the charter").
    """

    repo_root: Path

    def distributions(self) -> tuple[Distribution, ...]:
        """Every workspace member, read off `packages/*/pyproject.toml`."""
        return distributions(self.repo_root)

    def distribution(self, name: str) -> Distribution:
        """One member by distribution name, e.g. `omniweave-core`."""
        for dist in self.distributions():
            if dist.name == name:
                return dist
        message = f"no workspace member named {name}"
        raise LookupError(message)

    def files(self, root: Path) -> tuple[Path, ...]:
        """Every `.py` under `root`, `__pycache__` excluded, in a stable order."""
        return tuple(source_files(root))

    def imports(self, path: Path) -> tuple[ImportSite, ...]:
        """Every import in `path`, at any scope, `if TYPE_CHECKING:` included."""
        return import_sites(path)

    def first_party_root(self, module: str) -> str | None:
        """The `omniweave*` distribution root a dotted module name belongs to, if any."""
        return first_party_root(module)

    def layers(self) -> dict[str, tuple[str, ...]]:
        """`tools/layers.toml` — the complete allowed set per package, closed."""
        text = (self.repo_root / "tools" / "layers.toml").read_text(encoding="utf-8")
        parsed = tomllib.loads(text)
        return {key: tuple(str(name) for name in value) for key, value in parsed.items()}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The uv workspace root — the directory holding `packages/` and `tools/`."""
    return REPO_ROOT


@pytest.fixture(scope="session")
def migrations() -> Path:
    """The migration set's directory. It is `omniweave-core` package data, not a root directory.

    See `MIGRATIONS_DIR` above for why, and `_plan/_notes/build-defects.md` D12 for the finding.
    Every test that reads the DDL takes this rather than composing the path itself, so the next
    move -- if the plan's CODEOWNERS line is resolved the other way -- is one edit.
    """
    return MIGRATIONS_DIR


@pytest.fixture(scope="session")
def plan() -> PlanDocs:
    """A reader over `_plan/`. Call `plan.require()` before asserting against it."""
    return PLAN


@pytest.fixture(scope="session")
def sources(repo_root: Path) -> SourceIndex:
    """The `ast`-level view of every distribution's `src/`, plus `tools/layers.toml`."""
    return SourceIndex(repo_root=repo_root)


@pytest.fixture(scope="session")
def interpreter() -> Interpreter:
    """A fresh-interpreter probe: `sys.modules`, `-X importtime` and audit events."""
    return INTERPRETER


@pytest.fixture
def pure_unit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make a T1 unit test's side effects raise instead of happening.

    13-quality.md section 2.7 specifies this as an autouse fixture over `tests/unit/`:
    a test that asserts a pure function's algebra must not open a socket, spawn a
    process, read the wall clock or touch a file outside `tmp_path`. It is **opt-in
    here** because this conftest sits above `tests/unit/` and arming it from this level
    would also arm it over the gate tests beside it — which spawn a fresh interpreter
    on purpose, that being the whole of G17's instrument. Making it autouse belongs to
    a `tests/unit/conftest.py`, which P2's fixture tree owns.

    `time.monotonic` and `time.perf_counter` are left alone: `clock.py` injects the
    clock a caller reads (02-architecture.md row 24), and pytest's own durations come
    from `perf_counter`.
    """
    allowed = (str(tmp_path), str(Path(tmp_path).resolve()))
    real_open = builtins.open

    def guarded_open(file: object, *args: object, **kwargs: object) -> object:
        if isinstance(file, (str, Path)) and not str(Path(file).resolve()).startswith(allowed):
            message = f"a T1 unit test opened {file!r} outside tmp_path (13-quality.md §2.7)"
            raise AssertionError(message)
        return real_open(file, *args, **kwargs)  # type: ignore[call-overload]

    def forbidden(name: str) -> Callable[..., object]:
        def raiser(*_args: object, **_kwargs: object) -> object:
            message = f"a T1 unit test reached {name} (13-quality.md §2.7)"
            raise AssertionError(message)

        return raiser

    monkeypatch.setattr(builtins, "open", guarded_open)
    monkeypatch.setattr(socket, "socket", forbidden("socket.socket"))
    monkeypatch.setattr(subprocess, "Popen", forbidden("subprocess.Popen"))
    monkeypatch.setattr(subprocess, "run", forbidden("subprocess.run"))
    monkeypatch.setattr(time, "time", forbidden("time.time"))


__all__ = [
    "MIGRATIONS_DIR",
    "MIGRATION_GLOB",
    "AuditReport",
    "Distribution",
    "ImportSite",
    "Interpreter",
    "PlanCitation",
    "PlanDocs",
    "SourceIndex",
    "distributions",
    "first_party_root",
    "import_sites",
    "migration_files",
    "source_files",
]
