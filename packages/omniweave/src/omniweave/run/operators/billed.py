"""The billed Passes' rows: each eligible Segment's decision and its work row. **D715.**

W8.8's eighth cell. 06:1514-1517: *"each Segment is its own `route_decision` (billed passes route
at `part` granularity, one decision each), its own `derive_run`, its own prompt and its own
`paid_key`."* `eligible()` (D714) says which Segments a billed Pass may run on; this module writes,
for each one, the three rows of 05:1103's *"write route_decision -- BEFORE anything runs"* and the
`seg:` work row that points at it. Nothing here runs the Pass.

## Rulings (the ledger's D715)

1. **A Segment's decision is the selector's, on the `ENRICH` rung** (05:844, *"`derive.*`"*). No
   `surface = "graph"` rule compiles yet (`route/policy.py` refuses the surface), so the rule is
   the selector itself: `rule_id = "graph.eligible"`, its origin 06:744. The read set is the two
   readings it compared, the Segment's `covered_frac` and `[graph] llm_coverage_floor`. The
   `cause` renders them, so *"why it was billed"* is a `GROUP BY`, as 05:1974 asks of a cause.
2. **The identity is the unit's content and the Segment's part.** `content_sha256` is the unit's,
   as every other decision's is; `unit_part` is the `seg:` part. The same Segment in two files is
   two decisions, which a decision keyed on a block digest would not be. 05:1915 keys on the
   unit's content, and a Segment's part says which part of it.
3. **The estimate is the card's `per_part` and no money** (06 section 2.3). `est_micros` and
   `reserved_micros` stay 0, as routing writes them: no `PriceBook` is loaded. `admission` is
   `admitted`, because nothing yet holds a reservation to defer it against.
4. **The work row is `billed_api`, `pending`, and names its decision and its Service.** `service`
   is the table the card's first `[hardware] services` entry names (D713). The cache key is the
   free rows' recipe over the Segment's `UnitRef`, part included. It stays so under D725:
   `paid_key` (06:1636) names the served model, which is known only once the row runs (ruling 8).
5. **Idempotent by identity.** The decision converges on `route_decision_identity`, and the work
   row on `work_identity`. A second enqueue over an unchanged store writes no row, and a Segment
   whose text changed has a new part and so a new decision and a new row.
6. **A document is in scope once it is segmented** (its `derive.segment` row is `done`), at its
   head generation. The order inside a run is the caller's: every cheaper Pass's cover must be
   written first, or the selector reads a ledger that is still filling. D724 makes that order the
   run's (`billed_phases`): the billed Passes are enqueued and drained one place at a time, in
   `(cost_rank, phase)` order, so a Pass at phase 20 reads the cover a Pass at phase 10 wrote in
   the same run.
7. **A Pass that binds runs only where its lane has cover** (D724, coverage ruling 10).

## The call cache (D725, 06 section 4.6)

8. **`paid_key` is 06:1636's recipe over what the host can know, taken when the row runs.** The
   Service is attached then, and its grant names the model the probe found. The pass, its
   `schema_version`,
   the Segment's `content_digest`, the model id and revision the grant names, the decode
   configuration (`DECODE`) and the vocabulary the billed view carries. In `prompt_fp`'s place
   stands the card's `prompt_version`: the prompt is rendered in the driver, by a package
   `omniweave` may not import, and `omniweave-llm`'s golden test pins each lane's rendered
   `prompt_fp` to the card's `prompt_version`, so editing a prompt without bumping the version
   fails CI.
   `driver_version` is left out, as 06:1614 has it: a bug-fix release never re-bills.
9. **What is cached is the Segment's frames and the cites they were answered against.** A Segment
   with the same `content_digest` in another document holds the same blocks in the same order
   under other cites, so a hit is replayed by position: the stored cites map onto the current
   view's, and nothing else in the frames is touched. A view whose block count differs is a miss.
10. **Only an answer that parsed is cached.** An unparsed answer is a malformed frame the model may
    not repeat, and caching it would replay a failure forever.
11. **A hit is `skipped_cached`**: the row is `done`, its run is written under the row's own
    decision, its Spend is zero, and no call is made.
12. **The read policy's clause 5 is asked of the Segment's part, not its file.** 08:1439's six
    clauses judge every entry (`cache.read_verdict`), and clause 5 calls a recorded unit other than
    the one asked for a collision. `paid_key` names no file, by 06:1636's recipe, so the same text
    in a second file is the same question and not a collision. The part is `seg:` and the
    `content_digest`'s first 16 hex, so a part that differs is still refused as clause 5 refuses it.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.cache import cache_key
from omniweave_core.canonical import canonical, sha256_canonical
from omniweave_core.drivers.resolve import CostClass
from omniweave_core.model.records import Producer
from omniweave_core.store.coverage import BILLED_PASSES, eligible, place_of
from omniweave_ports.types import UnitRef

from omniweave.plan import operator_of
from omniweave.route.decision import RouteDecision
from omniweave.route.rung import Rung
from omniweave.route.spend import Spend
from omniweave.run.dispatch import dispatch_key
from omniweave.run.operators.derive import DERIVE_PRIORITY
from omniweave.run.routing import INGEST_HINTS_DIGEST, decision_rows

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from omniweave_core.drivers.resolve import Candidate
    from omniweave_core.store.coverage import BilledPass, Eligible
    from omniweave_core.store.items import ItemView

    from omniweave.run.operators.derive import DerivePlan
    from omniweave.run.routing import ReadSet

__all__ = [
    "BILLED_ENQUEUE_SQL",
    "COVERED_KEY",
    "DECODE",
    "FLOOR_KEY",
    "RULE_ID",
    "RULE_ORIGIN",
    "BilledQueued",
    "billed_phases",
    "enqueue_billed",
    "paid_key",
    "remembered",
    "replayed",
]

RULE_ID: Final = "graph.eligible"
RULE_ORIGIN: Final = "builtin:06-structure-extraction.md:744"
COVERED_KEY: Final = "graph.covered_frac"
FLOOR_KEY: Final = "graph.llm_coverage_floor"
COVERAGE_VERSION: Final = "coverage/1"
"""The reading's provider version: `store.coverage`'s arithmetic as D703 and D705 fixed it."""

BILLED_ENQUEUE_SQL: Final = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, status, priority,
                 driver, decision_id, dispatch_key, service)
VALUES(:unit_uri, :unit_part, :operator, :op_version, :cache_key, 'billed_api', 'pending',
       :priority, :driver, :decision_id, :dispatch_key, :service)
ON CONFLICT(unit_uri, unit_part, operator, op_version) DO NOTHING
"""

_SEGMENTED_SQL: Final = """
SELECT u.unit_uri, u.content_sha256, IFNULL(u.bytes, 0) FROM unit AS u
 WHERE EXISTS (SELECT 1 FROM work WHERE unit_uri = u.unit_uri AND unit_part = ''
                AND operator = 'derive.segment' AND status = 'done')
 ORDER BY u.unit_uri
"""
_DOC_SQL: Final = "SELECT doc_ord FROM doc WHERE doc_key = ?"


@dataclass(slots=True)
class BilledQueued:
    """What one enqueue wrote, per billed Pass: Segments handed over, and rows that are new."""

    eligible: Counter[str] = field(default_factory=Counter)
    queued: Counter[str] = field(default_factory=Counter)
    documents: Counter[str] = field(default_factory=Counter)

    def merged(self, other: BilledQueued) -> BilledQueued:
        """This enqueue's counts and `other`'s, one phase's after another's (D724)."""
        return BilledQueued(
            self.eligible + other.eligible,
            self.queued + other.queued,
            self.documents + other.documents,
        )

    def lines(self) -> list[str]:
        """One report line per billed Pass the plan held (D716)."""
        return [
            f"  billed    {pass_id}: {self.eligible[pass_id]} Segment(s) of "
            f"{self.documents[pass_id]} document(s) under the coverage floor, "
            f"{self.queued[pass_id]} queued"
            for pass_id in sorted({*self.eligible, *self.queued, *self.documents})
        ]


DECODE: Final = {"temperature": 0, "response_format": "json_schema", "strict": True, "decodable": 1}
"""Ruling 8: the decode configuration `LanePass` sends (D711, D717), as `paid_key`'s `decode_digest`
input. Changing what is sent changes the answer, so it changes this, and every key with it."""


def paid_key(card: Any, view: ItemView, model_id: str, model_rev: str) -> str:
    """Ruling 8: 06:1636's `paid_key` for one Segment, as 64 hex."""
    header = json.loads(view.body.split(b"\n", 1)[0])
    sibling = card.derive_sibling
    return sha256_canonical(
        {
            "pass": card.identity.id,
            "schema_version": card.identity.schema_version,
            "segment": view.ref.content_digest.hex(),
            "prompt_version": "" if sibling is None else sibling.prompt_version,
            "model_id": model_id,
            "model_rev": model_rev,
            "decode": DECODE,
            "vocab": {
                "etypes": header.get("etypes", []),
                "document_scoped": header.get("document_scoped", []),
                "relations": header.get("relations", []),
            },
        }
    )


def _cites(view: ItemView) -> list[str]:
    """The view's member cites, in block order."""
    found = []
    for line in view.body.splitlines():
        frame = json.loads(line)
        if frame.get("t") == "block":
            found.append(str(frame["cite"]))
    return found


def remembered(view: ItemView, body: bytes) -> bytes | None:
    """Rulings 9-10: what the cache keeps of one Segment's answer; `None` when it did not parse."""
    frames = [json.loads(line) for line in body.splitlines() if line.strip()]
    if any("unparsed" in frame for frame in frames):
        return None
    return canonical({"cites": _cites(view), "frames": frames})


def replayed(payload: bytes, view: ItemView) -> bytes | None:
    """Ruling 9: a cached answer replayed onto `view`'s cites by position, or `None` (a miss)."""
    try:
        kept = json.loads(payload)
        cites, frames = list(kept["cites"]), list(kept["frames"])
    except (ValueError, KeyError, TypeError):
        return None
    now = _cites(view)
    if len(now) != len(cites) or not all(isinstance(frame, dict) for frame in frames):
        return None
    moved = dict(zip(cites, now, strict=True))
    lines = []
    for frame in frames:
        moved_frame = _remap(frame, moved)
        if moved_frame.get("t") == "seg":
            moved_frame["seg"] = view.seg
        lines.append(json.dumps(moved_frame, separators=(",", ":"), ensure_ascii=False))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _remap(node: Any, moved: Mapping[str, str]) -> Any:
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "cite" and isinstance(value, str):
                out[key] = moved.get(value, value)
            elif key == "cites" and isinstance(value, list):
                out[key] = [moved.get(str(c), c) for c in value]
            else:
                out[key] = _remap(value, moved)
        return out
    if isinstance(node, list):
        return [_remap(value, moved) for value in node]
    return node


def billed_phases(plan: DerivePlan) -> list[tuple[str, ...]]:
    """The plan's billed Passes grouped by place, cheapest first (ruling 6, D724)."""
    by_id = {billed.pass_id: billed for billed in BILLED_PASSES}
    places: dict[tuple[int, int], list[str]] = {}
    for candidate in plan.billed:
        pass_id = candidate.card.identity.id
        places.setdefault(by_id[pass_id].place, []).append(pass_id)
    return [tuple(places[place]) for place in sorted(places)]


def enqueue_billed(
    connection: Any,
    plan: DerivePlan,
    *,
    floor: float,
    now_ms: int,
    passes: Collection[str] | None = None,
) -> BilledQueued:
    """Rulings 1-7 for every billed Pass the plan holds, or those `passes` names, over every
    segmented document."""
    out = BilledQueued()
    by_id = {billed.pass_id: billed for billed in BILLED_PASSES}
    units = connection.execute(_SEGMENTED_SQL).fetchall()
    for candidate in plan.billed:
        if passes is not None and candidate.card.identity.id not in passes:
            continue
        billed = by_id[candidate.card.identity.id]
        place = place_of(connection, billed)
        for uri, sha, size in units:
            found = connection.execute(_DOC_SQL, (bytes.fromhex(str(sha))[:16],)).fetchone()
            if found is None:
                continue
            handed = list(
                eligible(
                    connection,
                    doc_ord=int(found[0]),
                    lane=billed.lane,
                    before=place,
                    floor=floor,
                    bound=billed.binds,
                )
            )
            if handed:
                out.documents[billed.pass_id] += 1
            for one in handed:
                unit = UnitRef(
                    uri=str(uri), part=one.part, content_sha256=str(sha), byte_len=int(size)
                )
                out.eligible[billed.pass_id] += 1
                out.queued[billed.pass_id] += _write(
                    connection,
                    plan,
                    candidate=candidate,
                    billed=billed,
                    unit=unit,
                    one=one,
                    floor=floor,
                    now_ms=now_ms,
                )
    return out


def _write(
    connection: Any,
    plan: DerivePlan,
    *,
    candidate: Candidate,
    billed: BilledPass,
    unit: UnitRef,
    one: Eligible,
    floor: float,
    now_ms: int,
) -> int:
    card = candidate.card
    decision, read_set = _decision(plan, card, billed, unit, one, floor=floor)
    for sql, params in decision_rows(
        unit.uri, decision, read_set, driver=billed.pass_id, generation=plan.ctx.generation,
        now_ms=now_ms,
    ):  # fmt: skip
        connection.execute(sql, params)
    producer = Producer(
        operator=operator_of(billed.pass_id),
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
                "operator": billed.pass_id,
                "op_version": card.identity.schema_version,
                "cache_key": cache_key(unit, producer, card, plan.ctx, salt=""),
                "priority": DERIVE_PRIORITY,
                "driver": billed.pass_id,
                "decision_id": decision.decision_id(),
                "dispatch_key": dispatch_key(
                    billed.pass_id, candidate.config_digest, str(candidate.isolation_granted)
                ),
                "service": _service(services[0]) if services else None,
            },
        ).rowcount
    )


def _decision(
    plan: DerivePlan, card: Any, billed: BilledPass, unit: UnitRef, one: Eligible, *, floor: float
) -> tuple[RouteDecision, ReadSet]:
    """Rulings 1-3: the selector's decision for one Segment, and the read set it compared."""
    read_set: ReadSet = ((COVERED_KEY, COVERAGE_VERSION, one.covered), (FLOOR_KEY, "", floor))
    per_part = card.cost_model.per_part if card.cost_model is not None else {}
    decision = RouteDecision(
        content_sha256=unit.content_sha256,
        unit_part=unit.part,
        lane=billed.lane,
        rung=Rung.ENRICH,
        policy_digest=plan.ctx.policy_digest,
        pricebook_digest=plan.ctx.pricebook_digest,
        hints_digest=INGEST_HINTS_DIGEST,
        read_set_digest=sha256_canonical([[k, v, value] for k, v, value in read_set]),
        matched=True,
        rule_id=RULE_ID,
        rule_origin=RULE_ORIGIN,
        driver=billed.pass_id,
        terminal=True,
        cause=f"{COVERED_KEY}={one.covered:.2f}<{floor:.2f}",
        cost_class=CostClass.BILLED_API,
        est_spend=_spend(per_part),
    )
    return decision, read_set


def _spend(per_part: Mapping[str, float]) -> Spend:
    """Ruling 3: the card's `per_part`, dimension by dimension; one it does not name is 0."""

    def dim(name: str) -> int:
        return int(per_part.get(name, 0))

    return Spend(
        wall_ms=dim("wall_ms"),
        cpu_ms=dim("cpu_ms"),
        gpu_ms=dim("gpu_ms"),
        tokens_in=dim("tokens_in"),
        tokens_out=dim("tokens_out"),
        calls=dim("calls"),
        bytes_egress=dim("bytes_egress"),
    )


def _service(declared: str) -> str:
    from omniweave_core.modelserver import service_name  # noqa: PLC0415 -- a billed row only

    return service_name(declared)
