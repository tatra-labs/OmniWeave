"""`SqliteArtifactStore`: the OUT tables' one writer -- the seal, the lookup, the aggregate. D751.

09-generation.md section 2's call order ends in `seal: artifact + artifact_unit + artifact_asset +
artifact_cite, sealed_at_ns`. Section 5.4 keys the lookup-before-build on six digests and gives
three rules for two compiles racing on one slug. Section 7.3 prints the restriction aggregate, and
section 10 prints the "which decks quote page 14 of this contract?" query. `0005_out.sql` is the
authority on every column, CHECK and trigger written here. INV-17 puts the connection in
`omniweave_core.store` and nowhere else, so this class runs its statements on a `StoreThread`, as
`store/cache.py` does for `omniweave_core.cache`, and `omniweave_core.out` reaches it through
these methods.

## Rulings

1. **One seal is one `Unit`.** The `artifact` row and every child row commit together or not at
   all, which is section 2's "no partial artefact and no half-sealed generation".
2. **The generation is allocated by the INSERT and must be the one the compile was planned
   under.** Section 5.4 rule 1 computes `MAX(artifact_gen) + 1` inside the INSERT so that two
   racers cannot both read it first. But the generation is already named before the seal: in
   `Plan.artifact_gen`, in the JobDir `<slug>@<gen>/`, and in the receipt whose sha256 the row
   stores. So the INSERT computes `MAX + 1` and inserts only when it equals the planned
   generation. When it does not, the compile lost a race and its receipt names a generation that
   is no longer the next one; the seal refuses with `OW_TARGET_GEN_CONTENDED`, naming the
   generation that won. Rule 2's single retry therefore belongs to the compile, which re-plans
   and rebuilds the receipt, and not to the INSERT, which cannot renumber what it seals.
3. **An identical compile is a hit, never an error** (rule 3). The loser re-reads the winner's
   row by the purity key and returns it with `hit = True`, writing no child row of its own. That
   covers both ways a loser can find out: the `artifact_pure` conflict, and the generation guard
   of ruling 2 when the winner took the planned generation.
4. **The lookup asks the index's question.** `lookup()` selects on every `artifact_pure` column
   with the index's own `IFNULL(..., x'')` expressions, so a hit is exactly the row the index
   would refuse a duplicate of.
5. **`artifact_pure` carries `brief_digest`.** This amends 09 section 5.4's printed index.
   Section 5.4 defines compile as a function of six digests, `brief_digest` among them, and says
   the index "additionally carries `slug` and `delivery`", so it is meant to hold all six. The
   printed index holds five. `lower()` receives the `Plan` and with it the `Brief`, so two briefs
   over one IL may lower to different bytes, and without the brief the second compile's
   lookup-before-build would return the first compile's bytes. `0005_out.sql` adds
   `IFNULL(brief_digest, x'')`.
6. **A sealed row admits one write: closing the loop.** 02-architecture.md routes a re-ingested
   artefact by "a matching `artifact` row with `read_back_doc_ord IS NULL`", so that column is
   NULL at seal and is set when `read_back` runs, after the row is sealed. 09 section 5.4's
   trigger refuses every UPDATE. `0005_out.sql` therefore names every other column in
   `artifact_sealed_no_update`'s `UPDATE OF` list and adds `artifact_read_back_once`, which lets
   `read_back_doc_ord` go from NULL to a document once. `close_loop()` is that write and the
   `artifact_el` rows beside it.
7. **The restriction aggregate is one statement over the rows the seal would write.** Section
   7.3's statement selects by `:aid`, and neither of its two evaluations has one: plan time comes
   before the compile, and compile time comes before the seal, which is the only writer of
   `artifact` (ruling 1). So the statement keeps its two halves, its `UNION ALL` and its
   predicate, and reads the asset ids and block ids it would have joined through as two JSON
   arrays (`json_each`, built in at `MIN_SQLITE` 3.42). The same text runs both times, and a
   sealed artefact is re-checked by passing its own rows.
8. **`restriction_bits` is never less than the sources'.** INV-16 has the runner stamp the
   producing card's bits, which the draft carries. The seal ORs in the bits of every asset and
   every cited block it writes, read from those rows inside the same transaction, so a derivative
   carries its sources' restrictions.
9. **A compile's citation names a block** (09 section 10: "a row written by a compile is never
   NULL"). A NULL `block_id`, or a `block_id` the store does not hold, is
   `OW_TARGET_CITE_UNRESOLVED`. The one exception is a NULL on an artefact whose origin is
   `read_back`, the one writer section 10 permits it.
10. **`verbatim` is refused where the store can disprove it.** `OW-T-102` proves both halves at
    validation time. The seal re-checks the half the store can see: a `verbatim` row needs a block
    whose `quote` is `VERBATIM` and a span. Anything else is `OW_TARGET_CITE_NOT_VERBATIM`.
11. **A ledger join names a frozen asset under its own slot.** An `artifact_asset` row whose asset
    id the store does not hold, or whose slot is not `asset-slot:` plus that asset's sha256, is
    `OW_TARGET_ASSET_UNFROZEN`.
12. **A release is a passed gate** (OUT5). An `ArtifactDraft` whose delivery is `release` and
    whose gate is anything but `passed` is refused at construction.
13. **Every digest crossing this boundary is `sha256:<64 hex>`**, the spelling
    `out.report.il_digest()` and `out.opc.part_digest()` already use. The columns are BLOBs, and
    the conversion happens here, once in each direction.
14. **The clock is injected.** `sealed_at_ns` is `Clock.wall_ns()`, never an ambient read.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal

from omniweave_core.errors import NotFoundError, StoreError, TargetError
from omniweave_core.model.enums import Quote
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.ledger import ROLES, SLOT_PREFIX
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_core.clock import Clock

__all__ = [
    "ARTIFACT_COLUMNS",
    "LOOKUP_SQL",
    "QUOTING_SQL",
    "RESTRICTION_SQL",
    "SEAL_SQL",
    "ArtifactDraft",
    "ArtifactRow",
    "AssetJoin",
    "CiteRow",
    "ElRow",
    "PureKey",
    "Quoting",
    "Restricted",
    "Sealed",
    "SqliteArtifactStore",
    "UnitRow",
    "artifact_rows",
    "latest_generation",
]

Origin = Literal["authored", "feedback", "read_back", "rebase"]
Delivery = Literal["release", "draft"]
CiteKind = Literal["quote", "paraphrase", "derived", "data"]

ORIGINS: Final = frozenset({"authored", "feedback", "read_back", "rebase"})
DELIVERIES: Final = frozenset({"release", "draft"})
CITE_KINDS: Final = frozenset({"quote", "paraphrase", "derived", "data"})

RESTRICTION_MASK: Final = (1 << 32) - 1
"""09 section 7.3: "32 reserved `restriction_bits`"."""

_DIGEST: Final = re.compile(r"sha256:([0-9a-f]{64})")
_UNIT_ID: Final = re.compile(r"u\d{2,}")

ARTIFACT_COLUMNS: Final = (
    "artifact_id",
    "slug",
    "artifact_gen",
    "parent_artifact_gen",
    "origin",
    "target",
    "compile_driver",
    "media_type",
    "path",
    "sha256",
    "byte_len",
    "part_digest",
    "il_digest",
    "il_store_ref",
    "constructs_digest",
    "ledger_digest",
    "brief_digest",
    "card_sha256",
    "toolchain_digest",
    "determinism",
    "gate_status",
    "delivery",
    "report_sha256",
    "receipt_sha256",
    "restriction_bits",
    "producer_id",
    "degradations",
    "read_back_doc_ord",
    "sealed_at_ns",
)
"""`artifact`'s columns in `0005_out.sql`'s order. A test holds this to `PRAGMA table_info`."""

_SELECT: Final = f"SELECT {', '.join(ARTIFACT_COLUMNS)} FROM artifact"  # noqa: S608 -- constants.

_PURE_WHERE: Final = (
    "target = :target AND slug = :slug AND delivery = :delivery AND il_digest = :il_digest"
    " AND constructs_digest = :constructs_digest AND ledger_digest = :ledger_digest"
    " AND IFNULL(brief_digest, x'') = IFNULL(:brief_digest, x'')"
    " AND card_sha256 = :card_sha256"
    " AND IFNULL(toolchain_digest, x'') = IFNULL(:toolchain_digest, x'')"
)

LOOKUP_SQL: Final = f"{_SELECT} WHERE {_PURE_WHERE}"
"""Ruling 4: every `artifact_pure` column, with the index's own expressions."""

_INSERTED: Final = ARTIFACT_COLUMNS[1:]
SEAL_SQL: Final = (
    f"INSERT INTO artifact({', '.join(_INSERTED)}) "  # noqa: S608 -- constant column names.
    "SELECT "
    + ", ".join("allocated.gen" if c == "artifact_gen" else f":{c}" for c in _INSERTED)
    + " FROM (SELECT IFNULL(MAX(artifact_gen), 0) + 1 AS gen FROM artifact WHERE slug = :slug)"
    " AS allocated WHERE allocated.gen = :artifact_gen"
)
"""Ruling 2: the INSERT allocates `MAX + 1` and writes only the generation it was planned under."""

RESTRICTION_SQL: Final = """\
SELECT 'asset' AS what, a.asset_id AS id, a.restriction_bits AS bits, NULL AS cite
  FROM json_each(:asset_ids) AS j JOIN asset a ON a.asset_id = j.value
 WHERE (a.restriction_bits & :barred_mask) != 0
UNION ALL
SELECT 'cite', b.block_id, b.restriction_bits, b.cite
  FROM json_each(:block_ids) AS j JOIN block b ON b.block_id = j.value
 WHERE (b.restriction_bits & :barred_mask) != 0
ORDER BY 1, 2"""
"""Ruling 7: 09 section 7.3's one statement, over the rows the seal would write."""

QUOTING_SQL: Final = """\
SELECT a.slug, a.artifact_gen, ac.unit, ac.el, ac.kind, ac.verbatim
FROM artifact_cite ac
JOIN artifact a USING (artifact_id)
JOIN block b ON b.block_id = ac.block_id
WHERE b.doc_ord = :doc AND b.page = :page AND a.delivery = 'release'
ORDER BY a.slug, ac.unit, ac.el"""
"""09 section 10's query, as printed, with the page bound."""

_PURE_CONFLICT: Final = "UNIQUE constraint failed: index 'artifact_pure'"
_SEALED: Final = "OW-T-511"
_FIX_GEN: Final = "ow out compile --target {target} --slug {slug}   # re-plans at the next gen"


def _blob(name: str, text: str) -> bytes:
    """Ruling 13: `sha256:<64 hex>` to the column's 32 bytes."""
    match = _DIGEST.fullmatch(text)
    if match is None:
        raise ValueError(f"{name} {text!r} is not sha256:<64 lower-case hex>")
    return bytes.fromhex(match.group(1))


def _text(raw: bytes | None) -> str | None:
    return None if raw is None else "sha256:" + raw.hex()


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True, slots=True)
class PureKey:
    """`artifact_pure`'s columns: the six purity digests, the target, the slug and the delivery."""

    target: str
    slug: str
    delivery: Delivery
    il_digest: str
    constructs_digest: str
    ledger_digest: str
    card_sha256: str
    brief_digest: str | None = None
    toolchain_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.target or not self.slug:
            raise ValueError("a purity key names its target and its slug")
        if self.delivery not in DELIVERIES:
            raise ValueError(f"delivery {self.delivery!r} is release or draft")
        for name in ("il_digest", "constructs_digest", "ledger_digest", "card_sha256"):
            _blob(name, getattr(self, name))
        for name in ("brief_digest", "toolchain_digest"):
            value = getattr(self, name)
            if value is not None:
                _blob(name, value)

    def params(self) -> dict[str, object]:
        return {
            "target": self.target,
            "slug": self.slug,
            "delivery": self.delivery,
            "il_digest": _blob("il_digest", self.il_digest),
            "constructs_digest": _blob("constructs_digest", self.constructs_digest),
            "ledger_digest": _blob("ledger_digest", self.ledger_digest),
            "card_sha256": _blob("card_sha256", self.card_sha256),
            "brief_digest": None
            if self.brief_digest is None
            else _blob("brief_digest", self.brief_digest),
            "toolchain_digest": None
            if self.toolchain_digest is None
            else _blob("toolchain_digest", self.toolchain_digest),
        }


@dataclass(frozen=True, slots=True)
class UnitRow:
    """One `artifact_unit` row: the unit, its outcome, and its retained per-unit IL."""

    unit: str
    ord: int
    outcome: UnitOutcome
    il_path: str
    il_sha256: str
    nsig: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if _UNIT_ID.fullmatch(self.unit) is None:
            raise ValueError(f"unit id {self.unit!r} does not match ^u\\d{{2,}}$")
        if self.ord < 1:
            raise ValueError(f"{self.unit}: ord {self.ord} is below 1")
        _blob(f"{self.unit}: il_sha256", self.il_sha256)
        if not self.nsig:
            raise ValueError(f"{self.unit}: an artifact_unit row carries its nsig")
        if self.outcome in {UnitOutcome.MANUAL_REQUIRED, UnitOutcome.BAKED} and not self.reason:
            raise ValueError(f"{self.unit}: a {self.outcome} unit needs a reason")


@dataclass(frozen=True, slots=True)
class AssetJoin:
    """One `artifact_asset` row: the ledger join onto L2's `asset` (09 section 7)."""

    asset_id: int
    slot: str
    role: str
    units: tuple[str, ...]
    ratio_variants: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"asset role {self.role!r} is not one of {sorted(ROLES)}")
        if not self.slot.startswith(SLOT_PREFIX):
            raise ValueError(f"slot {self.slot!r} is not asset-slot:<sha256>")
        if not self.units:
            raise ValueError(f"asset {self.asset_id} under {self.slot} is used by no unit")


@dataclass(frozen=True, slots=True)
class CiteRow:
    """One `artifact_cite` row: which element of which unit cites which block, at a pinned gen."""

    unit: str
    el: str
    cite: str
    block_id: int | None
    doc_gen: int
    kind: CiteKind
    span_a: int | None = None
    span_b: int | None = None
    verbatim: bool = False

    def __post_init__(self) -> None:
        if self.kind not in CITE_KINDS:
            raise ValueError(f"cite kind {self.kind!r} is not one of {sorted(CITE_KINDS)}")
        if (self.span_a is None) != (self.span_b is None):
            raise ValueError(f"{self.el}: a span has both ends or neither")
        if (
            self.span_a is not None
            and self.span_b is not None
            and not (0 <= self.span_a < self.span_b)
        ):
            raise ValueError(f"{self.el}: span [{self.span_a}, {self.span_b}) is empty or negative")


@dataclass(frozen=True, slots=True)
class ElRow:
    """One `artifact_el` row: the IL element a read-back block came from (09 section 11)."""

    unit: str
    el: str
    block_id: int


@dataclass(frozen=True, slots=True)
class ArtifactDraft:
    """Everything a seal writes except what the store allocates: the id, and the time."""

    key: PureKey
    artifact_gen: int
    origin: Origin
    compile_driver: str
    media_type: str
    path: str
    sha256: str
    byte_len: int
    part_digest: str
    il_store_ref: str
    determinism: tuple[str, ...]
    gate_status: GateStatus
    report_sha256: str
    receipt_sha256: str
    producer_id: int
    units: tuple[UnitRow, ...]
    assets: tuple[AssetJoin, ...] = ()
    cites: tuple[CiteRow, ...] = ()
    restriction_bits: int = 0
    """The producing card's stamp (INV-16). The seal ORs in the sources' bits (ruling 8)."""
    parent_artifact_gen: int | None = None
    degradations: tuple[Mapping[str, Any], ...] = ()
    read_back_doc_ord: int | None = None

    def __post_init__(self) -> None:
        if self.origin not in ORIGINS:
            raise ValueError(f"origin {self.origin!r} is not one of {sorted(ORIGINS)}")
        if self.artifact_gen < 1:
            raise ValueError(f"artifact_gen {self.artifact_gen} is below 1")
        if self.parent_artifact_gen is not None and not (
            1 <= self.parent_artifact_gen < self.artifact_gen
        ):
            raise ValueError(
                f"parent_artifact_gen {self.parent_artifact_gen} is not an earlier generation"
            )
        if self.key.delivery == "release" and self.gate_status is not GateStatus.PASSED:
            raise ValueError(f"a release needs a passed gate, not {self.gate_status}")
        if not self.il_store_ref.startswith("cas://"):
            raise ValueError(f"il_store_ref {self.il_store_ref!r} is not a cas:// reference")
        if "part" not in self.determinism:
            raise ValueError("determinism must include part: the floor every target has")
        if not 0 <= self.restriction_bits <= RESTRICTION_MASK:
            raise ValueError(f"restriction_bits {self.restriction_bits} is not 32 bits")
        for name in ("sha256", "part_digest", "report_sha256", "receipt_sha256"):
            _blob(name, getattr(self, name))
        self._check_children()

    def _check_children(self) -> None:
        ids = [u.unit for u in self.units]
        if not ids:
            raise ValueError("an artefact has at least one unit")
        if len(set(ids)) != len(ids):
            raise ValueError(f"unit ids repeat: {ids}")
        if [u.ord for u in self.units] != list(range(1, len(ids) + 1)):
            raise ValueError(f"unit ords are not 1..{len(ids)} in roster order")
        known = set(ids)
        joins = [(a.asset_id, a.slot, a.role) for a in self.assets]
        if len(set(joins)) != len(joins):
            raise ValueError("an (asset_id, slot, role) join repeats")
        for join in self.assets:
            if not set(join.units) <= known:
                raise ValueError(f"asset {join.asset_id} names units outside the roster")
        cites = [(c.unit, c.el, c.cite) for c in self.cites]
        if len(set(cites)) != len(cites):
            raise ValueError("a (unit, el, cite) citation repeats")
        for cite in self.cites:
            if cite.unit not in known:
                raise ValueError(f"cite {cite.cite} on {cite.el} names unit {cite.unit!r}")

    def params(self, *, sealed_at_ns: int, restriction_bits: int) -> dict[str, object]:
        return {
            **self.key.params(),
            "artifact_gen": self.artifact_gen,
            "parent_artifact_gen": self.parent_artifact_gen,
            "origin": self.origin,
            "compile_driver": self.compile_driver,
            "media_type": self.media_type,
            "path": self.path,
            "sha256": _blob("sha256", self.sha256),
            "byte_len": self.byte_len,
            "part_digest": _blob("part_digest", self.part_digest),
            "il_store_ref": self.il_store_ref,
            "determinism": _canonical(sorted(set(self.determinism))),
            "gate_status": str(self.gate_status),
            "report_sha256": _blob("report_sha256", self.report_sha256),
            "receipt_sha256": _blob("receipt_sha256", self.receipt_sha256),
            "restriction_bits": restriction_bits,
            "producer_id": self.producer_id,
            "degradations": _canonical([dict(d) for d in self.degradations]),
            "read_back_doc_ord": self.read_back_doc_ord,
            "sealed_at_ns": sealed_at_ns,
        }


@dataclass(frozen=True, slots=True)
class ArtifactRow:
    """One sealed `artifact` row, read back, digests in ruling 13's spelling."""

    artifact_id: int
    slug: str
    artifact_gen: int
    parent_artifact_gen: int | None
    origin: str
    target: str
    compile_driver: str
    media_type: str
    path: str
    sha256: str
    byte_len: int
    part_digest: str
    il_digest: str
    il_store_ref: str
    constructs_digest: str
    ledger_digest: str
    brief_digest: str | None
    card_sha256: str
    toolchain_digest: str | None
    determinism: tuple[str, ...]
    gate_status: GateStatus
    delivery: str
    report_sha256: str
    receipt_sha256: str
    restriction_bits: int
    producer_id: int
    degradations: tuple[Mapping[str, Any], ...]
    read_back_doc_ord: int | None
    sealed_at_ns: int

    @classmethod
    def of(cls, row: Sequence[Any]) -> ArtifactRow:
        values = dict(zip(ARTIFACT_COLUMNS, row, strict=True))
        for name in (
            "sha256",
            "part_digest",
            "il_digest",
            "constructs_digest",
            "ledger_digest",
            "brief_digest",
            "card_sha256",
            "toolchain_digest",
            "report_sha256",
            "receipt_sha256",
        ):
            values[name] = _text(values[name])
        values["determinism"] = tuple(json.loads(values["determinism"]))
        values["degradations"] = tuple(json.loads(values["degradations"]))
        values["gate_status"] = GateStatus(values["gate_status"])
        return cls(**values)

    @property
    def key(self) -> PureKey:
        return PureKey(
            target=self.target,
            slug=self.slug,
            delivery="release" if self.delivery == "release" else "draft",
            il_digest=self.il_digest,
            constructs_digest=self.constructs_digest,
            ledger_digest=self.ledger_digest,
            card_sha256=self.card_sha256,
            brief_digest=self.brief_digest,
            toolchain_digest=self.toolchain_digest,
        )


@dataclass(frozen=True, slots=True)
class Sealed:
    """What `seal()` returns: the row, and whether it is an earlier identical compile's (rule 3)."""

    row: ArtifactRow
    hit: bool


@dataclass(frozen=True, slots=True)
class Restricted:
    """One row of the restriction aggregate: a barred asset, or a barred cited block."""

    what: Literal["asset", "cite"]
    id: int
    bits: int
    cite: str | None


@dataclass(frozen=True, slots=True)
class Quoting:
    """One row of 09 section 10's "which decks quote this page?" query."""

    slug: str
    artifact_gen: int
    unit: str
    el: str
    kind: str
    verbatim: bool


def _ids(values: Iterable[int]) -> str:
    return json.dumps(sorted(set(values)))


def _lookup(connection: sqlite3.Connection, key: PureKey) -> ArtifactRow | None:
    row = connection.execute(LOOKUP_SQL, key.params()).fetchone()
    return None if row is None else ArtifactRow.of(row)


def artifact_rows(
    connection: sqlite3.Connection, slug: str | None = None
) -> tuple[ArtifactRow, ...]:
    """Every sealed row, or one slug's, by slug then generation. D769, for `ow out list`.

    Readable on a read-only connection, as `latest_generation()` is, and empty on a store
    from before `0005_out.sql`, which has sealed nothing.
    """
    if not _has_artifacts(connection):
        return ()
    where, args = (" WHERE slug = ?", (slug,)) if slug is not None else ("", ())
    rows = connection.execute(f"{_SELECT}{where} ORDER BY slug, artifact_gen", args)
    return tuple(ArtifactRow.of(row) for row in rows)


def _has_artifacts(connection: sqlite3.Connection) -> bool:
    present = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'artifact'"
    ).fetchone()
    return present is not None


def latest_generation(connection: sqlite3.Connection, slug: str) -> int:
    """The newest sealed generation of `slug` on any connection, read-only included, or 0.

    `ow out scaffold` reads it through `connect_readonly()`, which opens a store without
    migrating it, so a store from before `0005_out.sql` has no `artifact` table and has
    sealed nothing (D765).
    """
    return _latest(connection, slug) if _has_artifacts(connection) else 0


def _latest(connection: sqlite3.Connection, slug: str) -> int:
    (latest,) = connection.execute(
        "SELECT IFNULL(MAX(artifact_gen), 0) FROM artifact WHERE slug = ?", (slug,)
    ).fetchone()
    return int(latest)


class SqliteArtifactStore:
    """The OUT tables over one `StoreThread`. Every method is one `Unit`."""

    __slots__ = ("_clock", "_thread", "_wait_ms")

    def __init__(
        self, thread: StoreThread, *, clock: Clock, wait_ms: int = INTERACTIVE_WAIT_MS
    ) -> None:
        self._thread = thread
        self._clock = clock
        self._wait_ms = wait_ms

    def _run(self, name: str, run: Any, cost_class: str = "free") -> object:
        return self._thread.run(
            Unit(name=name, run=run, cost_class=cost_class, wait_ms=self._wait_ms)
        )

    # -- read ----------------------------------------------------------------------------------

    def lookup(self, key: PureKey) -> ArtifactRow | None:
        """OUT12's lookup-before-build: the row an identical compile already sealed, or `None`."""
        found = self._run("out.lookup", lambda connection: _lookup(connection, key))
        return found if isinstance(found, ArtifactRow) else None

    def latest(self, slug: str) -> int:
        """The newest sealed generation of `slug`, or 0. `ow out scaffold` proposes one past it."""
        found = self._run("out.latest", lambda connection: _latest(connection, slug))
        return found if isinstance(found, int) else 0

    def get(self, slug: str, artifact_gen: int) -> ArtifactRow:
        def run(connection: sqlite3.Connection) -> object:
            row = connection.execute(
                f"{_SELECT} WHERE slug = ? AND artifact_gen = ?", (slug, artifact_gen)
            ).fetchone()
            return None if row is None else ArtifactRow.of(row)

        found = self._run("out.get", run)
        if not isinstance(found, ArtifactRow):
            raise NotFoundError(
                f"no artefact {slug}@{artifact_gen} in this store", fix=f"ow out list --slug {slug}"
            )
        return found

    def units(self, artifact_id: int) -> tuple[UnitRow, ...]:
        """The artefact's `artifact_unit` rows in roster order."""

        def run(connection: sqlite3.Connection) -> object:
            return tuple(
                UnitRow(
                    unit=unit,
                    ord=ord_,
                    outcome=UnitOutcome(outcome),
                    il_path=il_path,
                    il_sha256="sha256:" + il_sha256.hex(),
                    nsig=nsig,
                    reason=reason,
                )
                for unit, ord_, outcome, il_path, il_sha256, nsig, reason in connection.execute(
                    "SELECT unit, ord, outcome, il_path, il_sha256, nsig, reason"
                    " FROM artifact_unit WHERE artifact_id = ? ORDER BY ord",
                    (artifact_id,),
                )
            )

        rows = self._run("out.units", run)
        return rows if isinstance(rows, tuple) else ()

    def restricted(
        self, *, asset_ids: Iterable[int], block_ids: Iterable[int], barred_mask: int
    ) -> tuple[Restricted, ...]:
        """Ruling 7: 09 section 7.3's aggregate, at plan time and again at compile time."""
        if not 0 <= barred_mask <= RESTRICTION_MASK:
            raise ValueError(f"barred_mask {barred_mask} is not 32 bits")
        params = {
            "asset_ids": _ids(asset_ids),
            "block_ids": _ids(block_ids),
            "barred_mask": barred_mask,
        }

        def run(connection: sqlite3.Connection) -> object:
            return tuple(
                Restricted(what, id_, bits, cite)
                for what, id_, bits, cite in connection.execute(RESTRICTION_SQL, params)
            )

        rows = self._run("out.restricted", run)
        return rows if isinstance(rows, tuple) else ()

    def quoting(self, doc_ord: int, page: int) -> tuple[Quoting, ...]:
        """09 section 10: every released artefact element that cites a block on this page."""

        def run(connection: sqlite3.Connection) -> object:
            return tuple(
                Quoting(slug, gen, unit, el, kind, bool(verbatim))
                for slug, gen, unit, el, kind, verbatim in connection.execute(
                    QUOTING_SQL, {"doc": doc_ord, "page": page}
                )
            )

        rows = self._run("out.quoting", run)
        return rows if isinstance(rows, tuple) else ()

    # -- write ---------------------------------------------------------------------------------

    def seal(self, draft: ArtifactDraft) -> Sealed:
        """Rulings 1-3 and 8-11: one transaction, the artefact and its rows, or the winner's."""

        def run(connection: sqlite3.Connection) -> object:
            bits = draft.restriction_bits | _source_bits(connection, draft)
            params = draft.params(sealed_at_ns=self._clock.wall_ns(), restriction_bits=bits)
            try:
                cursor = connection.execute(SEAL_SQL, params)
            except sqlite3.IntegrityError as exc:
                if str(exc) != _PURE_CONFLICT:
                    raise
                return _winner(connection, draft)
            if cursor.rowcount == 0:
                return _winner(connection, draft)
            artifact_id = cursor.lastrowid
            if artifact_id is None:  # pragma: no cover -- an INSERT that wrote a row has an id.
                raise StoreError("the seal wrote no rowid", fix="report this as a bug")
            _children(connection, artifact_id, draft)
            return Sealed(_by_id(connection, artifact_id), hit=False)

        sealed = self._run("out.seal", run, cost_class="local_compute")
        if not isinstance(sealed, Sealed):  # pragma: no cover -- the closure returns or raises.
            raise StoreError("the out.seal unit returned no row", fix="report this as a bug")
        return sealed

    def close_loop(self, artifact_id: int, doc_ord: int, els: Sequence[ElRow]) -> ArtifactRow:
        """Ruling 6: `read_back_doc_ord`, NULL to a document once, and the `artifact_el` map."""

        def run(connection: sqlite3.Connection) -> object:
            units = {
                unit
                for (unit,) in connection.execute(
                    "SELECT unit FROM artifact_unit WHERE artifact_id = ?", (artifact_id,)
                )
            }
            stray = sorted({e.unit for e in els} - units)
            if stray:
                raise ValueError(f"artifact {artifact_id} has no unit {stray}")
            try:
                cursor = connection.execute(
                    "UPDATE artifact SET read_back_doc_ord = ? WHERE artifact_id = ?",
                    (doc_ord, artifact_id),
                )
            except sqlite3.IntegrityError as exc:
                if not str(exc).startswith(_SEALED):
                    raise
                raise TargetError(
                    f"artifact {artifact_id} was already read back: {exc}",
                    symbol="OW_TARGET_ARTIFACT_SEALED",
                    fix="ow out compile   # a new artifact_gen is read back on its own",
                ) from exc
            if cursor.rowcount == 0:
                raise NotFoundError(f"no artifact {artifact_id}", fix="ow out list")
            connection.executemany(
                "INSERT INTO artifact_el(artifact_id, unit, el, block_id) VALUES (?, ?, ?, ?)",
                [(artifact_id, e.unit, e.el, e.block_id) for e in els],
            )
            return _by_id(connection, artifact_id)

        row = self._run("out.close_loop", run)
        if not isinstance(row, ArtifactRow):  # pragma: no cover -- the closure returns or raises.
            raise StoreError("the out.close_loop unit returned no row", fix="report this bug")
        return row


def _by_id(connection: sqlite3.Connection, artifact_id: int) -> ArtifactRow:
    row = connection.execute(f"{_SELECT} WHERE artifact_id = ?", (artifact_id,)).fetchone()
    if row is None:  # pragma: no cover -- read inside the transaction that wrote it.
        raise StoreError(f"artifact {artifact_id} vanished", fix="report this as a bug")
    return ArtifactRow.of(row)


def _winner(connection: sqlite3.Connection, draft: ArtifactDraft) -> Sealed:
    """Rulings 2 and 3: the identical compile's row as a hit, else the generation that won."""
    found = _lookup(connection, draft.key)
    if found is not None:
        return Sealed(found, hit=True)
    slug = draft.key.slug
    latest = _latest(connection, slug)
    raise TargetError(
        f"artefact {slug!r} was planned as generation {draft.artifact_gen}, and generation "
        f"{latest} is the latest sealed, so the next is {latest + 1}: another compile of this "
        "slug sealed first",
        symbol="OW_TARGET_GEN_CONTENDED",
        fix=_FIX_GEN.format(target=draft.key.target, slug=slug),
    )


def _source_bits(connection: sqlite3.Connection, draft: ArtifactDraft) -> int:
    """Rulings 8-11: check every source the seal writes, and OR their restriction bits."""
    bits = 0
    assets = {
        asset_id: (sha, asset_bits)
        for asset_id, sha, asset_bits in connection.execute(
            "SELECT asset_id, sha256, restriction_bits FROM asset"
            " WHERE asset_id IN (SELECT value FROM json_each(?))",
            (_ids(a.asset_id for a in draft.assets),),
        )
    }
    for join in draft.assets:
        held = assets.get(join.asset_id)
        if held is None or join.slot != SLOT_PREFIX + bytes(held[0]).hex():
            raise TargetError(
                f"asset {join.asset_id} is not frozen under {join.slot}",
                symbol="OW_TARGET_ASSET_UNFROZEN",
                fix="ow out scaffold --asset <path>   # freeze it, then slot its digest",
            )
        bits |= held[1]
    blocks = {
        block_id: (quote, block_bits)
        for block_id, quote, block_bits in connection.execute(
            "SELECT block_id, quote, restriction_bits FROM block"
            " WHERE block_id IN (SELECT value FROM json_each(?))",
            (_ids(c.block_id for c in draft.cites if c.block_id is not None),),
        )
    }
    for cite in draft.cites:
        held = None if cite.block_id is None else blocks.get(cite.block_id)
        if held is None:
            if draft.origin == "read_back" and cite.block_id is None:
                continue
            raise TargetError(
                f"{cite.unit}/{cite.el} cites {cite.cite}, which names no block in this store",
                symbol="OW_TARGET_CITE_UNRESOLVED",
                fix="ow out check --stage final",
            )
        quote, block_bits = held
        if cite.verbatim and (quote != Quote.VERBATIM or cite.span_a is None):
            raise TargetError(
                f"{cite.unit}/{cite.el} claims a verbatim quote of {cite.cite}, whose block is "
                f"quote={Quote(quote).name.lower()}"
                + ("" if cite.span_a is not None else " and which names no span"),
                symbol="OW_TARGET_CITE_NOT_VERBATIM",
                fix=f"ow open {cite.cite} --raw",
            )
        bits |= block_bits
    return bits


def _children(connection: sqlite3.Connection, artifact_id: int, draft: ArtifactDraft) -> None:
    connection.executemany(
        "INSERT INTO artifact_unit(artifact_id, unit, ord, outcome, il_path, il_sha256, nsig,"
        " reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                artifact_id,
                u.unit,
                u.ord,
                str(u.outcome),
                u.il_path,
                _blob("il_sha256", u.il_sha256),
                u.nsig,
                u.reason,
            )
            for u in draft.units
        ],
    )
    connection.executemany(
        "INSERT INTO artifact_asset(artifact_id, asset_id, slot, role, units, ratio_variants)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                artifact_id,
                a.asset_id,
                a.slot,
                a.role,
                _canonical(sorted(set(a.units))),
                _canonical(sorted(set(a.ratio_variants))),
            )
            for a in draft.assets
        ],
    )
    connection.executemany(
        "INSERT INTO artifact_cite(artifact_id, unit, el, cite, block_id, doc_gen, kind, span_a,"
        " span_b, verbatim) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                artifact_id,
                c.unit,
                c.el,
                c.cite,
                c.block_id,
                c.doc_gen,
                c.kind,
                c.span_a,
                c.span_b,
                int(c.verbatim),
            )
            for c in draft.cites
        ],
    )
