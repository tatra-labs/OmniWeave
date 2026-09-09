"""G17 — the lazy-core gate: `import omniweave_core` imports none of the nine.

The nine are `{model, store, archive, retrieve, answer, out, host, toolchain, modelserver}`.

**Why.** The per-turn hook path. `ow hook prompt` has a p95 budget of 250 ms warm (G26) and every
failure on that hook is a silent exit 0, so a deadline breach turns the adoption lever off with no
symptom — the worst failure shape available on the agent path (01-principles.md, INV-3). Core pays
for every module this import touches, and the nine names are the nine largest things it could
touch. 11-repo-layout.md section 1.3 calls their laziness "a STRUCTURAL property, not a
convention", which is why it is a gate and not a review habit.

**What it reads.** Fresh interpreters — `import omniweave_core` under `sys.modules` and under
`-X importtime` — and, for the static half, every `.py` under
`packages/omniweave-core/src/omniweave_core/` that the eager import actually loaded.

**What it asserts**, four clauses:

1. **absence** — none of `omniweave_core.<name>` is in `sys.modules` after a bare
   `import omniweave_core`, and none is attributed to it by `-X importtime`. Two instruments,
   because they answer different questions: the trace reports what was *executed*, `sys.modules`
   reports what is *reachable*.
2. **the offending line** — for every core module the eager import did load, no module-scope
   runtime import names a lazy submodule. This is the clause that says *which file and which
   line*, and it finds exactly the violation INV-3 names: "a module-level `from .store import
   Store` added to make a type annotation resolve at runtime instead of under `TYPE_CHECKING`".
   `if TYPE_CHECKING:` bodies are excluded here on purpose — they never execute, so an annotation
   resolved there costs the hook path nothing. That exclusion is the difference between this gate
   and G4, which counts `TYPE_CHECKING` imports because a layer violation is a fact about the
   source and not about the runtime.
3. **the negative control** — the same instrument, shown `import omniweave_core.store`, must
   report it. A `sys.modules` assertion that can only pass is not a gate. `store` is the name used
   because it is the largest of the nine and the only site that may call `sqlite3.connect`
   (INV-17), so if any name is going to arrive through a convenience re-export it is this one.
4. **deferred, not absent** — every one of the nine that has a home on disk imports on demand.
   Without this clause G17 is satisfiable by deletion, which passes the absence assertion and
   breaks every caller. `toolchain` and `modelserver` are single modules rather than packages and
   `modelserver.py` lands at P4 W4.9, so the count of homes present is not nine and this clause
   asserts over what exists rather than over the list.

**A note on where the nine are reached from.** `omniweave_core/__init__.py` resolves them in
`__getattr__` with **nine literal function-scope `import omniweave_core.<name> as module`
statements**, not a dispatch through `importlib.import_module` — which semgrep bans outside
`host/`. Clause 2's walk is module-scope-only by design and therefore ignores those nine
correctly: they are the mechanism that makes G17 true, not a violation of it. G4's walk, which is
scope-blind, sees them and allows them because `omniweave_core` is its own root.

The same four clauses are asserted from the test tree by
`packages/omniweave-core/tests/test_g17.py`, whose header names this script as the CI half by
name. Exit 0 clean, 1 with one `G17 FAIL` block per finding. Specified in charter.md section D1
gate G17, 11-repo-layout.md section 1.3 and 02-architecture.md section 3.3.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess  # noqa: TID251 — a fresh interpreter is the only witness for G17.
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "LAZY",
    "Finding",
    "Interpreter",
    "check_absence",
    "check_negative_control",
    "check_reachable",
    "check_static",
    "core_src",
    "emit",
    "find_repo_root",
    "main",
    "module_scope_runtime_imports",
]

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
"""The nine, verbatim from charter.md section D1 gate G17 and 11-repo-layout.md section 1.3.

Order is the charter's, not alphabetical, so the tuple can be diffed against the braced set the
six plan documents print. `drivers` is deliberately **not** among them: 11-repo-layout.md section
1.3's tree marks `drivers/` `T-CONTRACT` with no `LAZY`, because `DriverCard` and `resolve()` are
on the discovery path `ow doctor` and `ow drivers list` already take.

`packages/omniweave-core/tests/unit/test_gates_structural.py` asserts this tuple against
`omniweave_core.LAZY`, so the gate and the module it gates cannot drift apart.
"""

_NEGATIVE_CONTROL = "store"
"""The one of the nine the control imports. See clause 3 in the module docstring."""

_MODULES_PROGRAM = """
{statement}
import json as _json, sys as _sys
print(_json.dumps(sorted(_sys.modules)))
"""

_IMPORTTIME_LINE = re.compile(r"^import time:\s+[\d-]+\s*\|\s+[\d-]+\s*\|\s*(?P<module>\S+)\s*$")

_TIMEOUT_S = 300.0

_PY = ".py"


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation, with the instrument that saw it and the fix that clears it."""

    instrument: str
    subject: str
    why: str
    fix: str

    def block(self) -> str:
        pad = " " * 10
        body = "\n".join(f"{pad}{line}" for line in (self.subject, *self.why.splitlines()))
        return f"G17 FAIL  {self.instrument}\n{body}\n{pad}fix: {self.fix}"


@dataclass(frozen=True, slots=True)
class Interpreter:
    """Runs a statement in a fresh interpreter. A subprocess is the only witness G17 has.

    Once this process has imported anything for its own reasons, its `sys.modules` can no longer
    answer "what does a *bare* `import omniweave_core` load".
    """

    executable: str

    def _run(self, flags: tuple[str, ...], source: str) -> tuple[str, str]:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, argv[0] is sys.executable
            [self.executable, *flags, "-c", source],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
        if completed.returncode != 0:
            message = (
                f"fresh interpreter exited {completed.returncode}\n"
                f"--- source ---\n{source}\n--- stderr ---\n{completed.stderr}"
            )
            raise RuntimeError(message)
        return completed.stdout, completed.stderr

    def modules_after(self, statement: str) -> frozenset[str]:
        """`sys.modules` once `statement` has run."""
        stdout, _ = self._run((), _MODULES_PROGRAM.format(statement=statement))
        names: list[str] = json.loads(stdout.strip().splitlines()[-1])
        return frozenset(names)

    def trace(self, statement: str) -> frozenset[str]:
        """Every module `-X importtime` reports while running `statement` — what was executed."""
        _, stderr = self._run(("-X", "importtime"), statement)
        return frozenset(
            matched.group("module")
            for line in stderr.splitlines()
            if (matched := _IMPORTTIME_LINE.match(line)) is not None
        )


def find_repo_root(start: Path) -> Path:
    """The nearest ancestor carrying the three things only the workspace root carries."""
    for candidate in (start, *start.parents):
        if (
            (candidate / "pyproject.toml").is_file()
            and (candidate / "packages").is_dir()
            and (candidate / "tools" / "layers.toml").is_file()
        ):
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


def core_src(repo_root: Path) -> Path:
    """`packages/omniweave-core/src/omniweave_core/`."""
    return repo_root / "packages" / "omniweave-core" / "src" / "omniweave_core"


def _module_name(repo_root: Path, path: Path) -> str:
    """`.../src/omniweave_core/a/b.py` -> `omniweave_core.a.b`."""
    src = repo_root / "packages" / "omniweave-core" / "src"
    parts = path.resolve().relative_to(src.resolve()).with_suffix("").parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _is_type_checking(test: ast.expr) -> bool:
    """`if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:`, however it was spelled."""
    match test:
        case ast.Name(id="TYPE_CHECKING"):
            return True
        case ast.Attribute(attr="TYPE_CHECKING"):
            return True
        case _:
            return False


def module_scope_runtime_imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    """The imports that run when the module is imported.

    Module scope, plus `try:` / `else:` / `finally:` at module scope — which is how a stdlib
    fallback is spelled — and plus the branches of a module-scope `if` that is not
    `if TYPE_CHECKING:`. A function body is excluded because a deferred import is the *fix* for a
    G17 violation rather than an instance of one; `omniweave_core/__init__.py`'s `__getattr__` is
    nine of them, and flagging those would flag the mechanism that makes this gate pass.
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


def _named_modules(node: ast.Import | ast.ImportFrom) -> list[str]:
    """The dotted module names one import statement can pull in.

    `from omniweave_core.store import Store` names `omniweave_core.store`; `from omniweave_core
    import store` names `omniweave_core.store` too, and that second spelling is the one a naive
    check misses.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if node.level > 0:
        return []  # a relative import; tools/gate_layers.py owns that failure
    module = node.module or ""
    return [module, *(f"{module}.{alias.name}" for alias in node.names)]


def check_absence(interpreter: Interpreter) -> list[Finding]:
    """Clause 1 — G17 itself, through both instruments."""
    findings: list[Finding] = []
    statement = "import omniweave_core"
    forbidden = {f"omniweave_core.{name}" for name in LAZY}
    for instrument, loaded in (
        (f"sys.modules after {statement!r}", interpreter.modules_after(statement)),
        (f"-X importtime -c {statement!r}", interpreter.trace(statement)),
    ):
        eager = tuple(name for name in LAZY if f"omniweave_core.{name}" in loaded)
        nested = tuple(
            sorted(
                name
                for name in loaded
                if any(name.startswith(f"{module}.") for module in forbidden)
            )
        )
        if eager:
            findings.append(
                Finding(
                    instrument=instrument,
                    subject=f"{statement} loaded {list(eager)}"
                    + (f" (and below them: {list(nested)})" if nested else ""),
                    why=(
                        "the nine lazy subpackages must not be reachable through a bare import of "
                        "core. `ow hook prompt` has a 250 ms warm p95 budget (G26) and every "
                        "failure on that hook is a silent exit 0, so a deadline breach turns the "
                        "adoption lever off with no symptom (INV-3)."
                    ),
                    fix=(
                        "defer the import: under `if TYPE_CHECKING:` for an annotation, or into "
                        "the function that needs it. See omniweave_core/__init__.__getattr__."
                    ),
                )
            )
    return findings


def check_static(repo_root: Path, interpreter: Interpreter) -> list[Finding]:
    """Clause 2 — the half that says *which line*.

    `check_absence` reports that something pulled a lazy name in; this reports the file and the
    line that did it, over exactly the modules the eager import loaded.
    """
    eager = {
        name
        for name in interpreter.modules_after("import omniweave_core")
        if name == "omniweave_core" or name.startswith("omniweave_core.")
    }
    forbidden = {f"omniweave_core.{name}" for name in LAZY}
    findings: list[Finding] = []
    src = core_src(repo_root)
    if not src.is_dir():
        return findings
    for path in sorted(src.rglob(f"*{_PY}")):
        if "__pycache__" in path.parts or _module_name(repo_root, path) not in eager:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in module_scope_runtime_imports(tree):
            hit = sorted(name for name in _named_modules(node) if name in forbidden)
            if not hit:
                continue
            findings.append(
                Finding(
                    instrument="the source (module-scope imports of eagerly loaded core modules)",
                    subject=(
                        f"{path.resolve().relative_to(repo_root).as_posix()}:{node.lineno}: "
                        f"{hit[0]}"
                    ),
                    why=(
                        "an eagerly imported core module names a lazy submodule at module scope. "
                        "This is INV-3's own example: a module-level `from .store import Store` "
                        "added to make a type annotation resolve at runtime instead of under "
                        "`TYPE_CHECKING`."
                    ),
                    fix="move it under `if TYPE_CHECKING:`, or into the function that needs it.",
                )
            )
    return findings


def check_negative_control(interpreter: Interpreter) -> list[Finding]:
    """Clause 3 — the instrument must see a lazy name when it really is imported."""
    statement = f"import omniweave_core.{_NEGATIVE_CONTROL}"
    loaded = interpreter.modules_after(statement)
    missing = tuple(
        name
        for name in (f"omniweave_core.{_NEGATIVE_CONTROL}", "omniweave_core")
        if name not in loaded
    )
    if not missing:
        return []
    return [
        Finding(
            instrument="the negative control",
            subject=f"{statement} did not put {list(missing)} in sys.modules",
            why=(
                "the instrument cannot see a lazy name that really was imported, so clause 1's "
                "silence means nothing. A gate whose instrument is silently broken reports green "
                "forever."
            ),
            fix="check that the probe interpreter resolves omniweave_core from this workspace.",
        )
    ]


def check_reachable(repo_root: Path, interpreter: Interpreter) -> list[Finding]:
    """Clause 4 — deferred, not absent. Every home that exists imports on demand.

    Asserted over the homes that are on disk rather than over the nine, because `modelserver.py`
    lands at P4 W4.9 and `toolchain.py` at P1 W1.6 (16-roadmap.md sections 4 and 7); requiring all
    nine today would be a gate failing on scope rather than on a defect.
    """
    src = core_src(repo_root)
    findings: list[Finding] = []
    for name in LAZY:
        if not (src / name).is_dir() and not (src / f"{name}{_PY}").is_file():
            continue
        statement = f"import omniweave_core.{name}"
        try:
            loaded = interpreter.modules_after(statement)
        except RuntimeError as error:
            findings.append(
                Finding(
                    instrument=f"{statement} (clause 4: deferred, not absent)",
                    subject=f"omniweave_core.{name} has a home on disk but does not import",
                    why=str(error).splitlines()[0],
                    fix="a lazy name that is absent rather than deferred breaks every caller.",
                )
            )
            continue
        if f"omniweave_core.{name}" not in loaded:
            findings.append(
                Finding(
                    instrument=f"{statement} (clause 4: deferred, not absent)",
                    subject=f"omniweave_core.{name} did not land in sys.modules",
                    why="G17 must not be satisfiable by deletion.",
                    fix="ship the module, or remove its home.",
                )
            )
    return findings


def emit(line: str = "") -> None:
    """Write one line to stdout; ruff's `T20` bans `print` repo-wide and `tools/` has no ignore."""
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run G17. 0 clean, 1 with one block per finding, 2 when the gate could not run."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        emit(f"usage: {Path(__file__).name}   (no arguments; it spawns fresh interpreters)")
        return 2

    repo_root = find_repo_root(Path(__file__).resolve())
    interpreter = Interpreter(executable=sys.executable)
    try:
        findings = check_negative_control(interpreter)
        findings.extend(check_absence(interpreter))
        findings.extend(check_static(repo_root, interpreter))
        findings.extend(check_reachable(repo_root, interpreter))
    except RuntimeError as error:
        emit("G17 CANNOT RUN  a probe interpreter failed:")
        for line in str(error).splitlines():
            emit(f"                {line}")
        emit("                fix: `uv sync`, then re-run.")
        return 2

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G17 FAIL  {len(findings)} finding(s).")
        return 1

    homes = tuple(
        name
        for name in LAZY
        if (core_src(repo_root) / name).is_dir() or (core_src(repo_root) / f"{name}{_PY}").is_file()
    )
    emit(
        f"G17 ok  import omniweave_core loads none of the {len(LAZY)} lazy names; "
        f"{len(homes)} of them have a home on disk and each imports on demand."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
