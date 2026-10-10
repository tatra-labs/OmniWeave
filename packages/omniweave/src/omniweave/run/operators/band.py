"""The LLM band's row: the band's manifest, its decision and its work row. **D728.**

W8.8, 06:1460-1478's decision Pass on the host's side, as D715 is the Segment Passes'. `op.resolve`
hands on the pairs it could not decide (`ResolveReport.band`, D727). This module renders each pair's
two sides, orders the pairs into batches of `LLM_BATCH`, and keeps the band's manifest in the CAS.
It writes 05:1103's three rows for the band and the `band:` work row that points at them. Nothing
here runs the Pass (D729 does).

## Rulings (the ledger's D728)

1. **A side is what the documents wrote**: the entity's `title`, its `etype` and its other alias
   surfaces, sorted, at most `MAX_ALIASES`. No key, cite or id reaches it (GR11). An alias with
   `taint & UNTRUSTED_SOURCE` and `doc_count = 1` is left out, as resolution's blocking leaves it
   out (06:1872): a name only a hostile document gave an entity must not argue for a merge.
2. **The pairs are ordered by their ends' identities** (`op.resolve` ruling 4's order), and every
   `LLM_BATCH` of them in that order is one batch: one call (D729).
3. **The manifest is the host's**: each pair's ends and band score, the two sides, and the witness.
   It goes into the CAS before the rows, and its sha256 is the decision's `content_sha256`, since
   the band is what the merge decision is about. The band is named by it: `band:` and the first
   16 hex. The driver's view of each batch is built from it when the row runs, without the ends.
4. **The witness is every document holding a live mention of either end of a pair**, as
   `(unit_uri, "", key)`: 04:570's tuple, its token naming the entity that was read.
5. **The band is filed under the first unit its witness names.** `work.unit_uri` must name a `unit`
   row and the band has none of its own, so it is filed under a unit it read. When that document
   goes, the row goes with it, and the next run's band is decided afresh.
6. **The decision is on the `entity` lane at `ENRICH`**, rule `graph.band`. Its read set is the
   band's pair and batch counts and its two bounds. The estimate is the card's `per_part` once a
   batch, and no money (D715 ruling 3).
7. **Idempotent by identity** (D715 ruling 5). An unchanged band names the same manifest, so a
   second enqueue writes no row. A band that differs is a new decision and a new row, and the call
   cache (D729) keeps a pair it has answered from being bought again.
8. **The band is one decision and one row a generation, not one a batch.** `derive_run_identity`
   gives a corpus Pass one run a generation, and every row a run writes resolves to one
   `route_decision` (06:152-155). Per-batch decisions would all write into that one run, and its
   merges could not say which decision billed them.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.cache import cache_key
from omniweave_core.canonical import canonical, sha256_canonical
from omniweave_core.drivers.resolve import CostClass
from omniweave_core.model.enums import Taint
from omniweave_core.model.records import Producer
from omniweave_ports.types import UnitRef

from omniweave.graph import fuzzy
from omniweave.plan import operator_of
from omniweave.route.decision import RouteDecision
from omniweave.route.rung import Rung
from omniweave.run.dispatch import dispatch_key
from omniweave.run.operators.billed import BILLED_ENQUEUE_SQL, estimate, service_table
from omniweave.run.operators.derive import DERIVE_PRIORITY, MERGE_LLM
from omniweave.run.routing import INGEST_HINTS_DIGEST, decision_rows

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.blobs import BlobStore
    from omniweave_core.drivers.resolve import Candidate

    from omniweave.graph.resolve import Band
    from omniweave.run.operators.derive import DerivePlan
    from omniweave.run.routing import ReadSet

__all__ = [
    "BAND_PASS",
    "BATCHES_KEY",
    "HIGH_KEY",
    "LLM_BATCH",
    "LOW_KEY",
    "MAX_ALIASES",
    "PAIRS_KEY",
    "RULE_ID",
    "RULE_ORIGIN",
    "BandQueued",
    "Manifest",
    "enqueue_band",
    "manifest",
    "ordered",
    "put_manifest",
]

BAND_PASS: Final = MERGE_LLM
LLM_BATCH: Final = 30
"""06:1460: at most thirty pairs to one call."""
MAX_ALIASES: Final = 8
"""Ruling 1: the other names a side shows. Enough to tell two firms apart, and bounded."""
RULE_ID: Final = "graph.band"
RULE_ORIGIN: Final = "builtin:06-structure-extraction.md:1754"
PAIRS_KEY: Final = "graph.band_pairs"
BATCHES_KEY: Final = "graph.band_batches"
LOW_KEY: Final = "graph.band_low"
HIGH_KEY: Final = "graph.band_high"

_ENTITY_SQL: Final = "SELECT title, etype, key FROM entity WHERE entity_id = ?"
_ALIASES_SQL: Final = """
SELECT DISTINCT surface FROM entity_alias
 WHERE entity_id = :entity AND NOT (taint & :untrusted AND doc_count = 1)
 ORDER BY surface
"""
_UNITS_SQL: Final = """
SELECT DISTINCT u.unit_uri FROM mention AS m
  JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
  JOIN doc AS d ON d.doc_ord = b.doc_ord
  JOIN unit AS u ON substr(u.content_sha256, 1, 32) = lower(hex(d.doc_key))
 WHERE m.entity_id = ? AND m.state = 0 AND u.state <> 'out_of_scope'
 ORDER BY u.unit_uri
"""


@dataclass(frozen=True, slots=True)
class Manifest:
    """Ruling 3: the band as the host keeps it."""

    members: tuple[tuple[int, int, float], ...]
    """Each pair's ends, `a` before `b` in identity order, and its band score, in batch order."""
    sides: tuple[tuple[Mapping[str, Any], Mapping[str, Any]], ...]
    witness: tuple[tuple[str, str, str], ...]

    @property
    def body(self) -> bytes:
        return canonical(
            {
                "members": [list(m) for m in self.members],
                "sides": [[dict(a), dict(b)] for a, b in self.sides],
                "witness": [list(w) for w in self.witness],
            }
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    @property
    def name(self) -> str:
        """Ruling 3: `band:` and the manifest's first 16 hex."""
        return f"band:{self.sha256[:16]}"

    @property
    def anchor(self) -> str:
        """Ruling 5: the first unit the witness names."""
        return min(w[0] for w in self.witness)

    @property
    def batches(self) -> tuple[range, ...]:
        """Ruling 2: each batch's positions in `members`, `LLM_BATCH` at a time."""
        n = len(self.members)
        return tuple(range(i, min(i + LLM_BATCH, n)) for i in range(0, n, LLM_BATCH))


def ordered(band: Sequence[Band], identity: Mapping[int, tuple[str, str, int]]) -> list[Band]:
    """Ruling 2: the pairs in their ends' identity order."""
    return sorted(band, key=lambda b: (identity[b.a], identity[b.b]))


def manifest(connection: Any, band: Sequence[Band]) -> Manifest | None:
    """Rulings 1-4: the band's manifest, read from the store, or `None` when there is no band. A
    pair whose end is gone is dropped."""
    ends = {e for b in band for e in (b.a, b.b)}
    rows = {e: connection.execute(_ENTITY_SQL, (e,)).fetchone() for e in ends}
    live = [b for b in band if rows[b.a] is not None and rows[b.b] is not None]
    identity = {e: (str(r[2]), str(r[1]), e) for e, r in rows.items() if r is not None}
    pairs = ordered(live, identity)
    untrusted = int(Taint.UNTRUSTED_SOURCE)
    witness = sorted(
        {
            (str(uri), "", str(rows[e][2]))
            for b in pairs
            for e in (b.a, b.b)
            for (uri,) in connection.execute(_UNITS_SQL, (e,)).fetchall()
        }
    )
    if not pairs or not witness:
        return None
    return Manifest(
        members=tuple((b.a, b.b, round(b.score, 4)) for b in pairs),
        sides=tuple(
            (
                _side(connection, rows[b.a], b.a, untrusted),
                _side(connection, rows[b.b], b.b, untrusted),
            )
            for b in pairs
        ),
        witness=tuple(witness),
    )


def _side(connection: Any, row: Any, entity_id: int, untrusted: int) -> dict[str, Any]:
    """Ruling 1: a surface, a type and the other names, as the documents wrote them."""
    title = str(row[0])
    names = [
        str(s)
        for (s,) in connection.execute(_ALIASES_SQL, {"entity": entity_id, "untrusted": untrusted})
        if str(s) != title
    ]
    return {"surface": title, "etype": str(row[1]), "aliases": names[:MAX_ALIASES]}


def put_manifest(cas: BlobStore, one: Manifest) -> None:
    """Ruling 3: the manifest into the CAS before its rows name it."""
    cas.put(io.BytesIO(one.body))


@dataclass(frozen=True, slots=True)
class BandQueued:
    """What one enqueue wrote: the pairs offered, the batches they make, and the row if new."""

    pairs: int = 0
    batches: int = 0
    queued: int = 0

    def lines(self) -> list[str]:
        """The report line."""
        return [
            f"  band      {BAND_PASS}: {self.pairs} pair(s) in {self.batches} batch(es), "
            f"{self.queued} queued"
        ]


def enqueue_band(
    connection: Any, plan: DerivePlan, one: Manifest | None, *, now_ms: int
) -> BandQueued:
    """Rulings 5-8: the band's decision and work row, under the plan's merge Pass."""
    candidate = plan.merge
    if candidate is None or one is None:
        return BandQueued()
    return BandQueued(
        pairs=len(one.members),
        batches=len(one.batches),
        queued=_write(connection, plan, candidate, one, now_ms=now_ms),
    )


def _write(
    connection: Any, plan: DerivePlan, candidate: Candidate, one: Manifest, *, now_ms: int
) -> int:
    card = candidate.card
    unit = UnitRef(uri=one.anchor, part=one.name, content_sha256=one.sha256, byte_len=len(one.body))
    decision, read_set = _decision(plan, card, unit, len(one.members), len(one.batches))
    for sql, params in decision_rows(
        unit.uri, decision, read_set, driver=BAND_PASS, generation=plan.ctx.generation,
        now_ms=now_ms,
    ):  # fmt: skip
        connection.execute(sql, params)
    producer = Producer(
        operator=operator_of(BAND_PASS),
        op_version=card.identity.schema_version,
        code_fingerprint="",
        options_digest=bytes.fromhex(candidate.config_digest),
    )
    services = card.hardware.services
    return int(
        connection.execute(
            BILLED_ENQUEUE_SQL,
            {
                "unit_uri": unit.uri,
                "unit_part": unit.part,
                "operator": BAND_PASS,
                "op_version": card.identity.schema_version,
                "cache_key": cache_key(unit, producer, card, plan.ctx, salt=""),
                "priority": DERIVE_PRIORITY,
                "driver": BAND_PASS,
                "decision_id": decision.decision_id(),
                "dispatch_key": dispatch_key(
                    BAND_PASS, candidate.config_digest, str(candidate.isolation_granted)
                ),
                "service": service_table(services[0]) if services else None,
            },
        ).rowcount
    )


def _decision(
    plan: DerivePlan, card: Any, unit: UnitRef, pairs: int, batches: int
) -> tuple[RouteDecision, ReadSet]:
    """Ruling 6: the band's decision, and the read set it compared."""
    read_set: ReadSet = (
        (PAIRS_KEY, "", pairs),
        (BATCHES_KEY, "", batches),
        (LOW_KEY, "", fuzzy.AMBIGUOUS_LOW),
        (HIGH_KEY, "", fuzzy.MERGE_THRESHOLD),
    )
    per_part = card.cost_model.per_part if card.cost_model is not None else {}
    decision = RouteDecision(
        content_sha256=unit.content_sha256,
        unit_part=unit.part,
        lane="entity",
        rung=Rung.ENRICH,
        policy_digest=plan.ctx.policy_digest,
        pricebook_digest=plan.ctx.pricebook_digest,
        hints_digest=INGEST_HINTS_DIGEST,
        read_set_digest=sha256_canonical([[k, v, value] for k, v, value in read_set]),
        matched=True,
        rule_id=RULE_ID,
        rule_origin=RULE_ORIGIN,
        driver=BAND_PASS,
        terminal=True,
        cause=(
            f"{pairs} pair(s) in [{fuzzy.AMBIGUOUS_LOW:g}, {fuzzy.MERGE_THRESHOLD:g}), "
            f"{batches} batch(es)"
        ),
        cost_class=CostClass.BILLED_API,
        est_spend=estimate({k: v * batches for k, v in per_part.items()}),
    )
    return decision, read_set
