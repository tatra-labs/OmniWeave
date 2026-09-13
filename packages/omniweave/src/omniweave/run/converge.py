"""`op.converge`: the dep delta, the attribution guard, and what `anchor_delta` can honestly be.

`02-architecture.md:75` gives the one-line charter -- *"`run/converge.py` op.converge: the
anchor_delta, the dep delta, the attribution guard"* -- and `07-store-and-retrieval.md:2963` the
full job: the run-final step that *"computes the `anchor_delta`, applies the `dep` reverse index,
re-derives `stat`, runs the per-unit attribution guard and enqueues what changed."*

`16-roadmap.md:546` schedules it as W4.6's second clause. `08-runtime.md` section 5.6 (:1806-1861)
is the specification, and its first sentence is the reason the cell exists at all: this pass
discharges **INV-18** -- an incremental run converges to a full rebuild -- and **must ship before
the watcher**, *"because INV-18 is the invariant a watcher breaks silently"*.

`16-roadmap.md:586`: *"No watcher. `ow watch` does not exist, and `op.converge` shipped here
precisely so that a watcher [can]."*

## The work row

An ordinary `op.*` row: `cost_class = 'free'`, priority **300** (08:619 -- *"a convergence step that
loses to a 300,000-row parse backlog leaves the graph incorrect for hours"*), a NULL `dispatch_key`
so it batches alone (08:755), and corpus granularity whose *"memo is the store"* (08:867). Its three
routing columns are NULL together by CHECK, which is what an `op.*` operator is.

## Three halves, and one of them cannot be honest yet (D177)

`16-roadmap.md:32` states **FE3**, and it names this mechanism in its own list of examples:

> **The recording precedes the mechanism that reads it.** ... `anchor_delta` diffs two `anchor`
> generations. Build the mechanism first and it has nothing to read, so it ships as a stub that
> always reports clean -- which is INV-12's failure mode with a green test suite on top.

`anchor` gets its writer at **W8.2** and `bound_by` its unbind at **W8.3**, both in P8. So at P4 the
symmetric difference of two empty sets is empty for every document -- and `08:1853` says an empty
`anchor_delta` is also what a body-only edit produces, *"the common case, and free"*. The correct
answer and the vacuous one are the same value.

What ships is therefore split:

* **`anchor_delta()` is a pure function** over `(name_norm, akind)` pairs. It needs no table, it is
  tested against 06's own invalidation matrix, and it is correct the day W8.2 supplies input.
* **The disclosure is structural.** `ConvergeReport.anchors_tracked` is `False` with no
  `AnchorSource`, and `ConvergeReport.complete` is `False` with it. That is 07:2949's own device one
  section earlier: `Verdict.freshness`'s `not_tracked`, *"deliberately not a gate: it is disclosed,
  not refused"*.
* **The ADDED retry and the REMOVED unbind are not written here.** The retry reads `ref_unresolved`
  (W8.2's view); the unbind writes `edge.bound_by` and `block_link.bound_by` under a roadmap row
  literally titled *"unbind-on-`anchor_delta`-removal"*. Inventing either would be writing
  statements against tables whose semantics their own cells have not fixed.

The dep half has no such problem: `dep` rows got their producer in the same cell, which is FE3
satisfied rather than violated.

## What "enqueues what changed" means, and why it is cost-class aware

08 section 5.7's `dispatch_policy` is the rule and its heading is the reason: **a watcher may never
bill**. A `free` invalidated row goes back to `pending` and re-derives; a `billed_api` one becomes a
`deferred` row, because *"a watcher that silently re-bills a VLM pass because something touched a
400-page PDF's mtime is the support ticket that ends a pilot"* (08:1877). `local_compute` follows
the trigger: `run_now` under `cli`, deferred to an operator's confirmation otherwise, which is what
`[drivers.cost] auto_refresh_classes = ["free"]` says in config form.

`work.stale_since` is stamped on the **first** transition only and kept across a reset -- 08:1891's
rule for the column, *"because it measures how long the answer has been untrustworthy, not how long
the attempt has run"*. `run/discover.py`'s `MARK_STALE_SQL` carries the same rule for
`unit.stale_since`, and this is the `work`-level writer it named as the re-entry it was deferring
to.

## The attribution guard is named four times and specified nowhere (D178)

`02:75`, `07:2964`, `glossary.md:536` and `16-roadmap.md:546` all name *"the per-unit attribution
guard"*. None of the four says what it does. The mechanism exists in one place only --
`_notes/mine-runtime.md` section 7.6.3, the mining note the settled documents distilled -- and its
two hard edges are transcribed here because they are what makes the guard sound:

> A loss is NEVER accounted by a unit whose derivation FAILED this run. ... *"Files in
> `failed_sources` never account for lost nodes: extraction did not complete, so their disappearance
> is the silent shrink this guard protects."* **A failed operator is the most likely cause of the
> loss, so it must never be accepted as its excuse.**

and the fail-closed rule:

> *"could not read the baseline" and "there is no baseline" are different outcomes.* An
> `except Exception: return {}` around a baseline load turns every downstream safety check into a
> no-op at the exact moment it was needed.

`Baseline` is a tagged type for exactly that reason: `known`, `absent` and `unreadable` are three
states and `if not baseline:` is unrepresentable.

The one thing the note asks for that cannot ship is its failure class. `UNEXPLAINED_LOSS` is not one
of `FailureClass`'s thirteen -- *"the thirteen classes a driver may raise"* -- and this refusal is
not a driver's raise but the host's. 08:1840 settles the analogous case in the runner's favour: a
host-side refusal of a driver's declaration becomes `FAILED_PERMANENT{DRIVER_BUG}`, and
`UNEXPLAINED_LOSS_REASON` is the message that names the offence. The override the note asks for,
`--allow-unexplained-loss`, is not in 02:996's list of named overrides either; it ships as the
`allow` argument, and the flag is D178's to allocate.

Specified in 02-architecture.md:75, 07-store-and-retrieval.md section 11.4 (:2951-2970),
08-runtime.md sections 5.6-5.8 (:1806-1893), 06-structure-extraction.md section 10 (:2273-2340) and
15-observability.md:110.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal, Protocol, TypeAlias

from omniweave_core.deps import invalidate
from omniweave_core.errors import RouteError
from omniweave_core.events import EventKind, Stage
from omniweave_core.store.maintenance import rederive_stat_on
from omniweave_core.store.sqlite import BATCH_WAIT_MS, Unit
from omniweave_ports.types import FailureClass

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave_core.deps import Change, DepIndex
    from omniweave_core.store.sqlite import StoreThread

__all__ = [
    "ACCOUNTED_REASONS",
    "BASELINE_UNREADABLE",
    "CONVERGE_STAGE",
    "DEFER_SQL",
    "OP_CONVERGE",
    "OP_CONVERGE_COST_CLASS",
    "OP_CONVERGE_PRIORITY",
    "OP_CONVERGE_VERSION",
    "REQUEUE_SQL",
    "UNEXPLAINED_LOSS_REASON",
    "AnchorDelta",
    "AnchorSource",
    "Baseline",
    "ConvergeReport",
    "Loss",
    "UnexplainedLoss",
    "anchor_delta",
    "anchor_deltas",
    "attribution_guard",
    "converge",
    "requeue",
    "requeue_params",
]


# --------------------------------------------------------------------------------------------
# 1. The operator. An `op.*` row, and what the DDL's three CHECKs make that mean.
# --------------------------------------------------------------------------------------------

OP_CONVERGE: Final[str] = "op.converge"
"""`work.operator`. One of the five core-only Operators (04:67); `evaluate()` never runs for it."""

OP_CONVERGE_VERSION: Final[int] = 1
"""`work.op_version`. 08:2054's manifest fragment prints `"op_version": 1` for this row."""

OP_CONVERGE_COST_CLASS: Final[str] = "free"
"""08:1810 and 08:2054. `0004_runtime.sql:130-132`: an `op.*` row declares its own cost class.

*"A core-only step invokes no driver; it does not follow that it costs nothing"* -- and this one
genuinely is free: one indexed join, a handful of `UPDATE`s and two `count(*)`s.
"""

OP_CONVERGE_PRIORITY: Final[int] = 300
"""08:619, the same 300 `op.identify` carries, for the opposite reason.

*"A convergence step that loses to a 300,000-row parse backlog leaves the graph incorrect for
hours."* The queue actually orders by it -- `work_claimable` is
`(cost_class, status, retry_after, priority DESC, dispatch_key, id)` -- so the number is a claim
about what runs first rather than a label.
"""

CONVERGE_STAGE: Final = Stage.CONVERGE
"""15:110's Stage: opens on the claim, closes on *"the anchor_delta applied, dependents enqueued"*.

15:112 notes that this Stage may be entered more than once in a run, *"a `converge` pass
re-enqueues `derive` work"*, which is why `stage_entries` sits beside `stage_ms` in the manifest.
"""


# --------------------------------------------------------------------------------------------
# 2. The anchor half -- the pure function, and the disclosure it comes with (D177).
# --------------------------------------------------------------------------------------------

AnchorName: TypeAlias = tuple[str, str]
"""`(name_norm, akind)`. 06:2295 and 08:1848 both fix the pair, in that order.

`akind` is `AnchorKind`'s lower-case member name, the same fourteen `ref_site.akind` holds, which
is the vocabulary `deps.name_key()` builds a `name` dep's key out of.
"""


@dataclass(frozen=True, slots=True)
class AnchorDelta:
    """One document's symmetric difference across a store phase. 06:2295.

    **Per document, and that word is load-bearing.** 06:2296: *"PER DOCUMENT, so a name moving
    between two changed documents does not cancel itself out."* A corpus-wide difference would see
    `figure:3.1` leave `a.pdf` and arrive in `b.pdf` as no change at all, and every reference bound
    to `a.pdf`'s definition would stay bound to a definition that is gone.

    `added` and `removed` are the two halves 06:2297-2299 sends to two different mechanisms: added
    names retry the unresolved set on `ref_site_name`; removed names unbind every `edge` and
    `block_link` carrying that `bound_by`, and **only** a row carrying it, *"because we never delete
    what we cannot restore"*.
    """

    doc: str
    added: tuple[AnchorName, ...]
    removed: tuple[AnchorName, ...]

    @property
    def empty(self) -> bool:
        """06:2301: *"A body-only edit leaves anchor_delta EMPTY -- the common case, and free."*"""
        return not self.added and not self.removed


def anchor_delta(
    doc: str,
    before: Iterable[AnchorName],
    after: Iterable[AnchorName],
) -> AnchorDelta:
    """The symmetric difference of one document's defined names across two generations.

    A set difference and nothing else, which is why it can ship four phases before the table it will
    read: `anchors(D, g)` and `anchors(D, g+1)` are two sets of pairs and the answer is
    `after - before` added, `before - after` removed. `anchor`'s PRIMARY KEY is
    `(doc_ord, gen, name_norm, akind)`, so a generation's pairs are a set in the store too and
    de-duplicating here agrees with the table rather than guessing at it.

    Sorted, so that a delta is a reproducible sequence: the removed half becomes an `IN (:removed)`
    list on `block_link_bound` and `edge_bound`, and two runs over one corpus that ordered it
    differently would produce two query plans and two statement boundaries for one change.
    """
    old = set(before)
    new = set(after)
    return AnchorDelta(doc=doc, added=tuple(sorted(new - old)), removed=tuple(sorted(old - new)))


class AnchorSource(Protocol):
    """What `anchor_deltas()` needs of a store: one document's pairs at one generation.

    Not `runtime_checkable`, like `deps.DepIndex` and `cache.BatchIndex`: a structural check over a
    one-method Protocol passes for anything with the attribute, so the check that matters is the one
    pyright does at the call site.

    **There is no implementation in this distribution, and that is the point of D177.**
    `anchor` has no writer before W8.2, so an `AnchorSource` reading it today would return the
    empty set for every document and let this pass report a clean convergence it did not
    verify.
    """

    def anchors(self, doc: str, gen: int, /) -> frozenset[AnchorName]:
        """The `(name_norm, akind)` pairs `doc` defines at `gen`."""
        ...


def anchor_deltas(
    docs: Sequence[str],
    *,
    source: AnchorSource,
    before_gen: int,
    after_gen: int,
) -> tuple[AnchorDelta, ...]:
    """One delta per document, empty ones included.

    Empty ones included **deliberately**: the count of documents examined is what separates "no
    document's anchors moved" from "no document was examined", and dropping the empties would make
    the two indistinguishable in the report. It is the same distinction `run/discover.py` draws
    between a unit that was walked and found unchanged and a unit that was never reached.
    """
    return tuple(
        anchor_delta(doc, source.anchors(doc, before_gen), source.anchors(doc, after_gen))
        for doc in docs
    )


# --------------------------------------------------------------------------------------------
# 3. The attribution guard (D178).
# --------------------------------------------------------------------------------------------

ACCOUNTED_REASONS: Final[tuple[str, ...]] = (
    "rederived",
    "deleted",
    "out_of_scope",
)
"""The three reasons a lost row is ACCOUNTED. `_notes/mine-runtime.md:6902-6906`, verbatim.

> A loss is ACCOUNTED iff: the unit was re-derived this run by that owner, OR the unit was deleted
> from the corpus, OR the unit went out of scope under an honoured rule.

`out_of_scope` carries 06:2309's explicit/inherited asymmetry with it and this module does not
re-decide it: an `.omniweaveignore` or an explicit `--exclude` is honoured on every refresh, a
`.gitignore`-derived exclusion only on an explicit full run. The caller that marks a unit out of
scope knows which rule did it; a guard that inferred it from the unit would be a second home for
`run/discover.py`'s `SKIP_REASON_CLASSES`.
"""

FAILED_REASON: Final[str] = "failed"
"""The reason that is NEVER accounting, and the starred clause of the guard.

> A failed operator is the most likely cause of the loss, so it must never be accepted as its
> excuse.

It is a member of the reason vocabulary rather than an absence, because a caller must be able
to say *"this unit failed"* and have the guard refuse -- distinctly from saying nothing, which
is a unit the caller did not classify and which the guard also refuses. Two silences with one
meaning would put the guard's soundness in the caller's hands.
"""

BASELINE_UNREADABLE: Final[str] = "baseline_unreadable"
"""The reason on a refusal `allow` cannot lift. See `attribution_guard()`."""

UNEXPLAINED_LOSS_REASON: Final[str] = "unexplained_loss"
"""The `failure_message` prefix on a work row the guard refuses. See the module docstring.

`FailureClass` has thirteen members and none of them is this one; 08:1840's precedent makes a
host-side refusal of a driver's declaration a `FAILED_PERMANENT{DRIVER_BUG}`, so the class is
`driver_bug` and this string is what tells an operator which host-side refusal it was.
"""

GUARD_FAILURE_CLASS: Final = FailureClass.DRIVER_BUG


@dataclass(frozen=True, slots=True)
class Baseline:
    """Rows before, per `(unit_uri, origin_operator)`, as a TAGGED type. The fail-closed rule.

    `_notes/mine-runtime.md:6920`: *"'could not read the baseline' and 'there is no baseline' are
    different outcomes. An `except Exception: return {}` around a baseline load turns every
    downstream safety check into a no-op at the exact moment it was needed."*

    Three states, so `if not baseline:` is unrepresentable:

    * `known` -- `counts` holds the before-picture. A missing key is zero rows, which is a fact.
    * `absent` -- there was no previous run. Nothing can be lost, so nothing can be unexplained.
    * `unreadable` -- the read failed. Every unit is unaccounted, because the alternative is to
      report clean on the one input whose absence the guard exists to notice.

    The same shape as `store/types.py`'s `Narrowing`, whose docstring says the same thing about
    `if candidates:`, and as `Verdict.freshness`'s five values rather than a boolean.
    """

    state: Literal["known", "absent", "unreadable"]
    counts: Mapping[tuple[str, str], int] = field(default_factory=dict)

    @classmethod
    def of(cls, counts: Mapping[tuple[str, str], int]) -> Baseline:
        return cls(state="known", counts=dict(counts))

    @classmethod
    def none(cls) -> Baseline:
        """No previous run. Distinct from an unreadable one, and the distinction is the guard."""
        return cls(state="absent")

    @classmethod
    def unreadable(cls) -> Baseline:
        return cls(state="unreadable")


@dataclass(frozen=True, slots=True)
class Loss:
    """One `(unit_uri, owner)` that holds fewer rows than it did, and why -- or not why."""

    unit_uri: str
    owner: str
    before: int
    after: int
    reason: str

    @property
    def lost(self) -> int:
        return self.before - self.after

    @property
    def accounted(self) -> bool:
        """`FAILED_REASON` is never accounting, and neither is a reason nobody supplied."""
        return self.reason in ACCOUNTED_REASONS


@dataclass(frozen=True, slots=True)
class UnexplainedLoss:
    """A refusal: this unit lost rows and nothing this run explains it.

    `_notes/mine-runtime.md:6908`: *"Unaccounted loss => REFUSE the transaction for that unit, mark
    the work row `failed_permanent`, and record it in the manifest."* Per unit, so *"a refusal
    quarantines one unit instead of aborting the run"*.
    """

    unit_uri: str
    owner: str
    lost: int
    reason: str

    @property
    def message(self) -> str:
        """What lands in `work.failure_message`, naming the offence and the unaccepted excuse."""
        return (
            f"{UNEXPLAINED_LOSS_REASON}: {self.unit_uri} lost {self.lost} row(s) owned by "
            f"{self.owner} and the reason recorded was {self.reason!r}"
        )


def attribution_guard(
    after: Mapping[tuple[str, str], int],
    *,
    baseline: Baseline,
    reasons: Mapping[str, str],
    allow: bool = False,
) -> tuple[UnexplainedLoss, ...]:
    """Per-unit, per-owner: is every lost row attributable to work this run actually did?

    `after` and `baseline.counts` are both `(unit_uri, origin_operator) -> row count`, which is the
    granularity the note insists on and the one `block_owner ON block(unit_uri, unit_part,
    origin_operator)` indexes. graphify's version compared *"one global `len(nodes)` scalar"*, which
    *"is blind to an equal-size swap, ignores edges entirely, and costs O(existing x new) per
    write"*. Per-unit is strictly better on three axes: it detects swaps, it costs O(delta), and a
    refusal quarantines one unit.

    **The owner axis is not decoration.** I4 gives every derived row an `origin_operator` and says
    why in one sentence: *"without this, a free AST/structure re-extraction after a keystroke
    silently deletes every LLM-derived row for that unit -- a free operation destroying billable
    output."* A guard keyed on the unit alone would score that swap as a net zero.

    `reasons` maps `unit_uri` to one of `ACCOUNTED_REASONS`, `FAILED_REASON`, or nothing at all; the
    last two are both refusals and the distinction is only in the message.

    **`allow` accepts a shrink. It does NOT accept an unreadable baseline**, and that is the
    override's scope written down rather than inferred: *"force means 'accept a shrink', not
    'clobber an unreadable graph'"* (graphify, quoted at `_notes/mine-runtime.md:6928`), under the
    rule the same paragraph states -- *"an override flag whose scope is 'skip whatever check just
    complained' is not an override, it is an off switch."* An operator who has looked at a loss and
    decided it is fine has decided about a loss they could see; an unreadable baseline is the case
    where nobody saw anything, so there is nothing for them to have accepted.

    An `absent` baseline returns nothing: there is no before-picture, so no row was lost. An
    `unreadable` one refuses **every** unit in `after`, which is the fail-closed half -- and it
    cannot be reached by accident, because `Baseline.unreadable()` is a constructor a caller has to
    choose.
    """
    if baseline.state == "absent":
        return ()
    if baseline.state == "unreadable":
        return tuple(
            UnexplainedLoss(unit_uri=uri, owner=owner, lost=before, reason=BASELINE_UNREADABLE)
            for (uri, owner), before in sorted(after.items())
        )
    found: list[UnexplainedLoss] = []
    for key, before in sorted(baseline.counts.items()):
        uri, owner = key
        now = after.get(key, 0)
        if now >= before:
            continue
        loss = Loss(
            unit_uri=uri,
            owner=owner,
            before=before,
            after=now,
            reason=reasons.get(uri, ""),
        )
        if loss.accounted or allow:
            continue
        found.append(
            UnexplainedLoss(
                unit_uri=uri, owner=owner, lost=loss.lost, reason=loss.reason or "none recorded"
            )
        )
    return tuple(found)


# --------------------------------------------------------------------------------------------
# 4. Enqueueing what changed. 08 section 5.7, and `stale_since`'s work-level writer.
# --------------------------------------------------------------------------------------------

REQUEUE_SQL: Final[str] = """
UPDATE work
   SET status = 'pending',
       claimed_by = NULL,
       claimed_gen = NULL,
       lease_expires = NULL,
       retry_after = NULL,
       stale_since = COALESCE(stale_since, :now_ms)
 WHERE id = :id
   AND status IN ('done', 'failed_permanent', 'deferred')
"""
"""Re-open one invalidated row. `run_now` in 08:1866's ladder, expressed as a queue transition.

**`COALESCE(stale_since, :now_ms)` is 08:1891's rule, not a micro-optimisation.** *"`stale_since` is
set on the FIRST transition only and is KEPT across a reset, because it measures how long the answer
has been untrustworthy, not how long the attempt has run."* A plain assignment would restart the
clock on every converge pass, and a row that has been wrong for a week would report having been
wrong since the last sweep -- which is the number an operator uses to decide whether to trust an
answer at all. `run/discover.py`'s `MARK_STALE_SQL` carries the identical `COALESCE` for
`unit.stale_since`.

The lease columns are cleared **together**: *"THE CLAIM IS THE LEASE"* (I23, charter.md:4105), so a
pending row holding a `claimed_by` is a row the reaper would count as leased and a second claimer
would refuse. `retry_after` goes too, because a re-derivation ordered by an invalidation is not a
retry of the failure that set it.

The `status IN` guard is what makes this idempotent across two converge passes: a row already
`pending` or `claimed` is being worked, and re-opening it would clear a live lease. `rowcount` is
therefore the honest count of rows this pass actually re-opened.
"""

DEFER_SQL: Final[str] = """
UPDATE work
   SET status = 'deferred',
       claimed_by = NULL,
       claimed_gen = NULL,
       lease_expires = NULL,
       failure_class = NULL,
       failure_message = :message,
       stale_since = COALESCE(stale_since, :now_ms)
 WHERE id = :id
   AND status IN ('done', 'failed_permanent', 'pending')
"""
"""The `billed_api` half of 08:1866, and 08:1877's sentence is the whole argument for it.

> A watcher that silently re-bills a VLM pass because something touched a 400-page PDF's mtime is
> the support ticket that ends a pilot. A billed unit becomes a `deferred` work row plus a
> pending-cost record the operator confirms.

`failure_class` is cleared rather than set: `TRANSITIONS["deferred_budget"]` gives the deferred
status a `null` failure class (08's transition table), because a deferral is a decision and not a
failure, and a `deferred` row carrying `corrupt_input` from a previous attempt would be read as one.
`failure_message` carries the reason so `ow status` can print why the row is waiting.

The pending-cost record itself is **not** written here: 10:2509 and 18:1354 make it `ow add`'s
return value, and 05's `budget.exhausted` write-back is W5.3's. This statement produces the row that
record will describe.
"""


class _Cursor(Protocol):
    """The one attribute the requeue reads back: how many rows the `status IN` guard admitted."""

    @property
    def rowcount(self) -> int: ...


class _Rows(Protocol):
    """The one connection method this module's statements need. `run/expand.py`'s device, verbatim.

    `sqlite3` is banned outside `store/` by `TID251` **and** by G8/G24's
    `omniweave-no-sqlite3-import-outside-store`, which is an AST rule and therefore catches an
    `if TYPE_CHECKING:` import too. So a closure handed to the store thread is annotated against the
    shape it uses rather than against the type it receives; `sqlite3.Connection` satisfies it
    structurally, which is what makes `Unit.run` accept it.
    """

    def execute(self, sql: str, parameters: Mapping[str, object], /) -> _Cursor: ...


def requeue_params(row_id: int, *, now_ms: int, message: str = "") -> Mapping[str, object]:
    """Bind one transition. `now_ms` is the STORE's clock, not a worker's (02 row 23)."""
    return {"id": row_id, "now_ms": now_ms, "message": message}


def requeue(
    thread: StoreThread,
    rows: Mapping[int, str],
    *,
    trigger: str,
    now_ms: int,
    wait_ms: int = BATCH_WAIT_MS,
) -> tuple[int, int]:
    """Re-open or defer each invalidated row by its cost class. Returns `(requeued, deferred)`.

    `rows` maps `work.id` to `cost_class`, which is what the invalidation query's `dependent_id`
    plus one join gives a caller; passing the class in rather than reading it here keeps this
    module's only store access the two `UPDATE`s.

    **One transaction for the batch.** A converge pass that re-opened half its dependents and
    crashed would leave a store that is partly converged and reports nothing about it, and the whole
    claim of INV-18 is that the incremental answer equals the full one. All or nothing.

    `trigger` decides `local_compute`: `run_now` under `cli`, deferred otherwise. That is
    `dispatch_policy`'s second line read together with the two route gates 08:1871 names --
    `gate.watcher-may-not-bill` and `gate.agent-triggered-may-not-bill` clamp `max_cost_class` to
    `local_compute` for `trigger` in `{watch, mcp, sdk}`, so `local_compute` is precisely the class
    whose treatment the trigger changes.

    **No `work.enqueue` event.** Its fields are `(work_id, cost_class, dispatch_key)` and it
    describes a row being written; this statement writes none -- it re-opens rows the planner wrote,
    and it does not read their `dispatch_key`. `dep.invalidate` carries `dependents`, which is the
    event the closed vocabulary already has for exactly this, and `converge()` emits it.
    """
    plan: list[tuple[bool, Mapping[str, object]]] = []
    for row_id, cost_class in sorted(rows.items()):
        if _runs_now(cost_class, trigger):
            plan.append((True, requeue_params(row_id, now_ms=now_ms)))
        else:
            plan.append(
                (
                    False,
                    requeue_params(
                        row_id,
                        now_ms=now_ms,
                        message=f"invalidated by op.converge; cost_class={cost_class}",
                    ),
                )
            )
    if not plan:
        return (0, 0)

    def run(connection: _Rows) -> object:
        opened = 0
        held = 0
        for now, params in plan:
            changed = connection.execute(REQUEUE_SQL if now else DEFER_SQL, params).rowcount
            if now:
                opened += changed
            else:
                held += changed
        return (opened, held)

    moved = thread.run(Unit(name="converge.requeue", run=run, cost_class="free", wait_ms=wait_ms))
    if not isinstance(moved, tuple):  # pragma: no cover -- the closure returns or raises.
        raise RouteError("the converge.requeue unit returned no counts", fix="report this as a bug")
    opened, held = moved
    return (int(opened), int(held))


def _runs_now(cost_class: str, trigger: str) -> bool:
    """08:1866's three lines. `free` always; `billed_api` never unless a human typed it."""
    if cost_class == "free":
        return True
    if cost_class == "local_compute":
        return trigger == "cli"
    return False


# --------------------------------------------------------------------------------------------
# 5. The pass.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConvergeReport:
    """What one `op.converge` pass did, and what it could not check.

    `complete` is the honest verdict and it is `False` while `anchors_tracked` is: a pass that
    applied the dep delta and could not diff a single anchor generation has done half of what
    07:2963 asks, and reporting otherwise is precisely FE3's *"stub that always reports clean"*.
    """

    dependents: frozenset[int]
    requeued: int
    deferred: int
    anchors_tracked: bool
    anchor_deltas: tuple[AnchorDelta, ...]
    unexplained: tuple[UnexplainedLoss, ...]
    stat: Mapping[str, int]

    @property
    def complete(self) -> bool:
        """Both halves ran and nothing was refused."""
        return self.anchors_tracked and not self.unexplained

    @property
    def anchors_moved(self) -> int:
        """Documents whose defined names changed. Zero is a fact only when `anchors_tracked`."""
        return sum(1 for delta in self.anchor_deltas if not delta.empty)


def converge(
    thread: StoreThread,
    delta: Sequence[Change],
    *,
    index: DepIndex,
    cost_classes: Callable[[frozenset[int]], Mapping[int, str]],
    trigger: str,
    now_ms: int,
    now_ns: int,
    anchors: tuple[Sequence[str], AnchorSource, int, int] | None = None,
    guard: tuple[Mapping[tuple[str, str], int], Baseline, Mapping[str, str]] | None = None,
    allow_unexplained_loss: bool = False,
    emit: Callable[..., object] | None = None,
    wait_ms: int = BATCH_WAIT_MS,
) -> ConvergeReport:
    """The run-final step: dep delta, enqueue, anchor delta, guard, `stat`. 07:2963's five.

    The order is 07:2963's own sentence order and it is not arbitrary. The dep delta runs first
    because it is the one that needs the store as the run left it; the guard runs after the requeue
    because a re-opened row is *"the unit was re-derived this run"*, which is an accounting reason;
    and `stat` runs last because 07:721 makes it the count of what is live **after** everything else
    moved, and a corpus size computed mid-pass is the number an over-fetch clamp would be wrong by.

    `anchors` and `guard` are optional tuples rather than four and three loose arguments, so that
    "this pass did not do the anchor half" is one `None` a reader can see instead of a defaulted
    argument they have to notice. `anchors=None` is D177's disclosure and sets
    `anchors_tracked=False`; `guard=None` is a caller that has no row census to offer, which is
    every caller until the derive passes write rows.

    **`stat` re-derivation is `omniweave_core.store.maintenance`'s**, not this module's. 07:721
    gives the table two writers -- *"(`op.converge`) and by `ow index stats`"* -- and the keys are
    the DDL's; `rederive_stat()` was extracted from `repair()`'s step 4 in this cell so that all
    three callers share one home rather than three transcriptions of `live_blocks`.
    """
    dependents = invalidate(delta, index=index)
    if emit is not None and delta:
        emit(
            kind=EventKind.DEP_INVALIDATE,
            fields={
                "kind": ",".join(sorted({change.kind for change in delta})),
                "keys": len(delta),
                "dependents": len(dependents),
            },
        )
    requeued, deferred = requeue(
        thread,
        cost_classes(dependents) if dependents else {},
        trigger=trigger,
        now_ms=now_ms,
        wait_ms=wait_ms,
    )
    deltas: tuple[AnchorDelta, ...] = ()
    if anchors is not None:
        docs, source, before_gen, after_gen = anchors
        deltas = anchor_deltas(docs, source=source, before_gen=before_gen, after_gen=after_gen)
    unexplained: tuple[UnexplainedLoss, ...] = ()
    if guard is not None:
        after, baseline, reasons = guard
        unexplained = attribution_guard(
            after, baseline=baseline, reasons=reasons, allow=allow_unexplained_loss
        )

    written = rederive_stat_on(thread, now_ns=now_ns, wait_ms=wait_ms)
    return ConvergeReport(
        dependents=dependents,
        requeued=requeued,
        deferred=deferred,
        anchors_tracked=anchors is not None,
        anchor_deltas=deltas,
        unexplained=unexplained,
        stat=written,
    )
