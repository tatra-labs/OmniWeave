"""`ow surface emit [--check|--bless]`: the byte-diff half of G25. 10 section 2.3; 11 section 1.9.

10:202: *"`ow surface emit` writes all seven; `ow surface emit --check` byte-diffs them,
CRLF-normalised, and fails CI (gate G25)."* This module is the spine that does it, and the three
rules it obeys are 11:484's, all three of which are needed and none of which is this file's idea:

1. **`.gitattributes` pins `eol=lf`** for every generated tree, so a checkout matches the generator
   on all three operating systems. That is already in the repository and is not this module's.
2. **Every generator writes `"\\n"` explicitly** -- `open(path, "w", newline="\\n")`, never the
   platform default. `write()` below is the only place in this package that opens a file for
   writing, so there is one site to get it right and one site semgrep has to watch (11:487).
3. **Every `--check` normalises CRLF before comparing.** `normalise()` is that, and it is applied
   to BOTH sides: the bytes read off disk and the bytes the renderer produced. Normalising only the
   file would make a generator that emitted `\\r\\n` pass its own gate.

## PURITY IS SPLIT FROM WRITING, AND THE SPLIT IS THE POINT

10:229 bans a clock, `os.environ`, `random` and IO from the generator, and G25 is worthless without
it: a byte-diff over a document that carries a timestamp fails on the second run for a reason that
is not a defect. But an emitter has to write files, so the ban cannot be over the module.

It is over the RENDERERS. `render()` returns bytes from `ACTIONS` and nothing else; `write()` is
the only function here that touches a path, and `check()` only reads. A test pins this module's and
`instructions.py`'s import sets, which is `route/eval.py`'s own mechanism (its docstring: *"the
module-level import set is pinned by a test"*) applied to the second purity island the plan names.

## WHAT `check()` REFUSES TODAY, WITH SIX RENDERERS UNWRITTEN

A `PENDING` row with a file committed at its path. That is not a placeholder assertion -- it is the
defect G25 is named after. 00:851 makes **LEANN's `llms.txt` G25's named defect**, and LEANN's
`llms.txt` is a hand-written file that looked generated: two tools declared against a server
defining four. A repository that committed `llms.txt` before anything could generate it would be in
exactly that state, and would stay there until someone wrote the renderer and discovered the
difference.

So `check()` is a gate from the day the register exists, not from the day the renderers do. It
replaces `test_no_generated_artefact_has_been_written_yet`, which asserted the same property over
two of the five paths by name.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave.gen.agents import render as _render_agents
from omniweave.gen.artefacts import ARTEFACTS, Shape, State
from omniweave.gen.cli_tree import render as _render_cli_tree
from omniweave.gen.llms import render as _render_llms
from omniweave.gen.mcp_tools import render as _render_mcp_tools
from omniweave.gen.sdk_stub import render as _render_sdk_stub

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from omniweave.gen.artefacts import Artefact

__all__ = [
    "IGNORED",
    "RENDERERS",
    "REPO_ROOT",
    "TREE_RENDERERS",
    "check",
    "emit",
    "normalise",
    "render",
    "render_tree",
    "write",
]


REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[5]
"""The repository root, four packages deep plus `src/omniweave/gen`.

Derived from `__file__` and not from `os.getcwd()`, which is one of the eight ambient inputs 10:229
bans: a generator whose output depended on the directory it was invoked from would byte-diff
differently in CI than on a laptop, which is the failure a byte-diff gate exists to make impossible.
"""


def _cli_tree_files() -> Mapping[str, bytes]:
    """Artefact 3's files. One today: `omniweave/cli/` is a package of one generated module."""
    return {"__init__.py": _render_cli_tree()}


RENDERERS: Final[Mapping[int, Callable[[], bytes]]] = MappingProxyType(
    {
        1: _render_mcp_tools,
        4: _render_sdk_stub,
        5: _render_llms,
        6: _render_agents,
    }
)
"""Artefact number -> the pure function that produces its bytes. Four entries and one absence.

Artefacts 1, 4, 5 and 6 are the `FILE` rows with a renderer: `schema/mcp-tools-v1.json` from
`omniweave.gen.mcp_tools`, `omniweave/sdk/_generated.pyi` from `omniweave.gen.sdk_stub`,
`llms.txt` from `omniweave.gen.llms` and `docs/AGENTS.md` from `omniweave.gen.agents`. Artefact 3
is a `TREE` and is in the table below.

Artefact 2 is `LIVE` and has no entry, because it has no path: `instructions.py` produces a string
delivered on `initialize`, gated by SV2's character cap rather than by a byte-diff. Artefact 7 is
`PENDING`. A `LIVE` row with a path and no renderer is a contradiction `check()` reports, and so is
the reverse -- a renderer for a row the register still calls `PENDING`.

Read-only, because `check()` and `emit()` both branch on membership and a table a caller could
append to at runtime would make the register a suggestion. The tests that need a different table
replace the attribute rather than mutating it.
"""

TREE_RENDERERS: Final[Mapping[int, Callable[[], Mapping[str, bytes]]]] = MappingProxyType(
    {
        3: _cli_tree_files,
    }
)
"""Artefact number -> the files of a generated DIRECTORY, keyed by path relative to it.

A second table rather than a wider return type on the first, because the two are asked different
questions. A `FILE` row has bytes; a `TREE` row has a membership as well, and the clause that makes
a generated directory worth having -- a file inside it that no renderer wrote is hand-written -- has
nothing to compare against in a `Mapping[int, Callable[[], bytes]]`. `Shape` on the register says
which table to read, and `_renderer_shape_failures()` fails a row that is in the wrong one.
"""

IGNORED: Final[tuple[str, ...]] = ("__pycache__",)
"""Directory names a tree's membership ignores.

One entry, and it is not a convenience: `__pycache__` is written by the interpreter on first import
and is `.gitignore`d, so a tree whose membership counted it would report a finding the moment a test
imported the package it is checking. The rule is "what git tracks", and this is the only untracked
thing that appears inside a generated package.
"""


def normalise(raw: bytes) -> bytes:
    """CRLF -> LF, applied to both sides of every comparison. 11:490, and the charter's own wording
    for G6 -- *"byte-diff, CRLF-normalised"* -- applied to all five gates that do one.

    A carriage return is folded only when it precedes a newline. A lone one is not a line ending
    any generator here emits, and folding it would hide a file that genuinely contains one.
    """
    return raw.replace(b"\r\n", b"\n")


def render(artefact: Artefact) -> bytes | None:
    """The artefact's bytes, or `None` when no renderer exists yet.

    Pure: it reads `RENDERERS` and the registry and touches no path, no clock and no environment.
    10:232 fixes the encoding of what comes back -- *"Output is `\\n`-terminated UTF-8 with no
    BOM"* -- and that is the renderer's to honour, because only the renderer knows where its last
    line ends.
    """
    renderer = RENDERERS.get(artefact.number)
    return None if renderer is None else renderer()


def render_tree(artefact: Artefact) -> Mapping[str, bytes] | None:
    """A `TREE` artefact's files, keyed by path relative to its directory, or `None`.

    Sorted on the way out, because 10:224 bans iteration over an unsorted set from a generator and
    a mapping's order reaches the diff through the order files are written in.
    """
    renderer = TREE_RENDERERS.get(artefact.number)
    return None if renderer is None else dict(sorted(renderer().items()))


def _committed_tree(root: Path) -> tuple[str, ...]:
    """Every file under `root`, relative and slash-separated, sorted, minus `IGNORED`."""
    if not root.is_dir():
        return ()
    found = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not any(part in IGNORED for part in path.relative_to(root).parts)
    ]
    return tuple(sorted(found))


def _write_bytes(target: Path, payload: bytes) -> bool:
    """Write `payload` at `target` if it differs. The ONE `open(..., "w")` in this package.

    `newline="\\n"` is 11:487's rule and the reason this is one function rather than a line in each
    renderer: semgrep bans a bare `open(..., "w")` under `omniweave/gen/`, and a ban is only as good
    as the number of places it has to watch.

    Writes nothing when the bytes already match, so a re-run is not a mtime change. That is not
    politeness: `--bless` is a reviewable act (11:486's three rules exist so a diff means something)
    and a no-op write would put every artefact in every diff.
    """
    if target.exists() and normalise(target.read_bytes()) == normalise(payload):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload.decode("utf-8"))
    return True


def write(artefact: Artefact, payload: bytes) -> bool:
    """Write `payload` at the artefact's path. Returns whether the bytes changed. The ONLY IO here.

    A `FILE` row only. A `TREE` row has no single payload, and passing one would silently write
    a directory path as a file; `emit()` calls `_write_bytes` per member instead.
    """
    if artefact.path is None:
        raise ValueError(f"artefact {artefact.number} has no path; it is not a file")
    if artefact.shape is Shape.TREE:
        raise ValueError(f"artefact {artefact.number} is a tree; write each of its files")
    return _write_bytes(REPO_ROOT / artefact.path, payload)


def _located(artefact: Artefact) -> str:
    """The artefact's path, for a caller that has already excluded the pathless row.

    A function rather than an `assert`, which S101 rightly bans in shipped source: an assertion
    that a register is self-consistent belongs in the register, where `_shape_failures()` already
    raises on a `FILE` or `TREE` row with no path at import.
    """
    if artefact.path is None:  # pragma: no cover -- `_shape_failures()` raises at import first
        raise ValueError(f"artefact {artefact.number} has no path")
    return artefact.path


def _check_file(artefact: Artefact) -> list[str]:
    """One `FILE` row, against the tree. The four clauses `check()`'s docstring lists."""
    target = REPO_ROOT / _located(artefact)
    payload = render(artefact)
    if artefact.state is State.PENDING:
        return _pending(artefact, payload is not None, target.exists())
    if payload is None:
        return [f"{artefact.path}: LIVE in gen/artefacts.py and no renderer is registered"]
    if not target.exists():
        return [f"{artefact.path}: LIVE and rendered, but nothing is committed there"]
    if normalise(target.read_bytes()) != normalise(payload):
        return [f"{artefact.path}: differs from what the generator produces"]
    return []


def _check_tree(artefact: Artefact) -> list[str]:
    """One `TREE` row: the same four clauses per member, plus the one only a directory has.

    Clause 5 is `tools/schemagen.py`'s `_stray_files()` applied inside a package: a file in a
    generated directory that no renderer wrote is hand-written by definition, and without it
    `omniweave/cli/` would be a place a second, unchecked module could be parked next to a gated
    one. `IGNORED` keeps `__pycache__` out of that judgement.
    """
    root = REPO_ROOT / _located(artefact)
    committed = _committed_tree(root)
    files = render_tree(artefact)
    if artefact.state is State.PENDING:
        return _pending(artefact, files is not None, bool(committed))
    if files is None:
        return [f"{artefact.path}/: LIVE in gen/artefacts.py and no renderer is registered"]
    findings: list[str] = []
    for relative, payload in files.items():
        member = root / relative
        if not member.is_file():
            findings.append(f"{artefact.path}/{relative}: LIVE and rendered, but not committed")
        elif normalise(member.read_bytes()) != normalise(payload):
            findings.append(f"{artefact.path}/{relative}: differs from what the generator produces")
    findings.extend(
        f"{artefact.path}/{relative}: committed, and no renderer writes it. "
        f"A hand-written file in a generated package is INV-20's defect (G25)"
        for relative in committed
        if relative not in files
    )
    return findings


def _pending(artefact: Artefact, rendered: bool, committed: bool) -> list[str]:
    """The two things a `PENDING` row may not be: renderable, or already on disk."""
    findings: list[str] = []
    if rendered:
        findings.append(
            f"{artefact.path}: PENDING, yet a renderer produced bytes for it -- "
            f"promote the row to LIVE in gen/artefacts.py"
        )
    if committed:
        findings.append(
            f"{artefact.path}: committed, but no renderer produces it. "
            f"A hand-written agent-facing artefact is INV-20's defect (G25); "
            f"delete it or land {artefact.lands_with}"
        )
    return findings


def check() -> tuple[str, ...]:
    """Every finding, in artefact order. `()` is `ow surface emit --check` passing. Gate G25.

    Five clauses, and the third is the one that was a gate before any renderer existed:

    1. a `LIVE` artefact whose renderer is missing -- the register claiming a capability the code
       does not have;
    2. a `LIVE` artefact whose committed bytes differ from its rendered bytes, CRLF-normalised on
       both sides;
    3. a `PENDING` artefact with something committed at its path -- the LEANN shape, and the reason
       this function was worth having before five of the renderers are written;
    4. a `LIVE` artefact with a path and nothing committed at all, which is a `--bless` nobody ran;
    5. `TREE` rows only: a file inside the generated directory that no renderer wrote.

    Reads and does not write, so `--check` in CI cannot repair the thing it is measuring.
    """
    findings: list[str] = []
    for artefact in ARTEFACTS:
        if artefact.shape is Shape.STRING:
            continue
        findings.extend(
            _check_tree(artefact) if artefact.shape is Shape.TREE else _check_file(artefact)
        )
    return tuple(findings)


def emit() -> tuple[str, ...]:
    """Write every `LIVE` artefact that has a path. Returns the paths that changed, in order.

    `ow surface emit` with no flag, and `--bless` is the same call: 11:486 makes blessing a
    reviewable act rather than a separate mechanism, so there is one writer and the review is the
    diff it leaves. A `TREE` row reports one path per member that moved, because that is what a
    reviewer will see in the diff.
    """
    changed: list[str] = []
    for artefact in ARTEFACTS:
        if artefact.path is None or artefact.state is not State.LIVE:
            continue
        if artefact.shape is Shape.TREE:
            files = render_tree(artefact)
            if files is None:
                continue
            changed.extend(
                f"{artefact.path}/{relative}"
                for relative, payload in files.items()
                if _write_bytes(REPO_ROOT / artefact.path / relative, payload)
            )
            continue
        payload = render(artefact)
        if payload is not None and write(artefact, payload):
            changed.append(artefact.path)
    return tuple(changed)
