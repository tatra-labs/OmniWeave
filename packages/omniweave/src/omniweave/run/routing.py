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
- **each plan's `CostClass` groups, in order**, as 05:1096-1100 prints them: compute a group,
  `evaluate()`, and stop when a rule matched and `deferrals_pending()` holds nothing open. What
  the roster knows without reading bytes is put first -- the format and its basis (`route.detect`,
  at identify), the size, the part count, the trust class, the trigger. A key the registry resolves
  to a provider that ships a computer (`evidence.COMPUTER_FILENAME`) is computed in a child, one
  per unit and group, by `omniweave_core.host.signals` (D628); that is `pdfium`'s three keys for a
  PDF. `route_signal` is read first, keyed on the content, the part, the key and the provider's
  version, so identical bytes never start a second child, and a held unit re-routed by the next
  run reads back what the first computed (05 section 5.4, D632). Every other key in a group is
  put UNAVAILABLE with the reason, and the key is counted as `signal_unavailable` on the report.
  The `GATE` rung's `max_cost_class` clamps the groups `DECODE` may compute (05:1117).

**A deferring rule whose key is still UNKNOWN once its group has run holds the unit** (D579,
kept by D628). 05:1130 lets `defer` degrade to `skip` there, and on the shipped policy that sends a
PDF pdfium cannot open -- or a scanned page, whose `ink.tiles` nothing computes -- past every PDF
rule to `decode.no-rule-matched`, which its own comment calls *"UNREACHABLE BY CONSTRUCTION"*, and
refuses it permanently as `unsupported_format`. D579's ruling was that *"a build that cannot compute
the promoted group must not settle"*; a group whose computation answered nothing for the key is the
same fact one step later. So the unit stays `identified`, and the report names the rule and why its
key is unknown.

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
import sys
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Final, Protocol, TypeAlias, cast

from omniweave_core.budget import Admitted
from omniweave_core.canonical import canonical, sha256_canonical
from omniweave_core.drivers.resolve import (
    COST_CLASS_ORDER,
    Policy,
    Requirement,
    resolution_report,
    resolve,
)
from omniweave_core.probe import probe_env
from omniweave_core.store.budget import SqliteBudgetLedger
from omniweave_core.store.sqlite import BATCH_WAIT_MS, Unit
from omniweave_ports.types import CostClass, Isolation

from omniweave import plan as planner
from omniweave.route.admit import admit
from omniweave.route.decision import RouteHints
from omniweave.route.demand import compile_demand, plan_for
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
    from omniweave_core.host.signals import SignalAnswer
    from omniweave_core.operator import RunContext
    from omniweave_core.store.sqlite import StoreThread

    from omniweave.route.decision import Modifiers, RouteDecision
    from omniweave.route.demand import DemandMap, DemandPlan, Group
    from omniweave.route.evidence import Scalar, SignalRegistry
    from omniweave.route.policy import RoutePolicy
    from omniweave.run.passwords import Passwords

__all__ = [
    "LANE",
    "PHASE",
    "RUNGS",
    "Compute",
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

_NOTHING: Final[str] = "the provider answered nothing for it"

RECOMPUTABLE: Final[frozenset[CostClass]] = frozenset({CostClass.FREE, CostClass.LOCAL_COMPUTE})
"""What `--ignore-evidence-cache` may recompute. 05:2822: *"can only ever spend
`free`/`local_compute`"*, and 18:988-990 leaves re-running billed work to `--allow-rebill`. A key of
any other class is read from `route_signal` as it would be without the flag. No shipped signal is
billed, so today the rule is every key; it is here so a billed provider cannot make the flag an
unnamed authorisation to re-bill, which is why 18:990-991 struck `--ignore-cache` (D633)."""


class Compute(Protocol):
    """`(package, source path, content_sha256, keys) -> SignalAnswer`: one child's worth of signals.

    `omniweave_core.host.signals.compute_in_child` is the one real implementation, and
    `route_identified` builds it over this run's scratch directory. A parameter for the reason
    `subproc.Spawn` is one: a routing test that had to start an interpreter per unit could only be
    written against the real child, and the routing decisions are what those tests are about.

    `password=` is passed only for a unit `[ingest] password_file` maps and whose secret resolved
    (ADR-15 D15.4), so a computer that takes none is called exactly as before.
    """

    def __call__(
        self, package: str, source: str, digest: str, keys: tuple[str, ...], /, **password: str
    ) -> SignalAnswer: ...


_PYTHON_TYPES: Final[dict[str, tuple[type, ...]]] = {
    "bool": (bool,),
    "int": (int,),
    "float": (float, int),
    "str": (str,),
}
"""A registered `dtype`'s Python types. `bool` is an `int` subclass, so `int` refuses it by name."""

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

SIGNAL_READ_SQL: Final[str] = """
SELECT value, unavailable_reason FROM route_signal
 WHERE content_sha256 = :content_sha256 AND unit_part = :unit_part AND signal_key = :signal_key
   AND signal_version = :signal_version
"""

SIGNAL_WRITE_SQL: Final[str] = """
INSERT OR REPLACE INTO route_signal(content_sha256, unit_part, signal_key, signal_version, value,
                                    unavailable_reason, compute_ms, computed_at)
VALUES(:content_sha256, :unit_part, :signal_key, :signal_version, :value, :unavailable_reason,
       :compute_ms, :computed_at)
"""
"""05 section 5.4: *"Writes are `INSERT OR REPLACE`, which is safe under concurrency because the
value is a pure function of the key."* `value` is the scalar's JSON, which gives back the Python
type it was given -- `1.0` stays a `float` -- so a cached key enters `read_set_digest` exactly as
the computed one did, and a decision read from the cache is the decision the child's answer
made."""

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
    children: Counter[str] = field(default_factory=Counter)
    """Signal children started, by provider: one per unit and `CostClass` group that needed one."""
    cached: Counter[str] = field(default_factory=Counter)
    """Signals read back from `route_signal` rather than computed, by provider (D632)."""

    def lines(self) -> tuple[str, ...]:
        if not (self.planned or self.refused or self.unrouted):
            return ()
        out = [f"  route     {_shown(self.planned, 'planned')}; {_shown(self.refused, 'refused')}"]
        if self.unrouted:
            out.append(f"  route     {_shown(self.unrouted, 'unrouted')}")
        if self.children:
            out.append(f"  route     {_shown(self.children, 'signal children')}")
        if self.cached:
            out.append(f"  route     {_shown(self.cached, 'signals cached')}")
        if self.unavailable:
            out.append(f"  route     signal_unavailable: {_shown(self.unavailable, '')}".rstrip())
        return tuple(out)


def _shown(counts: Counter[str], label: str) -> str:
    total = sum(counts.values())
    detail = ", ".join(f"{name} {count}" for name, count in sorted(counts.items()))
    head = f"{total} {label}".strip()
    return f"{head} ({detail})" if detail else head


def resolve_policy(
    config: Config, *, locked_ids: frozenset[str] = frozenset(), offline: bool = False
) -> Policy:
    """`resolve()`'s `Policy` from `[drivers]`, with this host's `ProbeEnv`. Startup step 7's half.

    `host_env` is `probe.probe_env()`, the one core builder of a `ProbeEnv`; without it every card
    that declares any `[hardware]` demand is `HARDWARE_ABSENT host_env_undeclared`, which is all
    three first-party cards. `locked_ids` is `omniweave.lock`'s driver rows, which no module in
    the workspace writes -- so `[drivers] require_lock = true`, the shipped default, refuses every
    driver until one does, and that is reported rather than waived (D576).

    `offline` is `ow add --offline` (18:897), carried into `ProbeEnv.offline` (04:150), so a card
    declaring `[hardware] needs_network = true` resolves out as `HARDWARE_ABSENT` (D631).
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
        host_env=probe_env((), offline=offline),
    )


def unit_evidence(
    row: Sequence[object],
    *,
    registry: SignalRegistry,
    trigger: str,
    computers: Mapping[str, str] | None = None,
    accept_partial: bool = False,
) -> Evidence:
    """The FREE group of 05 section 5.1 that the roster already holds, for one unit's one part.

    Every key is the `builtin` provider's (05:2135) and carries its version into the read set.
    `unit.corrupt` is recorded UNAVAILABLE with a reason, rather than guessed, for a container
    detection has no structural check for (D641 builds PDF and ZIP): a `False` would be a claim
    nothing checked. `unit.encrypted` is detection's for every format (ADR-15 D15.1), and for a
    PDF the `pdfium` child's when it is installed (D15.2).

    **`accept_partial` is `ow ingest --accept-partial` (05:2821).** A unit whose check failed is
    recorded UNAVAILABLE naming the override instead of `True`, so `gate.corrupt` does not match and
    the driver tries; 05:2821 records it as *"`kind="signal_unavailable"` naming `unit.corrupt`"*,
    which is the route tally's line.

    **A key whose provider for this format ships a computer is left for it.** `unit.part_count`
    resolves to `pdfium` for a PDF (05:2199's *"`FPDF_GetPageCount` on a PDF"*), and the read set
    must record the provider resolution chose (05:2222); putting the roster's count under
    `builtin`'s version first would leave the computer nothing to answer.
    """
    _uri, digest, size, parts, fmt, _media, trust, derived = row
    chosen = json.loads(str(derived or "{}")).get("format_evidence", {})
    ev = Evidence(content_sha256=str(digest), unit_part=expand.UNIDENTIFIED_PART)
    computed_elsewhere = computers or {}

    def put(key: str, value: object, reason: str | None = None) -> None:
        resolved = registry.resolve(key, str(fmt or ""))
        if resolved is not None and resolved.provider in computed_elsewhere:
            return
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
    #  ADR-15 D15.1: detection's trailer scan for a PDF, as for a CFB or an OCF package. For a
    #  PDF this is the fallback only: D15.2 makes `unit.encrypted` the `pdfium` provider's, which
    #  opens the file, so `put()` leaves the key to that child whenever it is installed.
    put("unit.encrypted", bool(chosen.get("encrypted", False)))
    corrupt = chosen.get("corrupt")
    if not isinstance(corrupt, dict):
        put("unit.corrupt", None, f"detection has no structural check for {fmt or 'this format'}")
    elif corrupt.get("value") and accept_partial:
        put(
            "unit.corrupt",
            None,
            f"--accept-partial overrides the structural check: {corrupt.get('check', '')}",
        )
    else:
        put("unit.corrupt", bool(corrupt.get("value")))
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
    demand: DemandMap
    computers: Mapping[str, str]
    compute: Compute
    ignore_evidence_cache: bool = False
    """`ow ingest --ignore-evidence-cache`: skip the read of every `RECOMPUTABLE` key, and write
    what the child answers over the row that was there (D633)."""
    accept_partial: bool = False
    """`ow ingest --accept-partial`: a failed structural check does not refuse (05:2821, D641)."""
    passwords: Passwords | None = None
    """`[ingest] password_file`'s mapping: a mapped unit's secret goes to its child (D15.4)."""
    tally: RouteTally = field(default_factory=RouteTally)
    resolutions: dict[str, Resolution] = field(default_factory=dict)

    def decide(self, ev: Evidence, row: Sequence[object]) -> RouteDecision | None:
        """`GATE` then `DECODE`, `text` lane, `select` phase: the first matched action, or none."""
        ceiling: CostClass | None = None
        for rung in RUNGS:
            decision, mods = self._rung(ev, row, plan_for(self.demand, rung, LANE, PHASE), ceiling)
            if rung is Rung.GATE:
                ceiling = mods.max_cost_class
            if decision.matched:
                return decision
        return None

    def _rung(
        self,
        ev: Evidence,
        row: Sequence[object],
        plan: DemandPlan,
        ceiling: CostClass | None,
    ) -> tuple[RouteDecision, Modifiers]:
        """05:1096-1100 for one `(rung, lane, phase)`: compute a group, evaluate, maybe stop.

        A group above `ceiling` is never computed (05:1117's *"still under the `GATE` clamp"*),
        which is `DemandPlan.next_group()`'s rule, and `deferrals_pending()` is asked under the same
        clamp so it cannot hold the loop open for a group it may not run. A plan with no group the
        clamp allows still evaluates once, over what is already put: a rung is decided by the keys
        it has, never skipped because it could compute none.
        """
        limit = len(COST_CLASS_ORDER) if ceiling is None else COST_CLASS_ORDER.index(ceiling)
        allowed = tuple(group for group in plan.groups if group.rank <= limit)
        steps: tuple[Group | None, ...] = allowed or (None,)
        decision, mods = None, None
        for group in steps:
            if group is not None:
                self._compute(group, ev, row)
            ev.clear_read_log()
            decision, mods = evaluate(self.policy, ev, HINTS, plan.rung, LANE, PHASE)
            if decision.matched and not plan.deferrals_pending(
                ev, before=decision.rule_id, ceiling=ceiling
            ):
                break
        return cast("RouteDecision", decision), cast("Modifiers", mods)

    def _compute(self, group: Group, ev: Evidence, row: Sequence[object]) -> None:
        """One group's keys into `ev`: each once, by the provider this unit's format resolves to.

        A key already put -- the roster's, or an earlier group's -- is not recomputed. A key with
        no provider for this format, or whose provider ships no computer, is put UNAVAILABLE with
        an empty version: no code produced it, which is `Evidence.read_set()`'s own rule for a key
        nobody computed, so a unit with no computer to call reads exactly as it did before there
        was one. The keys a computer serves go to it in one child per provider, and come back each
        under the resolved provider's version, whether it answered a value or a reason.

        **`route_signal` is read first, per key** (05:1097's *"route_signal cache first, per
        (key,ver)"*). A key whose row exists for this content, part and version is put from it,
        and only the rest go to the child; a group the cache holds whole starts none. What the
        child answered is written back unless the request was refused (`SignalAnswer.refusal`).

        **A unit a password maps reads and writes no `route_signal` row** (ADR-15 D15.4). Its
        child's answer is a function of the password as well as the content, so a cached answer
        from a run without it (`unit.encrypted = true`) would refuse the file the password opens,
        and an answer with it, cached, would be a row derived from a secret. It costs such a unit
        one child per group per run.
        """
        uri, digest = str(row[0]), str(row[1])
        secret = None if self.passwords is None else self.passwords.secret_for(uri)
        fmt = str(row[4] or "")
        asked: dict[str, list[str]] = {}
        for key in group.keys:
            if ev.computed(key):
                continue
            spec = self.registry.resolve(key, fmt)
            if spec is None:
                ev.put(
                    key, None, provider_version="", unavailable_reason=f"no provider serves {fmt}"
                )
            elif spec.provider not in self.computers:
                ev.put(
                    key,
                    None,
                    provider_version="",
                    unavailable_reason=f"the {spec.provider} provider ships no computer",
                )
            else:
                asked.setdefault(spec.provider, []).append(key)
        for provider, keys in asked.items():
            versions = {key: self._version(key, fmt) for key in keys}
            kept = self._cached(
                digest,
                {
                    key: v
                    for key, v in versions.items()
                    if secret is None and not self._recomputes(key)
                },
            )
            hits = len(kept.values) + len(kept.unavailable)
            if hits:
                self.tally.cached[provider] += hits
            missing = tuple(
                key for key in keys if key not in kept.values and key not in kept.unavailable
            )
            found = kept
            if missing:
                self.tally.children[provider] += 1
                started = self.ctx.clock.monotonic_ns()
                extra = {} if secret is None else {"password": secret}
                answered = self.compute(self.computers[provider], uri, digest, missing, **extra)
                elapsed_ms = (self.ctx.clock.monotonic_ns() - started) // 1_000_000
                if answered.refusal is None and secret is None:
                    self._remember(digest, versions, missing, answered, elapsed_ms)
                found = replace(
                    answered,
                    values={**kept.values, **answered.values},
                    unavailable={**kept.unavailable, **answered.unavailable},
                )
            for key in keys:
                self._put(ev, key, fmt, found)

    def _recomputes(self, key: str) -> bool:
        """Whether the read is skipped for `key`: under the flag, for a class it may spend."""
        return self.ignore_evidence_cache and self.registry.cost_class_of(key) in RECOMPUTABLE

    def _version(self, key: str, fmt: str) -> str:
        spec = self.registry.resolve(key, fmt)
        return "" if spec is None else spec.version

    def _cached(self, digest: str, versions: Mapping[str, str]) -> SignalAnswer:
        """The `route_signal` rows for these keys at these versions: a value, or a kept reason."""
        from omniweave_core.host.signals import SignalAnswer  # noqa: PLC0415 -- signal path

        def run(connection: object) -> dict[str, tuple[object, object]]:
            rows: dict[str, tuple[object, object]] = {}
            for key, version in versions.items():
                found = connection.execute(  # type: ignore[attr-defined]
                    SIGNAL_READ_SQL,
                    {
                        "content_sha256": digest,
                        "unit_part": expand.UNIDENTIFIED_PART,
                        "signal_key": key,
                        "signal_version": version,
                    },
                ).fetchone()
                if found is not None:
                    rows[key] = (found[0], found[1])
            return rows

        rows = cast(
            "dict[str, tuple[object, object]]",
            self.thread.run(
                Unit(name="route.signal.read", run=run, cost_class="free", wait_ms=BATCH_WAIT_MS)
            ),
        )
        values: dict[str, Scalar] = {}
        unavailable: dict[str, str] = {}
        for key, (value, reason) in rows.items():
            if value is None:
                unavailable[key] = str(reason or _NOTHING)
            else:
                values[key] = cast("Scalar", json.loads(cast("bytes", value)))
        return SignalAnswer(values=values, unavailable=unavailable)

    def _remember(
        self,
        digest: str,
        versions: Mapping[str, str],
        keys: Sequence[str],
        found: SignalAnswer,
        elapsed_ms: int,
    ) -> None:
        """One row per key the computer answered, in one transaction of its own.

        Its own, and not the decision's: a unit whose rule defers on the key is held, and writes no
        decision, and the next run's routing of that same unit is exactly the read this is for.
        `compute_ms` is the request's wall time, which every key it answered shares.
        """
        statements: list[tuple[str, Mapping[str, object]]] = [
            (
                SIGNAL_WRITE_SQL,
                {
                    "content_sha256": digest,
                    "unit_part": expand.UNIDENTIFIED_PART,
                    "signal_key": key,
                    "signal_version": versions[key],
                    "value": (
                        json.dumps(found.values[key], allow_nan=False).encode("utf-8")
                        if key in found.values
                        else None
                    ),
                    "unavailable_reason": (
                        None if key in found.values else found.unavailable.get(key, _NOTHING)
                    ),
                    "compute_ms": elapsed_ms,
                    "computed_at": self.now_ms,
                },
            )
            for key in keys
        ]
        self._commit(statements, name="route.signal.write")

    def _put(self, ev: Evidence, key: str, fmt: str, found: SignalAnswer) -> None:
        """One computed key, under its provider's version. A wrong-`dtype` value is refused.

        A cached key comes through here too, as the provider answered it, so the `dtype` check is
        the same whichever way the value arrived.
        """
        version = self._version(key, fmt)
        if key not in found.values:
            reason = found.unavailable.get(key, _NOTHING)
            ev.put(key, None, provider_version=version, unavailable_reason=reason)
            return
        value = found.values[key]
        dtype = self.registry.dtype_of(key)
        wanted = _PYTHON_TYPES.get(dtype, ())
        if not isinstance(value, wanted) or (dtype != "bool" and isinstance(value, bool)):
            ev.put(
                key,
                None,
                provider_version=version,
                unavailable_reason=f"the provider answered {type(value).__name__}, not {dtype}",
            )
            return
        ev.put(key, value, provider_version=version)

    def resolution(self, media_type: str) -> Resolution:
        found = self.resolutions.get(media_type)
        if found is None:
            found = resolve(Requirement(port=PORT, format=media_type), self.catalog, self.resolving)
            self.resolutions[media_type] = found
        return found

    def route(self, row: Sequence[object]) -> None:
        ev = unit_evidence(
            row,
            registry=self.registry,
            trigger=self.ctx.trigger,
            computers=self.computers,
            accept_partial=self.accept_partial,
        )
        decision = self.decide(ev, row)
        #  The read set is the decision's identity (05:1880): the window `_rung()` opened for the
        #  `evaluate()` that decided, which `deferrals_pending()` reads inside and never widens.
        read_set = ev.read_set()
        digest = ev.read_set_digest()
        for key, _version, value in read_set:
            if value is None:
                self.tally.unavailable[key] += 1
        if decision is None:
            self.tally.unrouted["no rule matched"] += 1
            return
        held = pending_deferrals(
            self.policy, ev, decision.rung, LANE, PHASE, before=decision.rule_id
        )
        if held:
            self.tally.unrouted[f"deferred ({', '.join(held)}): {self._why(ev, held[0])}"] += 1
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

    def _why(self, ev: Evidence, rule_id: str) -> str:
        """Why a holding rule is UNKNOWN: its first unknown key and that key's recorded reason.

        A key the loop never computed -- its group is above the `GATE` clamp, or no registered
        provider puts it in any group -- has no reason to read, and says so.
        """
        rule = next(rule for rule in self.policy.rules if rule.id == rule_id)
        for key in rule.when.keys:
            if not ev.computed(key):
                return f"{key}: not computed"
            reason = ev.unavailable_reason(key)
            if reason is not None:
                return f"{key}: {reason}"
        return "its keys are known and its condition is not"

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

    def _commit(
        self, statements: Sequence[tuple[str, Mapping[str, object]]], *, name: str = "route.decide"
    ) -> None:
        def run(connection: object) -> None:
            for sql, params in statements:
                connection.execute(sql, params)  # type: ignore[attr-defined]

        self.thread.run(Unit(name=name, run=run, cost_class="free", wait_ms=BATCH_WAIT_MS))


def _child_compute(ctx: RunContext) -> Compute:
    """`compute_in_child` over this run's scratch directory, created on first use."""

    def compute(
        package: str, source: str, digest: str, keys: tuple[str, ...], /, **password: str
    ) -> SignalAnswer:
        from omniweave_core.host.signals import compute_in_child  # noqa: PLC0415 -- signal path

        from omniweave.run.operators.parse import worker_env  # noqa: PLC0415

        scratch = ctx.roots.cache / "tmp" / ctx.run_id
        scratch.mkdir(parents=True, exist_ok=True)
        return compute_in_child(
            package,
            source=source,
            content_sha256=digest,
            keys=keys,
            executable=sys.executable,
            cwd=str(scratch),
            env=worker_env(),
            password=password.get("password"),
        )

    return compute


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
    computers: Mapping[str, str] | None = None,
    compute: Compute | None = None,
    ignore_evidence_cache: bool = False,
    accept_partial: bool = False,
    passwords: Passwords | None = None,
) -> RouteTally:
    """Route every unit this generation identified. One transaction per unit, keyset-paged.

    `computers` is `evidence.Installed.computers`: the providers whose package ships a computer,
    by name. Absent, nothing is computed and every group key the roster does not hold is
    unavailable. `compute` defaults to `host.signals.compute_in_child`, run from this run's scratch
    directory with a worker's named environment. `ignore_evidence_cache` is `ow ingest`'s flag of
    that name (`_Router.ignore_evidence_cache`).
    """
    router = _Router(
        thread=thread,
        ctx=ctx,
        policy=policy,
        registry=registry,
        catalog=catalog,
        resolving=resolving,
        source_root=source_root,
        now_ms=now_ms,
        demand=compile_demand(policy, registry=registry),
        computers=computers or {},
        compute=compute or _child_compute(ctx),
        ignore_evidence_cache=ignore_evidence_cache,
        accept_partial=accept_partial,
        passwords=passwords,
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
