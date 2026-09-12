"""Batch formation, AIMD, crash quarantine and Sequence sessions -- the DECISIONS, not the
mechanisms.

16-roadmap.md:547 gives W4.7 four things and its own estimation basis says why the cell is small:
*"a Batch is invisible to the work table, the spend ledger, the trace and the failure taxonomy, and
visible only as `call`-span attributes -- which is exactly what keeps this item small."* A Batch
adds no table, no status, no span level and no failure class. It is a grouping of rows the claim
already returned, a number that goes up and down, and a rule about when a session may not be split.

## The fork this file is on the far side of, and the direction it took

`_notes/build-defects.md` D103 reports that two cells of 02-architecture.md assign the same three
mechanisms to two different modules. :238's does-NOT column reads *"batching policy, retries and
quarantine decisions -- all `omniweave/run/dispatch.py`'s"*, while :831's S4 cell describes AIMD,
the retry at `batch = 1` and the three-crash quarantine as things `subproc` does. Both are true
under exactly one reading, and D103 states it and asks the plan for the nine words that would make
it a rule: **mechanisms in `omniweave_core.host`; decisions in `omniweave/run/dispatch.py`.**

That is the reading this module ships, and it is the one D103 predicted W4.7 would have to pick:

* `adapt_batch(state, event)` is the mechanism; `AimdRegistry` is the decision -- WHICH state,
  keyed by what, seeded from where, and what the ceiling is when the card declares none.
* `retry_batch_size(event, attempt)` is the mechanism; `BatchPolicy.observe()` is the decision --
  whether a retry is offered at all, and in what order the crash is counted.
* `CrashLedger.record()` is the mechanism; `BatchPolicy` is the decision -- that the ledger is
  written once per batch and reaches `resolve()` through `Policy.quarantined` and no second channel.
* `Worker.invoke()` produces an `InvokeReport`; `fan_out()` is the decision -- that one report
  becomes exactly `len(batch)` per-unit outcomes, which is I24.

Nothing here re-implements a mechanism and nothing there makes a policy choice. A reviewer who
finds arithmetic in this file that is also in `subproc.py` has found a bug in one of them.

## The four Sequence rules, and the one the SQL does not actually guarantee

08-runtime.md section 2.3 gives a Sequence four rules. Three of them transcribe into code that does
what the plan says. The first does not, and the gap is reported rather than papered over.

Rule 1 is *"a Sequence is claimed whole or not at all"*, implemented by passing
`:batch = max(cfg_batch, sequence_len)` to the claim. That widening is **necessary and not
sufficient**. `CLAIM_SQL`'s picked set is `ORDER BY w.priority DESC, w.id LIMIT :batch` over every
claimable row sharing the head's `dispatch_key` -- not over the sequence. A sequence's parts are
claimed together only because the planner inserts them contiguously, so they occupy contiguous
`id`s at one priority; nothing in the statement, the schema or the plan says they must. The moment
some other unit's rows interleave at that priority, `max(cfg_batch, sequence_len)` claims a prefix
of the sequence and the session is split -- which is the exact thing rule 1 exists to prevent, and
it pays `per_session` twice.

So `whole_sequences()` re-checks the property after the claim and hands back the parts of any
sequence that arrived incomplete. That is the fail-closed direction: a released part is claimed
again next poll, at worst a wasted round trip, where a dispatched half-session is a double charge
nothing detects. Filed.

## What is deliberately NOT here

* **The loop.** claim -> admit -> dispatch -> complete -> reap is W4.2's, and `supervisor.py`'s own
  docstring records which half of that cell shipped and which did not. This module is called BY the
  dispatch step and calls nothing.
* **The middleware order.** 08-runtime.md section 2.4 makes `omniweave/run/pipeline.py` the ONLY
  caller of `DriverHost.invoke()`, semgrep-enforced. `with_cache`, `with_budget`, `with_retries`
  and the rest are that file's; a batch reaches the host through them, not through this one.
* **`Degradation`, the type.** 15-observability.md:964-996 is its sole home and
  `omniweave_core/observe/degradation.py` does not exist. Rule 3 needs one
  `Degradation(kind="budget")`, so `REGEN_DEGRADATION_KIND` transcribes the single literal and
  `regen_reprice_message()` writes the sentence, on `subproc.py`'s
  `IsolationShortfall.DEGRADATION_KIND` precedent.
* **The `UnitRef`s.** `WorkRow` carries `unit_uri` and `unit_part` and neither `content_sha256` nor
  `byte_len`; those are the `unit` roster's, which the loop reads. `invocation_units()` pairs a
  batch with a roster and refuses a pairing that is not one-to-one and in order, because
  `RESULT{unit_index}` is an index INTO THE BATCH and that ordering is therefore load-bearing.
* **Anything asynchronous.** Every function here is pure or holds only its own dict. `asyncio` is
  permitted in this package and is not needed: a policy that awaited would be a policy that could
  not be tested without a loop.

Specified in 08-runtime.md sections 2.2 and 2.3, 02-architecture.md sections 3.6 and 5,
12-performance.md section 5.9, 15-observability.md sections 2.1 and 3, and 16-roadmap.md:547
(P4 W4.7).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import ConfigError, RouteError
from omniweave_core.host.subproc import (
    AimdState,
    BatchEvent,
    CrashLedger,
    HostVerdict,
    InvokeReport,
    WorkerKey,
    adapt_batch,
    retry_batch_size,
)
from omniweave_core.operator import ulid
from omniweave_core.work import WorkRow
from omniweave_ports.types import DriverResult, Isolation, UnitRef

if TYPE_CHECKING:  # pragma: no cover -- typing only; nothing here reads a clock or a price.
    from omniweave_core.clock import Clock

    from omniweave.route.spend import Spend

__all__ = [
    "CALL_SPAN_ATTRIBUTES",
    "CONFIG_DIGEST_HEX_LEN",
    "DISPATCH_KEY_HEX_LEN",
    "INVOKE_ID_PREFIX",
    "MAX_SEQUENCE_UNITS",
    "REGEN_DEGRADATION_KIND",
    "SEQUENCE_LEN_SQL",
    "SEQUENCE_MICROS_TOLERANCE",
    "SEQUENCE_RESERVATION_SCOPE",
    "AimdRegistry",
    "Batch",
    "BatchPolicy",
    "BatchVerdict",
    "Deferral",
    "UnitOutcome",
    "apportion_micros",
    "call_attributes",
    "check_apportionment",
    "defer_together",
    "dispatch_key",
    "fan_out",
    "form_batches",
    "invocation_units",
    "new_invoke_id",
    "partial_sequences",
    "regen_reprice_message",
    "sequence_claim_size",
    "session_failure",
    "start_batch",
    "whole_sequences",
]


# =============================================================================================
# 1. `dispatch_key` -- the queue's batching key, and why sixteen characters is enough
# =============================================================================================

DISPATCH_KEY_HEX_LEN: Final = 16
"""`sha256(...)[:16]`. 02-architecture.md:479 and :68, 12-performance.md:1021.

Sixteen hex characters is 64 bits, and the birthday bound puts a first collision around 4.3 billion
distinct keys. The population being hashed is `(driver_id, config_digest, isolation)` triples that
appear in ONE run -- tens, on a corpus with a large roster -- so the truncation needs no second
opinion. It is short because it is denormalised onto every `work` row (02-architecture.md:461), and
a 64-character column would cost four times the bytes to say the same thing."""

CONFIG_DIGEST_HEX_LEN: Final = 64
"""`omniweave_core.identity.config_digest`'s width, checked rather than assumed -- see below."""

_ISOLATIONS: Final[frozenset[str]] = frozenset(member.value for member in Isolation)

_LOWER_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")


def dispatch_key(driver_id: str, config_digest: str, isolation: str) -> str:
    """`sha256(driver_id || config_digest || isolation)[:16]`. 02-architecture.md:479.

    **The three inputs are validated, and that is what makes the bare concatenation safe.** Hashing
    `a || b || c` with no separator is ambiguous in general: `("ab", "c")` and `("a", "bc")` produce
    one string. Here the middle field is exactly `CONFIG_DIGEST_HEX_LEN` characters of lowercase hex
    and the last is a member of a closed three-member vocabulary of which none is a suffix of
    another, so the concatenation parses uniquely from the right and two different triples cannot
    produce one key. The plan writes the concatenation and not the check; the check is what turns
    its `||` from a hope into a property, and it costs one `len()` and one set membership per key.

    Refuses rather than normalises an uppercase digest: `identity.config_digest` emits lowercase,
    and accepting both spellings here would give one configuration two dispatch keys and therefore
    two worker pools -- which is INV-21's *"two spellings of one digest"* exactly.
    """
    if not driver_id:
        raise RouteError(
            "a dispatch key needs a driver id; an op.* row has no driver and no key at all",
            fix="pass the resolved driver_id, or leave work.dispatch_key NULL for an op.* row",
        )
    if len(config_digest) != CONFIG_DIGEST_HEX_LEN or any(
        char not in _LOWER_HEX for char in config_digest
    ):
        raise RouteError(
            f"config_digest must be {CONFIG_DIGEST_HEX_LEN} lowercase hex characters and this is "
            f"{len(config_digest)}: an unchecked width makes the concatenation ambiguous",
            fix="pass omniweave_core.identity.config_digest(...)'s output unmodified",
        )
    if isolation not in _ISOLATIONS:
        raise RouteError(
            f"{isolation!r} is not an Isolation: {sorted(_ISOLATIONS)}",
            fix="pass the GRANTED isolation, as Isolation(...).value",
        )
    joined = f"{driver_id}{config_digest}{isolation}".encode()
    return hashlib.sha256(joined).hexdigest()[:DISPATCH_KEY_HEX_LEN]


INVOKE_ID_PREFIX: Final = "iv_"
"""The prefix on `INVOKE{invoke_id}`. NOT the plan's -- the plan never prints a format.

`invoke_id` appears in six places (04-driver-system.md:1699-1703's `INVOKE`, `RESULT`, `PROGRESS`
and `CANCEL` rows, 15-observability.md:140's `call` span, 08-runtime.md:2393's shutdown sequence)
and nothing anywhere says what it is, who mints it, or what it must be unique across. Two of those
uses fix the requirements between them: `CANCEL{invoke_id, generation}` has to name one outstanding
`INVOKE` on one worker, and a `call`-span attribute has to be joinable across a whole run's trace.
A ULID satisfies both and is already this codebase's answer for `run_id`
(`omniweave_core.operator.new_run_id`), so `'iv_' + ulid(...)` reuses the minted form rather than
inventing a second one. Reported as a gap, with this as the resolution."""


def new_invoke_id(clock: Clock, entropy: bytes) -> str:
    """`'iv_' + ulid(clock.wall_ns(), entropy)` -- 29 characters, sortable by mint time.

    Both inputs are arguments for `new_run_id`'s reason: a function that read the clock and
    `os.urandom` itself could not be tested for the property that matters, which is that two
    invocations a millisecond apart sort in the order they were issued.
    """
    return INVOKE_ID_PREFIX + ulid(clock.wall_ns(), entropy)


# =============================================================================================
# 2. `Batch` -- the set of claimed rows sharing a `dispatch_key`
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Batch:
    """One `INVOKE`'s worth of claimed rows. glossary.md:432, 08-runtime.md section 2.2.

    *"The set of claimed work rows sharing a `dispatch_key`, sent in one `INVOKE`. Invisible to the
    work table, the spend ledger, the trace and the failure taxonomy; visible only as span
    attributes."*

    **The row order is the wire order and therefore load-bearing.** `RESULT{unit_index}` is an index
    into `INVOKE`'s `units` list (04-driver-system.md:1700), `invoke()` validates it against the
    batch width and kills the worker on an out-of-range one, and `fan_out()` maps index `i` back to
    `rows[i]`. `SqliteStore.claim()` returns its rows sorted `(-priority, id)` precisely so that
    *"priority survives batching"* (08:625) is checkable; preserving that order here is what carries
    the property to the driver.

    Frozen and a tuple, not a list: a batch that could grow after its `invoke_id` was minted would
    be a batch whose `batch_size` span attribute was recorded before its last member joined.
    """

    invoke_id: str
    rows: tuple[WorkRow, ...]

    def __post_init__(self) -> None:
        if not self.invoke_id:
            raise RouteError(
                "a Batch with no invoke_id: CANCEL{invoke_id, generation} would name nothing",
                fix="mint one with new_invoke_id(clock, os.urandom(10))",
            )
        if not self.rows:
            raise RouteError(
                "a Batch with no rows; an INVOKE with no units is refused by the host as well",
                fix="claim at least one work row before forming a batch",
            )
        keys = {row.dispatch_key for row in self.rows}
        if len(keys) > 1:
            raise RouteError(
                f"a Batch spans {len(keys)} dispatch keys: {sorted(str(key) for key in keys)}. "
                f"One batch is one driver, one configuration and one isolation",
                fix="group the claimed rows with form_batches() before constructing a Batch",
            )
        if self.rows[0].dispatch_key is None and len(self.rows) > 1:
            raise RouteError(
                f"{len(self.rows)} rows with a NULL dispatch_key in one batch; a NULL BATCHES "
                f"ALONE (0004_runtime.sql:104-105) because an op.* row has no driver to send to",
                fix="give each op.* row its own Batch; form_batches() does this",
            )

    @property
    def dispatch_key(self) -> str | None:
        """The one key every row shares. `None` for an `op.*` row, which batches alone."""
        return self.rows[0].dispatch_key

    @property
    def driver(self) -> str | None:
        """The one driver. `None` on an `op.*` batch -- the three routing columns are nullable
        together, bound to the `op.` prefix by a CHECK (08-runtime.md:1036)."""
        return self.rows[0].driver

    @property
    def cost_class(self) -> str:
        """One `dispatch_key` is one `cost_class` -- `store/queue.py`'s narrow-claim argument."""
        return self.rows[0].cost_class

    @property
    def service(self) -> str | None:
        """The `call` span's `service` attribute (15-observability.md:140)."""
        return self.rows[0].service

    @property
    def size(self) -> int:
        """`batch_size`, the span attribute. Never a row count in any ledger (I24)."""
        return len(self.rows)

    @property
    def row_ids(self) -> tuple[int, ...]:
        """The `work.id`s, in wire order. What `complete()` is called with, one at a time."""
        return tuple(row.id for row in self.rows)

    @property
    def parts(self) -> tuple[tuple[str, str], ...]:
        """`(unit_uri, unit_part)` per row, in wire order -- the unit span's identity
        (15-observability.md:80). NOT `UnitRef`s: see `invocation_units()`."""
        return tuple((row.unit_uri, row.unit_part) for row in self.rows)

    @property
    def sequence_ids(self) -> tuple[str, ...]:
        """Every distinct non-NULL `sequence_id` in the batch, in first-appearance order."""
        seen: dict[str, None] = {}
        for row in self.rows:
            if row.sequence_id is not None:
                seen.setdefault(row.sequence_id, None)
        return tuple(seen)


def form_batches(rows: Sequence[WorkRow], *, mint: Callable[[], str]) -> tuple[Batch, ...]:
    """Group claimed rows into batches: one per `dispatch_key`, and one EACH for a NULL key.

    A single `claim()` returns a `dispatch_key`-coherent set by construction -- the `head` CTE picks
    one key and the outer UPDATE claims only rows sharing it -- so on the ordinary path this returns
    exactly one batch. It groups anyway, and the reason is the paths that are not a single claim: a
    retry re-forms a batch from rows the dispatcher already holds, and `whole_sequences()` hands
    back a subset. A function that assumed coherence would be a function that could be handed an
    incoherent set by its own module.

    **First-appearance order, not sorted order.** The claim returns `(-priority, id)` and a `dict`
    preserves insertion order, so the highest-priority key's batch comes first and each batch holds
    its rows in the claim's order. Sorting by key would discard `priority DESC` at the batch level,
    which is the mistake 08:625-630 says round-robin over drivers makes.

    `mint` is a callable and not a clock because this function has no business reading one; the
    caller passes `lambda: new_invoke_id(ctx.clock, os.urandom(ULID_ENTROPY_BYTES))`.
    """
    grouped: dict[str, list[WorkRow]] = {}
    solo: list[WorkRow] = []
    order: list[str | int] = []
    for row in rows:
        if row.dispatch_key is None:
            solo.append(row)
            order.append(len(solo) - 1)
            continue
        if row.dispatch_key not in grouped:
            grouped[row.dispatch_key] = []
            order.append(row.dispatch_key)
        grouped[row.dispatch_key].append(row)
    return tuple(
        Batch(invoke_id=mint(), rows=(solo[entry],))
        if isinstance(entry, int)
        else Batch(invoke_id=mint(), rows=tuple(grouped[entry]))
        for entry in order
    )


def invocation_units(
    batch: Batch, roster: Mapping[tuple[str, str], UnitRef]
) -> tuple[UnitRef, ...]:
    """Pair a batch with the `unit` roster, IN BATCH ORDER, refusing a pairing that is not 1:1.

    `WorkRow` carries `unit_uri` and `unit_part`; `UnitRef` additionally carries `content_sha256`
    and `byte_len`, which live on the `unit` table and reach the dispatcher through the loop. The
    refusal is the point: `RESULT{unit_index}` indexes this tuple, so a missing entry does not
    produce a short `INVOKE` -- it produces a batch whose results are attributed to the wrong rows.

    A `UnitRef` whose `(uri, part)` does not match the row it was supplied for is refused for the
    same reason: a roster keyed correctly but holding a mismatched value would silently re-point one
    unit's bytes at another's work row.
    """
    units: list[UnitRef] = []
    for row in batch.rows:
        key = (row.unit_uri, row.unit_part)
        unit = roster.get(key)
        if unit is None:
            raise RouteError(
                f"the roster has no unit for {key!r}, which is row {row.id} of invoke "
                f"{batch.invoke_id}: RESULT{{unit_index}} indexes the batch, so a short units "
                f"list mis-attributes every later result",
                fix="read the unit row for every claimed part before forming the INVOKE",
            )
        if (unit.uri, unit.part) != key:
            raise RouteError(
                f"the roster maps {key!r} to a UnitRef for {(unit.uri, unit.part)!r}",
                fix="key the roster by (UnitRef.uri, UnitRef.part), not by anything derived",
            )
        units.append(unit)
    return tuple(units)


# =============================================================================================
# 3. The batch size: a configured start, a card clamp, and AIMD between them
# =============================================================================================


def start_batch(configured: Mapping[str, int], cost_class: str, *, card_max: int) -> int:
    """`[runtime.claim] batch`, clamped by `card.isolation.batch_max_units`. 08-runtime.md:2587.

    *"the AIMD starting point, clamped by the card"* -- so `min`, and the card may lower the
    configured number and never raise it. An operator who sets `batch.free = 256` against a card
    declaring 32 gets 32; the card is the author's statement about what the driver can hold in
    memory at once, and config is not entitled to overrule it.

    **`card_max = 0` is UNDECLARED, not zero.** `IsolationSpec.batch_max_units` defaults to 0 and
    `card.py` reads a missing key as 0, so a card that says nothing about batching must not clamp to
    nothing. This is more than tidiness: the value returned here becomes `AimdState.card_max`, and
    `adapt_batch`'s recovery arm is `min(state.batch + 1, state.card_max)` -- feeding it a literal 0
    would make twenty clean batches SHRINK the batch to zero, and a zero batch claims no rows while
    looking like it worked.
    """
    if cost_class not in configured:
        raise ConfigError(
            f"[runtime.claim] batch names no value for {cost_class!r}; it has {sorted(configured)}",
            fix="set [runtime.claim] batch = { free = 256, local_compute = 32, billed_api = 8 }",
        )
    start = int(configured[cost_class])
    if start < 1:
        raise ConfigError(
            f"[runtime.claim] batch.{cost_class} = {start}; a batch of no rows is not a batch",
            fix=f"set [runtime.claim] batch.{cost_class} to 1 or more",
        )
    if card_max < 0:
        raise ConfigError(
            f"[isolation] batch_max_units = {card_max} on the card; 0 means undeclared and a "
            f"negative means nothing",
            fix="remove the key, or set [isolation] batch_max_units to a positive integer",
        )
    return start if card_max == 0 else min(start, card_max)


class AimdRegistry:
    """`AimdState` per `(driver_id, config_digest)` -- 08-runtime.md:760's own key.

    The state transition is the mechanism's; WHICH state, and what it is seeded with, is the
    decision, and the seed is the part the plan does not print.

    **The ceiling is the clamped start, not the raw card number.** `adapt_batch` recovers toward
    `state.card_max`, and the only correct value for that field is `start_batch()`'s output: the
    configured start when the card declares no maximum, and the card's maximum when it is the
    smaller of the two. Passing `card.isolation.batch_max_units` straight through would either
    recover to zero on a silent card or recover PAST the operator's configured start on a card
    declaring a larger one -- and an operator who lowered `[runtime.claim] batch.billed_api` to 1
    would watch it climb back to 8 over 140 clean batches.

    **Keyed on `WorkerKey` and NOT on `dispatch_key`.** The two differ by the isolation grant
    (`subproc.py:2336`), and a driver that had to fall back from `inproc` to `subproc` for a missing
    control is the same driver with the same memory behaviour. Splitting its AIMD state in two would
    make each half learn the halving separately.

    There is no eviction and no TTL: the registry is run-scoped, like `CrashLedger`, and its size is
    bounded by the number of distinct `(driver, config)` pairs a run resolves.
    """

    __slots__ = ("_states",)

    def __init__(self) -> None:
        self._states: dict[WorkerKey, AimdState] = {}

    def state(self, key: WorkerKey, *, ceiling: int) -> AimdState:
        """This key's state, seeded at `(ceiling, 0, ceiling)` the first time it is asked for."""
        if ceiling < 1:
            raise ConfigError(
                f"an AIMD ceiling of {ceiling} would start every batch empty",
                fix="pass start_batch(...)'s output, which is 1 or more",
            )
        current = self._states.get(key)
        if current is None:
            current = AimdState(batch=ceiling, clean_streak=0, card_max=ceiling)
            self._states[key] = current
        return current

    def size(self, key: WorkerKey, *, ceiling: int) -> int:
        """The size the next claim of this key should ask for."""
        return self.state(key, ceiling=ceiling).batch

    def observe(self, key: WorkerKey, event: BatchEvent, *, ceiling: int) -> AimdState:
        """Feed one batch's outcome to `adapt_batch` and keep the answer. Returns the new state."""
        adapted = adapt_batch(self.state(key, ceiling=ceiling), event)
        self._states[key] = adapted
        return adapted

    def known(self) -> tuple[WorkerKey, ...]:
        """Every key with a state, in first-seen order. For the manifest, and for tests."""
        return tuple(self._states)


# =============================================================================================
# 4. The verdict one batch earns: a next size, a retry, and possibly a quarantine
# =============================================================================================


@dataclass(frozen=True, slots=True)
class BatchVerdict:
    """What the dispatcher does next, after one `InvokeReport`.

    `retry_at` is `None` on every event but a crash, and `None` on the crash's own retry: 02:831 and
    04:1720-1722 say the batch retries *"once at `batch = 1`"*, and once is the load-bearing word.
    `quarantined` is sticky and run-scoped, so a `True` here is `True` for the rest of the run and
    `resolve()` reads it through `Policy.quarantined`.
    """

    next_batch: int
    clean_streak: int
    retry_at: int | None = None
    quarantined: bool = False

    @property
    def retries(self) -> bool:
        return self.retry_at is not None


class BatchPolicy:
    """The dispatcher's three decisions in one object: how big, retry or not, quarantine or not.

    It holds two pieces of state -- an `AimdRegistry` and a `CrashLedger` -- and both are run-scoped
    with no persistence, because a quarantine is *"for the run"* (04-driver-system.md:1727) and an
    AIMD ceiling learned on yesterday's machine is not a fact about today's.

    The configured numbers are constructor arguments and none is declared here, on `CrashLedger`'s
    own precedent: `config.py` declares the defaults, the caller reads them, and a policy object
    that reached for a config would be a policy object that could not be constructed in a test.
    """

    __slots__ = ("_aimd", "_configured", "_crashes", "_max_sequence_units")

    def __init__(
        self,
        *,
        configured: Mapping[str, int],
        crash_threshold: int = 3,
        crash_window_s: int = 60,
        max_sequence_units: int = 64,
    ) -> None:
        self._configured = dict(configured)
        self._aimd = AimdRegistry()
        self._crashes = CrashLedger(threshold=crash_threshold, window_s=crash_window_s)
        self._max_sequence_units = max_sequence_units

    @property
    def max_sequence_units(self) -> int:
        return self._max_sequence_units

    def ceiling(self, cost_class: str, *, card_max: int) -> int:
        """`start_batch()` over this policy's configured table."""
        return start_batch(self._configured, cost_class, card_max=card_max)

    def size(self, key: WorkerKey, *, cost_class: str, card_max: int) -> int:
        """How many rows the next claim of this driver should ask for."""
        return self._aimd.size(key, ceiling=self.ceiling(cost_class, card_max=card_max))

    def observe(
        self,
        key: WorkerKey,
        event: BatchEvent,
        *,
        cost_class: str,
        card_max: int,
        now_ms: int,
        attempt: int = 0,
    ) -> BatchVerdict:
        """One batch's outcome in, one decision out. The ONLY place the crash ledger is written.

        Order matters and is argued rather than incidental:

        1. **AIMD first**, so the size is adapted even for a driver this crash quarantines. The
           quarantine is per driver and the AIMD state is per `(driver, config)`; a driver that
           comes back under a different configuration should not also have to relearn its size.
        2. **The crash is recorded once**, here, and never by the caller. `CrashLedger.record`
           appends a timestamp, so a second call for one crash counts it twice and quarantines a
           driver in two batches rather than three.
        3. **The retry is offered even when the driver has just been quarantined.** 02:831 puts the
           quarantine at *"three crashes in 60 s"* and the retry at the FIRST crash, and the retry
           at `batch = 1` is what localises the poison unit -- which is the information an operator
           needs precisely when the driver is being taken away. `resolve()` refusing the driver on
           the next PLAN is a different decision from finishing the batch in hand.
        """
        state = self._aimd.observe(key, event, ceiling=self.ceiling(cost_class, card_max=card_max))
        quarantined = key.driver_id in self._crashes.quarantined()
        if event is BatchEvent.DRIVER_CRASHED:
            quarantined = self._crashes.record(key.driver_id, now_ms=now_ms)
        return BatchVerdict(
            next_batch=state.batch,
            clean_streak=state.clean_streak,
            retry_at=retry_batch_size(event, attempt=attempt),
            quarantined=quarantined,
        )

    def quarantined(self) -> frozenset[str]:
        """The set `drivers.resolve.Policy.quarantined` takes. INV-21 allows no second channel."""
        return self._crashes.quarantined()

    def aimd(self) -> AimdRegistry:
        """The registry, for the manifest. Read it; `observe()` is the only writer."""
        return self._aimd


# =============================================================================================
# 5. Sequence sessions -- 08-runtime.md section 2.3's four rules
# =============================================================================================

MAX_SEQUENCE_UNITS: Final = 64
"""`[runtime] max_sequence_units = 64` (08-runtime.md:2606, a key that document introduces).

08:804-805 gives the reason it is bounded at all: *"an unbounded widening defeats `max_inflight`."*
The widened claim is the one place a batch may exceed the configured size, so without a cap a single
5,000-page session would claim 5,000 rows and every admission number derived at preflight would be a
number about nothing."""

SEQUENCE_LEN_SQL: Final = """
SELECT count(*) FROM work
 WHERE sequence_id = :sid AND status IN ('pending','failed_transient')
"""
"""08-runtime.md:801-803, transcribed. The two claimable statuses and no others.

`pending` and `failed_transient` are `CLAIM_SQL`'s own two, which is what makes this count the
number of parts the widened claim could actually take. Counting every part of the sequence instead
-- including the `done` ones -- would widen the claim by the length of a session that is mostly
finished, and a REGEN of one part of a 42-part sequence would ask for 42 rows in order to claim
one."""

SEQUENCE_RESERVATION_SCOPE: Final = "unit"
"""Rule 2: *"One reservation for the session, at `scope = 'unit'`."*

`omniweave_core.budget.SCOPES` holds it and `DIM_SCOPES` decides which dimensions may use it. The
scope is `unit` and not a `sequence` scope of its own because a Sequence *"adds no state machine, no
table and no span level"* (08:822) -- and a session is a contiguous run of one unit's parts, so the
unit IS the session's extent."""

SEQUENCE_MICROS_TOLERANCE: Final = 1
"""I30's second self-check: `Sum(part micros) == session micros +/- 1 micro` (08:818).

`apportion_micros` is in fact EXACT -- the remainder is given away in full rather than dropped -- so
this tolerance is slack the implementation does not use. It is declared at the plan's number anyway,
because the check belongs to I30 and a checker that tightened it to zero would start failing the day
some other apportionment lands that genuinely rounds."""

REGEN_DEGRADATION_KIND: Final = "budget"
"""Rule 3's one literal, from 15-observability.md:968's twenty-seven-member closed vocabulary.

08:813-815 spells the member out -- *"the `Degradation(kind="budget")` message says so"* -- and it
reuses `budget` rather than minting a `sequence` member, which is the same economy
05-ingest-and-routing.md section 6.4 makes when it reuses `budget` for a cost-class clamp. The type
is 15-observability.md's sole property and does not exist yet; this is the literal, not the type."""


def sequence_claim_size(
    configured: int, sequence_len: int, *, max_sequence_units: int = MAX_SEQUENCE_UNITS
) -> int:
    """Rule 1's widening: `max(cfg_batch, sequence_len)`, refusing a session over the cap.

    08:799-803. A `max` and not a sum: a sequence shorter than the configured batch needs no
    widening at all, because the ordinary batch already takes more rows than the session has.

    **The cap is on `sequence_len` and not on the returned size.** 08:804-805 refuses *"a longer
    session"*, and a 42-part session under a `batch.free` of 256 legitimately returns 256. Applying
    the cap to the result would refuse an ordinary free-class claim for having a large configured
    batch, which is not a session at all.

    The refusal names `SEQUENCE_TOO_LONG`, which 08:805 places *"at plan time"* -- the planner is
    where a session that cannot be scheduled should be turned away, before any row exists. It is
    raised here as well and not instead: a dispatcher that widened a claim past the cap because the
    planner had a bug would defeat `max_inflight` silently, and this is the cheaper of the two
    places to find out.
    """
    if sequence_len < 1:
        raise RouteError(
            f"sequence_len is {sequence_len}; a session with no claimable part is not a session",
            fix="count with SEQUENCE_LEN_SQL and skip the widening when it returns 0",
        )
    if sequence_len > max_sequence_units:
        raise RouteError(
            f"a session of {sequence_len} parts is over [runtime] max_sequence_units "
            f"{max_sequence_units}; an unbounded widening defeats [budget] max_inflight",
            symbol="OW_SEQUENCE_TOO_LONG",
            fix=(
                f"raise [runtime] max_sequence_units above {sequence_len}, or lower the policy's "
                f"then.sequence max_parts so the planner mints shorter sessions"
            ),
        )
    if configured < 1:
        raise ConfigError(
            f"[runtime.claim] batch is {configured}; a claim of no rows is not a claim",
            fix="set [runtime.claim] batch.<class> to 1 or more",
        )
    return max(configured, sequence_len)


def partial_sequences(rows: Sequence[WorkRow], *, lengths: Mapping[str, int]) -> tuple[str, ...]:
    """The `sequence_id`s present in `rows` with fewer parts than `lengths` says they have.

    `lengths` is `SEQUENCE_LEN_SQL`'s answer per sequence, read BEFORE the claim. A sequence whose
    count has since grown is not detectable and does not need to be: a part added after the claim
    was not claimable when the claim ran, so the session in hand is the session that existed.

    Returned in first-appearance order so the caller's release is deterministic, and never as a set:
    two runs given the same rows must release the same rows in the same order, which is the same
    determinism requirement rule 4's apportionment has.
    """
    present: dict[str, int] = {}
    for row in rows:
        if row.sequence_id is not None:
            present[row.sequence_id] = present.get(row.sequence_id, 0) + 1
    partial: list[str] = []
    for sequence_id, count in present.items():
        expected = lengths.get(sequence_id)
        if expected is None:
            raise RouteError(
                f"no claimable length was read for sequence {sequence_id!r}, so whether it arrived "
                f"whole cannot be decided",
                fix="count every sequence_id in the claimed set with SEQUENCE_LEN_SQL first",
            )
        if count < expected:
            partial.append(sequence_id)
    return tuple(partial)


def whole_sequences(
    rows: Sequence[WorkRow], *, lengths: Mapping[str, int]
) -> tuple[tuple[WorkRow, ...], tuple[WorkRow, ...]]:
    """Rule 1, enforced after the claim: `(dispatchable, release)`.

    The widened claim is necessary and not sufficient -- the module docstring argues why -- so this
    is the check that makes *"claimed whole or not at all"* true rather than likely. Every part of
    an incomplete session goes in the second tuple; everything else, sequenced or not, goes in the
    first, in the claim's own order.

    A released row is a row whose lease must be given back: it is still `claimed` in the store, and
    a dispatcher that dropped it on the floor would wait out `lease_ms` before the reaper returned
    it. Returning them rather than acting on them is deliberate -- this module makes no store call.
    """
    partial = frozenset(partial_sequences(rows, lengths=lengths))
    keep = tuple(row for row in rows if row.sequence_id not in partial)
    release = tuple(row for row in rows if row.sequence_id in partial)
    return keep, release


@dataclass(frozen=True, slots=True)
class Deferral:
    """One budget denial's blast radius. Rule 2.

    A Sequence defers as one: 08:807-810 says *"a denial defers EVERY part of the Sequence with the
    same `deferred_dim`, and `deferred_sweeper` returns them together"*, so the sweeper that brings
    them back finds the whole session rather than a part of one that cannot run alone.
    """

    row_ids: tuple[int, ...]
    deferred_dim: str
    sequence_id: str | None = None


def defer_together(rows: Sequence[WorkRow], *, deferred_dim: str) -> tuple[Deferral, ...]:
    """Group a denied set into deferrals: one per Sequence, one per unsequenced row.

    The `deferred_dim` is the same string on every member of a session, which is what lets the
    sweeper's `WHERE deferred_dim = ?` return them together. An unsequenced row is its own deferral
    because there is nothing to hold it with.

    First-appearance order again, and the row ids inside a deferral keep the claim's order.
    """
    if not deferred_dim:
        raise RouteError(
            "a deferral with no dimension: deferred_sweeper has nothing to wait on",
            fix="pass the omniweave_core.budget.DIMS member whose headroom the denial named",
        )
    sessions: dict[str, list[int]] = {}
    order: list[Deferral | str] = []
    for row in rows:
        if row.sequence_id is None:
            order.append(Deferral(row_ids=(row.id,), deferred_dim=deferred_dim))
            continue
        if row.sequence_id not in sessions:
            sessions[row.sequence_id] = []
            order.append(row.sequence_id)
        sessions[row.sequence_id].append(row.id)
    return tuple(
        entry
        if isinstance(entry, Deferral)
        else Deferral(row_ids=tuple(sessions[entry]), deferred_dim=deferred_dim, sequence_id=entry)
        for entry in order
    )


def session_failure(rows: Sequence[WorkRow], failure_class: str) -> tuple[tuple[int, str], ...]:
    """Rule 3: one `FailureClass` for the session, one `work` transition per part carrying it.

    08:811-813: *"A session that dies mid-run yields one `FailureClass` and `len(sequence)` `work`
    transitions carrying it -- the Batch invisibility rule (I24) is unchanged."* So this returns
    exactly `len(rows)` pairs and never one, which is the whole content of the rule: a session is
    not a ledger entity, and a reader counting transitions must find one per part whether the parts
    died together or separately.
    """
    if not failure_class:
        raise RouteError(
            "a session failure with no class; every transition names one",
            fix="pass the FailureClass the session's own failure produced",
        )
    return tuple((row.id, failure_class) for row in rows)


def regen_reprice_message(sequence_id: str, *, part: str, parts_in_session: int) -> str:
    """Rule 3's second half, as the one sentence a `Degradation(kind="budget")` carries.

    08:812-816: *"a `REGEN` of one part cannot reuse the dead session: the retry re-plans as a fresh
    Sequence of one part, at `per_part` pricing, and the `Degradation(kind="budget")` message says
    so, because a retry silently priced at `per_session` is a cost surprise."*

    The sentence names the amortisation that was lost, because that is the number the operator is
    about to see on the bill: a session cost that `parts_in_session` parts were sharing is now
    carried by one retry.
    """
    return (
        f"part {part} re-plans as a session of one after {sequence_id} died mid-run: its "
        f"per_session cost was amortised over {parts_in_session} parts and this attempt pays "
        f"per_part pricing alone"
    )


def apportion_micros(session_micros: int, token_shares: Sequence[int]) -> tuple[int, ...]:
    """Rule 4: split a session's actual cost across its parts by token share. Exact, deterministic.

    08:816-820: *"One spend row per part, with `micros` split from the session actual in proportion
    to that part's `tokens_in + tokens_out` ... Integer division makes the +/-1 real: the remainder
    goes to the highest-token part, deterministically, so two runs apportion identically."*

    Three properties, and every one of them is a test:

    1. **The sum is the session's, exactly.** Each part takes `floor(session * share / total)` and
       the ENTIRE remainder -- at most `len(parts) - 1` micros, not one -- goes to the highest-token
       part. I30 allows +/-1; this gives 0, because the remainder is handed over rather than dropped
       and there is no reason to drop it.
    2. **Ties go to the earliest part.** That is not what the plan says, because the plan does not
       say; two parts with identical token counts have to break the tie somehow, and the first one
       is the only choice that does not depend on iteration order.
    3. **A zero-token session splits evenly.** The proportion is undefined when no part reported a
       token -- a free driver's session, or one that failed before its first call -- and the plan
       does not cover it. Even shares with the remainder to part 0 keeps property 1 true and keeps
       the answer deterministic, which is more than dividing by zero would. Reported as a gap.
    """
    if not token_shares:
        raise RouteError(
            "apportioning a session across no parts",
            fix="pass one token count per part of the sequence, in part order",
        )
    if session_micros < 0:
        raise RouteError(
            f"a session cost of {session_micros} micros; spend is never negative",
            fix="pass the session's actual micros, which PriceBook.micros() floors at zero",
        )
    if any(share < 0 for share in token_shares):
        raise RouteError(
            f"a negative token count in {tuple(token_shares)}",
            fix="pass tokens_in + tokens_out per part, which DriverMetrics floors at zero",
        )
    count = len(token_shares)
    total = sum(token_shares)
    if total == 0:
        shares = [session_micros // count] * count
        target = 0
    else:
        shares = [session_micros * share // total for share in token_shares]
        target = max(range(count), key=lambda index: (token_shares[index], -index))
    shares[target] += session_micros - sum(shares)
    return tuple(shares)


def check_apportionment(session_micros: int, parts: Sequence[int]) -> None:
    """I30's second self-check, as a refusal. 08:818.

    Called by whoever writes the spend rows, against the numbers actually written -- not against
    `apportion_micros`'s return value, which would make the check a tautology over its own output.
    """
    drift = abs(sum(parts) - session_micros)
    if drift > SEQUENCE_MICROS_TOLERANCE:
        raise RouteError(
            f"the {len(parts)} parts of a session sum to {sum(parts)} micros against a session "
            f"actual of {session_micros}: {drift} micros are attributable to no part (I30)",
            fix="apportion with apportion_micros(), which hands the remainder over in full",
        )


# =============================================================================================
# 6. I24 -- one report in, exactly `len(batch)` per-unit outcomes out
# =============================================================================================


@dataclass(frozen=True, slots=True)
class UnitOutcome:
    """One unit's answer, carrying the row it belongs to. Exactly one of the two is populated.

    This is the type that makes I24 true. 08:780-784: *"One `RESULT` frame per unit, one `work`
    transition per unit, one spend row per unit, one `unit` span per unit"* -- so the dispatcher's
    output is a sequence of these and never a batch-shaped object, and every ledger writer
    downstream reads one of these at a time with no way to see the batch it came in.
    """

    row: WorkRow
    result: DriverResult | None = None
    verdict: HostVerdict | None = None

    def __post_init__(self) -> None:
        if (self.result is None) == (self.verdict is None):
            both = "both a result and a verdict" if self.result is not None else "neither"
            raise RouteError(
                f"row {self.row.id} has {both}; a unit answered exactly once, or the batch is "
                f"mis-attributed",
                fix="build these with fan_out(), which synthesises a verdict for a silent unit",
            )


def fan_out(batch: Batch, report: InvokeReport) -> tuple[UnitOutcome, ...]:
    """The invisibility rule, as a function. One `InvokeReport` becomes `batch.size` outcomes.

    08:782-784 states the test this exists to pass: *"a `batch = 32` run with one poison unit
    asserts 32 transitions, 32 spend rows, 32 unit spans and exactly one
    `FAILED_PERMANENT{DRIVER_CRASHED}`."* The count is the property -- a batch that produced 31
    transitions because one unit was never answered for would have made the batch visible in the
    work table, which is exactly what I24 forbids.

    **A unit with neither a result nor a verdict gets a synthesised crash.** `Worker.invoke()`
    already attributes a death to the first unanswered unit, so this path is reached only when a
    host that is not `subproc` returns a short report. Raising instead would turn a driver's silence
    into a dispatcher exception and lose the other 31 answers; `HostVerdict.crashed` with no exit
    status says precisely what is known, which is nothing.

    The widths are checked first and a mismatch is refused, because a report of a different length
    is not a short answer -- it is a report from another batch, and pairing it by index would
    attribute one unit's result to another unit's row.
    """
    if len(report.results) != batch.size or len(report.failures) != batch.size:
        raise RouteError(
            f"invoke {batch.invoke_id} sent {batch.size} units and the report carries "
            f"{len(report.results)} results and {len(report.failures)} failures",
            fix="pair a batch with the report of its own INVOKE; unit_index indexes the batch",
        )
    outcomes: list[UnitOutcome] = []
    for row, result, verdict in zip(batch.rows, report.results, report.failures, strict=True):
        if result is None and verdict is None:
            outcomes.append(
                UnitOutcome(row=row, verdict=HostVerdict.crashed(exit_status=None, stderr_tail=b""))
            )
            continue
        outcomes.append(UnitOutcome(row=row, result=result, verdict=verdict))
    return tuple(outcomes)


# =============================================================================================
# 7. The `call` span -- the ONLY place a batch is visible
# =============================================================================================

CALL_SPAN_ATTRIBUTES: Final[tuple[str, ...]] = (
    "driver",
    "driver_version",
    "driver_schema_v",
    "isolation",
    "invoke_id",
    "batch_index",
    "batch_size",
    "dispatch_key",
    "service",
    "provider",
    "wall_ms",
    "cpu_ms",
    "gpu_ms",
    "tokens_in",
    "tokens_out",
    "calls",
    "bytes_egress",
    "micros",
)
"""15-observability.md:140's `call` row, transcribed in order. EIGHTEEN attributes.

The order is the document's and is kept because the row is a specification a reviewer can diff:
15-observability.md:84 says `batch_index` and `batch_size` are *"attributes on `call`, never rows"*,
and :85 gives the reason the distinction is worth a constant -- *"a Batch is visible for diagnosis
and invisible for accounting (I24). Adding a level is a charter amendment, not a refactor."* The
last eight are the `Spend` vector plus its price, which is what makes a `call` span answerable
without joining to the spend ledger."""


def call_attributes(
    batch: Batch,
    *,
    batch_index: int,
    driver_version: str = "",
    driver_schema_v: int = 0,
    isolation: str = "",
    provider: str = "",
    spend: Spend | None = None,
    micros: int = 0,
) -> Mapping[str, object]:
    """The eighteen, for one `call` span. A mapping, not a span: this module opens nothing.

    `batch_index` is the batch's ordinal WITHIN ITS CLAIM, so a claim that formed three batches
    produces 0, 1 and 2 -- which is what lets a reader of one span know whether the batch it is
    looking at was the whole of a claim or a third of it. The plan names the attribute and not its
    origin; this is the only reading under which `batch_index` and `batch_size` together say
    anything a `dispatch_key` does not already say.

    `spend` is `omniweave.route.Spend` or `None`, and `None` means the seven dimensions are zero
    rather than absent: a `call` span for a free driver has a real `wall_ms` and seven honest zeros,
    and omitting the keys would make a trace consumer branch on whether a driver was billed.
    """
    if batch_index < 0:
        raise RouteError(
            f"batch_index is {batch_index}; it is an ordinal within one claim",
            fix="pass the batch's position in form_batches()'s output",
        )
    values: dict[str, object] = {
        "driver": batch.driver or "",
        "driver_version": driver_version,
        "driver_schema_v": driver_schema_v,
        "isolation": isolation,
        "invoke_id": batch.invoke_id,
        "batch_index": batch_index,
        "batch_size": batch.size,
        "dispatch_key": batch.dispatch_key or "",
        "service": batch.service or "",
        "provider": provider,
        "wall_ms": getattr(spend, "wall_ms", 0),
        "cpu_ms": getattr(spend, "cpu_ms", 0),
        "gpu_ms": getattr(spend, "gpu_ms", 0),
        "tokens_in": getattr(spend, "tokens_in", 0),
        "tokens_out": getattr(spend, "tokens_out", 0),
        "calls": getattr(spend, "calls", 0),
        "bytes_egress": getattr(spend, "bytes_egress", 0),
        "micros": micros,
    }
    return MappingProxyType({name: values[name] for name in CALL_SPAN_ATTRIBUTES})
