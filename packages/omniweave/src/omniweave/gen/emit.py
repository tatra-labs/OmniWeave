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
from typing import TYPE_CHECKING, Final

from omniweave.gen.artefacts import ARTEFACTS, State

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from omniweave.gen.artefacts import Artefact

__all__ = [
    "RENDERERS",
    "REPO_ROOT",
    "check",
    "emit",
    "normalise",
    "render",
    "write",
]


REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[5]
"""The repository root, four packages deep plus `src/omniweave/gen`.

Derived from `__file__` and not from `os.getcwd()`, which is one of the eight ambient inputs 10:229
bans: a generator whose output depended on the directory it was invoked from would byte-diff
differently in CI than on a laptop, which is the failure a byte-diff gate exists to make impossible.
"""

RENDERERS: Final[Mapping[int, Callable[[], bytes]]] = {}
"""Artefact number -> the pure function that produces its bytes. Empty today, and correctly so.

Artefact 2 is `LIVE` and has no entry, because it has no path: `instructions.py` produces a string
delivered on `initialize`, gated by SV2's character cap rather than by a byte-diff. Every other row
is `PENDING`. A `LIVE` row with a path and no renderer is a contradiction `check()` reports.
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


def write(artefact: Artefact, payload: bytes) -> bool:
    """Write `payload` at the artefact's path. Returns whether the bytes changed. The ONLY IO here.

    `newline="\\n"` is 11:487's rule and the reason this is one function rather than a line in each
    renderer: semgrep bans a bare `open(..., "w")` under `omniweave/gen/`, and a ban is only as good
    as the number of places it has to watch.

    Writes nothing when the bytes already match, so a re-run is not a mtime change. That is not
    politeness: `--bless` is a reviewable act (11:486's three rules exist so a diff means something)
    and a no-op write would put every artefact in every diff.
    """
    if artefact.path is None:
        raise ValueError(f"artefact {artefact.number} has no path; it is not a file")
    target = REPO_ROOT / artefact.path
    if target.exists() and normalise(target.read_bytes()) == normalise(payload):
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(payload.decode("utf-8"))
    return True


def check() -> tuple[str, ...]:
    """Every finding, in artefact order. `()` is `ow surface emit --check` passing. Gate G25.

    Four clauses, and the third is the one that is a gate today:

    1. a `LIVE` artefact with a path whose renderer is missing -- the register claiming a
       capability the code does not have;
    2. a `LIVE` artefact whose committed bytes differ from its rendered bytes, CRLF-normalised on
       both sides;
    3. a `PENDING` artefact with a file committed at its path -- the LEANN shape, and the reason
       this function is worth having before six of the renderers are written;
    4. a `LIVE` artefact with a path and no committed file at all, which is a `--bless` nobody ran.

    Reads and does not write, so `--check` in CI cannot repair the thing it is measuring.
    """
    findings: list[str] = []
    for artefact in ARTEFACTS:
        if artefact.path is None:
            continue
        target = REPO_ROOT / artefact.path
        payload = render(artefact)
        if artefact.state is State.PENDING:
            if payload is not None:
                findings.append(
                    f"{artefact.path}: PENDING, yet a renderer produced bytes for it -- "
                    f"promote the row to LIVE in gen/artefacts.py"
                )
            if target.exists():
                findings.append(
                    f"{artefact.path}: committed, but no renderer produces it. "
                    f"A hand-written agent-facing artefact is INV-20's defect (G25); "
                    f"delete it or land {artefact.lands_with}"
                )
            continue
        if payload is None:
            findings.append(
                f"{artefact.path}: LIVE in gen/artefacts.py and no renderer is registered"
            )
        elif not target.exists():
            findings.append(f"{artefact.path}: LIVE and rendered, but nothing is committed there")
        elif normalise(target.read_bytes()) != normalise(payload):
            findings.append(f"{artefact.path}: differs from what the generator produces")
    return tuple(findings)


def emit() -> tuple[str, ...]:
    """Write every `LIVE` artefact that has a path. Returns the paths that changed, in order.

    `ow surface emit` with no flag, and `--bless` is the same call: 11:486 makes blessing a
    reviewable act rather than a separate mechanism, so there is one writer and the review is the
    diff it leaves.
    """
    changed: list[str] = []
    for artefact in ARTEFACTS:
        if artefact.path is None or artefact.state is not State.LIVE:
            continue
        payload = render(artefact)
        if payload is not None and write(artefact, payload):
            changed.append(artefact.path)
    return tuple(changed)
