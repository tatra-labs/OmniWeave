"""The LLM band's row: the band's manifest, its decision and its work row. **D728, D729.**

W8.8, 06:1460-1478's decision Pass on the host's side, as D715 is the Segment Passes'. `op.resolve`
hands on the pairs it could not decide (`ResolveReport.band`, D727). This module renders each pair's
two sides, orders the pairs into batches of `LLM_BATCH`, and keeps the band's manifest in the CAS.
It writes 05:1103's three rows for the band and the `band:` work row that points at them. Nothing
here runs the Pass: D729's `BandRun` does, from `DeriveOperator`, batch by batch.

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

## The row, run (D729)

9. **A pair's answer is bought once.** Its `paid_key` (06 section 4.6) is the Pass, its
   `schema_version`, the card's `prompt_version`, the granted model's id and revision, `DECODE`,
   and the pair's two sides: everything the model is shown of it. No position, batch or file is in
   it, so the same two sides in another band is the same question.
10. **One batch, one INVOKE.** The pairs the cache cannot answer, in band order, go `LLM_BATCH` to
    an INVOKE, renumbered from 0, under the band's witness (D726 ruling 2). A row is one decision
    however many INVOKEs it takes (ruling 8), and D719's lease extension keeps it claimed.
11. **A decision is kept by its position in the batch it was sent in.** A frame without `same`, or
    one naming a position the batch does not hold, is held as `OW_GRAPH_UNPARSED_ITEM`
    (`row_kind = 'merge'`), with the batch named.
12. **A `same` answer is an `llm_band` merge**: winner `a` and loser `b` (`op.resolve` ruling 7's
    order), `Method.LLM`, `INFERRED`, the guards the band passed, and the model's reason. It is
    written under the generation's one run of the Pass, which names the band's decision. Its score
    is the band score, `jaro_winkler`, not 06 section 5.3's `llm_logprob`: an OpenAI-shaped server
    need not return log-probabilities, and constrained decoding bends them. The band score orders
    the model's merges after every fuzzy one. A `not same` writes nothing: a pair left apart is the
    safe default (06:1477).
13. **Every parsed answer is kept, `same` or not**, so a later band asking the pair again is
    answered from the cache. Read-policy clause 5 is not asked of a pair: its key names its two
    sides and no unit, so a pair answered under another band's row is not a collision.
14. **A row the cache answers whole is `skipped_cached`**: no call and zero Spend, and its merges
    are written all the same.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.blobs import format_ref
from omniweave_core.cache import CacheEntry, CacheLayer, CacheVerdict, cache_key, read_verdict
from omniweave_core.canonical import canonical, sha256_canonical
from omniweave_core.drivers.resolve import CostClass
from omniweave_core.errors import OwError
from omniweave_core.model.enums import Taint, Trust, enum_val_rows
from omniweave_core.model.records import Producer
from omniweave_core.operator import Outcome, StepMetrics, StepResult
from omniweave_core.store import sqlite as ow
from omniweave_core.store.cache import SqliteCacheIndex
from omniweave_core.store.items import register_pass
from omniweave_ports.types import FailureClass, UnitRef

from omniweave.graph import fuzzy
from omniweave.plan import operator_of
from omniweave.route.decision import RouteDecision
from omniweave.route.rung import Rung
from omniweave.run.dispatch import dispatch_key, new_invoke_id
from omniweave.run.operators.billed import BILLED_ENQUEUE_SQL, DECODE, estimate, service_table
from omniweave.run.operators.derive import DERIVE_PRIORITY, MERGE_LLM, as_spend
from omniweave.run.routing import INGEST_HINTS_DIGEST, decision_rows

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.blobs import BlobStore
    from omniweave_core.drivers.resolve import Candidate
    from omniweave_core.host.subproc import ServiceGrant
    from omniweave_core.operator import SpendVector
    from omniweave_core.store.queue import WorkRow

    from omniweave.graph.resolve import Band
    from omniweave.run.dispatch import Batch
    from omniweave.run.operators.derive import DeriveOperator, DerivePlan
    from omniweave.run.routing import ReadSet

__all__ = [
    "BAND_PASS",
    "BATCHES_KEY",
    "GUARDS",
    "HIGH_KEY",
    "LLM_BATCH",
    "LOW_KEY",
    "MAX_ALIASES",
    "PAIRS_KEY",
    "RULE_ID",
    "RULE_ORIGIN",
    "SCORE_KIND",
    "UNPARSED_CODE",
    "BandQueued",
    "BandRun",
    "Manifest",
    "decided",
    "enqueue_band",
    "manifest",
    "ordered",
    "pair_key",
    "put_manifest",
    "view",
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
  JOIN unit AS u ON u.unit_uri = d.uri
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

    @classmethod
    def of(cls, body: bytes) -> Manifest:
        """The manifest `body` holds (ruling 3).

        Raises:
            ValueError: `body` is not one; also `KeyError` or `TypeError` for a field it lacks.
        """
        kept = json.loads(body)
        return cls(
            members=tuple((int(a), int(b), float(s)) for a, b, s in kept["members"]),
            sides=tuple((dict(x), dict(y)) for x, y in kept["sides"]),
            witness=tuple((str(u), str(p), str(t)) for u, p, t in kept["witness"]),
        )

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


# =============================================================================================
# D729: the row, run
# =============================================================================================

GUARDS: Final = (
    *(name for name, _ in fuzzy.GUARDS),
    "scoped_label_crossdoc",
    "cooccurrence_in_segment",
)
"""Ruling 12: the guards a band pair passed, as `op.resolve` records them on a fuzzy merge."""
SCORE_KIND: Final = "jaro_winkler"
UNPARSED_CODE: Final = "OW_GRAPH_UNPARSED_ITEM"

_METHOD_LLM: Final = next(
    ordinal for domain, ordinal, name in enum_val_rows() if domain == "method" and name == "llm"
)
_SHA_SQL: Final = "SELECT content_sha256 FROM route_decision WHERE decision_id = ?"
_RUN_SQL: Final = """
INSERT OR IGNORE INTO derive_run(segment_id, pass_id, at_gen, producer_id, method, origin_operator,
                                 origin_driver, driver_schema_v, cost_class, decision_id,
                                 input_digest, cache_key, status, n_items, n_quarantined, spend)
VALUES(NULL, :pass_id, :gen, :producer_id, :method, :pass_id, :pass_id, :version, 'billed_api',
       :decision_id, :input_digest, :cache_key, 'empty', 0, 0, :spend)
"""
_RUN_ID_SQL: Final = (
    "SELECT run_id FROM derive_run WHERE pass_id = :pass_id AND segment_id IS NULL"
    " AND at_gen = :gen"
)
_MERGE_SQL: Final = """
INSERT INTO entity_merge(loser_id, winner_id, polarity, stage, method, trust, score, score_kind,
                         guards, reason, run_id, decided_at_gen)
SELECT :loser, :winner, 1, 'llm_band', :method, :trust, :score, :score_kind, :guards, :reason,
       :run_id, :gen
 WHERE EXISTS (SELECT 1 FROM entity WHERE entity_id = :loser)
   AND EXISTS (SELECT 1 FROM entity WHERE entity_id = :winner)
   AND NOT EXISTS (SELECT 1 FROM entity_merge WHERE loser_id = :loser AND winner_id = :winner
                    AND polarity = 1 AND retired_at_gen IS NULL)
"""
_QUARANTINE_SQL: Final = """
INSERT INTO quarantine(code, run_id, row_kind, payload, block_id, detail, at_gen)
VALUES(:code, :run_id, 'merge', :payload, NULL, '{}', :gen)
"""
_RUN_COUNTS_SQL: Final = """
UPDATE derive_run
   SET n_items = (SELECT count(*) FROM entity_merge WHERE run_id = :run_id),
       n_quarantined = (SELECT count(*) FROM quarantine WHERE run_id = :run_id),
       status = CASE WHEN EXISTS (SELECT 1 FROM entity_merge WHERE run_id = :run_id)
                     THEN 'ok' ELSE 'empty' END
 WHERE run_id = :run_id
"""


def _spend_of(spend_json: str) -> dict[str, int]:
    """The Spend a pair's cache entry recorded, as a hit replays it (D733)."""
    try:
        kept = json.loads(spend_json)
        return {k: int(v) for k, v in kept.items() if k in _DIMENSIONS}
    except (ValueError, TypeError, AttributeError):
        return {}


_DIMENSIONS: Final = frozenset(
    {"wall_ms", "cpu_ms", "gpu_ms", "tokens_in", "tokens_out", "calls", "bytes_egress"}
)


def pair_key(card: Any, a: Mapping[str, Any], b: Mapping[str, Any], model_id: str,
             model_rev: str) -> str:  # fmt: skip
    """Ruling 9: one pair's `paid_key`, over what the model is shown of it."""
    sibling = card.derive_sibling
    return sha256_canonical(
        {
            "pass": card.identity.id,
            "schema_version": card.identity.schema_version,
            "prompt_version": "" if sibling is None else sibling.prompt_version,
            "model_id": model_id,
            "model_rev": model_rev,
            "decode": DECODE,
            "pair": [dict(a), dict(b)],
        }
    )


def view(one: Manifest, name: str, positions: Sequence[int]) -> bytes:
    """Ruling 10: one batch as the driver reads it (D726): the header, then the pairs renumbered
    from 0, and no end's id."""
    frames: list[dict[str, Any]] = [
        {
            "t": "pairs",
            "batch": name,
            "n": len(positions),
            "witness": [{"unit_uri": u, "unit_part": p, "token": t} for u, p, t in one.witness],
        }
    ]
    frames += [
        {"t": "pair", "pair": j, "a": dict(one.sides[i][0]), "b": dict(one.sides[i][1])}
        for j, i in enumerate(positions)
    ]
    return b"".join(
        json.dumps(f, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
        for f in frames
    )


def decided(body: bytes, n: int) -> tuple[dict[int, tuple[bool, str]], list[dict[str, Any]]]:
    """Ruling 11: the batch's decisions by position, and its malformed frames."""
    found: dict[int, tuple[bool, str]] = {}
    malformed: list[dict[str, Any]] = []
    for line in body.splitlines():
        frame = json.loads(line) if line.strip() else {}
        if frame.get("t") != "decision":
            continue
        pair = frame.get("pair")
        if "same" in frame and isinstance(pair, int) and 0 <= pair < n:
            found[pair] = (bool(frame["same"]), str(frame.get("reason", "")))
        else:
            malformed.append(frame)
    return found, malformed


@dataclass(frozen=True, slots=True)
class _Asked:
    """One batch's answer: decisions by position in `members`, the malformed, and its Spend."""

    found: dict[int, tuple[bool, str]]
    malformed: list[dict[str, Any]]
    spend: dict[str, int]


@dataclass(frozen=True, slots=True)
class _Refused:
    """One batch the driver did not answer."""

    failure: FailureClass
    message: str


class BandRun:
    """Rulings 9-14: the band's row run batch by batch, its merges written under its decision."""

    __slots__ = ("_op",)

    def __init__(self, operator: DeriveOperator) -> None:
        self._op = operator

    def __call__(
        self, batch: Batch, *, granted: Any, card: Any, producer: Producer
    ) -> list[StepResult]:
        grants, refused = self._op._grants(card)
        return [
            self._row(batch, row, granted=granted, card=card, producer=producer, grants=grants,
                      refused=refused)
            for row in batch.rows
        ]  # fmt: skip

    def _row(
        self,
        batch: Batch,
        row: WorkRow,
        *,
        granted: Any,
        card: Any,
        producer: Producer,
        grants: tuple[ServiceGrant, ...],
        refused: str,
    ) -> StepResult:
        op = self._op
        unit = UnitRef(uri=row.unit_uri, part=row.unit_part, content_sha256="", byte_len=0)
        if refused:  # D713: a Service that will not attach fails the row, never the drain
            return op._failed(
                BAND_PASS, row, unit, producer, failure=FailureClass.UPSTREAM_UNAVAILABLE,
                message=refused,
            )  # fmt: skip
        one = self._manifest(row)
        if one is None:
            return op._failed(BAND_PASS, row, unit, producer, failure=FailureClass.EMPTY_RESULT,
                              message=f"the manifest {row.unit_part} names is gone")  # fmt: skip
        keys = [pair_key(card, a, b, grants[0].model_id, grants[0].model_rev) for a, b in one.sides]
        answers, replayed = self._cached(keys)
        count = op._tally.band
        count.rows += 1
        count.cached += len(answers)
        asks = [i for i in range(len(keys)) if i not in answers]
        held: list[dict[str, Any]] = []
        spent: dict[str, int] = {}
        for k, start in enumerate(range(0, len(asks), LLM_BATCH)):
            positions = asks[start : start + LLM_BATCH]
            got = self._ask(batch, row, one, k, positions, granted=granted, grants=grants)
            if isinstance(got, _Refused):
                return op._failed(BAND_PASS, row, unit, producer, failure=got.failure,
                                  message=got.message)  # fmt: skip
            fresh = {positions[j]: answer for j, answer in got.found.items()}
            answers.update(fresh)
            held += [{"batch": f"{one.name}/{k}", "frame": f} for f in got.malformed]
            for dim, value in got.spend.items():
                spent[dim] = spent.get(dim, 0) + value
            self._remember(row, keys, card=card, granted=granted, fresh=fresh, spend=got.spend,
                           n=len(positions))  # fmt: skip
            count.calls += 1
            count.asked += len(positions)
        merged = self._land(row, one, card=card, producer=producer, answers=answers, held=held,
                            spent=spent)  # fmt: skip
        billed = spent if asks else replayed
        count.merged += merged
        count.quarantined += len(held)
        return StepResult(
            outcome=Outcome.OK if asks else Outcome.SKIPPED_CACHED,
            unit=unit,
            identity=producer,
            cache_key=row.cache_key,
            produced=(),
            metrics=StepMetrics(
                spend=cast("SpendVector", as_spend(billed)),
                was_cache_hit=not asks,
                rows_written=merged,
            ),
        )

    def _manifest(self, row: WorkRow) -> Manifest | None:
        """Ruling 3: the decision names the manifest by its sha256."""
        op = self._op

        def read(connection: Any) -> Any:
            return connection.execute(_SHA_SQL, (row.decision_id,)).fetchone()

        found = cast(
            "tuple[str] | None",
            op._thread.run(
                ow.Unit(name="band.manifest", run=read, cost_class="free", wait_ms=ow.BATCH_WAIT_MS)
            ),
        )
        if found is None:
            return None
        try:
            with op._parse._cas.open(str(found[0])) as handle:
                return Manifest.of(handle.read())
        except (OSError, ValueError, KeyError, OwError):
            return None

    def _cached(self, keys: Sequence[str]) -> tuple[dict[int, tuple[bool, str]], dict[str, int]]:
        """Ruling 13: each pair the cache holds an answer for, by position, and the Spend the hits
        replay (D733)."""
        op = self._op
        index = SqliteCacheIndex(op._thread, clock=op._parse._ctx.clock)
        found = index.get_many(list(dict.fromkeys(keys)))
        out: dict[int, tuple[bool, str]] = {}
        replayed: dict[str, int] = {}
        for i, key in enumerate(keys):
            entry = found.get(key)
            answer = None if entry is None else self._answer(entry.ref)
            asked = ("", "") if entry is None else (entry.unit_uri, entry.unit_part)
            if (
                read_verdict(entry, asked_for=asked, blob_ok=answer is not None)
                is not (CacheVerdict.HIT)
                or answer is None
            ):
                continue
            out[i] = answer
            index.touch(key)
            for dim, value in _spend_of(cast("Any", entry).spend_json).items():
                replayed[dim] = replayed.get(dim, 0) + value
        return out, replayed

    def _answer(self, ref: str) -> tuple[bool, str] | None:
        try:
            with self._op._parse._cas.open_ref(ref) as handle:
                kept = json.loads(handle.read())
            return bool(kept["same"]), str(kept["reason"])
        except (OSError, ValueError, KeyError, TypeError, OwError):
            return None

    def _ask(
        self,
        batch: Batch,
        row: WorkRow,
        one: Manifest,
        k: int,
        positions: Sequence[int],
        *,
        granted: Any,
        grants: tuple[ServiceGrant, ...],
    ) -> _Asked | _Refused:
        """Ruling 10: one batch, one INVOKE."""
        op = self._op
        body = view(one, f"{one.name}/{k}", positions)
        digest = op._parse._cas.put(io.BytesIO(body))
        sent = UnitRef(uri=row.unit_uri, part=row.unit_part, content_sha256=digest.hex(),
                       byte_len=len(body))  # fmt: skip
        invoke = batch.invoke_id if k == 0 else new_invoke_id(op._parse._ctx.clock, os.urandom(10))
        reply = op._call(
            type(batch)(invoke_id=invoke, rows=(row,)), [(0, (), sent, format_ref(digest))],
            granted, BAND_PASS, grants,
        )  # fmt: skip
        if reply.outcomes[0] not in (Outcome.OK, Outcome.OK_PARTIAL):
            verdict = None if reply.report is None else reply.report.failures[0]
            failure = FailureClass.DRIVER_CRASHED if verdict is None else verdict.failure_class
            return _Refused(failure, "" if verdict is None else verdict.message)
        produced = reply.produced[0] if reply.produced else ()
        items = [ref for ref in produced if ref.kind == "graph_items"]
        if len(items) != 1:
            return _Refused(
                FailureClass.DRIVER_BUG, f"{BAND_PASS} produced {len(items)} graph_items refs"
            )
        found, malformed = decided(op._body(items[0]), len(positions))
        spend = reply.spend[0] if reply.spend else None
        dims = ("tokens_in", "tokens_out", "calls", "bytes_egress")
        return _Asked(found, malformed, {d: int(getattr(spend, d, 0)) for d in dims})

    def _remember(
        self,
        row: WorkRow,
        keys: Sequence[str],
        *,
        card: Any,
        granted: Any,
        fresh: Mapping[int, tuple[bool, str]],
        spend: Mapping[str, int],
        n: int,
    ) -> None:
        """Ruling 13: each answered pair kept under its key, with its share of the batch's Spend."""
        op = self._op
        share = canonical({d: v // max(n, 1) for d, v in spend.items()}).decode("utf-8")
        entries = []
        for i, (same, reason) in fresh.items():
            kept = canonical({"same": same, "reason": reason})
            entries.append(
                CacheEntry(
                    cache_key=keys[i],
                    layer=CacheLayer.CALL,
                    cost_class="billed_api",
                    ref=format_ref(op._parse._cas.put(io.BytesIO(kept))),
                    bytes=len(kept),
                    unit_uri=row.unit_uri,
                    unit_part=row.unit_part,
                    driver=BAND_PASS,
                    driver_schema_v=card.identity.schema_version,
                    config_digest=granted.config_digest,
                    origin_operator=BAND_PASS,
                    spend_json=share,
                    micros=0,
                )
            )
        if entries:
            SqliteCacheIndex(op._thread, clock=op._parse._ctx.clock).put(
                entries, allowed_units=frozenset({(row.unit_uri, row.unit_part)})
            )

    def _land(
        self,
        row: WorkRow,
        one: Manifest,
        *,
        card: Any,
        producer: Producer,
        answers: Mapping[int, tuple[bool, str]],
        held: Sequence[Mapping[str, Any]],
        spent: Mapping[str, int],
    ) -> int:
        """Ruling 12: the `same` answers as `llm_band` merges, the malformed held, under the
        generation's one run of the Pass, which names the band's decision."""
        op = self._op
        producer_id = op._producer_id(producer)
        gen = op._parse._ctx.generation

        def write(connection: Any) -> int:
            register_pass(connection, card)
            connection.execute(
                _RUN_SQL,
                {
                    "pass_id": BAND_PASS,
                    "gen": gen,
                    "producer_id": producer_id,
                    "method": _METHOD_LLM,
                    "version": card.identity.schema_version,
                    "decision_id": row.decision_id,
                    "input_digest": hashlib.blake2b(one.body, digest_size=16).digest(),
                    "cache_key": row.cache_key,
                    "spend": canonical(dict(spent)).decode("utf-8"),
                },
            )
            run_id = int(connection.execute(_RUN_ID_SQL, {"pass_id": BAND_PASS, "gen": gen})
                         .fetchone()[0])  # fmt: skip
            merged = 0
            for i, (same, reason) in sorted(answers.items()):
                if not same:
                    continue
                a, b, score = one.members[i]
                merged += connection.execute(
                    _MERGE_SQL,
                    {
                        "loser": b,
                        "winner": a,
                        "method": _METHOD_LLM,
                        "trust": int(Trust.INFERRED),
                        "score": score,
                        "score_kind": SCORE_KIND,
                        "guards": json.dumps(list(GUARDS)),
                        "reason": reason,
                        "run_id": run_id,
                        "gen": gen,
                    },
                ).rowcount
            for frame in held:
                connection.execute(
                    _QUARANTINE_SQL,
                    {"code": UNPARSED_CODE, "run_id": run_id,
                     "payload": canonical(dict(frame)).decode("utf-8"), "gen": gen},
                )  # fmt: skip
            connection.execute(_RUN_COUNTS_SQL, {"run_id": run_id})
            return merged

        return cast(
            "int",
            op._thread.run(
                ow.Unit(name="band.write", run=write, cost_class="free", wait_ms=ow.BATCH_WAIT_MS)
            ),
        )
