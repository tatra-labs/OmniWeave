"""`r1` ... `r7`: the round-trip laws as executable predicates. **D757.**

09-generation.md section 11. Section 11.4: "`omniweave_core/out/roundtrip.py` exposes `r1 ... r7` as
**executable predicates**, imported by `omniweave-conform`'s `target` suite." A predicate takes
the facts a law is stated over, already observed, and returns a `LawResult`. It never compiles,
reads back or projects anything itself, so the suite can feed it a golden fixture, a foreign
artefact or a hand-built counterexample through one door.

## Rulings

1. **A law is judged over observed facts, never over a pipeline it runs.** Each predicate's
   arguments are the nouns of section 11.1's statement: the declared determinism and two
   artefacts' digests (R1); IL elements and read-back blocks (R2); two rounds' BODY blocks (R3);
   outcomes and copied-part digests (R4); construct rows and what the corpus showed (R5);
   unrepresented parts and the ledger (R6); a roster and its outcomes (R7).
2. **Every failure is named, and distinct kinds stay distinct.** Section 11.1 says R2's missing,
   duplicated, kind-mismatched and text-mismatched cases "are each a distinct failure". A
   `Failure` therefore carries a `kind` from its law's closed set, the subject (an `el`, a unit, a
   construct, a part) and a message. A law passes iff it has no failure.
3. **R1 compares exactly the declared classes**, and a declared class that either artefact has no
   digest for is a failure, never a pass: an unmeasured class is not an equal one.
4. **R3 compares sequences, not sets.** The statement's multiset is "in `(page, ord)` order", so
   the BODY blocks of each round are sorted by `(page, ord)` and their digests compared in that
   order. A non-BODY block never takes part.
5. **R4's dependency set is source-refs together with definition dependencies.** A unit whose set
   meets the edit may be anything. A unit whose set is disjoint from the edit may be
   `passthrough` or `patched` (R4(b)'s clause) and never `rebuilt`.
6. **R6 builds the refusal it requires.** `r6()` fails on every unrepresented part without a
   ledger row, and its message is section 11.1's: each unit with its exact part paths, and
   both ways out.
7. **Applicability is the card's, checked against fidelity** (section 11.4). `applicable()`
   reports every law the card does not declare as not applicable, so the claim's weakness is
   visible. It refuses `r4` without `fidelity = "passthrough"`, and `r2` or `r3` with `fidelity =
   "none"`, because those laws are not meaningful there.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from omniweave_core.ident import nfc
from omniweave_core.out.plan import UnitOutcome

__all__ = [
    "FIDELITIES",
    "LAWS",
    "Applicability",
    "Failure",
    "ILElement",
    "LawResult",
    "ReadBlock",
    "RoundBlock",
    "applicable",
    "r1",
    "r2",
    "r3",
    "r4a",
    "r4b",
    "r5",
    "r6",
    "r7",
]

LAWS: Final = ("r1", "r2", "r3", "r4", "r5", "r6", "r7")
FIDELITIES: Final = frozenset({"none", "structure", "passthrough", "patched"})
Fidelity = Literal["none", "structure", "passthrough", "patched"]


@dataclass(frozen=True, slots=True)
class Failure:
    """Ruling 2: one way a law did not hold."""

    kind: str
    subject: str
    msg: str


@dataclass(frozen=True, slots=True)
class LawResult:
    """One law's verdict over one case."""

    law: str
    failures: tuple[Failure, ...] = ()

    @property
    def passed(self) -> bool:
        return not self.failures

    def kinds(self) -> frozenset[str]:
        return frozenset(f.kind for f in self.failures)


def _result(law: str, failures: Iterable[Failure]) -> LawResult:
    return LawResult(law, tuple(sorted(failures, key=lambda f: (f.kind, f.subject))))


# ---------------------------------------------------------------------------
# R1 RETAINED-IL IDENTITY
# ---------------------------------------------------------------------------


def r1(declared: Iterable[str], built: Mapping[str, str], rebuilt: Mapping[str, str]) -> LawResult:
    """`compile(I) =_det A`: equal digests at every declared class, each one measured (ruling 3)."""
    failures = []
    for cls in sorted(set(declared)):
        a, b = built.get(cls), rebuilt.get(cls)
        if a is None or b is None:
            failures.append(Failure("unmeasured", cls, f"class {cls} has no digest to compare"))
        elif a != b:
            failures.append(Failure("differs", cls, f"class {cls}: {a[:19]} is not {b[:19]}"))
    return _result("r1", failures)


# ---------------------------------------------------------------------------
# R2 ADDRESS SURVIVAL
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ILElement:
    """An IL element carrying `data-ow-el`, as R2 reads it."""

    el: str
    construct: str
    visible_text: str
    cites: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class ReadBlock:
    """A read-back Block, as R2 reads it: `x.ow.el`, the kind, the text, `x.ow.cites` (D785)."""

    el: str | None
    kind: str
    text: str | None
    cites: frozenset[str] = frozenset()


def r2(
    elements: Sequence[ILElement], blocks: Sequence[ReadBlock], kind_map: Mapping[str, str]
) -> LawResult:
    """Exactly one Block per element, of the mapped kind, its text and its cites (ruling 2)."""
    by_el: dict[str | None, list[ReadBlock]] = {}
    for block in blocks:
        by_el.setdefault(block.el, []).append(block)
    failures = []
    for e in elements:
        found = by_el.get(e.el, [])
        if not found:
            failures.append(Failure("missing", e.el, f"no read-back Block carries {e.el}"))
            continue
        if len(found) > 1:
            failures.append(Failure("duplicated", e.el, f"{len(found)} Blocks carry {e.el}"))
            continue
        block = found[0]
        want = kind_map.get(e.construct)
        if want is None or block.kind != want:
            failures.append(
                Failure("kind", e.el, f"{e.construct} maps to {want!r}; the Block is {block.kind}")
            )
        if nfc(block.text or "") != nfc(e.visible_text):
            failures.append(Failure("text", e.el, f"the Block's text is not {e.el}'s visible text"))
        if block.cites != e.cites:
            failures.append(
                Failure("cites", e.el, f"cites {sorted(block.cites)} are not {sorted(e.cites)}")
            )
    return _result("r2", failures)


# ---------------------------------------------------------------------------
# R3 SECOND-ROUND FIXED POINT
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoundBlock:
    """One read-back Block of one round, as R3 reads it."""

    page: int
    ord: int
    layer: str
    content_digest: str


def r3(d1: Iterable[RoundBlock], d2: Iterable[RoundBlock]) -> LawResult:
    """Ruling 4: BODY `content_digest`s in `(page, ord)` order, equal across the two rounds."""

    def body(blocks: Iterable[RoundBlock]) -> list[str]:
        kept = sorted((b for b in blocks if b.layer == "body"), key=lambda b: (b.page, b.ord))
        return [b.content_digest for b in kept]

    first, second = body(d1), body(d2)
    if first == second:
        return LawResult("r3")
    at = next(
        (i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b),
        min(len(first), len(second)),
    )
    return _result(
        "r3",
        [
            Failure(
                "not-fixed",
                f"body[{at}]",
                f"round one has {len(first)} BODY blocks and round two {len(second)}; "
                f"they first differ at position {at}",
            )
        ],
    )


# ---------------------------------------------------------------------------
# R4 EDIT LOCALITY
# ---------------------------------------------------------------------------

_COPIED: Final = frozenset({UnitOutcome.PASSTHROUGH, UnitOutcome.CLONED_PASSTHROUGH})


def r4a(outcomes: Mapping[str, UnitOutcome], copied: Mapping[str, tuple[str, str]]) -> LawResult:
    """Zero edits: every unit copied, and each copied part's sha256 equal to its source's."""
    failures = []
    for unit, outcome in sorted(outcomes.items()):
        if outcome not in _COPIED:
            failures.append(Failure("not-copied", unit, f"{unit} is {outcome} after zero edits"))
            continue
        pair = copied.get(unit)
        if pair is None:
            failures.append(Failure("unasserted", unit, f"{unit} has no part digest to compare"))
        elif pair[0] != pair[1]:
            failures.append(
                Failure("bytes-moved", unit, f"{unit}'s copied part is not its source's")
            )
    return _result("r4", failures)


def r4b(
    outcomes: Mapping[str, UnitOutcome],
    dependencies: Mapping[str, frozenset[str]],
    edited: frozenset[str],
) -> LawResult:
    """Ruling 5: a unit whose source-refs and definition deps miss the edit is never rebuilt."""
    failures = []
    for unit, outcome in sorted(outcomes.items()):
        if dependencies.get(unit, frozenset()) & edited:
            continue
        if outcome not in {UnitOutcome.PASSTHROUGH, UnitOutcome.PATCHED}:
            failures.append(
                Failure("not-local", unit, f"{unit} shares nothing with the edit and is {outcome}")
            )
    return _result("r4", failures)


# ---------------------------------------------------------------------------
# R5 DECLARED LOSS, BOTH DIRECTIONS
# ---------------------------------------------------------------------------


def r5(
    *,
    declared_loss: frozenset[str],
    observed_loss: frozenset[str],
    loss_shown: frozenset[str],
    exact: frozenset[str],
    exercised: frozenset[str],
    moved: frozenset[str],
) -> LawResult:
    """Every clause of R5, so `loses = ["*"]` cannot be a green report.

    `declared_loss` is the rows whose `round_trip` is `lossy` or `dropped`; `loss_shown` the ones
    with a fixture where the loss occurs and emits `OW_ROUNDTRIP_LOST`; `exact` the `exact` rows;
    `exercised` the rows the golden corpus uses; `moved` the rows whose payload mutation moved
    `il_digest_rt`.
    """
    failures = [
        Failure("undeclared-loss", c, f"{c} was lost and no row declares it")
        for c in observed_loss - declared_loss
    ]
    failures += [
        Failure("loss-never-shown", c, f"{c} declares a loss no fixture shows")
        for c in declared_loss - loss_shown
    ]
    failures += [
        Failure("exact-unexercised", c, f"{c} is exact and the golden corpus never uses it")
        for c in exact - exercised
    ]
    failures += [
        Failure("exact-invisible", c, f"mutating {c}'s payload does not move il_digest_rt")
        for c in exact - moved
    ]
    return _result("r5", failures)


# ---------------------------------------------------------------------------
# R6 NOTHING SILENTLY DROPPED
# ---------------------------------------------------------------------------


def r6(unrepresented: Mapping[str, Sequence[str]], ledgered: frozenset[str]) -> LawResult:
    """Ruling 6: each unrepresented part has a ledger row, or the refusal names it and the exits.

    `unrepresented` maps a unit (with its source index, `u03 (source slide 5)`) to the part
    paths in it that the IL cannot represent; `ledgered` is the paths carried as opaque
    passthrough assets with a ledger row.
    """
    dropped = {
        unit: sorted(p for p in parts if p not in ledgered)
        for unit, parts in sorted(unrepresented.items())
    }
    dropped = {unit: parts for unit, parts in dropped.items() if parts}
    if not dropped:
        return LawResult("r6")
    lines = [
        "round-trip export would drop source video, audio, or opaque payload relationships:",
        *(f"  unit {unit}: {', '.join(parts)}" for unit, parts in dropped.items()),
        "Keep each listed source unit unedited, or remove the opaque relationship from the source",
        "artefact before importing.",
    ]
    message = "\n".join(lines)
    return _result("r6", [Failure("dropped", unit, message) for unit in dropped])


# ---------------------------------------------------------------------------
# R7 TOTAL CLASSIFICATION
# ---------------------------------------------------------------------------


def r7(units: Sequence[str], outcomes: Mapping[str, UnitOutcome]) -> LawResult:
    """Every output unit in exactly one outcome, and the sum equal to `unit_count`."""
    failures = [
        Failure("unclassified", u, f"{u} has no outcome") for u in units if u not in outcomes
    ]
    failures += [
        Failure("stray", u, f"{u} has an outcome and is not in the roster")
        for u in outcomes
        if u not in set(units)
    ]
    repeated = [u for u, n in Counter(units).items() if n > 1]
    failures += [Failure("repeated", u, f"{u} appears twice in the roster") for u in repeated]
    return _result("r7", failures)


# ---------------------------------------------------------------------------
# Applicability (section 11.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Applicability:
    """Ruling 7: what a card's `laws` claim, and what it leaves visibly unclaimed."""

    applies: tuple[str, ...]
    not_applicable: tuple[str, ...]


_NEEDS: Final[Mapping[str, frozenset[str]]] = {
    "r2": frozenset({"structure", "passthrough", "patched"}),
    "r3": frozenset({"structure", "passthrough", "patched"}),
    "r4": frozenset({"passthrough"}),
}


def applicable(laws: Iterable[str], fidelity: str) -> Applicability:
    """Ruling 7: refuse an unknown law, a fidelity outside the four, a law the tier forbids."""
    if fidelity not in FIDELITIES:
        raise ValueError(f"fidelity {fidelity!r} is not one of {sorted(FIDELITIES)}")
    declared = set(laws)
    unknown = sorted(declared - set(LAWS))
    if unknown:
        raise ValueError(f"laws {unknown} are not {list(LAWS)}")
    for law in sorted(declared):
        tiers = _NEEDS.get(law)
        if tiers is not None and fidelity not in tiers:
            raise ValueError(
                f"{law} is not meaningful at fidelity {fidelity!r}: it needs {sorted(tiers)}"
            )
    return Applicability(
        applies=tuple(law for law in LAWS if law in declared),
        not_applicable=tuple(law for law in LAWS if law not in declared),
    )
