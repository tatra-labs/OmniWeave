"""The run manifest -- one JSON document per `run_id`, written incrementally, and the two cost
self-checks that make its numbers trustworthy.

15-observability.md:33 homes it here and fixes four things about it in one row: *"one JSON document
per `run_id`, written **incrementally**"*, kept *"until deleted; `run.manifest_path` points at it"*,
and read by *"`ow queue status`, `ow why <run_id>`, CI Counters, a human"*. 02-architecture.md
section 4.1 row 19 names the file it writes -- `{output_root}/runs/{run_id}.json` -- and
16-roadmap.md:548 schedules it with W4.8, beside the events it is the counterpart of.

## It is not a log, and the difference is enforceable

15:44 makes that a terminology lock: *"The manifest is not a log. It carries counts,
`failures_by_class`, cache statistics, `cost.would_have_been_micros_if_uncached`, per-Stage timings
and `degradations[]`, and it is written incrementally so a crash at hour six leaves a partial
manifest that still names what completed."* Three consequences are structural rather than stylistic:

* **Every member is a count, a duration, a digest or a closed-vocabulary map.** There is no free
  text field and no message list. `Degradation.message` reaches it only inside a
  `DegradationRollup.exemplar`, which is one record per kind and is bounded by construction.
* **It is rewritten, never appended to.** A log grows; this is a snapshot of the same twenty-one
  members at a later moment. `write()` renders the whole document and replaces the file.
* **A partial manifest is a correct manifest.** `status = "running"` with `ended_ns = None` is the
  shape a killed run leaves behind, and it is what 15:68 means by *"written at every Stage boundary
  and at every `degrade()`, so a killed run has one"*.

## Why the write is an `os.replace` and not a truncate-and-rewrite

The one property the plan asks of this file is that it survives the crash that produced it. A
rewrite in place has a window in which the file on disk is neither the old document nor the new one,
and a run killed inside that window leaves a truncated JSON document -- the exact failure mode the
incremental write exists to prevent. So `write()` renders `bytes`, writes them to a sibling under
`{run_id}.json.tmp`, and `Path.replace`s that over the target, which is `os.replace` and is atomic
within one filesystem. The sibling is in the same directory for that reason and not for tidiness.

Bytes, never text mode: 11-repo-layout.md section 1.9's third rule is *"every generator writes the
line ending explicitly"*, and a manifest read by a CI Counter on Linux after a Windows run must not
differ by a carriage return per line.

## Determinism without `sort_keys`

`render()` does **not** pass `sort_keys=True`, and that is a decision rather than an omission. The
one map whose key order carries meaning is `stage_ms`, whose vocabulary is the pipeline in order --
`discover`, `plan`, `parse`, `derive`, `index`, `converge`, `maintain` (15 section 2.2) -- and
alphabetising it to `converge, derive, discover, index, maintain, parse, plan` would make the single
table a human reads unreadable. Determinism comes from the other end instead: `__post_init__`
rebuilds every mapping in a declared order, so two runs that did the same thing produce the same
bytes and `manifest.write`'s `sha256` is a fact about the content.

## The two self-checks, and the scope the ledger cannot express

08-runtime.md:2289-2295 gives this module two assertions and says *"a failure of either is a hard
run failure, not a warning"*:

1. `sum(route_spend.micros) == manifest.cost.billed_micros`, **exactly**.
2. Every `ok` / `ok_partial` row with a `decision_id` has at least one spend row, and a Sequence's
   apportionment sums to the session plus or minus one micro.

Both ship, as `reconcile()` and `unpriced()` over rows a caller reads with the two SQL statements
below -- the same split `dispatch.py` uses for `SEQUENCE_LEN_SQL`, because a check that needs a live
store to run is a check nobody runs. The Sequence half of (2) is already discharged one layer down
by `omniweave.run.dispatch.check_apportionment`, called by whoever writes the spend rows against the
numbers actually written; this module does not restate it.

**What neither can do is scope itself to one run, and `_notes/build-defects.md` D158 reports it.**
`route_spend` has no `run_id` and no timestamp; the only run-scoping column anywhere on the spend
join is `route_decision.generation`, and `route_decision` is append-only and immutable
(05-ingest-and-routing.md section 5's rule 6, `ON CONFLICT ... DO NOTHING`), so that column names
the generation that **first decided** the row rather than the one that paid for it. A resumed run --
08:507's own worked example resumes 331,455 claimable rows -- pays attempt 2 against decisions
stamped with the previous generation, so a generation-scoped sum omits exactly the resumed work.
`billed_micros` is therefore accumulated by the writer from what this run committed, and
`reconcile()` compares that accumulation against whatever total the caller read; the SQL is supplied
with its limits stated rather than withheld.

## What is deliberately NOT here

* **The loop, and when a Stage closes.** `supervisor.py` owns the Stage boundaries; this module is
  told `stage_closed(stage, elapsed_ms)` and does arithmetic.
* **`Degradation` and `DegradationRollup`.** 15 section 6.3 is that type's sole home and it is
  `omniweave_core.observe.degradation`. What is here is the **bounded accumulator** -- 15:1118's own
  heading is *"What the manifest stores, and why it stays bounded"* -- because holding 188 `budget`
  records to roll them up at the end is the unboundedness that section exists to refuse.
* **The rendering.** `ow why <run_id>` prints 15 section 7's report; this module produces the JSON
  it reads. 15:29 assigns the manifest's *rendering* to that document and the writer to this one.
* **`omniweave.index.lock`.** 02:489 lists it in this module's emits column, but 07-store-and-
  retrieval.md section 9.4 gives it a merge driver, a sort-merge and a byte-stable timestamp-free
  line format, and `omniweave_core.store.indexlock` already ships all three. Writing a second
  producer here would be two homes for one artefact; the Supervisor calls that module.

Specified in 15-observability.md sections 1, 1.1, 2.2 and 6.3, 08-runtime.md sections 4.7, 7.5 and
7.6, 02-architecture.md sections 4.1 and 7.6, and 16-roadmap.md:548 (P4 W4.8).
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, cast, get_args

from omniweave_core.budget import DIMS as BUDGET_DIMS
from omniweave_core.cache import CacheVerdict
from omniweave_core.errors import ConfigError, RouteError
from omniweave_core.events import STAGE_MS_KEYS, SinkStats, Stage, TimedStage
from omniweave_core.observe.degradation import (
    MAX_ROLLUP_PARTS,
    Degradation,
    DegradationKind,
    DegradationRollup,
    register_order,
)
from omniweave_core.operator import Outcome
from omniweave_ports.types import FailureClass

from omniweave.run.supervisor import HostFacts

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path

    from omniweave_core.clock import Clock

__all__ = [
    "BILLED_MICROS_SQL",
    "MANIFEST_DIR",
    "MANIFEST_SUFFIX",
    "MAX_OFFENDERS_SHOWN",
    "OBSERVE_KEYS",
    "PRICED_OUTCOMES",
    "RUN_STATUSES",
    "SPEND_AUDIT_SQL",
    "TEMP_SUFFIX",
    "TERMINAL_STATUSES",
    "TRIGGERS",
    "CacheStats",
    "CostBlock",
    "DegradationTally",
    "ManifestWriter",
    "Provenance",
    "RunManifest",
    "RunStatus",
    "RunTally",
    "SpendAudit",
    "Timings",
    "Trigger",
    "check_spend_audit",
    "manifest_path",
    "reconcile",
    "render",
    "unpriced",
]


# =============================================================================================
# 1. Where the document goes, and the two closed vocabularies it inherits from the `run` row
# =============================================================================================

MANIFEST_DIR: Final = "runs"
MANIFEST_SUFFIX: Final = ".json"
"""`{output_root}/runs/{run_id}.json`, transcribed from 02-architecture.md section 4.1 row 19.

Under `output`, not under `.omniweave/`: the store is the operator's cache and is `.gitignore`d
(07-store-and-retrieval.md:15), while `run.manifest_path` is a path handed to `ow why` months later.
15:399 makes the retention explicit in the other direction -- *"a run whose manifest is still
referenced by an open `eval_run` is exempt"* -- which only means something if the file outlives the
store directory's own sweeps."""

TEMP_SUFFIX: Final = ".tmp"
"""The sibling `write()` renders into before `Path.replace`. A SIBLING, not a temp directory:
`os.replace` is atomic only within one filesystem, and `{output_root}` and the system temp
directory are routinely on two."""

Trigger = Literal["cli", "hook", "upstream", "watch", "mcp", "sdk"]
"""`run.trigger`'s CHECK, and `RunContext.trigger` (08-runtime.md:269). The last two members were
widened into the vocabulary by charter section 5 C15, which `0004_runtime.sql:243` records."""

RunStatus = Literal["running", "ok", "partial", "failed", "interrupted", "abandoned"]
"""`run.status`'s CHECK, verbatim from `0004_runtime.sql:257-258`.

The DDL's own comment is the reason this is a `Literal` here rather than an enum imported from
somewhere: *"`run.status` is a SECOND closed vocabulary spelled `status` and it is deliberately NOT
an enum_val domain; the enum_val domain is `claim_status`, over claim.status"*. Two closed
vocabularies spelled `status` over two domains, and neither may borrow the other's members."""

Timings = Literal["always", "never"]
"""`[observe] timings`, whose two values `omniweave_core.config` declares and
`omniweave.toml.example:403` prints. Carried on the manifest because 15:120 makes `"never"` *"the
only supported way to get a manifest with no wall-clock content in it at all"*, and without the
switch's value a reader cannot tell an omitted `stage_ms` from a run that entered no Stage."""

TRIGGERS: Final[tuple[str, ...]] = get_args(Trigger)
RUN_STATUSES: Final[tuple[str, ...]] = get_args(RunStatus)
TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(RUN_STATUSES) - {"running"}
"""The five a run rests in. `running` is the only one that may carry `ended_ns = None`."""

OBSERVE_KEYS: Final[tuple[str, ...]] = tuple(SinkStats().as_manifest_fields())
"""The `observe.*` block's key set, READ FROM its producer rather than transcribed.

15:434 names four of these -- `observe.events_emitted`, `observe.events_dropped`,
`observe.serialise_ns_total`, `observe.shard_bytes` -- and `SinkStats.as_manifest_fields()` produces
six, adding `events_refused` and `shards_rolled`. Deriving the tuple from that method is what keeps
one home for the key set: a seventh number added to the sink appears here the day it is added, and a
`Literal` spelled out in this file would have been the second place to change."""

PRICED_OUTCOMES: Final[tuple[Outcome, ...]] = (Outcome.OK, Outcome.OK_PARTIAL)
"""The two outcomes 08:2292's second self-check names. A `skipped_cached` row DOES carry a spend row
-- `route_spend.was_cache_hit` exists for it (05:2572) -- but `skipped_unchanged` never ran at all
and `deferred_budget` was refused, so neither owes one. The check is stated over the two that spent
rather than over `work.status`, and see `SpendAudit` for why that distinction cannot be made in
SQL."""


def manifest_path(output_root: Path, run_id: str) -> Path:
    """`{output_root}/runs/{run_id}.json`. Pure; creates nothing.

    `run_id` is validated for path separators rather than trusted: it reaches here from
    `RunContext.run_id`, which is minted as `'r_' + ulid(...)` and is therefore always safe -- but
    this function is also the one an `ow why <run_id>` argument flows through, and that argument is
    a user string. A `run_id` of `../../etc/passwd` would otherwise resolve outside `output_root`.
    """
    if not run_id or any(char in run_id for char in "/\\") or run_id in (".", ".."):
        raise ConfigError(
            f"{run_id!r} is not a run id: a manifest file name is one path segment",
            fix="pass the run_id from RunContext.run_id, which is 'r_' + a 26-char ULID",
        )
    return output_root / MANIFEST_DIR / f"{run_id}{MANIFEST_SUFFIX}"


# =============================================================================================
# 2. The nested blocks: provenance, cache statistics, cost
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Provenance:
    """What produced these numbers: nine columns of the `run` row, in the DDL's order.

    The manifest outlives the store it was written beside -- 15:1568 makes the crash bundle *"the
    last shard plus the manifest -- three files, no screenshots, no traceback"* -- so it has to be
    self-describing. A count with no configuration behind it is a number about nothing, and 15:789
    says the same thing about money in particular: *"a bill without the price list it was computed
    against is not auditable"*, which is what `pricebook_digest` is doing here.

    `schema` is the SCHEMA MAJOR this run wrote, and the `run` DDL's comment is worth repeating
    because the name is crowded: it *"is not a second home for the store's version: index_state.
    schema is the only place on disk holding '<major>.<minor>'"*. It is nested inside this block
    rather than sitting at the manifest's top level so that a bare `schema` key never appears beside
    a JSON document's own `$schema` vocabulary.
    """

    omniweave_version: str = ""
    contract: int = 0
    schema: int = 0
    config_digest: str = ""
    semantic_digest: str = ""
    policy_digest: str = ""
    pricebook_digest: str = ""
    catalog_digest: str = ""
    lock_digest: str = ""


@dataclass(frozen=True, slots=True)
class CacheStats:
    """`manifest.cache` -- the five numbers 08 section 4.7's verdicts make computable.

    08:1798: *"Every miss carries its clause. `verdicts` is what makes `manifest.cache.
    corrupt_entries`, `legacy_vintage_hits` and `rebilled_units` computable, and it is the
    difference between 'the cache is not helping' and 'the cache is corrupt'."* So the carrier is a
    `CacheVerdict` counter and these five are its projection -- `from_verdicts()` is the only
    constructor that should be used, and it is what keeps the counter the single home.

    `corrupt_entries` earns its own field rather than being read off the counter by a reader because
    08:1447 makes it a **self-healing** condition: a corrupt blob is *"counted into
    `manifest.cache.corrupt_entries` and overwritten on the next success -- self-healing with no
    flag. graphify re-billed a corrupt entry every run until #2405 counted it."* The count is the
    entire evidence that it happened.
    """

    hits: int = 0
    misses: int = 0
    corrupt_entries: int = 0
    legacy_vintage_hits: int = 0
    rebilled_units: int = 0

    def __post_init__(self) -> None:
        for name in ("hits", "misses", "corrupt_entries", "legacy_vintage_hits", "rebilled_units"):
            if getattr(self, name) < 0:
                raise ConfigError(
                    f"cache.{name} is {getattr(self, name)}; a count is never negative",
                    fix="build this with CacheStats.from_verdicts()",
                )

    @classmethod
    def from_verdicts(
        cls, counts: Mapping[CacheVerdict, int], *, rebilled_units: int = 0
    ) -> CacheStats:
        """Project a `CacheVerdict` counter onto the five numbers the manifest prints.

        `hit_legacy` counts as a hit **and** as a legacy hit: it served the request, and it is the
        mixed-vintage warning at the same time. Counting it only as legacy would make
        `hits + misses` smaller than the number of units probed, and a reader checking that sum
        would find a hole.
        """
        unknown = tuple(verdict for verdict in counts if verdict not in set(CacheVerdict))
        if unknown:
            raise ConfigError(
                f"{unknown} are not CacheVerdict members; the seven are "
                f"{tuple(v.value for v in CacheVerdict)}",
                fix="count with the verdicts probe() returned",
            )
        hits = counts.get(CacheVerdict.HIT, 0) + counts.get(CacheVerdict.HIT_LEGACY, 0)
        misses = sum(
            count
            for verdict, count in counts.items()
            if verdict not in (CacheVerdict.HIT, CacheVerdict.HIT_LEGACY)
        )
        return cls(
            hits=hits,
            misses=misses,
            corrupt_entries=counts.get(CacheVerdict.MISS_CORRUPT, 0),
            legacy_vintage_hits=counts.get(CacheVerdict.HIT_LEGACY, 0),
            rebilled_units=rebilled_units,
        )


@dataclass(frozen=True, slots=True)
class CostBlock:
    """`manifest.cost` -- three money figures, two GPU figures, and one of them is exact.

    08:2318-2321 fixes the first three and their relationship: *"The manifest carries two figures,
    not one. `manifest.cost.billed_micros` is `Sigma route_spend.micros` and stays exact, which is
    what self-check 1 asserts. `manifest.cost.op_micros` is `Sigma work.cost_micros WHERE operator
    LIKE 'op.%'`, and `manifest.cost.total_micros` is their sum."* `total_micros` is carried rather
    than left to the reader because the plan names it as a manifest figure; it is also **checked**
    here, because a figure that is both stored and derivable is a figure that can disagree with
    itself.

    `would_have_been_micros_if_uncached` is 08:2298's third number: *"it comes from
    `cache_index.spend_json` replayed at the current `PriceBook` -- the only honest way to report
    savings when 90% of calls are hits."* It is a counterfactual and is never added to the bill.

    The two GPU figures are 15's extension 10: *"`cost.gpu_ms_apportioned` separated from
    `cost.gpu_ms_measured`"*, because a Service-backed driver cannot see the server's GPU time and
    the runner apportions it by `wall_ms` (15 section 5.3). Keeping them in one field would make a
    measurement and an estimate indistinguishable, and 15:800's render prints a tilde against the
    apportioned half for exactly that reason.
    """

    billed_micros: int = 0
    op_micros: int = 0
    total_micros: int = 0
    would_have_been_micros_if_uncached: int = 0
    gpu_ms_measured: int = 0
    gpu_ms_apportioned: int = 0

    def __post_init__(self) -> None:
        for entry in dataclasses.fields(self):
            name = entry.name
            if getattr(self, name) < 0:
                raise ConfigError(
                    f"cost.{name} is {getattr(self, name)}; spend is never negative",
                    fix="price through Spend.micros(), which floors at zero",
                )
        if self.total_micros != self.billed_micros + self.op_micros:
            raise RouteError(
                f"cost.total_micros is {self.total_micros} against billed {self.billed_micros} "
                f"plus op {self.op_micros} = {self.billed_micros + self.op_micros} (08:2321)",
                fix="build this with CostBlock.of(), which sums the two",
            )

    @classmethod
    def of(cls, *, billed_micros: int = 0, op_micros: int = 0, **rest: int) -> CostBlock:
        """`total_micros` computed rather than passed, which is the only safe way to pass it."""
        return cls(
            billed_micros=billed_micros,
            op_micros=op_micros,
            total_micros=billed_micros + op_micros,
            **rest,
        )


# =============================================================================================
# 3. `RunManifest` -- the document. T-GENERATED reads this: `schema/run-manifest-v1.json`
# =============================================================================================


def _ordered(values: Mapping[Any, int], order: tuple[Any, ...], *, where: str) -> Mapping[Any, int]:
    """One map, rebuilt in a declared key order, with unknown keys refused and zeros dropped.

    Three jobs in one pass, and each is load-bearing:

    * **Order.** `render()` does not sort keys (see the module docstring), so the bytes are stable
      only because every map is rebuilt here in a vocabulary's own order.
    * **Closure.** 15:66 bounds the manifest by calling its two largest members *"dicts keyed by a
      closed vocabulary"*. A key outside the vocabulary is refused rather than passed through,
      because a typo'd key is how such a bound stops holding.
    * **Zeros dropped.** A count of zero and an absent key say the same thing, and keeping both
      shapes would mean two documents for one run. An absent Stage in `stage_ms` is 15:117's own
      reading -- `stage_entries[s]` beside it is what says whether the Stage was entered.
    """
    allowed = {str(key) for key in order}
    unknown = sorted(str(key) for key in values if str(key) not in allowed)
    if unknown:
        raise ConfigError(
            f"{where}: {unknown} are outside the closed vocabulary "
            f"{tuple(str(key) for key in order)}",
            fix=f"key {where} by a member of that vocabulary",
        )
    negative = sorted(str(key) for key, count in values.items() if count < 0)
    if negative:
        raise ConfigError(
            f"{where}: {negative} carry a negative count",
            fix="a manifest member is a count, a duration or a digest; none of them goes down",
        )
    lookup = {str(key): count for key, count in values.items()}
    return MappingProxyType({key: lookup[str(key)] for key in order if lookup.get(str(key))})


def _unmeasured_host() -> HostFacts:
    """A `HostFacts` with nothing measured, for a manifest built before preflight ran.

    Zeros rather than `None`: 08:661 makes the facts *"measured ONCE at preflight and recorded in
    the run manifest, so a performance number is attributable to a machine"*, and a run that failed
    before preflight has a manifest whose performance numbers are attributable to nothing. Zero
    `cpus` is not a machine, so it reads as "unmeasured" without a second shape for the field.
    """
    return HostFacts(cpus=0, ram_bytes=0, free_disk_bytes=0)


@dataclass(frozen=True, slots=True)
class RunManifest:
    """One run, as twenty-one members. The declaration `schema/run-manifest-v1.json` is emitted
    from.

    Field order is the reading order of the document: who ran, then what it did, then what it cost,
    then what it gave up, then what the observing itself cost. `tools/schemagen.py` reflects this
    class with `typing.get_type_hints()`, so every annotation here resolves at run time and none of
    them may be a quoted forward reference -- see `_notes/build-defects.md` D157, which states that
    as a general property of the T-SCHEMA tier.

    **Every mapping is rebuilt in `__post_init__`** into a `MappingProxyType` over a canonically
    ordered dict. That is what makes the document byte-stable between two runs that did the same
    thing, and it is also what makes a frozen dataclass actually frozen: a `Mapping` field handed a
    live `dict` would otherwise be mutable through the caller's reference.
    """

    run_id: str
    generation: int = 0
    trigger: Trigger = "cli"
    status: RunStatus = "running"
    started_ns: int = 0
    ended_ns: int | None = None
    provenance: Provenance = field(default_factory=Provenance)
    host: HostFacts = field(default_factory=_unmeasured_host)
    timings: Timings = "always"
    stage_ms: Mapping[TimedStage, int] = field(default_factory=dict)
    stage_entries: Mapping[TimedStage, int] = field(default_factory=dict)
    units: int = 0
    outcomes: Mapping[Outcome, int] = field(default_factory=dict)
    failures_by_class: Mapping[FailureClass, int] = field(default_factory=dict)
    deferred_by_dim: Mapping[str, int] = field(default_factory=dict)
    interrupted_inflight: int = 0
    runtime_overhead_ms: int = 0
    cache: CacheStats = field(default_factory=CacheStats)
    cost: CostBlock = field(default_factory=CostBlock)
    degradations: Mapping[DegradationKind, DegradationRollup] = field(default_factory=dict)
    observe: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ConfigError(
                "a manifest with no run_id; the file is named after it",
                fix="pass RunContext.run_id",
            )
        if self.status not in RUN_STATUSES:
            raise ConfigError(
                f"{self.status!r} is not a run status; the six are {RUN_STATUSES}",
                fix="use one of run.status's CHECK values",
            )
        if self.trigger not in TRIGGERS:
            raise ConfigError(
                f"{self.trigger!r} is not a trigger; the six are {TRIGGERS}",
                fix="use one of run.trigger's CHECK values",
            )
        if self.timings not in get_args(Timings):
            raise ConfigError(
                f"{self.timings!r} is not an [observe] timings value",
                fix="always | never",
            )
        if self.status == "running" and self.ended_ns is not None:
            raise ConfigError(
                f"a running manifest with ended_ns={self.ended_ns}; a run that ended has a "
                f"terminal status",
                fix=f"set status to one of {sorted(TERMINAL_STATUSES)} when you set ended_ns",
            )
        if self.ended_ns is not None and self.ended_ns < self.started_ns:
            raise ConfigError(
                f"ended_ns {self.ended_ns} precedes started_ns {self.started_ns}; both are wall "
                f"readings from the injected Clock",
                fix="stamp both from ctx.clock.wall_ns()",
            )
        for name in (
            "generation",
            "started_ns",
            "units",
            "interrupted_inflight",
            "runtime_overhead_ms",
        ):
            if getattr(self, name) < 0:
                raise ConfigError(
                    f"{name} is {getattr(self, name)}; a manifest member does not go down",
                    fix="accumulate through RunTally, which only adds",
                )
        if self.timings == "never" and self.stage_ms:
            raise ConfigError(
                f"[observe] timings = 'never' with {len(self.stage_ms)} stage_ms entries; 15:120 "
                f"makes that switch the only way to get a manifest with no wall-clock content",
                fix="omit stage_ms when timings is 'never'; stage_entries stays, it is a count",
            )
        _set = object.__setattr__
        _set(self, "stage_ms", _ordered(self.stage_ms, STAGE_MS_KEYS, where="stage_ms"))
        _set(
            self,
            "stage_entries",
            _ordered(self.stage_entries, STAGE_MS_KEYS, where="stage_entries"),
        )
        _set(self, "outcomes", _ordered(self.outcomes, tuple(Outcome), where="outcomes"))
        _set(
            self,
            "failures_by_class",
            _ordered(self.failures_by_class, tuple(FailureClass), where="failures_by_class"),
        )
        _set(
            self,
            "deferred_by_dim",
            _ordered(self.deferred_by_dim, BUDGET_DIMS, where="deferred_by_dim"),
        )
        _set(self, "observe", _ordered(self.observe, OBSERVE_KEYS, where="observe"))
        _set(self, "degradations", _rolled(self.degradations))
        missing = tuple(stage for stage in self.stage_ms if stage not in self.stage_entries)
        if missing:
            raise ConfigError(
                f"stage_ms times {missing} with no stage_entries beside them; 15:117 puts the "
                f"entry count beside the time so a reader can tell one 600 s Stage from six 100 s "
                f"ones",
                fix="record both at every Stage close; RunTally.stage_closed() does",
            )

    @property
    def degraded(self) -> bool:
        """Whether any recorded kind is one of `FORCES_DEGRADED`'s seven.

        Read off the rolled-up entries rather than stored, because the roll-up already has one
        entry per kind and a stored boolean would be a second place the same fact could be wrong.
        """
        return any(entry.exemplar.forces_degraded for entry in self.degradations.values())

    def as_json(self) -> dict[str, object]:
        """The document, as plain JSON values, in field order. `render()`'s only input."""
        return {
            entry.name: _jsonable(getattr(self, entry.name)) for entry in dataclasses.fields(self)
        }


def _rolled(
    entries: Mapping[DegradationKind, DegradationRollup],
) -> Mapping[DegradationKind, DegradationRollup]:
    """`degradations`, rebuilt in register order with each entry's key checked against its own kind.

    `register_order` is `omniweave_core.observe.degradation`'s, and its docstring gives the reason
    the order is the register's rather than the run's: *"the manifest is a JSON document a human
    diffs between runs, so its `degradations` map is written in register order rather than in the
    order the run happened to degrade -- two runs that degraded the same way produce the same
    bytes."*

    An entry whose key disagrees with `entry.kind` is refused. That pairing is the only thing making
    `manifest.degradations[<kind>]` a true statement, and `rollup()` already refuses a mixed-kind
    merge one layer down for the same reason.
    """
    mismatched = sorted(key for key, entry in entries.items() if entry.kind != key)
    if mismatched:
        raise ConfigError(
            f"degradations{mismatched} hold entries of another kind; the map key IS the entry's "
            f"kind (15:1128)",
            fix="group by Degradation.kind and key each entry by it",
        )
    return MappingProxyType({key: entries[key] for key in sorted(entries, key=register_order)})


# =============================================================================================
# 4. Rendering, and the atomic incremental write
# =============================================================================================

_SEPARATORS: Final = (",", ": ")
INDENT: Final = 2
"""Pretty-printed, because 15:33 names *"a human"* among the four readers and a CI Counter reading
`jq` output does not care either way. Two spaces rather than four: the document nests three deep at
most and a 27-entry `degradations` map at four-space indent wraps on a terminal."""


def _key(key: object) -> str:
    """A JSON object key. An `Enum` member becomes its value; anything else becomes its `str`."""
    return key.value if isinstance(key, enum.Enum) else str(key)


def _jsonable(value: object) -> object:
    """One dataclass, mapping or scalar, as JSON values. Field order preserved, never sorted.

    The `Enum` arm comes before the scalar one and it is not decoration: every closed vocabulary in
    this document is a `StrEnum`, which `json.dumps` would serialise correctly by accident because
    a `StrEnum` member IS a `str`. An `IntEnum` in the same position would serialise as its ordinal
    and a plain `Enum` would raise, so taking `.value` explicitly makes the wire form a decision
    rather than an inheritance detail.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            entry.name: _jsonable(getattr(value, entry.name)) for entry in dataclasses.fields(value)
        }
    if isinstance(value, Mapping):
        return {_key(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (int, float, str)):
        return value
    raise ConfigError(
        f"{value!r} is not a JSON value; the manifest carries counts, durations, digests and "
        f"closed-vocabulary maps and nothing else",
        fix="the manifest is not a log: see this module's docstring",
    )


def render(manifest: RunManifest) -> bytes:
    """The document's bytes. UTF-8, `\\n`, no `sort_keys`, one trailing newline.

    `allow_nan=False` because a JSON document with `NaN` in it is not JSON, and every number here is
    an integer anyway -- the check is there so that the day one is not, the failure is at the writer
    rather than in whatever reads the file next.
    """
    text = json.dumps(
        manifest.as_json(),
        indent=INDENT,
        separators=_SEPARATORS,
        ensure_ascii=False,
        allow_nan=False,
    )
    return (text + "\n").encode("utf-8")


class ManifestWriter:
    """Renders and replaces `{output_root}/runs/{run_id}.json`, and emits `manifest.write`.

    One writer per run, held by the process that holds the `store.write` lock -- 15:69: *"one writer
    process holds the `store.write` lock, so one manifest has one author"*. Nothing here locks,
    because that sentence means the lock is already held by the caller; a second lock in this module
    would be a second answer to a question the store has already answered.

    The `manifest.write` event carries `path` and `sha256`, which is `tools/events.toml`'s row for
    that kind and the whole of it. The digest is over the bytes actually replaced, so two runs whose
    manifests agree have one digest and `ow trace tree` shows the rewrite that changed nothing.
    """

    __slots__ = ("_clock", "_emit", "_last_sha256", "_path", "_writes")

    def __init__(
        self,
        path: Path,
        *,
        clock: Clock | None = None,
        emit: Callable[..., object] | None = None,
    ) -> None:
        self._path = path
        self._clock = clock
        self._emit = emit
        self._writes = 0
        self._last_sha256 = ""

    @property
    def path(self) -> Path:
        return self._path

    @property
    def writes(self) -> int:
        """How many times the file has been replaced. 15:1140 makes the rewrite happen *"at every
        Stage boundary and at every `degrade()`"*, so this is nine plus the degradation count on a
        full ingest -- a number small enough that no batching is needed and large enough that a
        reader should be able to see it did not run away."""
        return self._writes

    @property
    def last_sha256(self) -> str:
        return self._last_sha256

    def write(self, manifest: RunManifest) -> str:
        """Render, replace, emit. Returns the sha256 hex of the bytes written.

        The parent directory is created here rather than at startup because the first write is the
        first time anything needs it, and a run that fails before its first Stage boundary should
        not have left an empty `runs/` behind.
        """
        payload = render(manifest)
        digest = hashlib.sha256(payload).hexdigest()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        staging = self._path.with_name(self._path.name + TEMP_SUFFIX)
        staging.write_bytes(payload)
        staging.replace(self._path)
        self._writes += 1
        self._last_sha256 = digest
        self._announce(digest)
        return digest

    def _announce(self, digest: str) -> None:
        """`manifest.write{path, sha256}`, if the run gave this writer a sink.

        A manifest write that cannot be announced is still a manifest write: the event stream is
        diagnostic and droppable (15 section 1, rule 1) and the file on disk is the artefact. So the
        sink is optional and a failure to emit is not a failure to write -- which is also why the
        emit happens AFTER the replace.
        """
        emit = self._emit
        if emit is None:
            return
        emit(path=str(self._path), sha256=digest)


# =============================================================================================
# 5. The bounded accumulators -- 15:1118, "what the manifest stores, and why it stays bounded"
# =============================================================================================


class DegradationTally:
    """One kind's records, accumulated into the entry the manifest stores -- never retained.

    15:1120 states the problem this class is the answer to: *"section 1.1 claims the manifest's
    `degradations[]` is bounded because it is 'a dict keyed by a closed vocabulary'. That holds only
    with a roll-up, because a 188-part document can produce 188 `budget` records."*

    `omniweave_core.observe.degradation.rollup()` merges a **sequence** of records, which is the
    right shape for a caller that already holds them; holding 188 of them until run end so as to
    call it is exactly the unboundedness 15 section 6.3 is refusing. So this accumulates the six
    members of `DegradationRollup` as records arrive and keeps `MAX_ROLLUP_PARTS + 1` of each
    unbounded one -- one over the cap, which is the smallest number that can still distinguish
    "exactly 64" from "more than 64" and therefore set `truncated` correctly.

    `exemplar` is the FIRST record, verbatim, which is `rollup()`'s choice and the reason
    `Degradation.message`, `knob` and `fix_command` reach the manifest at all.
    """

    __slots__ = ("_exemplar", "_first_ns", "_last_ns", "_n", "_parts", "_units")

    def __init__(self, record: Degradation, *, at_ns: int) -> None:
        self._exemplar = record
        self._n = 0
        self._first_ns = at_ns
        self._last_ns = at_ns
        self._units: dict[str, None] = {}
        self._parts: dict[int, None] = {}
        self.add(record, at_ns=at_ns)

    @property
    def kind(self) -> DegradationKind:
        return self._exemplar.kind

    @property
    def n(self) -> int:
        return self._n

    def add(self, record: Degradation, *, at_ns: int) -> None:
        """Merge one record. Refuses another kind, for `rollup()`'s reason: an entry is a kind."""
        if record.kind != self._exemplar.kind:
            raise ConfigError(
                f"a {record.kind!r} record merged into the {self._exemplar.kind!r} entry; the "
                f"manifest keys on the kind, so one entry is one kind",
                fix="group by kind first; manifest.degradations[<kind>] is the grouping",
            )
        if at_ns < self._last_ns:
            raise ConfigError(
                f"a record at {at_ns} after one at {self._last_ns}; first_ns and last_ns come from "
                f"the host Clock and a monotonic reading does not go backwards (15:1131)",
                fix="stamp with ctx.clock.monotonic_ns() at the degrade() site",
            )
        self._n += 1
        self._last_ns = at_ns
        if record.unit_uri is not None and len(self._units) <= MAX_ROLLUP_PARTS:
            self._units.setdefault(record.unit_uri, None)
        for part in record.parts_affected:
            if len(self._parts) > MAX_ROLLUP_PARTS and part not in self._parts:
                continue
            self._parts.setdefault(part, None)

    def entry(self) -> DegradationRollup:
        """The `manifest.degradations[<kind>]` value. Bounded by construction, never by truncation
        of a list this object never held."""
        units = tuple(self._units)
        parts = tuple(sorted(self._parts))
        return DegradationRollup(
            kind=self._exemplar.kind,
            n=self._n,
            first_ns=self._first_ns,
            last_ns=self._last_ns,
            units=units[:MAX_ROLLUP_PARTS],
            parts_affected=parts[:MAX_ROLLUP_PARTS],
            truncated=len(units) > MAX_ROLLUP_PARTS or len(parts) > MAX_ROLLUP_PARTS,
            exemplar=self._exemplar,
        )


class RunTally:
    """The run's mutable counters, and the one thing that produces a `RunManifest` from them.

    The split is deliberate: this object goes up, `RunManifest` is frozen, and `ManifestWriter` puts
    bytes on disk. A reader looking for "can this number go down" has one class to read, and a test
    that wants a manifest does not need a filesystem.

    Every method here is a `+=` or a `setdefault`. Nothing reads a clock -- `at_ns` is passed in,
    because 15:1131 makes `first_ns`/`last_ns` *"host Clock at merge time -- injected, never
    ambient"* and because a tally that read the machine could not be tested without one.
    """

    __slots__ = (
        "_cache_verdicts",
        "_deferred",
        "_degradations",
        "_failures",
        "_gpu_apportioned",
        "_gpu_measured",
        "_interrupted_inflight",
        "_op_micros",
        "_outcomes",
        "_rebilled_units",
        "_runtime_overhead_ms",
        "_spend_micros",
        "_stage_entries",
        "_stage_ms",
        "_uncached_micros",
        "_units",
    )

    def __init__(self) -> None:
        self._stage_ms: dict[TimedStage, int] = {}
        self._stage_entries: dict[TimedStage, int] = {}
        self._outcomes: dict[Outcome, int] = {}
        self._failures: dict[FailureClass, int] = {}
        self._deferred: dict[str, int] = {}
        self._cache_verdicts: dict[CacheVerdict, int] = {}
        self._degradations: dict[DegradationKind, DegradationTally] = {}
        self._units = 0
        self._spend_micros = 0
        self._op_micros = 0
        self._uncached_micros = 0
        self._gpu_measured = 0
        self._gpu_apportioned = 0
        self._rebilled_units = 0
        self._interrupted_inflight = 0
        self._runtime_overhead_ms = 0

    # -- the pipeline ------------------------------------------------------------------------

    def stage_closed(self, stage: Stage, elapsed_ms: int) -> None:
        """One `plan` span closed. 15:116: *"`stage_ms[s]` is the SUM of the elapsed times of every
        `plan` span carrying that Stage"*, with `stage_entries[s]` counting them.

        `query` and `compile` are refused by name rather than silently dropped. 15's Stage table
        marks both *"no"* in its `in stage_ms` column -- a read writes no manifest, and a compile
        writes a receipt -- so a caller that closed one against this tally has confused two
        artefacts, and swallowing it would put a read's latency in an ingest's timing map.
        """
        if stage not in STAGE_MS_KEYS:
            why = (
                "a read writes no manifest"
                if stage == Stage.QUERY
                else "a compile writes a receipt"
            )
            raise ConfigError(
                f"{stage} is not in stage_ms: 15 section 2.2's table marks it 'no', because {why}",
                fix=f"the seven that time are {tuple(str(s) for s in STAGE_MS_KEYS)}",
            )
        if elapsed_ms < 0:
            raise ConfigError(
                f"a Stage that took {elapsed_ms} ms; an elapsed time is a difference of two "
                f"monotonic readings",
                fix="measure with ctx.clock.monotonic_ns() at both boundaries",
            )
        # The guard above is the proof: `STAGE_MS_KEYS` is `TimedStage`'s own projection, so a
        # Stage that survives it is one of the seven.
        timed = cast("TimedStage", stage)
        self._stage_ms[timed] = self._stage_ms.get(timed, 0) + elapsed_ms
        self._stage_entries[timed] = self._stage_entries.get(timed, 0) + 1

    def settled(
        self,
        outcome: Outcome,
        *,
        failure_class: FailureClass | None = None,
        deferred_dim: str | None = None,
    ) -> None:
        """One work row reached a terminal transition. The count and its two breakdowns, at once.

        `failures_by_class` is 15:44's member and it counts the two `FAILED_*` outcomes only:
        `DEFERRED_BUDGET` is *"NOT a failure"* (08:2285, and the `Outcome` enum's own comment says
        so), and folding it in would make the manifest's failure count the number an operator
        retries against.

        `deferred_by_dim` is 08:2273's *"the manifest's deferred count by dimension"*, and the
        dimension is `StepResult.deferred_dim`, which that outcome requires.
        """
        if outcome not in set(Outcome):
            raise ConfigError(
                f"{outcome!r} is not an Outcome; the eight are {tuple(o.value for o in Outcome)}",
                fix="pass StepResult.outcome",
            )
        self._units += 1
        self._outcomes[outcome] = self._outcomes.get(outcome, 0) + 1
        if outcome in (Outcome.FAILED_TRANSIENT, Outcome.FAILED_PERMANENT):
            if failure_class is None:
                raise ConfigError(
                    f"{outcome} with no failure_class; StepResult requires one on both FAILED_* "
                    f"outcomes, because the retry ladder escalates from the class's first cooldown",
                    fix="pass StepResult.failure_class",
                )
            self._failures[failure_class] = self._failures.get(failure_class, 0) + 1
        if outcome is Outcome.DEFERRED_BUDGET:
            if deferred_dim is None:
                raise ConfigError(
                    "deferred_budget with no deferred_dim; StepResult requires one",
                    fix="pass StepResult.deferred_dim",
                )
            if deferred_dim not in BUDGET_DIMS:
                raise ConfigError(
                    f"{deferred_dim!r} is not a budget dimension; the eight are {BUDGET_DIMS}",
                    fix="defer against one of omniweave_core.budget.DIMS",
                )
            self._deferred[deferred_dim] = self._deferred.get(deferred_dim, 0) + 1

    # -- money -------------------------------------------------------------------------------

    def spent(
        self,
        micros: int,
        *,
        gpu_ms_measured: int = 0,
        gpu_ms_apportioned: int = 0,
        would_have_been_micros: int = 0,
    ) -> None:
        """One committed attempt's `route_spend` row, added to `cost.billed_micros`.

        Called where the spend row is written, which is `Store.complete()`'s transaction -- so this
        accumulates *committed* attempts and nothing else. 08:517 is why that matters: the
        reconciliation *"is exact only over committed attempts"*, because an interrupted run's
        in-flight reservations are released rather than committed and the provider may still bill
        for them. `interrupted()` is where that residue is recorded, as a count.
        """
        if micros < 0 or would_have_been_micros < 0:
            raise RouteError(
                f"a spend row of {micros} micros; spend is never negative",
                fix="price through Spend.micros(), which floors at zero",
            )
        self._spend_micros += micros
        self._uncached_micros += would_have_been_micros
        self._gpu_measured += gpu_ms_measured
        self._gpu_apportioned += gpu_ms_apportioned

    def op_spent(self, micros: int) -> None:
        """One `op.*` row's `work.cost_micros`. 08:2320, and it is NOT part of `billed_micros`.

        08:2583 gives the reason the two are separate rather than summed into one figure:
        `route_spend.decision_id` is `NOT NULL` and an `op.*` work row has a NULL `decision_id` by
        CHECK, *"so a core-only step cannot have a route_spend row"*. Adding its cost to
        `billed_micros` would make self-check 1 fail on every run that ran `op.cluster`.
        """
        if micros < 0:
            raise RouteError(
                f"an op.* row costing {micros} micros",
                fix="price through Spend.micros(), which floors at zero",
            )
        self._op_micros += micros

    # -- the cache ---------------------------------------------------------------------------

    def probed(self, verdict: CacheVerdict, *, rebilled: bool = False) -> None:
        """One unit's cache verdict. `rebilled` marks a unit that paid for work the cache held."""
        if verdict not in set(CacheVerdict):
            raise ConfigError(
                f"{verdict!r} is not a CacheVerdict; the seven are "
                f"{tuple(v.value for v in CacheVerdict)}",
                fix="pass the verdict probe() returned for this unit",
            )
        self._cache_verdicts[verdict] = self._cache_verdicts.get(verdict, 0) + 1
        if rebilled:
            self._rebilled_units += 1

    # -- the downgrades ----------------------------------------------------------------------

    def degrade(self, record: Degradation, *, at_ns: int) -> None:
        """One `Degradation`, merged into its kind's entry. 15:1140 rewrites the manifest here."""
        entry = self._degradations.get(record.kind)
        if entry is None:
            self._degradations[record.kind] = DegradationTally(record, at_ns=at_ns)
        else:
            entry.add(record, at_ns=at_ns)

    # -- the residues ------------------------------------------------------------------------

    def interrupted(self, in_flight: int) -> None:
        """08:2427: *"The manifest records `interrupted_inflight: n` -- the count, not the amount"*.

        The amount is unknowable: a provider may have billed for tokens generated after we stopped
        listening, and the reservation was released rather than committed. `17-risks.md` carries
        that as the open gap `08#N1`, whose pre-committed fallback is that the manifest *"must say
        'under-counts by at most N in-flight parts' in those words rather than presenting a total as
        complete"*. This integer is that N.
        """
        if in_flight < 0:
            raise ConfigError(
                f"{in_flight} in-flight parts at interrupt",
                fix="pass the number of claimed rows the cancel found",
            )
        self._interrupted_inflight = in_flight

    def overhead(self, ms: int) -> None:
        """12:569's `runtime_overhead_ms`: the per-unit scheduler cost, for the run whose `ow cost`
        is zero and whose wall time is six minutes. Set, not added -- it is one measurement."""
        if ms < 0:
            raise ConfigError(f"{ms} ms of overhead", fix="a duration is never negative")
        self._runtime_overhead_ms = ms

    # -- the snapshot ------------------------------------------------------------------------

    def snapshot(
        self,
        *,
        run_id: str,
        generation: int = 0,
        trigger: Trigger = "cli",
        status: RunStatus = "running",
        started_ns: int = 0,
        ended_ns: int | None = None,
        provenance: Provenance | None = None,
        host: HostFacts | None = None,
        timings: Timings = "always",
        observe: Mapping[str, int] | None = None,
    ) -> RunManifest:
        """Freeze the counters into the document. Called at every Stage boundary and every
        `degrade()`.

        `observe` comes from `SinkStats.as_manifest_fields()` on the run's sink and is passed in
        rather than accumulated here: 15:438's four numbers are the *sink's* own, and a second
        counter in this class would be a second answer to how many events were emitted.
        """
        return RunManifest(
            run_id=run_id,
            generation=generation,
            trigger=trigger,
            status=status,
            started_ns=started_ns,
            ended_ns=ended_ns,
            provenance=Provenance() if provenance is None else provenance,
            host=_unmeasured_host() if host is None else host,
            timings=timings,
            stage_ms={} if timings == "never" else dict(self._stage_ms),
            stage_entries=dict(self._stage_entries),
            units=self._units,
            outcomes=dict(self._outcomes),
            failures_by_class=dict(self._failures),
            deferred_by_dim=dict(self._deferred),
            interrupted_inflight=self._interrupted_inflight,
            runtime_overhead_ms=self._runtime_overhead_ms,
            cache=CacheStats.from_verdicts(
                self._cache_verdicts, rebilled_units=self._rebilled_units
            ),
            cost=CostBlock.of(
                billed_micros=self._spend_micros,
                op_micros=self._op_micros,
                would_have_been_micros_if_uncached=self._uncached_micros,
                gpu_ms_measured=self._gpu_measured,
                gpu_ms_apportioned=self._gpu_apportioned,
            ),
            degradations={kind: entry.entry() for kind, entry in self._degradations.items()},
            observe=dict(observe or {}),
        )


# =============================================================================================
# 6. The two self-checks. 08:2289-2295 -- "a failure of either is a hard run failure"
# =============================================================================================

BILLED_MICROS_SQL: Final = """
SELECT COALESCE(SUM(s.micros), 0)
  FROM route_spend s
  JOIN route_decision d ON d.decision_id = s.decision_id
 WHERE d.generation = :generation
"""
"""Self-check 1's ledger side. **It under-counts a resumed run, and D158 reports why.**

`route_spend` carries no `run_id` and no timestamp, so the only run-scoping column on the join is
`route_decision.generation`, which `0004_runtime.sql:357` documents as *"the run's `generation`"*.
But `route_decision` is append-only and its insert is `ON CONFLICT ... DO NOTHING`
(05-ingest-and-routing.md section 5 rule 6), so that column records the generation that **first
decided** the row. A resumed run re-attempts rows the previous generation decided and writes
`route_spend(decision_id, attempt = 2)` against them, and those micros join to the older generation.

The statement is shipped anyway, because a check with a stated limit is worth more than no check:
`reconcile()` takes the total as an argument, so a caller that has a better source -- the run's own
committed attempts, which `RunTally.spent()` accumulates -- passes that instead."""

SPEND_AUDIT_SQL: Final = """
SELECT w.id, w.decision_id, COUNT(s.attempt)
  FROM work w
  LEFT JOIN route_spend s ON s.decision_id = w.decision_id
 WHERE w.status = 'done' AND w.decision_id IS NOT NULL
 GROUP BY w.id, w.decision_id
"""
"""Self-check 2's ledger side: every settled routed row, with the number of spend rows against it.

A `LEFT JOIN`, so a row with **no** spend row comes back with a count of zero -- which is the
violation being looked for, and an inner join would have hidden exactly the rows the check is about.

**`work.status = 'done'` is wider than 08:2292's `ok`/`ok_partial`, and it has to be.** 08:95-99's
transition table sends four Outcomes to `done`: `ok`, `ok_partial`, `skipped_cached` and
`skipped_unchanged`. The `work` table has no `outcome` column, so SQL cannot narrow further, and of
those four only `skipped_unchanged` legitimately owes no spend row -- a cache hit writes one, with
`was_cache_hit = 1` (05:2572). `unpriced()` therefore takes the Outcome from the runner's own
`StepResult` and does the narrowing in Python."""


MAX_OFFENDERS_SHOWN: Final = 8
"""How many work ids `check_spend_audit()` names before it switches to a count.

A run that lost the spend row of every unit would otherwise raise an exception whose text is the
size of the corpus, and the eight it does print are enough for an operator to go and look at one."""


@dataclass(frozen=True, slots=True)
class SpendAudit:
    """One settled routed work row, paired with the Outcome the runner recorded for it.

    The pairing is the point. `SPEND_AUDIT_SQL` can produce `(work_id, decision_id, spend_rows)` and
    nothing more, because `work.status` folds four Outcomes into `done`; the fourth field comes from
    the `StepResult` the runner committed. A check written entirely in SQL would either miss the
    `skipped_unchanged` rows it must skip or flag them, and both are wrong answers.
    """

    work_id: int
    decision_id: str | None
    outcome: Outcome
    spend_rows: int

    def __post_init__(self) -> None:
        if self.spend_rows < 0:
            raise ConfigError(
                f"work row {self.work_id} with {self.spend_rows} spend rows",
                fix="COUNT() does not go negative; check the query",
            )


def reconcile(ledger_micros: int, manifest_micros: int) -> None:
    """Self-check 1. `Sigma route_spend.micros == manifest.cost.billed_micros`, **exactly**.

    08:2291: *"Not within a tolerance -- every micro is attributable to exactly one
    `(unit, part, decision, attempt)` (I30)."* There is no epsilon here and there must never be one:
    the sum is over integers priced once by `Spend.micros()`, so a drift of one micro is a row
    attributed to nothing, not a rounding artefact. 15:806 assigns the mismatch an `OW-R-*` code,
    which is `RouteError`'s namespace.

    The failure message names the difference and its sign, because the two directions have
    different causes: the ledger ahead of the manifest is a spend row the writer never saw (a second
    writer, or a resumed attempt -- D158), and the manifest ahead of the ledger is a commit that
    rolled back.
    """
    if ledger_micros == manifest_micros:
        return
    drift = ledger_micros - manifest_micros
    direction = "the ledger holds more" if drift > 0 else "the manifest claims more"
    raise RouteError(
        f"Sigma route_spend.micros = {ledger_micros} against manifest.cost.billed_micros = "
        f"{manifest_micros}: {direction}, by {abs(drift)} micros, which is attributable to no "
        f"(unit, part, decision, attempt) (I30)",
        fix="run `ow cost --verify` to find the unattributed rows; this is a hard run failure",
    )


def unpriced(rows: Iterable[SpendAudit]) -> tuple[int, ...]:
    """Self-check 2's first half: the work ids that spent and have no spend row.

    08:2292: *"Every `ok` / `ok_partial` row with a `decision_id` has at least one spend row."* The
    three qualifiers are all load-bearing and all three are applied here:

    * **`ok`/`ok_partial`** -- `PRICED_OUTCOMES`. A `skipped_unchanged` row never ran and a
      `deferred_budget` row was refused; neither owes a row, and 08:2285 makes the second point in
      as many words: *"A denial is never a failure."*
    * **with a `decision_id`** -- an `op.*` row has a NULL one by CHECK and therefore *cannot* have
      a spend row (08:2583). Flagging one would fail every run that ran `op.identify`.
    * **at least one** -- not exactly one. `[budget.per_part] calls = 3` is spent across attempts on
      one decision, so a row legitimately has several (05:2594).

    Returns the offending work ids in ascending order, so the caller's error message is stable.
    """
    return tuple(
        sorted(
            row.work_id
            for row in rows
            if row.outcome in PRICED_OUTCOMES
            and row.decision_id is not None
            and row.spend_rows == 0
        )
    )


def check_spend_audit(rows: Sequence[SpendAudit]) -> None:
    """Self-check 2, as a refusal. 08:2295: *"A failure of either is a hard run failure."*

    The message names at most eight ids and then the count, because a run that lost the spend row of
    every unit would otherwise produce an exception whose text is the size of the corpus.
    """
    offenders = unpriced(rows)
    if not offenders:
        return
    shown = ", ".join(str(work_id) for work_id in offenders[:MAX_OFFENDERS_SHOWN])
    hidden = len(offenders) - MAX_OFFENDERS_SHOWN
    more = f" and {hidden} more" if hidden > 0 else ""
    raise RouteError(
        f"{len(offenders)} settled work row(s) spent with no route_spend row: {shown}{more}. "
        f"An ok or ok_partial row with a decision_id has at least one (I30)",
        fix="run `ow cost --verify`; a priced attempt that wrote no spend row fails the run",
    )
