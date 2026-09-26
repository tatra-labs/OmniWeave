"""Hops 5-8 for every identified unit: evidence, `evaluate()`, `resolve()`, the decision, `admit()`.

02:460 names the expander task's second pass: *"then, per part, resolution, evidence, `evaluate()`,
`admit()` and finally `omniweave.plan`'s single `INSERT`"*. `run/expand.py` is the first pass and
this module is the second; `omniweave.plan` is the one statement at its end.

## WHICH PART OF 05 SECTION 4.3'S LOOP RUNS HERE

05:1089-1106 is a loop over seven rungs, every admitted lane, two phases and the `CostClass` groups
of each demand plan, and it ends by running the driver. This build runs its front:

- **one lane, `text`**, which 05:1089 makes mandatory. The lane admissions `evaluate()` returns as
  modifiers are counted and not acted on: nothing here runs a second lane's driver;
- **two rungs, `GATE` then `DECODE`**, stopping at the first action. `REPAIR` and above read a
  decoded part, and nothing has been decoded;
- **the `select` phase**. `settle` is by definition the phase that reads a driver's output
  (05:1140);
- **the FREE group, from the roster**. No signal computer exists: `signals.toml` declares 25 keys
  and no code computes one. What is known without reading bytes is here -- the format and its basis
  (`route.detect`, at identify), the size, the part count, the trust class, the trigger. A rule
  that `defer`s on a key nobody computes degrades to `skip` exactly as 05:1130 says, and the key is
  counted as `signal_unavailable` on the report.

Then, for a matched action: a GATE refusal is a decision row with `driver = ''` and a failed unit
(05:1180); a DECODE driver goes through `resolve()` (hop 5, memoised per media type), the decision
row is written *before anything runs* (05:1103), `admit()` answers for its cost class (hop 8), and
`omniweave.plan` writes the routed row -- all four in one transaction per unit.

**A driver the catalog cannot resolve plans nothing.** The unit stays `identified` and the report
names the rejection. 05:1105-1106's answer -- the `DEGRADE` rung's `degrade.driver-unavailable`,
read through `driver.unavailable` -- is a later rung's.

**A container is not settled.** `decode.container-expanded` answers `outcome = "ok"` because *"a
container's children were minted at acquire"*; here they never were (05:764-776 is not built), so
settling the container would record work that did not happen. It is reported unrouted (D577).

Specified in 02-architecture.md section 4.1 (hops 5-9), 05-ingest-and-routing.md sections 4.3
and 4.6, and 04-driver-system.md section 4.8.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final, TypeAlias, cast

from omniweave_core.budget import Admitted
from omniweave_core.canonical import canonical, sha256_canonical
from omniweave_core.drivers.resolve import Policy, Requirement, resolution_report, resolve
from omniweave_core.probe import probe_env
from omniweave_core.store.budget import SqliteBudgetLedger
from omniweave_core.store.sqlite import BATCH_WAIT_MS, Unit
from omniweave_ports.types import CostClass, Isolation

from omniweave import plan as planner
from omniweave.route.admit import admit
from omniweave.route.decision import RouteHints
from omniweave.route.eval import evaluate, pending_deferrals
from omniweave.route.evidence import Evidence
from omniweave.route.ledger import payload_bytes
from omniweave.route.rung import Rung
from omniweave.run import expand

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.canonical import JsonValue
    from omniweave_core.config import Config
    from omniweave_core.drivers.catalog import Catalog
    from omniweave_core.drivers.resolve import Candidate, Resolution
    from omniweave_core.operator import RunContext
    from omniweave_core.store.sqlite import StoreThread

    from omniweave.route.decision import RouteDecision
    from omniweave.route.evidence import Scalar, SignalRegistry
    from omniweave.route.policy import RoutePolicy

__all__ = [
    "LANE",
    "PHASE",
    "RUNGS",
    "RouteTally",
    "resolve_policy",
    "route_identified",
    "unit_evidence",
]

LANE: Final[str] = "text"
RUNGS: Final[tuple[Rung, ...]] = (Rung.GATE, Rung.DECODE)
PHASE: Final[str] = "select"
PORT: Final[str] = "parse/1"
ReadSet: TypeAlias = "tuple[tuple[str, str, Scalar], ...]"
HINTS: Final[RouteHints] = RouteHints()
"""An `ow ingest` passes no hints: `--max-rung` and `--allow-cost` are `ow add`'s and `ow query`'s
flags, and `RouteHints` has no field `ow ingest` would set (05:2018-2033)."""

_BUILTIN: Final[str] = "builtin"

IDENTIFIED_UNITS_SQL: Final[str] = """
SELECT unit_uri, content_sha256, bytes, part_count, format, media_type, trust_class, derived
  FROM unit
 WHERE state = 'identified' AND last_seen_gen = :generation AND unit_uri > :after
 ORDER BY unit_uri
 LIMIT :limit
"""

EVIDENCE_SQL: Final[str] = """
INSERT INTO route_evidence(evidence_digest, payload, first_seen_at) VALUES(:digest, :payload, :at)
ON CONFLICT(evidence_digest) DO NOTHING
"""

DECISION_SQL: Final[str] = """
INSERT INTO route_decision(
  decision_id, content_sha256, unit_part, lane, rung, policy_digest, pricebook_digest,
  hints_digest, read_set_digest, driver, cost_class, rule_id, rule_origin, cause, reason,
  slice_key, evidence_digest, est_spend, est_micros, reserved_micros, admission, degraded,
  degradations, generation, decided_at)
VALUES(
  :decision_id, :content_sha256, :unit_part, :lane, :rung, :policy_digest, :pricebook_digest,
  :hints_digest, :read_set_digest, :driver, :cost_class, :rule_id, :rule_origin, :cause, :reason,
  :slice_key, :evidence_digest, :est_spend, 0, 0, :admission, :degraded, :degradations,
  :generation, :decided_at)
ON CONFLICT(content_sha256, unit_part, lane, rung, policy_digest, pricebook_digest, hints_digest,
            read_set_digest) DO NOTHING
"""
"""05:1175-1177: *"`INSERT ... ON CONFLICT(<the eight identity columns>) DO NOTHING`"* -- two runs
that compute one decision converge on one row, because a decision is a pure function of its
identity. `decision_id` is derived from the same eight, so the conflicting row carries the id this
run computed and no re-select is needed to learn it."""

UNIT_DECISION_SQL: Final[str] = """
INSERT OR IGNORE INTO route_unit_decision(unit_uri, unit_part, lane, decision_id, first_seen_at)
VALUES(:unit_uri, :unit_part, :lane, :decision_id, :at)
"""

RESOLUTION_SQL: Final[str] = """
INSERT INTO resolution_report(run_id, resolution_digest, port, requirement_json, report_json,
                              first_seen_ms)
VALUES(:run_id, :digest, :port, :requirement_json, :report_json, :at)
ON CONFLICT(run_id, resolution_digest) DO UPDATE SET hits = hits + 1
"""
"""04:1442: one row per `(run_id, resolution_digest)` with a hit counter, *"not one per unit"*."""

REFUSED_SQL: Final[str] = """
UPDATE unit SET state = 'failed', acq_failure_class = :failure_class
 WHERE unit_uri = :unit_uri AND state = 'identified'
"""
"""A matched refusal is terminal: 05:405's *"failed (a permanent FailureClass, no doc row)"*."""


@dataclass(slots=True)
class RouteTally:
    """What hops 5-9 did with each identified unit, counted by the name a reader acts on."""

    planned: Counter[str] = field(default_factory=Counter)
    refused: Counter[str] = field(default_factory=Counter)
    unrouted: Counter[str] = field(default_factory=Counter)
    unavailable: Counter[str] = field(default_factory=Counter)

    def lines(self) -> tuple[str, ...]:
        if not (self.planned or self.refused or self.unrouted):
            return ()
        out = [f"  route     {_shown(self.planned, 'planned')}; {_shown(self.refused, 'refused')}"]
        if self.unrouted:
            out.append(f"  route     {_shown(self.unrouted, 'unrouted')}")
        if self.unavailable:
            out.append(f"  route     signal_unavailable: {_shown(self.unavailable, '')}".rstrip())
        return tuple(out)


def _shown(counts: Counter[str], label: str) -> str:
    total = sum(counts.values())
    detail = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
    head = f"{total} {label}".strip()
    return f"{head} ({detail})" if detail else head


def resolve_policy(config: Config, *, locked_ids: frozenset[str] = frozenset()) -> Policy:
    """`resolve()`'s `Policy` from `[drivers]`, with this host's `ProbeEnv`. Startup step 7's half.

    `host_env` is `probe.probe_env()`, the one core builder of a `ProbeEnv`; without it every card
    that declares any `[hardware]` demand is `HARDWARE_ABSENT host_env_undeclared`, which is all
    three first-party cards. `locked_ids` is `omniweave.lock`'s driver rows, which no module in
    the workspace writes -- so `[drivers] require_lock = true`, the shipped default, refuses every
    driver until one does, and that is reported rather than waived (D576).
    """
    get = config.get
    return Policy(
        locked_ids=locked_ids,
        require_lock=bool(get("drivers.require_lock")),
        allow_unattested=bool(get("drivers.allow_unattested")),
        allow_cost_classes=frozenset(CostClass(str(c)) for c in get("drivers.cost.allow_classes")),  # type: ignore[union-attr]
        inproc_ids=frozenset(str(d) for d in get("drivers.inproc")),  # type: ignore[union-attr]
        enabled=frozenset(str(d) for d in get("drivers.enabled")),  # type: ignore[union-attr]
        isolation_floor=Isolation(str(get("drivers.isolation_floor"))),
        host_env=probe_env((), offline=False),
    )


def unit_evidence(row: Sequence[object], *, registry: SignalRegistry, trigger: str) -> Evidence:
    """The FREE group of 05 section 5.1 that the roster already holds, for one unit's one part.

    Every key is the `builtin` provider's (05:2135) and carries its version into the read set.
    Two non-nullable keys are recorded UNAVAILABLE with a reason rather than guessed:
    `unit.corrupt`, because detection performs no container structural check; and `unit.encrypted`
    for a PDF, because the trailer `/Encrypt` scan the `gate.encrypted` rule's comment names is not
    built. A `False` in either would be a claim nothing checked.
    """
    _uri, digest, size, parts, fmt, _media, trust, derived = row
    chosen = json.loads(str(derived or "{}")).get("format_evidence", {})
    ev = Evidence(content_sha256=str(digest), unit_part=expand.UNIDENTIFIED_PART)

    def put(key: str, value: object, reason: str | None = None) -> None:
        specs = [spec for spec in registry.specs_for(key) if spec.provider == _BUILTIN]
        version = specs[0].version if specs else ""
        ev.put(key, value, provider_version=version, unavailable_reason=reason)  # type: ignore[arg-type]

    put("unit.format", fmt)
    basis = (chosen.get("chosen") or {}).get("basis")
    if basis is not None:
        put("unit.format_basis", basis)
    put("unit.bytes", int(cast("int", size or 0)))
    put("unit.part_count", int(cast("int", parts or 0)))
    put("unit.trust_class", trust)
    put("unit.schema_requested", False)
    put("trigger.kind", trigger)
    if fmt == "pdf":
        put(
            "unit.encrypted",
            None,
            "the PDF trailer /Encrypt scan (gate.encrypted's comment) is not built",
        )
    else:
        put("unit.encrypted", bool(chosen.get("encrypted", False)))
    put("unit.corrupt", None, "detection performs no container structural check")
    return ev


@dataclass(slots=True)
class _Router:
    thread: StoreThread
    ctx: RunContext
    policy: RoutePolicy
    registry: SignalRegistry
    catalog: Catalog
    resolving: Policy
    source_root: str
    now_ms: int
    tally: RouteTally = field(default_factory=RouteTally)
    resolutions: dict[str, Resolution] = field(default_factory=dict)

    def decide(self, ev: Evidence) -> RouteDecision | None:
        """`GATE` then `DECODE`, `text` lane, `select` phase: the first matched action, or none."""
        for rung in RUNGS:
            ev.clear_read_log()
            decision, _mods = evaluate(self.policy, ev, HINTS, rung, LANE, PHASE)
            if decision.matched:
                return decision
        return None

    def resolution(self, media_type: str) -> Resolution:
        found = self.resolutions.get(media_type)
        if found is None:
            found = resolve(Requirement(port=PORT, format=media_type), self.catalog, self.resolving)
            self.resolutions[media_type] = found
        return found

    def route(self, row: Sequence[object]) -> None:
        ev = unit_evidence(row, registry=self.registry, trigger=self.ctx.trigger)
        decision = self.decide(ev)
        #  The read set is the decision's identity (05:1880), so it is taken before anything else
        #  reads the evidence -- `pending_deferrals()` evaluates the deferring rules' conditions.
        read_set = ev.read_set()
        digest = ev.read_set_digest()
        for key, _version, value in read_set:
            if value is None:
                self.tally.unavailable[key] += 1
        if decision is None:
            self.tally.unrouted["no rule matched"] += 1
            return
        deferred = pending_deferrals(
            self.policy, ev, decision.rung, LANE, PHASE, before=decision.rule_id
        )
        if deferred:
            #  D579. 05:1114-1116: a rule EARLIER in file order is UNKNOWN and defers, so its group
            #  is promoted and evaluation restarts. No code computes that group, so nothing may
            #  settle on the later match: `decode.no-rule-matched` would refuse every PDF.
            self.tally.unrouted[f"deferred ({', '.join(deferred)}): no signal computer"] += 1
            return
        decision = replace(
            decision,
            content_sha256=str(row[1]),
            unit_part=expand.UNIDENTIFIED_PART,
            pricebook_digest="",
            hints_digest=_hints_digest(HINTS),
            read_set_digest=digest,
        )
        if decision.outcome == "refuse":
            self._refuse(row, decision, read_set)
            return
        if not decision.driver:
            self.tally.unrouted[f"{decision.rule_id}: no driver (D577)"] += 1
            return
        self._plan(row, decision, read_set)

    def _refuse(self, row: Sequence[object], decision: RouteDecision, read_set: ReadSet) -> None:
        unit_uri = str(row[0])
        statements = [
            *self._decision_rows(unit_uri, decision, read_set, driver=""),
            (REFUSED_SQL, {"unit_uri": unit_uri, "failure_class": decision.failure_class}),
        ]
        self._commit(statements)
        self.tally.refused[decision.rule_id] += 1

    def _plan(self, row: Sequence[object], decision: RouteDecision, read_set: ReadSet) -> None:
        unit_uri, digest, size, _parts, _fmt, media, _trust, derived = row
        resolution = self.resolution(str(media or ""))
        candidate = _candidate(resolution, decision.driver)
        self._report(resolution)
        if candidate is None:
            self.tally.unrouted[f"{decision.driver}: {_why(resolution, decision.driver)}"] += 1
            return
        card = candidate.card
        cost = str(card.cost_model.cost_class) if card.cost_model is not None else "free"
        decision = replace(decision, cost_class=CostClass(cost))
        verdict = admit(decision, SqliteBudgetLedger(self.thread, wait_ms=BATCH_WAIT_MS))
        if not isinstance(verdict, Admitted):
            self.tally.unrouted[f"{decision.driver}: admission {type(verdict).__name__}"] += 1
            return
        unit = expand.counted(str(unit_uri), str(digest), int(cast("int", size or 0)), str(media))
        salt = expand.salt_for(json.loads(str(derived or "{}")), source_root=self.source_root)
        planned = planner.plan_row(
            unit,
            card=card,
            candidate=candidate,
            decision_id=decision.decision_id(),
            ctx=self.ctx,
            salt=salt,
        )
        self._commit(
            [
                *self._decision_rows(str(unit_uri), decision, read_set, driver=decision.driver),
                *planned.statements(),
            ]
        )
        self.tally.planned[decision.driver] += 1

    def _decision_rows(
        self,
        unit_uri: str,
        decision: RouteDecision,
        read_set: ReadSet,
        *,
        driver: str,
        admission: str = "admitted",
    ) -> list[tuple[str, Mapping[str, object]]]:
        """05:1103's *"write route_decision -- BEFORE anything runs"*, with its evidence first."""
        unavailable = sorted(key for key, _v, value in read_set if value is None)
        decision_id = decision.decision_id()
        return [
            (
                EVIDENCE_SQL,
                {
                    "digest": decision.read_set_digest,
                    "payload": payload_bytes(read_set),
                    "at": self.now_ms,
                },
            ),
            (
                DECISION_SQL,
                {
                    "decision_id": decision_id,
                    "content_sha256": decision.content_sha256,
                    "unit_part": decision.unit_part,
                    "lane": decision.lane,
                    "rung": int(decision.rung),
                    "policy_digest": decision.policy_digest,
                    "pricebook_digest": decision.pricebook_digest,
                    "hints_digest": decision.hints_digest,
                    "read_set_digest": decision.read_set_digest,
                    "driver": driver,
                    "cost_class": str(decision.cost_class),
                    "rule_id": decision.rule_id,
                    "rule_origin": decision.rule_origin,
                    "cause": decision.cause,
                    "reason": decision.reason,
                    "slice_key": decision.slice_key,
                    "evidence_digest": decision.read_set_digest,
                    "est_spend": canonical(_spend_json(decision)).decode("utf-8"),
                    "admission": admission,
                    "degraded": 1 if unavailable else 0,
                    "degradations": json.dumps(
                        [{"kind": "signal_unavailable", "key": key} for key in unavailable],
                        separators=(",", ":"),
                    ),
                    "generation": self.ctx.generation,
                    "decided_at": self.now_ms,
                },
            ),
            (
                UNIT_DECISION_SQL,
                {
                    "unit_uri": unit_uri,
                    "unit_part": decision.unit_part,
                    "lane": decision.lane,
                    "decision_id": decision_id,
                    "at": self.now_ms,
                },
            ),
        ]

    def _report(self, resolution: Resolution) -> None:
        payload = resolution_report(resolution)
        self._commit(
            [
                (
                    RESOLUTION_SQL,
                    {
                        "run_id": self.ctx.run_id,
                        "digest": resolution.resolution_digest,
                        "port": PORT,
                        "requirement_json": canonical(
                            cast("JsonValue", payload["requirement_json"])
                        ).decode(),
                        "report_json": canonical(
                            cast("JsonValue", payload["report_json"])
                        ).decode(),
                        "at": self.now_ms,
                    },
                )
            ]
        )

    def _commit(self, statements: Sequence[tuple[str, Mapping[str, object]]]) -> None:
        def run(connection: object) -> None:
            for sql, params in statements:
                connection.execute(sql, params)  # type: ignore[attr-defined]

        self.thread.run(
            Unit(name="route.decide", run=run, cost_class="free", wait_ms=BATCH_WAIT_MS)
        )


def _candidate(resolution: Resolution, driver: str) -> Candidate | None:
    return next((one for one in resolution.candidates if one.driver_id == driver), None)


def _why(resolution: Resolution, driver: str) -> str:
    """The rejection that removed `driver`, or `not installed` when the catalog never held it."""
    rejected = next((one for one in resolution.rejected if one.driver_id == driver), None)
    return "not installed" if rejected is None else str(rejected.code)


def _hints_digest(hints: RouteHints) -> str:
    """`sha256_canonical` over the five `RouteHints` fields, by name. 05:1925's `hints_digest`."""
    return sha256_canonical(
        cast(
            "JsonValue",
            {
                "lane": hints.lane,
                "max_rung": None if hints.max_rung is None else hints.max_rung.name,
                "prefer_capability": hints.prefer_capability,
                "deadline_ms": hints.deadline_ms,
                "schema": hints.schema,
            },
        )
    )


def _spend_json(decision: RouteDecision) -> dict[str, JsonValue]:
    spend = decision.est_spend
    return {
        "wall_ms": spend.wall_ms,
        "cpu_ms": spend.cpu_ms,
        "gpu_ms": spend.gpu_ms,
        "tokens_in": spend.tokens_in,
        "tokens_out": spend.tokens_out,
        "calls": spend.calls,
        "bytes_egress": spend.bytes_egress,
        "provider": spend.provider,
    }


def route_identified(
    thread: StoreThread,
    *,
    ctx: RunContext,
    policy: RoutePolicy,
    registry: SignalRegistry,
    catalog: Catalog,
    resolving: Policy,
    source_root: str,
    now_ms: int,
    limit: int = 512,
) -> RouteTally:
    """Route every unit this generation identified. One transaction per unit, keyset-paged."""
    router = _Router(
        thread=thread,
        ctx=ctx,
        policy=policy,
        registry=registry,
        catalog=catalog,
        resolving=resolving,
        source_root=source_root,
        now_ms=now_ms,
    )
    after = ""
    while True:
        page = cast(
            "list[tuple[object, ...]]",
            thread.run(
                Unit(
                    name="route.identified",
                    run=lambda c, a=after: c.execute(  # type: ignore[attr-defined]
                        IDENTIFIED_UNITS_SQL,
                        {"generation": ctx.generation, "after": a, "limit": limit},
                    ).fetchall(),
                    cost_class="free",
                    wait_ms=BATCH_WAIT_MS,
                )
            ),
        )
        if not page:
            return router.tally
        after = str(page[-1][0])
        for row in page:
            router.route(row)
