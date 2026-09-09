"""G1 — `omniweave-core` resolves to exactly two first-party distributions and zero third-party.

**What it reads.** `packages/omniweave-core/pyproject.toml` and
`packages/omniweave-ports/pyproject.toml` (the declarations), `uv.lock` through
`uv export --locked` (the resolution), and both `src/` trees as source text (the imports).

**What it asserts**, with three instruments, because one would be a single point of failure:

1. **the declared closure** — walking `[project] dependencies` transitively from `omniweave-core`
   reaches exactly `{omniweave-core, omniweave-ports}`, every requirement on the way names an
   `omniweave-*` distribution, `omniweave-ports` declares nothing at all, and core's only
   `[project.optional-dependencies]` key is `sqlite`;
2. **the resolution in a clean environment** — `uv export --package omniweave-core --no-dev
   --locked` emits exactly those two distributions and nothing else, and the same for
   `omniweave-ports`, which must resolve to **itself alone** (02-architecture.md section 3.2,
   rule 1's "how G4 knows" column);
3. **the source** — no `.py` under either `src/` imports a module that is neither
   `sys.stdlib_module_names` nor first-party. This is the instrument that sees an *undeclared*
   dependency, which neither of the first two can: a `from pydantic import BaseModel` inside
   `omniweave_core/model/` is a defect the moment it is written, whether or not pydantic happens
   to be in the venv that runs the gate (INV-2's own violation example).

**Why `--locked` rather than a network resolve.** `uv.lock` is uv's recorded resolution of exactly
these declarations, and `--locked` re-checks the lock against every `pyproject.toml` before
exporting, so a stale lock is a failure here rather than a silent read of superseded data. It also
means the gate needs no index and no network, which is what lets it run in the same pre-merge job
as G4 on a machine with nothing installed.

**What is deliberately *not* asserted.** `[build-system] requires = ["hatchling>=1.27"]` is a
build-time dependency and never enters a wheel's `METADATA`; `[dependency-groups] dev` is not a
runtime dependency either and is charter D1's own list. The `[sqlite]` extra is permitted because
it is not a capability — `store/sqlite.py` refuses at open below `MIN_SQLITE = (3, 42, 0)` and
names the extra as the remedy the probe that failed prints — so this gate asserts the *set of
extra names* rather than resolving the extra: an extra that made something newly possible would be
a dependency with a flag in front of it, and INV-2 would hold only for the users who did not set
the flag (11-repo-layout.md section 2.1).

The negative evidence the invariant was written against: `torch` and `torchvision` are **base**
requirements of docling, so its DOCX reader costs ~2.5-3.5 GB installed with CUDA wheels;
`leann-core` requires torch and AGPL PyMuPDF and four PDF libraries including archived `PyPDF2`
(01-principles.md, INV-2).

The same three properties are asserted from the test tree by
`packages/omniweave-core/tests/test_purity.py`, whose header assigns "the clean-environment
*resolve* half" to this script by name. Exit 0 clean, 1 with one `G1 FAIL` block per finding, 2
when the gate itself could not run. Specified in 02-architecture.md section 3.3 and 16-roadmap.md
sections 2.4 and 4.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess  # noqa: TID251 — G1's resolve half IS a `uv export`; there is no library here.
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CORE",
    "EXPECTED_CLOSURE",
    "PERMITTED_EXTRAS",
    "PORTS",
    "Finding",
    "check_declared_closure",
    "check_extras",
    "check_resolution",
    "check_source_imports",
    "emit",
    "find_repo_root",
    "main",
    "normalise",
    "parse_requirements",
    "stdlib_names",
    "third_party_imports",
]

CORE = "omniweave-core"
PORTS = "omniweave-ports"

EXPECTED_CLOSURE: tuple[str, ...] = (CORE, PORTS)
"""G1's subject, verbatim from charter D1: "`omniweave-core` resolves to exactly TWO first-party
distributions, `omniweave-core` + `omniweave-ports`, and zero third-party ones".

Two rather than one because core is the host and is written in the driver-facing vocabulary; its
single first-party edge points at `omniweave_ports` rather than duplicating six types
(02-architecture.md section 3.2 rule 2).
"""

PERMITTED_EXTRAS: tuple[str, ...] = ("sqlite",)
"""The only `[project.optional-dependencies]` key `omniweave-core` may carry, ever.

"No other core extra may exist, because an extra that adds a capability makes INV-2 conditional"
(11-repo-layout.md section 2.1).
"""

_ALWAYS_AVAILABLE = frozenset({"__future__", "__main__"})
"""Importable names that are not modules a distribution depends on."""

_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
"""PEP 508: the distribution name is the leading run of name characters."""

_NORMALISE = re.compile(r"[-_.]+")

_PY = ".py"


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation, with the instrument that saw it and the fix that clears it."""

    instrument: str
    subject: str
    why: str
    fix: str

    def block(self) -> str:
        """The `G1 FAIL` block. Charter section 6.4: every message ends with the command."""
        pad = " " * 9
        body = "\n".join(f"{pad}{line}" for line in (self.subject, *self.why.splitlines()))
        return f"G1 FAIL  {self.instrument}\n{body}\n{pad}fix: {self.fix}"


def normalise(name: str) -> str:
    """PEP 503 normalisation, so `omniweave_core` and `omniweave-core` are one distribution."""
    return _NORMALISE.sub("-", name).lower()


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


def _pyproject(repo_root: Path, distribution: str) -> dict[str, object]:
    path = repo_root / "packages" / distribution / "pyproject.toml"
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _dependencies(repo_root: Path, distribution: str) -> tuple[str, ...]:
    project = _pyproject(repo_root, distribution).get("project")
    if not isinstance(project, dict):
        return ()
    declared = project.get("dependencies", [])
    if not isinstance(declared, list):
        return ()
    return tuple(str(requirement) for requirement in declared)


def check_declared_closure(repo_root: Path) -> list[Finding]:
    """Instrument 1: G1 stated as a closure over the declarations rather than as a resolve.

    Walking the closure rather than reading one `dependencies` list is what catches the shape the
    invariant actually forbids — core staying clean while `omniweave-ports` grows a dependency and
    every consumer of core inherits it.
    """
    findings: list[Finding] = []
    instrument = "the declarations (packages/*/pyproject.toml)"
    closure: set[str] = set()
    frontier = [CORE]
    while frontier:
        name = frontier.pop()
        if name in closure:
            continue
        closure.add(name)
        for requirement in _dependencies(repo_root, name):
            matched = _REQUIREMENT_NAME.match(requirement)
            if matched is None:
                findings.append(
                    Finding(
                        instrument=instrument,
                        subject=f"{name}: {requirement!r}",
                        why="this requirement has no PEP 508 distribution name to classify.",
                        fix="write a requirement, not a comment.",
                    )
                )
                continue
            required = normalise(matched.group(0))
            if not required.startswith("omniweave-"):
                findings.append(
                    Finding(
                        instrument=instrument,
                        subject=f"{name} depends on {requirement}",
                        why=(
                            f"{required} is third party. omniweave-core and omniweave-ports have "
                            "ZERO third-party runtime dependencies (INV-2, charter D1). Amending "
                            "this amends the CHARTER."
                        ),
                        fix="put the dependency behind a driver distribution and a Port.",
                    )
                )
                continue
            frontier.append(required)
    if sorted(closure) != sorted(EXPECTED_CLOSURE):
        findings.append(
            Finding(
                instrument=instrument,
                subject=f"closure(omniweave-core) = {sorted(closure)}",
                why=(
                    f"G1 requires exactly {list(EXPECTED_CLOSURE)} — two first-party "
                    "distributions and nothing else (charter D1)."
                ),
                fix="restore packages/omniweave-core/pyproject.toml's single dependency line.",
            )
        )
    declared_by_ports = _dependencies(repo_root, PORTS)
    if declared_by_ports:
        findings.append(
            Finding(
                instrument=instrument,
                subject=f"{PORTS} dependencies = {list(declared_by_ports)}",
                why=(
                    "rule 1: omniweave-ports depends on nothing. It is the only distribution in "
                    "the workspace with an empty `dependencies`, which is what makes a third "
                    "party's whole omniweave surface ~40 KB (02-architecture.md section 3.2)."
                ),
                fix="empty the list. A ports dependency is a charter amendment.",
            )
        )
    return findings


def check_extras(repo_root: Path) -> list[Finding]:
    """Instrument 1, second clause: `[sqlite]` and no other extra, ever."""
    project = _pyproject(repo_root, CORE).get("project")
    optional = project.get("optional-dependencies", {}) if isinstance(project, dict) else {}
    declared = tuple(sorted(optional)) if isinstance(optional, dict) else ()
    if declared == tuple(sorted(PERMITTED_EXTRAS)):
        return []
    return [
        Finding(
            instrument="the declarations (packages/omniweave-core/pyproject.toml)",
            subject=f"[project.optional-dependencies] = {list(declared)}",
            why=(
                f"the only permitted extra is {list(PERMITTED_EXTRAS)}, and it is permitted "
                "because it is a capability REMEDY rather than a capability: store/sqlite.py "
                "refuses at open below MIN_SQLITE = (3, 42, 0) and names it in the failure. An "
                "extra that made something newly possible would be a dependency with a flag in "
                "front of it (11-repo-layout.md section 2.1)."
            ),
            fix="remove the extra, or ship its capability as a driver distribution.",
        )
    ]


def parse_requirements(text: str) -> tuple[str, ...]:
    """The distribution names in a `requirements.txt`, normalised, in file order.

    `uv export` writes workspace members as `-e ./packages/<name>` and everything else as a PEP 508
    requirement, with `# via …` provenance indented under each. Comment and continuation lines are
    dropped; a `-e` line contributes the directory it names, which for a uv workspace member is the
    distribution name.
    """
    names: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.endswith("\\"):
            continue
        if line.startswith("-e "):
            names.append(normalise(line[3:].strip().rstrip("/").rsplit("/", 1)[-1]))
            continue
        if line.startswith("-"):
            continue
        matched = _REQUIREMENT_NAME.match(line)
        if matched is not None:
            names.append(normalise(matched.group(0)))
    return tuple(names)


def _uv_export(uv: str, repo_root: Path, distribution: str) -> tuple[str, str, int]:
    """`uv export --package <distribution> --no-dev --locked`, as (stdout, stderr, returncode).

    `--no-dev` drops `[dependency-groups] dev`, which is where the eleven development tools live;
    `--locked` refuses to proceed against a `uv.lock` that no longer matches the declarations, so
    the resolve this gate reads is provably the resolve of the tree it is gating. `--no-hashes`
    only because hash blocks wrap across lines and carry no distribution name.
    """
    completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, executable from `which`.
        [
            uv,
            "export",
            "--package",
            distribution,
            "--no-dev",
            "--no-hashes",
            "--locked",
            "--format",
            "requirements-txt",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    return completed.stdout, completed.stderr, completed.returncode


def check_resolution(uv: str, repo_root: Path) -> list[Finding]:
    """Instrument 2: the clean-environment resolve, read out of the lock uv itself produced."""
    findings: list[Finding] = []
    expectations = (
        (CORE, tuple(sorted(EXPECTED_CLOSURE))),
        (PORTS, (PORTS,)),
    )
    for distribution, expected in expectations:
        instrument = f"the resolution (uv export --package {distribution} --no-dev --locked)"
        stdout, stderr, code = _uv_export(uv, repo_root, distribution)
        if code != 0:
            findings.append(
                Finding(
                    instrument=instrument,
                    subject=f"uv exited {code}",
                    why=stderr.strip() or "uv produced no diagnosis.",
                    fix="uv lock, then re-run. A stale uv.lock is not a resolve.",
                )
            )
            continue
        resolved = tuple(sorted(set(parse_requirements(stdout))))
        third_party = tuple(name for name in resolved if not name.startswith("omniweave-"))
        if third_party:
            findings.append(
                Finding(
                    instrument=instrument,
                    subject=f"resolved third party: {list(third_party)}",
                    why=(
                        f"{distribution} has ZERO third-party runtime dependencies (INV-2, "
                        "charter D1 gate G1)."
                    ),
                    fix="remove the dependency; a capability belongs in a driver distribution.",
                )
            )
        if resolved != expected:
            findings.append(
                Finding(
                    instrument=instrument,
                    subject=f"resolved {list(resolved)}",
                    why=(
                        f"G1 requires exactly {list(expected)}. "
                        + (
                            "omniweave-ports resolves to itself alone (02-architecture.md "
                            "section 3.2, rule 1)."
                            if distribution == PORTS
                            else "Two first-party distributions and nothing else."
                        )
                    ),
                    fix="restore the declared dependencies, then uv lock.",
                )
            )
    return findings


def stdlib_names() -> frozenset[str]:
    """The standard library of the running interpreter.

    `sys.stdlib_module_names` is frozen per version and includes the private `_`-prefixed
    accelerators, which is what makes it usable as a membership test rather than as a heuristic. A
    hand-maintained list is the thing it exists to replace.
    """
    return frozenset(sys.stdlib_module_names) | _ALWAYS_AVAILABLE


def third_party_imports(src: Path) -> list[tuple[Path, int, str]]:
    """Every import under `src` that is neither stdlib nor first-party, as (path, line, name).

    Relative imports are skipped: they carry no root to classify and are `tools/gate_layers.py`'s
    failure, not this one's.
    """
    stdlib = stdlib_names()
    offences: list[tuple[Path, int, str]] = []
    for path in sorted(src.rglob(f"*{_PY}")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                candidates = [] if node.level > 0 else [node.module or ""]
            else:
                continue
            for dotted in candidates:
                root = dotted.split(".", 1)[0]
                if not root or root in stdlib:
                    continue
                if root == "omniweave" or root.startswith("omniweave_"):
                    continue
                offences.append((path, node.lineno, dotted))
    return offences


def check_source_imports(repo_root: Path) -> list[Finding]:
    """Instrument 3: the imports themselves, resolved against `sys.stdlib_module_names`.

    Walking source rather than the installed environment is deliberate. The violation INV-2 names
    is "a `from pydantic import` inside `omniweave_core/model/`", and that line is a defect the
    moment it is written — a resolve cannot see it, because an undeclared import is by definition
    absent from the declarations the resolve reads.
    """
    findings: list[Finding] = []
    for distribution in EXPECTED_CLOSURE:
        src = repo_root / "packages" / distribution / "src"
        if not src.is_dir():
            continue
        for path, line, dotted in third_party_imports(src):
            findings.append(
                Finding(
                    instrument="the source (ast walk over packages/*/src/)",
                    subject=f"{path.resolve().relative_to(repo_root).as_posix()}:{line}: {dotted}",
                    why=(
                        f"{dotted.split('.', 1)[0]} is neither stdlib nor first-party, so "
                        f"{distribution} has a third-party dependency the declarations do not "
                        "admit (INV-2)."
                    ),
                    fix="stdlib, or a driver distribution behind a Port.",
                )
            )
    return findings


def emit(line: str = "") -> None:
    """Write one line to stdout; ruff's `T20` bans `print` repo-wide and `tools/` has no ignore."""
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run G1. 0 clean, 1 with one block per finding, 2 when the gate could not run."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        emit(f"usage: {Path(__file__).name}   (no arguments; the workspace is found by walking up)")
        return 2

    repo_root = find_repo_root(Path(__file__).resolve())
    uv = shutil.which("uv")
    if uv is None:
        emit("G1 CANNOT RUN  no `uv` on PATH, so the clean-environment resolve has no resolver.")
        emit("               fix: run this gate as `uv run tools/gate_core_pure.py`.")
        return 2

    findings = check_declared_closure(repo_root)
    findings.extend(check_extras(repo_root))
    findings.extend(check_resolution(uv, repo_root))
    findings.extend(check_source_imports(repo_root))

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G1 FAIL  {len(findings)} finding(s).")
        return 1

    emit(
        f"G1 ok  {CORE} declares, resolves and imports exactly {list(EXPECTED_CLOSURE)}; "
        f"{PORTS} resolves to itself alone; extras {list(PERMITTED_EXTRAS)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
