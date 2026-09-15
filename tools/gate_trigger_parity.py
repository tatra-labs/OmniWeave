"""RT8's parity check: `route_decision_monotone` and `OW-P-005` must agree, pair by pair.

`uv run tools/gate_trigger_parity.py` is 16-roadmap.md:637's P5 exit-criteria line, spelled there
as "SQL trigger vs compiler rejection". W5.4 is the work item and its estimation basis is the whole
argument in one sentence (16:606): *"SQLite prohibits a subquery in a `CHECK`, so the constraint
must be a trigger -- and two enforcers need one truth, which is the parity test."*

INV-13's `S` half is the trigger and its `L` half is the loader. 01-principles.md:399:

> **Enforced by.** `S` -- a generated `BEFORE INSERT` trigger on the parent join
> (`route_decision_monotone`, raising `OW-R-030`), because SQLite prohibits a subquery in a `CHECK`,
> with CI parity against the policy compiler's rejection of a backward `escalate_to`.

RT8 (05:3348) says the same thing from the other side and adds the word this gate exists for: the
compiler's rejection *"is CI parity for the charter's `route_decision_monotone` trigger **rather
than a second opinion**"*. A second opinion is two enforcers that may differ; parity is two
enforcers that may not. Nothing but a test can tell them apart, because both are correct in
isolation and the failure is only ever visible in the difference.

WHAT IS COMPARED, AND OVER WHAT
-------------------------------
Both enforcers answer the same yes/no question about an ordered pair of rungs, and this gate asks
each of them the question 49 times -- every `(parent, child)` over the seven-member ladder:

* the **trigger** is asked by inserting a parent `route_decision` row at `parent`, then a child row
  at `child` carrying `parent_decision_id`. `RAISE(ABORT, 'OW-R-030 ...')` is the rejection.
* the **compiler** is asked by loading a one-rule policy whose rule sits at `parent` and whose
  `then.escalate_to` is `child`. `RouteError` carrying `OW-P-005` is the rejection.

A pair on which the two disagree is a finding, in either direction, and both directions matter for
different reasons. A pair the trigger rejects and the compiler accepts ships a policy that compiles
and then fails at insert time, in production, after the driver has already run -- INV-13 held, but
by the enforcer that costs the most to hit. A pair the compiler rejects and the trigger accepts is
worse: a hand-written `INSERT`, a migration backfill or a future writer that does not go through
`load_layer()` puts a non-monotone escalation in the store, and `ow why` then explains a chain that
INV-13 says cannot exist.

THREE MORE PROPERTIES, EACH OF WHICH WOULD MAKE THE 49 COMPARISONS VACUOUS
--------------------------------------------------------------------------
1. **A root decision is never rejected.** The trigger's `WHEN NEW.parent_decision_id IS NOT NULL`
   guard means a row with no parent is outside its subject. Seven more inserts, one per rung, with
   a NULL parent -- and the honest statement of what they add is that they LOCALISE rather than
   that they catch something the pairs cannot. A pair probe inserts a parent first, and that parent
   is itself a root, so a guard that fires on parentless rows makes every pair look rejected: the
   gate would be red, at 21 findings, all of them naming the child row and none of them true. The
   root check turns that into one sentence per rung saying which insert actually failed.
2. **The `CHECK` the plan says is impossible really is.** 05:2705 is unusually specific: *"it CANNOT
   be a `CHECK`: 'subqueries prohibited in CHECK constraints' (verified on SQLite 3.45.1), so the
   DDL that tried was unrunnable and would have left the routing migration unapplied with INV-13
   unenforced."* That is a claim about the interpreter this gate is already running on, so it is
   checked rather than quoted: the gate tries to create the table the plan says will not create, and
   fails if SQLite accepts it. A SQLite that started allowing the subquery would not break anything
   -- but it would mean the reason the trigger exists had stopped being true, and a reader deserves
   to learn that from a gate rather than from a rewrite.
3. **`skip_rungs` has no trigger counterpart, and the gate says so rather than implying parity.**
   RT8's sentence (05:3348) covers two compiler rejections -- *"a backward `escalate_to` and a
   `skip_rungs` member at or below the rule's own rung"* -- and only the first has a row to
   reject. Skipping a
   rung writes nothing, so there is no `INSERT` for a trigger to see. The `skip_rungs` matrix is
   still computed and printed, as the compiler's verdict with the trigger column reading `n/a`:
   omitting it would leave a reader believing this gate covers all of RT8.

WHY THIS GATE OPENS A DATABASE AND IMPORTS FIRST-PARTY
-------------------------------------------------------
INV-17 restricts `import sqlite3` to `omniweave_core/store/` and `tools/gate_migrations.py` takes
the same exemption in the same shape: the ban's subject is production code reaching for a second
connection to a store, and this gate opens no store. It applies the committed DDL to a scratch file
that is deleted before it returns, and the alternative -- reading the trigger's SQL text and
reasoning about `<=` -- is not a weaker version of this check but a different one, which would pass
on a trigger whose `WHEN` clause never fires.

The first-party import is the point of the gate rather than a convenience. Parity means the
**shipped** rejection, so asking a re-implementation of `_check_forward()` would compare the trigger
against a copy and leave the real loader untested. `tools/gate_migrations.py`'s docstring makes the
same argument for `MIN_SQLITE` and `SCHEMA_STRING`: a number that is single-homed on purpose is read
from its home.

EXIT CODES
----------
`0` parity holds. `1` at least one pair disagrees, or one of the three properties above fails. `2`
the gate did not run -- no migration directory, or `omniweave.route` not importable -- which is
`tools/gate_migrations.py`'s `EXIT_NOT_RUN` convention and not a pass.
"""

from __future__ import annotations

import argparse
import sqlite3  # noqa: TID251 -- RT8's subject is a trigger, and a trigger has to be run.
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TextIO

REPO = Path(__file__).resolve().parents[1]

MIGRATIONS = (
    REPO
    / "packages"
    / "omniweave-core"
    / "src"
    / "omniweave_core"
    / "store"
    / "schema"
    / "migrations"
)
"""Same constant, same location and same reasoning as `tools/gate_migrations.py:146` and
`tools/gate_schema_lint.py`'s -- D12 rules the migrations are package data under
`omniweave_core/store/`, and a third spelling of the path is a third thing to get wrong."""

TRIGGER = "route_decision_monotone"
CODE_SQL = "OW-R-030"
CODE_COMPILER = "OW-P-005"

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

_CHECK_DDL = """
CREATE TABLE _check_probe (
    decision_id TEXT PRIMARY KEY,
    parent_decision_id TEXT,
    rung INTEGER NOT NULL
        CHECK (parent_decision_id IS NULL
               OR rung > (SELECT rung FROM _check_probe WHERE decision_id = parent_decision_id))
)
"""
"""The DDL 05:2705 says is unrunnable, written as the migration would have had to write it.

Not committed anywhere and never applied to a real database: it exists to be refused. Property 2
runs it against the same interpreter the rest of the gate uses, so the trigger's justification is
measured on this machine rather than taken from a parenthetical about SQLite 3.45.1."""


@dataclass(frozen=True, slots=True)
class Verdict:
    """One enforcer's answer for one `(parent, child)` pair."""

    rejected: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Finding:
    """A disagreement, or a property that did not hold. `where` is the pair or the property name."""

    clause: str
    where: str
    detail: str


# --------------------------------------------------------------------------------------------
# 1. The trigger, asked by inserting rows.
# --------------------------------------------------------------------------------------------


def _apply(db: sqlite3.Connection) -> None:
    """Apply every committed migration in name order, then turn foreign keys on.

    Every migration and not only `0004_runtime.sql`: `route_decision` carries a `REFERENCES` into
    `route_evidence` and the runtime file's own earlier statements, and applying one file out of a
    dense set is exactly the forward reference `G27(b)` exists to catch. Borrowing its ordering here
    keeps this gate from passing on a set that one does not.
    """
    for path in sorted(MIGRATIONS.glob("[0-9]*.sql")):
        db.executescript(path.read_text(encoding="utf-8"))
    db.execute("PRAGMA foreign_keys = ON")


_ROW = (
    "INSERT INTO route_decision (decision_id, content_sha256, unit_part, lane, rung, "
    "policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class, "
    "rule_id, rule_origin, slice_key, parent_decision_id, evidence_digest, est_spend, "
    "est_micros, reserved_micros, admission, generation, decided_at) "
    "VALUES (?, ?, '', 'text', ?, 'p', 'b', 'h', ?, '', 'free', 'r', 'o', 's', ?, 'ev', "
    "'{}', 0, 0, 'admitted', 1, 0)"
)
"""Every `NOT NULL` column without a default, and nothing else.

`read_set_digest` is parameterised because `route_decision_identity` is a UNIQUE index over eight
columns that are otherwise constant across these 49 inserts -- so without a varying component the
second pair would fail on the index rather than on the trigger, and the gate would report a
rejection the trigger did not make."""


_EVIDENCE = (
    "INSERT OR IGNORE INTO route_evidence (evidence_digest, payload, swept_at, first_seen_at) "
    "VALUES ('ev', NULL, 0, 0)"
)
"""The `route_evidence` row `route_decision.evidence_digest` points at, written as a SWEPT one.

`swept_at` is non-null because the table carries `CHECK ((payload IS NULL) = (swept_at IS NOT
NULL))` (05:2745): a null payload with a null `swept_at` is the shape that constraint exists to
forbid. A swept row is the right stand-in anyway -- this gate asserts nothing about a payload, and
05:2740 says a swept decision *"still names the read set it was taken over; it just cannot be
replayed."*"""


def _integrity(exc: sqlite3.IntegrityError) -> Verdict:
    """`OW-R-030` is a trigger rejection; any other `IntegrityError` is a broken fixture.

    The distinction is the same one `compiler_verdict()` draws for `OW-P-005`, and it is what keeps
    this gate honest: a `NOT NULL` this probe forgot, or a `CHECK` on a neighbouring column, would
    otherwise be reported as the trigger firing -- and the gate would go green on the pairs where
    the trigger is supposed to fire while measuring nothing at all.
    """
    if CODE_SQL not in str(exc):
        raise exc
    return Verdict(rejected=True, detail=str(exc))


def trigger_verdict(db: sqlite3.Connection, parent: int, child: int) -> Verdict:
    """Insert a parent at `parent` and a child at `child`. `rejected` is `RAISE(ABORT)` firing.

    Rolled back either way, so the 49 pairs share one applied schema and leave nothing behind. A
    savepoint rather than a transaction because `executescript()` above already committed, and a
    rollback that discarded the schema would make every pair after the first fail on a missing
    table.
    """
    tag = f"{parent}_{child}"
    db.execute("SAVEPOINT pair")
    try:
        db.execute(_EVIDENCE)
        db.execute(_ROW, (f"dec_p{tag}", "a" * 64, parent, f"rs_p{tag}", None))
        db.execute(_ROW, (f"dec_c{tag}", "a" * 64, child, f"rs_c{tag}", f"dec_p{tag}"))
    except sqlite3.IntegrityError as exc:
        return _integrity(exc)
    finally:
        db.execute("ROLLBACK TO pair")
        db.execute("RELEASE pair")
    return Verdict(rejected=False)


def root_verdict(db: sqlite3.Connection, rung: int) -> Verdict:
    """A decision with no parent, at `rung`. Property 1: never rejected, at any rung."""
    db.execute("SAVEPOINT root")
    try:
        db.execute(_EVIDENCE)
        db.execute(_ROW, (f"dec_r{rung}", "a" * 64, rung, f"rs_r{rung}", None))
    except sqlite3.IntegrityError as exc:
        return _integrity(exc)
    finally:
        db.execute("ROLLBACK TO root")
        db.execute("RELEASE root")
    return Verdict(rejected=False)


def check_refuses_subquery(db: sqlite3.Connection) -> Verdict:
    """Property 2. `rejected` means SQLite refused the `CHECK` -- which is the passing direction."""
    try:
        db.executescript(_CHECK_DDL)
    except sqlite3.OperationalError as exc:
        return Verdict(rejected=True, detail=str(exc))
    db.executescript("DROP TABLE _check_probe")
    return Verdict(rejected=False)


# --------------------------------------------------------------------------------------------
# 2. The compiler, asked by loading a policy.
# --------------------------------------------------------------------------------------------


_RULE = """
surface = "route"
schema = "omniweave.policy/1"
policy_name = "parity"
policy_version = 1

[[rule]]
id = "parity.probe"
rung = "{parent}"
when = {{ key = "unit.bytes", op = "ge", value = 0 }}
then = {{ {then} }}
"""


def compiler_verdict(parent: str, child: str, *, key: str = "escalate_to") -> Verdict:
    """Load a one-rule policy at `parent` escalating to (or skipping) `child`. `OW-P-005` rejects.

    `key` is `escalate_to` for the 49 pairs and `skip_rungs` for the matrix RT8 names beside them.
    Both reach the same `_check_forward()`, which is what makes one function enough to ask both.

    A `RouteError` that is not `OW-P-005` is not a rejection of the pair: it means the probe policy
    itself was malformed, and reporting it as a verdict would turn a broken fixture into a parity
    finding. It propagates.
    """
    from omniweave.route.policy import RouteError, load_layer  # noqa: PLC0415 -- see the docstring

    then = f'escalate_to = "{child}"' if key == "escalate_to" else f'skip_rungs = ["{child}"]'
    raw = _RULE.format(parent=parent, then=then).encode()
    try:
        load_layer(raw, layer="site", origin="parity-probe")
    except RouteError as exc:
        if CODE_COMPILER not in str(exc):
            raise
        return Verdict(rejected=True, detail=str(exc))
    return Verdict(rejected=False)


# --------------------------------------------------------------------------------------------
# 3. The comparison.
# --------------------------------------------------------------------------------------------


def parity(db: sqlite3.Connection) -> tuple[list[Finding], int]:
    """Every pair, both properties, and the `skip_rungs` matrix. Returns findings and pair count."""
    from omniweave.route.rung import Rung  # noqa: PLC0415 -- the gate may run on a broken tree

    findings: list[Finding] = []
    ladder = tuple(Rung)
    for parent in ladder:
        for child in ladder:
            sql = trigger_verdict(db, int(parent), int(child))
            compiled = compiler_verdict(parent.name, child.name)
            if sql.rejected != compiled.rejected:
                findings.append(
                    Finding(
                        clause="escalate_to",
                        where=f"{parent.name} -> {child.name}",
                        detail=(
                            f"{TRIGGER} {'rejects' if sql.rejected else 'accepts'} the row and "
                            f"load_layer() {'rejects' if compiled.rejected else 'accepts'} the "
                            f"rule; RT8 requires one verdict, not two opinions"
                        ),
                    )
                )
            expected = int(child) <= int(parent)
            if sql.rejected != expected:
                findings.append(
                    Finding(
                        clause="monotone",
                        where=f"{parent.name} -> {child.name}",
                        detail=(
                            f"{TRIGGER} {'rejected' if sql.rejected else 'accepted'} a child at "
                            f"rung {int(child)} under a parent at {int(parent)}; INV-13 is "
                            "child.rung > parent.rung"
                        ),
                    )
                )
    findings.extend(_properties(db, ladder))
    return findings, len(ladder) ** 2


def _properties(db: sqlite3.Connection, ladder: Sequence[object]) -> list[Finding]:
    """Properties 1 and 2, plus the `skip_rungs` half that has no trigger to compare against."""
    findings: list[Finding] = []
    for rung in ladder:
        verdict = root_verdict(db, int(rung))  # type: ignore[call-overload]
        if verdict.rejected:
            findings.append(
                Finding(
                    clause="root",
                    where=str(getattr(rung, "name", rung)),
                    detail=(
                        f"{TRIGGER} rejected a decision with no parent: its WHEN guard is "
                        f"`NEW.parent_decision_id IS NOT NULL` and a first decision is outside "
                        f"its subject ({verdict.detail})"
                    ),
                )
            )
    probe = check_refuses_subquery(db)
    if not probe.rejected:
        findings.append(
            Finding(
                clause="check",
                where=f"sqlite {sqlite3.sqlite_version}",
                detail=(
                    "this SQLite ACCEPTED a subquery in a CHECK constraint. 05:2705 says it "
                    "cannot, which is the whole reason INV-13 is enforced by a trigger; the "
                    "justification in the migration's comment has stopped being true here"
                ),
            )
        )
    return findings


def skip_rungs_matrix(ladder: Sequence[object]) -> list[tuple[str, str, bool]]:
    """RT8's second compiler rejection, computed and reported with no trigger column."""
    return [
        (
            str(getattr(parent, "name", parent)),
            str(getattr(child, "name", child)),
            compiler_verdict(
                str(getattr(parent, "name", parent)),
                str(getattr(child, "name", child)),
                key="skip_rungs",
            ).rejected,
        )
        for parent in ladder
        for child in ladder
    ]


# --------------------------------------------------------------------------------------------
# 4. The runner.
# --------------------------------------------------------------------------------------------


def _emit(out: TextIO, message: str = "") -> None:
    print(message, file=out)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gate_trigger_parity",
        description="RT8: route_decision_monotone and OW-P-005 must agree on every rung pair.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print the full verdict matrix, not only the disagreements",
    )
    return parser


def main(argv: Sequence[str] | None = None, *, writer: TextIO | None = None) -> int:
    """`0` parity, `1` a disagreement or a failed property, `2` the gate could not run."""
    args = _parser().parse_args(argv)
    out = writer if writer is not None else sys.stdout
    if not MIGRATIONS.is_dir() or not sorted(MIGRATIONS.glob("[0-9]*.sql")):
        _emit(out, f"trigger-parity NOT RUN  no migrations under {MIGRATIONS}")
        return EXIT_NOT_RUN
    try:
        from omniweave.route.rung import Rung  # noqa: PLC0415 -- see `except` below
    except ImportError as exc:  # pragma: no cover -- a tree without omniweave installed
        _emit(out, f"trigger-parity NOT RUN  omniweave.route is not importable: {exc}")
        return EXIT_NOT_RUN

    with tempfile.TemporaryDirectory() as tmp:
        db = sqlite3.connect(Path(tmp) / "parity.sqlite3")
        try:
            _apply(db)
            findings, pairs = parity(db)
        finally:
            db.close()

    skips = skip_rungs_matrix(tuple(Rung))
    _emit(out, f"trigger-parity  {TRIGGER} ({CODE_SQL})  vs  load_layer() ({CODE_COMPILER})")
    _emit(out, f"  escalate_to   {pairs} ordered rung pairs compared, both directions")
    _emit(out, f"  root rows     {len(tuple(Rung))} rungs, parent_decision_id NULL, none rejected")
    _emit(out, f"  CHECK probe   sqlite {sqlite3.sqlite_version} refuses a subquery in a CHECK")
    _emit(
        out,
        f"  skip_rungs    {sum(1 for *_, hit in skips if hit)} of {len(skips)} rejected by the "
        "compiler; no trigger counterpart, because a skipped rung writes no row",
    )
    if args.verbose:
        _emit(out)
        for parent, child, hit in skips:
            _emit(out, f"    skip_rungs  {parent:8s} -> {child:8s}  {'reject' if hit else 'ok'}")
    _emit(out)
    if findings:
        for finding in findings:
            _emit(out, f"FAIL  {finding.clause:<12} {finding.where}")
            _emit(out, f"      {finding.detail}")
        _emit(out, f"\ntrigger-parity FAIL  {len(findings)} finding(s).")
        return EXIT_FAIL
    _emit(out, "trigger-parity ok  two enforcers, one truth (RT8).")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
