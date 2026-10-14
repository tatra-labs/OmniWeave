"""`.oweval`: the evaluation store's schema, its one open and its one write. **D814.**

16-roadmap.md W10.1: *"`.oweval` as a separate SQLite file: `eval_corpus`, `eval_run`,
`eval_assertion`, `eval_verdict`, `eval_metric`, `eval_counter`, `eval_perf`, `eval_calibration`,
`eval_flake`"*. The DDL is the charter's (section D10, *"`.oweval` -- a separate SQLite file"*),
shipped as `schema/oweval/0001_eval.sql`, and the view `eval_scoreboard` is in it.

## Why this is in core, when `ow eval` is omniweave-conform's

ADR-10 decision 4 gives the `eval` Action group to `omniweave-conform`, and 13-quality.md:380 gives
the file one writer, `ow eval import`, writing in **one** transaction. INV-17 puts
`sqlite3.connect` in exactly one module, and G24 bans `import sqlite3`, `BEGIN` and `.commit()`
outside `omniweave_core/store/`. `omniweave.route.ledger` runs its SQL outside the store, inside
a transaction its caller opened; an import opens its own, so the transaction is opened here, and
the schema it writes into ships beside it. The harness builds rows; this module owns the file.

## Rulings

1. **`.oweval` is its own chain**: `schema/oweval/NNNN_<slug>.sql`, versioned by
   `PRAGMA user_version`. It is not in `schema/migrations/`, whose prefixes G27(b) holds to
   `.owstore`'s `1..N`, and `.owstore` writes no `user_version`, so the two files cannot be
   mistaken for each other by it.
2. **It opens through `sqlite.connect()`**, the one connect, whose pragmas are a superset of the
   charter's three (`busy_timeout`, `foreign_keys`, `journal_mode = WAL`). An empty file is
   created: every pending file in one transaction, then `user_version`. A file with a schema and
   no version is not an `.oweval` and is refused, as is one a newer harness wrote, and one whose
   version names tables it does not have.
3. **`eval_perf` takes 12-performance.md section 7.4's columns** and keeps the charter's foreign
   key and CHECK. The SQL file's header is the argument: `peak_wal_bytes`, as 12 spells it twice;
   both peaks NULLable, because a reading not taken is NULL and never 0; and the cascade 13:1720's
   prune runs through.
4. **One write is one transaction.** `write()` inserts a `Batch` between one `BEGIN IMMEDIATE` and
   one `COMMIT`, parents first. A refused row rolls the whole batch back and raises `StoreError`
   naming its table.
5. **Each table's rows go in in primary-key order**, whatever order the batch holds them in.
   13:385 sorts so that the file is *"byte-reproducible regardless of worker scheduling"*; its key,
   `(suite, subject, assertion_id, evaluator)`, is not unique without `run_id`, and the primary key
   is, so the file's bytes depend on the rows and not on who produced them first.
6. **A corpus and its assertions are recorded once, and a repeat must be identical.** 13:1726:
   they *"are the corpus, not the run"*, and every run against one names the same rows. A repeat
   that differs is refused, because a corpus version is immutable. A run is recorded once: a second
   import of a `run_id` is refused, not merged.
7. **A row's Python type is its column's meaning.** Flags are `bool` and go in as 0 or 1.
   `measured_on` is `drivers.card.MeasuredOn`, which refuses a partial record at construction
   (DR14), and goes in as canonical JSON, as do `fairness`, `spec` and every list. A field's
   default is its column's DDL default and nothing else.
8. **`eval_run` carries `not_measured` and `confounders`.** 13 section 11.1 requires both,
   non-empty, on every published row, and names their source as "the run"; the charter's
   `eval_run` has no column for either, so a publish would have nothing to read. They are JSON
   lists defaulting to `[]`: emptiness is `Q-G19`'s to refuse at publish, not this file's at write.

Specified in 13-quality.md sections 2.10, 3, 8.1, 8.7 and 11.4, 12-performance.md section 7.4, and
the charter's section D10.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, fields
from importlib.resources import files
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_core.canonical import canonical
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import StoreError
from omniweave_core.store.sqlite import connect

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from omniweave_core.canonical import JsonValue

__all__ = [
    "EVAL_SCHEMA",
    "EVAL_TABLES",
    "Assertion",
    "Batch",
    "Calibration",
    "Corpus",
    "Counter",
    "Flake",
    "Metric",
    "Perf",
    "Run",
    "Standing",
    "Verdict",
    "open_oweval",
    "runs",
    "scoreboard",
    "user_version",
    "write",
]

SCHEMA_ANCHOR: Final = "omniweave_core.store"
SCHEMA_PARTS: Final = ("schema", "oweval")

EVAL_SCHEMA: Final = 1
"""The newest `schema/oweval/` file's number, which a current file's `user_version` equals."""

EVAL_TABLES: Final = (
    "eval_corpus",
    "eval_run",
    "eval_assertion",
    "eval_verdict",
    "eval_metric",
    "eval_calibration",
    "eval_counter",
    "eval_perf",
    "eval_flake",
)
"""W10.1's nine, in the DDL's order."""

_NAME: Final = re.compile(r"^(?P<number>[0-9]{4})_[a-z0-9_]+\.sql\Z")
_EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})
_JSON_OBJECTS: Final = frozenset({"fairness", "spec"})
_JSON_LISTS: Final = frozenset(
    {"degradations", "not_measured", "confounders", "slices", "label_sources"}
)
_FIX_OPEN: Final = "pass the path of an .oweval file, or of one that does not exist yet"
_FIX_WRITE: Final = "fix the row the message names; nothing from this batch was written"


# --------------------------------------------------------------------------------------------
# 1. The rows: one frozen dataclass per table, named as the DDL names its columns.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Corpus:
    """One `eval_corpus` row: a corpus release and its three independent booleans (13 section
    4.5)."""

    TABLE: ClassVar[str] = "eval_corpus"
    KEY: ClassVar[tuple[str, ...]] = ("corpus_id", "version")

    corpus_id: str
    version: str
    corpus_digest: str
    tier: str
    n_docs: int
    n_assertions: int
    n_checked: int
    document_redistributable: bool
    assertions_redistributable: bool
    publishable: bool


@dataclass(frozen=True, slots=True)
class Run:
    """One `eval_run` row: one evaluation execution and everything that qualifies its numbers."""

    TABLE: ClassVar[str] = "eval_run"
    KEY: ClassVar[tuple[str, ...]] = ("run_id",)

    run_id: str
    suite: str
    corpus_id: str
    corpus_version: str
    corpus_digest: str
    subject: str
    subject_version: str
    producer_id: int | None
    measured_on: MeasuredOn
    timing_basis: str
    witness: str
    cassette: str
    policy_digest: str | None
    pricebook_digest: str | None
    harness_version: str
    code_fingerprint: str
    hardware: str
    started_ns: int
    ended_ns: int | None
    status: str
    unpinned: bool = False
    entrant_bias: bool = False
    fairness: Mapping[str, JsonValue] = _EMPTY
    spend_micros: int = 0
    degradations: tuple[str, ...] = ()
    not_measured: tuple[str, ...] = ()
    confounders: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Assertion:
    """One `eval_assertion` row: olmOCR-Bench's record, generalised (13 section 8.1)."""

    TABLE: ClassVar[str] = "eval_assertion"
    KEY: ClassVar[tuple[str, ...]] = ("assertion_id",)

    assertion_id: str
    corpus_id: str
    corpus_version: str
    doc: str
    page: int | None
    type: str
    spec: Mapping[str, JsonValue]
    addr: str | None
    evaluable_in: str
    checked: str | None
    derived_from_sha256: str
    max_diffs: int = 0
    slices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Verdict:
    """One `eval_verdict` row, the grain everything aggregates from. A pass stores an empty
    explanation (13:1028), which is the column's default."""

    TABLE: ClassVar[str] = "eval_verdict"
    KEY: ClassVar[tuple[str, ...]] = ("run_id", "assertion_id", "evaluator")

    run_id: str
    assertion_id: str
    evaluator: str
    passed: bool
    score: float | None
    slice_key: str
    explanation: str = ""
    wall_ms: int = 0
    micros: int = 0


@dataclass(frozen=True, slots=True)
class Metric:
    """One `eval_metric` row: a number, its interval and method, and a state whose zero value is
    `unknown`."""

    TABLE: ClassVar[str] = "eval_metric"
    KEY: ClassVar[tuple[str, ...]] = ("run_id", "metric", "slice_key")

    run_id: str
    metric: str
    value: float | None
    n: int
    ci_lo: float | None
    ci_hi: float | None
    method: str
    truth_kind: str
    state: str
    slice_key: str = "__macro__"


@dataclass(frozen=True, slots=True)
class Calibration:
    """One `eval_calibration` bucket. `ece` and `brier` are `None` for an ordinal signal."""

    TABLE: ClassVar[str] = "eval_calibration"
    KEY: ClassVar[tuple[str, ...]] = (
        "eval_set_id",
        "score_kind",
        "producer_id",
        "slice_key",
        "bucket",
    )

    eval_set_id: str
    score_kind: str
    producer_id: int
    slice_key: str
    bucket: int
    bucket_lo: float
    bucket_hi: float
    n: int
    n_correct: int
    p_hat: float
    wilson_lo: float
    wilson_hi: float
    ece: float | None
    brier: float | None
    label_sources: tuple[str, ...]
    measured_at_ns: int
    harness_version: str


@dataclass(frozen=True, slots=True)
class Counter:
    """One `eval_counter` row: an exactly reproducible integer."""

    TABLE: ClassVar[str] = "eval_counter"
    KEY: ClassVar[tuple[str, ...]] = ("run_id", "counter", "scope")

    run_id: str
    counter: str
    scope: str
    value: int


@dataclass(frozen=True, slots=True)
class Perf:
    """One `eval_perf` row (ruling 3). A peak not measured is `None`."""

    TABLE: ClassVar[str] = "eval_perf"
    KEY: ClassVar[tuple[str, ...]] = ("run_id", "budget_id")

    run_id: str
    budget_id: str
    pacer_before_ns: int
    pacer_after_ns: int
    work_ns: int
    time_ratio: float
    peak_rss_bytes: int | None
    peak_wal_bytes: int | None
    status: str


@dataclass(frozen=True, slots=True)
class Flake:
    """One `eval_flake` row: a test's runs on one day."""

    TABLE: ClassVar[str] = "eval_flake"
    KEY: ClassVar[tuple[str, ...]] = ("test_id", "day")

    test_id: str
    day: str
    runs: int
    fails: int
    reran_green: int


Row = Corpus | Run | Assertion | Verdict | Metric | Calibration | Counter | Perf | Flake


@dataclass(frozen=True, slots=True)
class Batch:
    """What one import writes, in one transaction (ruling 4)."""

    corpora: tuple[Corpus, ...] = ()
    assertions: tuple[Assertion, ...] = ()
    runs: tuple[Run, ...] = ()
    verdicts: tuple[Verdict, ...] = ()
    metrics: tuple[Metric, ...] = ()
    counters: tuple[Counter, ...] = ()
    perf: tuple[Perf, ...] = ()
    calibration: tuple[Calibration, ...] = ()
    flake: tuple[Flake, ...] = ()


@dataclass(frozen=True, slots=True)
class Standing:
    """One `eval_scoreboard` row: the view's columns, `standing` computed in SQL and never here."""

    run_id: str
    metric: str
    slice_key: str
    suite: str
    subject: str
    subject_version: str
    corpus_id: str
    corpus_version: str
    witness: str
    unpinned: bool
    entrant_bias: bool
    value: float | None
    ci_lo: float | None
    ci_hi: float | None
    n: int
    method: str
    truth_kind: str
    publishable: bool
    standing: str


# --------------------------------------------------------------------------------------------
# 2. Open: create, or recognise, or refuse (ruling 2).
# --------------------------------------------------------------------------------------------


def user_version(connection: sqlite3.Connection) -> int:
    """`PRAGMA user_version`: the `.oweval` schema a file is at, and 0 for a file that is none."""
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def open_oweval(path: Path) -> sqlite3.Connection:
    """Open `path` as an `.oweval`, creating its schema when the file is new or empty."""
    connection = connect(path)
    try:
        _ready(connection, path)
    except BaseException:
        connection.close()
        raise
    return connection


def _ready(connection: sqlite3.Connection, path: Path) -> None:
    """Ruling 2: create the schema on an empty file, or recognise it, or refuse."""
    version = user_version(connection)
    if version > EVAL_SCHEMA:
        raise StoreError(
            f"{path} is .oweval schema {version}, newer than this harness's {EVAL_SCHEMA}",
            fix="upgrade omniweave-core to the release that wrote it",
        )
    if version == 0 and _object_count(connection):
        raise StoreError(
            f"{path} holds a schema and no .oweval version: it is not an .oweval",
            fix=_FIX_OPEN,
        )
    _apply_pending(connection, version)
    missing = [table for table in EVAL_TABLES if not _has_table(connection, table)]
    if missing:
        raise StoreError(
            f"{path} says .oweval schema {EVAL_SCHEMA} and has no {', '.join(missing)}",
            fix=_FIX_OPEN,
        )


def _chain() -> tuple[tuple[int, str, str], ...]:
    """Every `schema/oweval/NNNN_<slug>.sql`, as `(number, name, text)` in numeric order."""
    root = files(SCHEMA_ANCHOR).joinpath(*SCHEMA_PARTS)
    found = []
    for item in root.iterdir():
        match = _NAME.match(item.name)
        if match is not None:
            found.append((int(match["number"]), item.name, item.read_text(encoding="utf-8")))
    found.sort()
    numbers = [number for number, _, _ in found]
    if numbers != list(range(1, EVAL_SCHEMA + 1)):
        raise StoreError(
            f"schema/oweval/ holds {numbers}, not 1..{EVAL_SCHEMA}",
            fix="reinstall omniweave-core; its package data is incomplete",
        )
    return tuple(found)


def _apply_pending(connection: sqlite3.Connection, version: int) -> None:
    """Every file above `version`, then the new `user_version`, in one transaction."""
    pending = [item for item in _chain() if item[0] > version]
    if not pending:
        return
    script = "".join(text for _, _, text in pending)
    try:
        connection.executescript(
            f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {pending[-1][0]};\n"
        )
    except BaseException as error:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        if isinstance(error, sqlite3.Error):
            names = ", ".join(name for _, name, _ in pending)
            raise StoreError(f"{names} did not apply: {error}", fix=_FIX_OPEN) from error
        raise
    connection.execute("COMMIT")


def _has_table(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _object_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0])


# --------------------------------------------------------------------------------------------
# 3. Write: one batch, one transaction, every table in primary-key order (rulings 4-7).
# --------------------------------------------------------------------------------------------


def write(connection: sqlite3.Connection, batch: Batch) -> None:
    """Insert `batch` in one transaction, parents first, or nothing at all."""
    groups: tuple[Sequence[Row], ...] = (
        batch.corpora,
        batch.assertions,
        batch.runs,
        batch.verdicts,
        batch.metrics,
        batch.counters,
        batch.perf,
        batch.calibration,
        batch.flake,
    )
    connection.execute("BEGIN IMMEDIATE")
    try:
        for group in groups:
            for row in sorted(group, key=_key):
                _insert(connection, row)
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


def _key(row: Row) -> tuple[tuple[int, Any], ...]:
    """The row's primary key, with `None` before every value so a NULL never meets a string."""
    return tuple(
        (0, "") if value is None else (1, value)
        for value in (getattr(row, name) for name in row.KEY)
    )


def _insert(connection: sqlite3.Connection, row: Row) -> None:
    names = [f.name for f in fields(row)]
    params = [_column(row, name) for name in names]
    if isinstance(row, Corpus | Assertion):
        existing = _existing(connection, row, names)
        if existing is not None:
            if list(existing) != params:
                raise StoreError(
                    f"{row.TABLE} {_label(row)} is already recorded with other content; "
                    "a corpus version is immutable",
                    fix="publish the changed corpus under a new version",
                )
            return
    columns = ", ".join(names)
    marks = ", ".join("?" * len(names))
    try:
        connection.execute(f"INSERT INTO {row.TABLE} ({columns}) VALUES ({marks})", params)  # noqa: S608
    except sqlite3.IntegrityError as error:
        raise StoreError(f"{row.TABLE} {_label(row)} refused: {error}", fix=_FIX_WRITE) from error


def _existing(connection: sqlite3.Connection, row: Corpus | Assertion, names: list[str]) -> Any:
    where = " AND ".join(f"{name} = ?" for name in row.KEY)
    sql = f"SELECT {', '.join(names)} FROM {row.TABLE} WHERE {where}"  # noqa: S608
    return connection.execute(sql, [getattr(row, name) for name in row.KEY]).fetchone()


def _label(row: Row) -> str:
    return "(" + ", ".join(f"{name}={getattr(row, name)!r}" for name in row.KEY) + ")"


def _column(row: Row, name: str) -> object:
    """Ruling 7: a flag as 0 or 1, a record or a list as canonical JSON, anything else as is."""
    value = getattr(row, name)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, MeasuredOn):
        return _json(asdict(value))
    if name in _JSON_OBJECTS:
        return _json(dict(value))
    if name in _JSON_LISTS:
        return _json(list(value))
    return value


def _json(value: JsonValue) -> str:
    return canonical(value).decode("utf-8")


# --------------------------------------------------------------------------------------------
# 4. Read: the publishing view, as the view computes it.
# --------------------------------------------------------------------------------------------


def runs(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """Each run's published fields, its JSON columns parsed (D828): what a scoreboard row carries
    beside the view's own columns, keyed by the `run_id` the view now names."""
    out = {}
    for run_id, measured_on, not_measured, confounders, fairness in connection.execute(
        "SELECT run_id, measured_on, not_measured, confounders, fairness FROM eval_run"
    ):
        out[str(run_id)] = {
            "measured_on": json.loads(measured_on),
            "not_measured": json.loads(not_measured),
            "confounders": json.loads(confounders),
            "fairness": json.loads(fairness),
        }
    return out


def scoreboard(connection: sqlite3.Connection) -> tuple[Standing, ...]:
    """`eval_scoreboard`'s rows in its first six columns' order. `standing` is the view's."""
    names = [f.name for f in fields(Standing)]
    rows = connection.execute(
        f"SELECT {', '.join(names)} FROM eval_scoreboard "  # noqa: S608
        "ORDER BY metric, slice_key, suite, subject, subject_version, corpus_id, corpus_version, "
        "run_id"
    ).fetchall()
    flags = [names.index(name) for name in ("unpinned", "entrant_bias", "publishable")]
    out = []
    for row in rows:
        values = list(row)
        for at in flags:
            values[at] = bool(values[at])
        out.append(Standing(*values))
    return tuple(out)
