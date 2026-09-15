"""The routing ledger as this package may touch it: three threshold rows, one view, one read set.

W5.5's four tables landed with W2.2's DDL (`0004_runtime.sql`). What W5.5 owes them is the half a
command needs: the `route_threshold` install that 05:2884 makes all-or-refuse, the
`route_scoreboard` read whose `state` column is the gate on `ow route propose`, and the
per-decision read of `route_evidence.payload` that turns a decision log into `fit.Observation`s.

## No `sqlite3` import, and that is INV-17 rather than a style

02:106 marks `store/sqlite.py` *"THE ONLY sqlite3.connect (INV-17)"* and `pyproject.toml` bans the
module everywhere else. So this file takes a connection it never opens, typed against the two
structural protocols below. The protocols are narrow on purpose: `execute` and `in_transaction` are
the whole surface, which is also the whole surface a test needs to fake.

## The install joins a transaction rather than opening one

05:2884, and the clause after the comma is the load-bearing one: *"The policy loader writes all
three `route_threshold` rows in the same transaction that installs `policy_digest`, or refuses to
install."* A function that always opened its own transaction could not honour that sentence -- two
transactions are exactly what it forbids -- so `install_thresholds()` opens one only when the
caller has not, and otherwise writes inside the caller's. When the run-row writer arrives it calls
this between its own `BEGIN` and `COMMIT` and the sentence is satisfied with no second mechanism.

**What has no home is the other half of that transaction.** Nothing on disk installs a
`policy_digest`: `run.policy_digest` is per run, `route_decision.policy_digest` is per decision, and
`meta`'s key list is closed and argued closed (`0001_init.sql:25`). D220.

## Why the three rows are rows, and why there is no Python twin of `state`

*"The thresholds are **rows**, not bind parameters, because a SQLite view may not contain a bind
parameter (verified on 3.45.1)"* (05:2883). That makes the view's text fixed and byte-diff gateable
while its `state` column still moves when the policy does -- and it also means the view is the only
implementation of the three-valued state. INV-23's own list of what a violation looks like
(01:669) ends with *"a scoreboard SQL view that recomputes a threshold instead of reading
`route_threshold` rows"*; a Python reader that recomputed `state` from `audited_n` and `divergence`
would be the same violation facing the other way. So `Rollup.state` is SELECTed. It is never
derived, not even to check the view -- that is what D-12 (15:1525) and the install's refusal are
for, from the side where the *inputs* are missing rather than the side where the arithmetic is
repeated.

## The observation source is the read set, not `route_signal`

`route_signal`'s primary key carries `signal_version` (05:2345), and `read_set_digest` -- 05:2665,
*"over the READ SET ONLY: the (key, provider version, value) triples the winning path
consulted, in read order"* -- is one of
`route_decision_identity`'s eight columns. So two rows of `route_signal` at two versions belong to
two different decisions, and joining a decision to the cache on `(content_sha256, unit_part,
signal_key)` alone would hand the fit a value the decision never read. The per-decision store of
what a decision actually read is `route_evidence.payload`, and that is what `observations()` reads.

The cost of being right about that is a window: evidence blobs age out at 30 days and decision rows
at 400 (05:3009). A swept payload yields no observation, `Log.swept` counts how many, and the
command prints it -- because a fit silently taken over the last thirty days of a four-hundred-day
log is a number whose `n` means something other than what it says. D221.

Specified in 05-ingest-and-routing.md sections 8.2 and 8.3; scheduled by 16-roadmap.md:607.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from omniweave_core.canonical import canonical
from omniweave_core.errors import RouteError

from omniweave.route.fit import Observation

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave.route.evidence import Scalar
    from omniweave.route.policy import RoutePolicy

__all__ = [
    "AUDIT_FIELDS",
    "DEFLATE_LEVEL",
    "STATES",
    "THRESHOLD_KEYS",
    "UNKNOWN",
    "Connection",
    "Cursor",
    "Log",
    "Rollup",
    "install_thresholds",
    "missing_thresholds",
    "observations",
    "payload_bytes",
    "read_set_from",
    "scoreboard",
    "threshold_rows",
    "thresholds",
]

AUDIT_FIELDS: Final[tuple[str, str, str]] = ("min_audit_n", "regress_at", "release_at")
"""The three `[audit]` names the loader reads. 05:2898 prints them with their shipped values --
`'audit.min_audit_n'  30`, `'audit.regress_at'  0.08`, `'audit.release_at'  0.048` -- and the
`[audit]` block at 05:1297-1299 declares them under their unprefixed names."""

THRESHOLD_KEYS: Final[tuple[str, ...]] = tuple(f"audit.{name}" for name in AUDIT_FIELDS)
"""`route_threshold.k` for each. Derived from `AUDIT_FIELDS` rather than written twice: the prefix
is the whole of the mapping, and two lists would be two places to forget a row."""

STATES: Final[tuple[str, str, str]] = ("UNKNOWN", "REGRESSED", "OK")
"""05:2878-2880's three, in the order the view's `CASE` tests them."""

UNKNOWN: Final[str] = STATES[0]
"""The zero value (05:2876). A slice at it yields no proposal at all (05:2995)."""

DEFLATE_LEVEL: Final[int] = 9
"""`deflate(canonical JSON of the read set)` (05:2736) names the codec and not the level. Pinned at
maximum here because the blob is content-addressed by a digest over the CANONICAL JSON rather than
over the compressed bytes, so the level cannot change an address -- it can only change how much of
a 400-day log an operator stores, and a read set is small, repetitive JSON that deflates well."""

_FIX = "uv run ow route lint --strict"
_TRIPLE = 3


# --------------------------------------------------------------------------------------------
# 1. The two structural protocols. A connection this package never opens.
# --------------------------------------------------------------------------------------------


class Cursor(Protocol):
    """What `execute()` returns, narrowed to the one call this module makes.

    `list[Sequence[Any]]` and not `list[tuple[object, ...]]`: a DBAPI row is a sequence of values
    whose types are the column affinities SQLite resolved at read time, and the alternative is a
    cast at every field of every row below. The `Any` is the truth about a database row, and the
    `Rollup` and `Observation` constructors are where it stops being one.
    """

    def fetchall(self) -> list[Sequence[Any]]: ...


class Connection(Protocol):
    """A DBAPI connection opened by `omniweave_core.store.sqlite.connect()` and passed in.

    `in_transaction` is read, never set: it is how `install_thresholds()` decides whether it is
    the outermost writer, which is the whole of 05:2884's "same transaction" clause.
    """

    @property
    def in_transaction(self) -> bool: ...

    def execute(self, sql: str, parameters: Sequence[object] = ..., /) -> Cursor: ...


# --------------------------------------------------------------------------------------------
# 2. The three rows, and the install that is all of them or none.
# --------------------------------------------------------------------------------------------

_UPSERT: Final[str] = (
    "INSERT INTO route_threshold (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v"
)
_SELECT: Final[str] = "SELECT k, v FROM route_threshold ORDER BY k"


def threshold_rows(policy: RoutePolicy) -> tuple[tuple[str, float], ...]:
    """The compiled policy's `[audit]` block as the three rows, or a refusal naming what is missing.

    Three refusals, and all three are the same refusal: a `route_threshold` the loader half-wrote
    is worse than one it did not write at all, because *"A missing threshold row makes the
    comparison NULL, which falls through to `'OK'`"* (05:2887) -- a silent all-clear on a slice
    that may be regressing.

    1. **A missing key.** Named individually, because the operator edits one line.
    2. **A non-numeric value.** `route_threshold.v` is `REAL NOT NULL`; a string stored there keeps
       its text type under SQLite's affinity rules, and the view's `<` against a text value orders
       by TYPE rather than by value -- so every slice would read `UNKNOWN` forever.
    3. **`release_at >= regress_at`.** 05:2973 calls the two a *"hysteresis"* and sets the shipped
       pair at `regress_at` times 0.6, and a release point at or above the regress point is not
       slack -- it is a slice that is REGRESSED and released at the same divergence. The 0.6 itself
       is NOT enforced: it is the shipped value, and 05 states it as arithmetic rather than as a
       constraint, so an operator who wants a wider band may have one.
    """
    rows: list[tuple[str, float]] = []
    for field_name, key in zip(AUDIT_FIELDS, THRESHOLD_KEYS, strict=True):
        if field_name not in policy.audit:
            raise RouteError(
                f"[audit] declares no {field_name}, so route_threshold would be missing {key!r} -- "
                "and a missing row makes route_scoreboard.state NULL, which falls through to 'OK'",
                fix=_FIX,
            )
        value = policy.audit[field_name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise RouteError(
                f"[audit] {field_name} = {value!r} is not a number, and route_threshold.v is "
                "REAL NOT NULL; the view compares a text value to a number by type rather than by "
                "value, so every slice would read UNKNOWN",
                fix=_FIX,
            )
        rows.append((key, float(value)))
    values = dict(rows)
    if values["audit.release_at"] >= values["audit.regress_at"]:
        raise RouteError(
            f"[audit] release_at = {values['audit.release_at']:g} is not below regress_at = "
            f"{values['audit.regress_at']:g}, so a slice would be REGRESSED and released at the "
            "same divergence; 05:2973 sets the shipped pair at regress_at times 0.6",
            fix=_FIX,
        )
    return tuple(rows)


def install_thresholds(conn: Connection, policy: RoutePolicy) -> tuple[tuple[str, float], ...]:
    """Write all three rows in ONE transaction, or write none. Returns what was written.

    `threshold_rows()` raises BEFORE the first `INSERT`, which is what makes "all or none" true
    without a rollback path: the only way to write one row and fail on the second would be a
    refusal this function discovered mid-write, and there is none.

    The transaction is the caller's when the caller has one. 05:2884 asks for these rows and the
    `policy_digest` install to be atomic with each other, so a function that always opened its own
    would have made the sentence unsatisfiable for every caller that also writes something else.
    """
    rows = threshold_rows(policy)
    joined = conn.in_transaction
    if not joined:
        conn.execute("BEGIN IMMEDIATE")
    try:
        for key, value in rows:
            conn.execute(_UPSERT, (key, value))
    except Exception:
        if not joined:
            conn.execute("ROLLBACK")
        raise
    if not joined:
        conn.execute("COMMIT")
    return rows


def thresholds(conn: Connection) -> dict[str, float]:
    """`route_threshold` as a mapping. Every row, not only the three: an unknown `k` is evidence."""
    return {str(row[0]): float(row[1]) for row in _rows(conn.execute(_SELECT))}


def missing_thresholds(conn: Connection) -> tuple[str, ...]:
    """D-12's predicate (15:1525), as a list rather than a boolean.

    *"`route_threshold` holds all three rows (`audit.min_audit_n`, `.regress_at`, `.release_at`)"*,
    and the failure it guards is *"a missing row makes `route_scoreboard.state` fall through to
    `OK`"*. The check belongs to `ow doctor`, which is not this package's; what is this package's
    is the question it asks, so the answer is a value a doctor check can print.
    """
    present = thresholds(conn)
    return tuple(key for key in THRESHOLD_KEYS if key not in present)


# --------------------------------------------------------------------------------------------
# 3. The scoreboard. Ten columns, read and never recomputed.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Rollup:
    """One `route_scoreboard` row: a `(slice_key, rule_id, driver)` rollup and its state.

    **`Rollup` and not `Slice`.** The glossary reserves Slice for the concept -- *"The accounting
    bucket for quality and cost: a **pure function of Evidence**, declared in the policy and capped
    by `max_slices`"* (glossary.md:1031) -- and this is one row of the view's `GROUP BY`, which is
    per `(slice_key, rule_id, driver)` (05:2875). A slice with three rules deciding in it is three
    of these, so a type called `Slice` would make `len(scoreboard(...))` read as a slice count.

    Every field is a column. `divergence` and `escalation_divergence` are `None` where the view's
    `CASE` returned NULL, which means "no audited decision" and "no escalated decision" -- two
    different absences, and both of them different from zero.
    """

    slice_key: str
    rule_id: str
    driver: str
    decisions_n: int
    audited_n: int
    divergence: float | None
    escalation_divergence: float | None
    complaints: int
    micros: int
    state: str

    @property
    def label(self) -> str:
        return f"{self.slice_key}/{self.rule_id}/{self.driver or '-'}"

    def render(self) -> str:
        divergence = "-" if self.divergence is None else f"{self.divergence:.4f}"
        escalation = (
            "-" if self.escalation_divergence is None else f"{self.escalation_divergence:.4f}"
        )
        return (
            f"{self.state:<9} {self.label:<46} n={self.decisions_n:<6} "
            f"audited={self.audited_n:<5} div={divergence:<7} esc={escalation:<7} "
            f"complaints={self.complaints:<4} {self.micros} micros"
        )


_SCOREBOARD: Final[str] = (
    "SELECT slice_key, rule_id, driver, decisions_n, audited_n, divergence, "
    "escalation_divergence, complaints, micros, state "
    "FROM route_scoreboard ORDER BY slice_key, rule_id, driver"
)
"""The view's ten columns, named rather than `SELECT *`, and in `Rollup`'s field order. A `*` would
make the positional unpacking below depend on the order `CREATE VIEW` happens to list them in, and
that order is byte-diff gated (Q-G19) for reasons that have nothing to do with this reader."""


def scoreboard(conn: Connection, *, slice_key: str = "") -> tuple[Rollup, ...]:
    """Every row of the view, or the rows of one slice. Ordered, because a report is diffed.

    The filter is applied HERE and not in SQL, because `route_scoreboard` is a `GROUP BY` over
    `route_decision` and a second `WHERE` outside it would be a second text that has to stay in
    step with the view's own. The result set is bounded by construction: `[slice] max_slices = 512`
    (05:1277) bounds `slice_key`, and a rollup of a bounded key set is bounded.
    """
    rows = tuple(
        Rollup(
            slice_key=str(row[0]),
            rule_id=str(row[1]),
            driver=str(row[2]),
            decisions_n=int(row[3]),
            audited_n=int(row[4]),
            divergence=None if row[5] is None else float(row[5]),
            escalation_divergence=None if row[6] is None else float(row[6]),
            complaints=int(row[7]),
            micros=int(row[8]),
            state=str(row[9]),
        )
        for row in _rows(conn.execute(_SCOREBOARD))
    )
    if not slice_key:
        return rows
    return tuple(row for row in rows if row.slice_key == slice_key)


# --------------------------------------------------------------------------------------------
# 4. The read set on disk, and the decision log a fit reads through it.
# --------------------------------------------------------------------------------------------


def payload_bytes(read_set: Iterable[tuple[str, str, Scalar]]) -> bytes:
    """`deflate(canonical JSON of the read set)` -- 05:2736's `route_evidence.payload`, encoded.

    The triples become a list of three-element lists, which is what `Evidence.read_set_digest()`
    already digests (`[[key, version, value], ...]`). One shape for the digest and the payload, so
    a stored blob and the identity column over it can never describe two different read sets.
    """
    triples = [[key, version, value] for key, version, value in read_set]
    return zlib.compress(canonical(triples), DEFLATE_LEVEL)  # type: ignore[arg-type]


def read_set_from(payload: bytes) -> dict[str, Scalar]:
    """A payload back to `{key: value}`. The provider version is dropped, and deliberately.

    A read set is `(key, provider_version, value)` in read order; what a fit reads is the value of
    one key. The version is why the triple exists -- it is in `read_set_digest`, so two versions of
    one provider are two decisions -- but a caller that has already selected a decision has already
    selected a version, and handing back a second copy would invite a comparison between the two
    that no column asks for. `ow route explain` prints the triples; this returns the reading.
    """
    decoded = json.loads(zlib.decompress(payload).decode("utf-8"))
    if not isinstance(decoded, list):
        raise RouteError(
            f"route_evidence.payload decoded to {type(decoded).__name__}, not the read set's list "
            "of [key, version, value] triples",
            fix="uv run ow store verify",
        )
    reading: dict[str, Scalar] = {}
    for triple in decoded:
        if not isinstance(triple, list) or len(triple) != _TRIPLE:
            raise RouteError(
                f"route_evidence.payload holds {triple!r}, not a [key, version, value] triple",
                fix="uv run ow store verify",
            )
        reading[str(triple[0])] = triple[2]
    return reading


@dataclass(frozen=True, slots=True)
class Log:
    """What `observations()` found, and what it could not use. Both halves, always.

    `swept` and `unread` are not diagnostics. A `Proposal` prints `n` per INV-19, and an `n` drawn
    from a log that silently dropped two thirds of itself is a number that means something other
    than what a reader takes it to mean -- so the two counts travel with the observations and
    `ow route propose` prints them beside every fit.
    """

    observations: tuple[Observation, ...] = ()
    swept: int = 0
    unread: int = 0

    @property
    def n(self) -> int:
        return len(self.observations)

    def render(self) -> str:
        return (
            f"{self.n} observation(s); {self.swept} dropped for a swept payload, "
            f"{self.unread} for a read set that does not name the signal"
        )


_OBSERVATIONS: Final[str] = """
SELECT d.decision_id, e.payload, q.label_sum, q.label_n, COALESCE(sp.micros, 0)
  FROM route_decision d
  JOIN route_evidence e ON e.evidence_digest = d.evidence_digest
  JOIN (SELECT decision_id, SUM(1.0 - agreement) AS label_sum, COUNT(*) AS label_n
          FROM route_quality
         WHERE source IN ('agree','audit') AND agreement IS NOT NULL
         GROUP BY decision_id) q ON q.decision_id = d.decision_id
  LEFT JOIN (SELECT decision_id, SUM(micros) AS micros
               FROM route_spend GROUP BY decision_id) sp ON sp.decision_id = d.decision_id
 WHERE d.slice_key = ? AND d.pinned = 0
 ORDER BY d.decision_id
"""
"""Both one-to-many children pre-aggregated in their own subquery, for the scoreboard's reason
(05:2944): `route_quality` holds up to four rows per decision and `route_spend` one per attempt, so
joining both to `route_decision` in one `FROM` multiplies each by the other's cardinality -- and an
`Observation` whose `micros` had been multiplied by its quality-row count would move the fit.

`pinned = 0` for the view's reason as well (05:2937, *"a pinned decision may not justify a
demotion"*). A pinned decision did not take the branch the rule would have taken, so its label
measures an operator's override rather than the threshold.

`source IN ('agree','audit')`: 05:2990's label is *"`1 - agree.decode_vs_page` on the decisions that
escalated (plus `audit` divergence where present)"*. `self` is excluded wherever anything is scored
(RT12), and `feedback` carries a `polarity` rather than an `agreement` -- its `agreement` is NULL,
which `IS NOT NULL` already drops, and naming the two sources anyway keeps this filter readable
against the view's."""


def observations(
    conn: Connection, *, slice_key: str, signal: str, decisions: Mapping[str, float] | None = None
) -> Log:
    """The decision log of one slice, reduced to the four numbers `fit()` reads.

    `signal` is the evidence key the threshold is compared against -- `ink.coverage`, not
    `ink_coverage_min`. The value comes from the decision's own read set (see the module
    docstring), so a decision whose payload has been swept, or whose read set never reached this
    key, contributes nothing and is counted instead.

    The label is the MEAN of `1 - agreement` over the decision's `agree` and `audit` rows. 05:2990
    adds audit to agree (*"plus `audit` divergence where present"*) rather than preferring one, and
    a mean is the only combination of the two that stays inside `[0, 1]` -- which `ci95()`'s normal
    interval on a mean assumes, and which a sum would leave the moment a decision carried both.

    `decisions` is an optional override for the signal value, keyed by `decision_id`. It exists for
    a caller that has already decoded the payloads for another purpose; it is not a fallback, and a
    decision absent from it still reads its payload.
    """
    found: list[Observation] = []
    swept = unread = 0
    for row in _rows(conn.execute(_OBSERVATIONS, (slice_key,))):
        decision_id = str(row[0])
        value = None if decisions is None else decisions.get(decision_id)
        if value is None:
            if row[1] is None:
                swept += 1
                continue
            raw = read_set_from(bytes(row[1])).get(signal)
            if raw is None or isinstance(raw, bool | str):
                unread += 1
                continue
            value = float(raw)
        label_n = int(row[3])
        found.append(
            Observation(
                signal=value,
                divergence=float(row[2]) / label_n,
                micros=int(row[4]),
                decision_id=decision_id,
            )
        )
    return Log(observations=tuple(found), swept=swept, unread=unread)


def _rows(cursor: Cursor) -> list[Sequence[Any]]:
    """`fetchall()`. One call site for the cursor, so the protocol above stays one method wide."""
    return cursor.fetchall()
