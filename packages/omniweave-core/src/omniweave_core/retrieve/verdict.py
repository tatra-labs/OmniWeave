"""The honesty record: fifteen gates in precedence order, and ONE site that says `absent`.

07:1975 makes this module the home of `VerdictState`, `ABSENCE_GATES`, `ABSENCE_BLOCKING_DIAGS` and
`build_verdict()`, and says what the type is for: it is rendered by `omniweave_core.answer`, and it
is *"the Python source from which `schema/verdict-v1.json` is generated and byte-diff gated by
`G6`"*. Everything below is written so that sentence stays true.

## The one rule, and the one `return`

INV-11 and SV8 are a single mechanism: `citable_as_absence` is `state is VerdictState.ABSENT` and
nothing else, and there is exactly one `return VerdictState.ABSENT` in the framework.
`tools/gate_semgrep.py` enforces both halves -- the bank confines the statement to this file and
`ast_findings()` rejects a SECOND site even here, which is what *"exactly one ... site"* actually
says. So the state ladder is written as 07:2135 prints it, with `return`s, and it is INLINED: a
closure inside `build_verdict()`, *"not a second entry point and not separately importable"*.

07:2137's four lines, in order, and each one is an argument:

```python
failed = [g for g in ABSENCE_GATES if gate_failed(g)]      # ALL FIFTEEN. No short-circuit
if failed:                              return VerdictState.DEGRADED
if not hits:                            return VerdictState.ABSENT   # THE ONE SITE
if confidence < fusion.low_confidence:  return VerdictState.LOW_CONFIDENCE
return VerdictState.OK
```

`ABSENT` is the RESIDUAL, not a gate's output (07:2152): no gate forces it and no gate can. It is
reached only by falling through all fifteen with an empty hit list, which is why one `return` is a
sufficient enforcement point and why a sixteenth hazard is added as a gate rather than as an `or`
inside the citability rule.

**`confidence` can be `None`, and `None` is not a high confidence.** D258: 07:1484 blesses `0.0` as
an explicit per-Channel weight, so a channel set whose ceiling-bearing members all weigh zero
produces a real `best_score` over a `0.0` ceiling. 07:2140 compares against
`fusion.low_confidence`, and `None < 0.35` raises. The ladder reads an uncomputable confidence as
`LOW_CONFIDENCE`, because the alternative -- treating it as `OK` -- publishes a verdict of "this is
good evidence" from a number that does not exist.

## All fifteen run, always

07:2202: *"A gate that fires does not end the ladder, and no renderer may show one that did."* That
is what lets 07 section 6.6's worked plan (5) report three fired gates at once and what makes an
`Injector` targeting gate 13 assertable on a corpus that also has a parse gap. `_GATES` is a tuple
of fifteen `(name, predicate)` pairs in `ABSENCE_GATES` order, every predicate is evaluated, and
the surviving causes come back in that order -- which 07:2166 calls *"the precedence order"*, so
07:2176's *"the first `DegradeCause` a caller reads is the one that subsumes the others"* holds.

Every row's forced state is `DEGRADED` and 07:2197 says the uniformity is the design: *"a gate's
only power is to take `ABSENT` off the table and say why. A gate that could force some other state
would be a second rule."* So no predicate returns a state; each returns a `DegradeCause` or `None`.

## Two `gates`, and confusing them is the easiest bug in the document

07:2046: `QueryPlan.gates` is the set that is NON-VACUOUS for this plan -- a disclosure authored by
a policy rule -- and `Verdict.gates` is the subset that FAILED. Every plan evaluates all fifteen; a
gate outside `QueryPlan.gates` is one whose precondition cannot hold, so it passes vacuously and
can never appear here. `state is ABSENT` therefore still requires all fifteen to pass, and
07:2065 adds *"no plan can buy an absence claim by shortening a list"*. This module does not
read `QueryPlan.gates`
at all, which is the strongest form of that: a gate a plan removed cannot be removed from the
evaluation, only from the rendering.

## `degradations` carries kind STRINGS

07:2034 types the field `tuple["Degradation", ...]` and names 15-observability.md as the owner.
`omniweave_core.observe.degradation` does not exist (charter erratum E15), and D248 records that
`store/reader.py` already carries `hub_capped`, `segment_lift_capped` and `pushdown_unavailable`
as strings for that reason, on `drivers/catalog.py`'s `UNPINNED_DEGRADATION` precedent. One rival
declaration of that type would be the thing INV-21 forbids, so the field is `tuple[str, ...]` of
15:986's closed twenty-seven kinds and the shape changes when the type lands.

## `DegradeCause.fix` is required to be a command, and the evidence rarely names one

07:1995 says `fix` is *"THE EXACT COMMAND THAT CLEARS IT"* and that `""` is legal *"only where no
command clears it -- gates 3 and 14, whose fix is 'retry' and 'wait'"*. 13 section 8.6 turns that
into a hard assertion: the damaged run's `DegradeCause.fix`, executed, must produce an undamaged
run. But the reads the gate table specifies do not carry the OBJECT such a command would take --
`Coverage` is eleven counts and no URI, `withheld` is counts, a `ChannelResult` is a status and a
ranking. Only gate 9 can name its object, because `Coverage.gaps` arrives as `DegradeCause`s built
where the document was in hand. D265. What ships is a command wherever the gate's own evidence
supplies every argument, `""` otherwise, and the knob or the count named in `detail` -- which
07:1992 makes the field `ow why absent` prints VERBATIM.

Stdlib only (INV-2 / G1), inside one of the nine LAZY subpackages, so `import omniweave_core` does
not reach it (G17).

Specified in 07-store-and-retrieval.md sections 6.7 and 6.8; scheduled by 16-roadmap.md:661.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.retrieve.ceiling import ceiling, confidence
from omniweave_core.retrieve.types import ABSENCE_GATES, CHANNELS, ChannelResult, ChannelStatus
from omniweave_core.store.types import Coverage

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from omniweave_core.retrieve.types import FusedHit, QueryPlan
    from omniweave_core.store.types import IndexCaps, Narrowing

# `Mapping` is a RUNTIME import for `retrieve/types.py`'s stated reason: `Verdict` is the
# declaration `ow schema emit` reflects with `typing.get_type_hints()` (07:1975), and a name that
# exists only under `TYPE_CHECKING` raises `NameError` there. `Callable` and `Sequence` appear in
# function signatures alone, which no reflector reads, so they stay behind the guard.

__all__ = [
    "ABSENCE_BLOCKING_DIAGS",
    "ABSENCE_GATES",
    "MAX_DID_YOU_MEAN",
    "Coverage",
    "DegradeCause",
    "Verdict",
    "VerdictState",
    "build_verdict",
]

MAX_DID_YOU_MEAN: Final[int] = 5
"""07:1987. Bounds the render of a by-product, never a second query (07:2068)."""

ABSENCE_BLOCKING_DIAGS: Final[tuple[str, ...]] = (
    "OW_ENCRYPTED",
    "OW_NEEDS_OCR",
    "OW_MALFORMED",
    "OW_MISSING_PART",
    "OW_TRUNCATED_BY_BUDGET",
    "OW_DRIVER_UNAVAILABLE",
    "OW_ORIGIN_SPAN_DOWNGRADE",
    "OW_INDEX_MODEL_CHANGED",
    "OW_TIMEOUT",
    "OW_UNSUPPORTED_FORMAT",
    "OW_RESOURCE_LIMIT",
    "OW_INTEGRITY_UNCHECKED",
    "OW_TABLE_SYNOPSIS_ONLY",
)
"""The thirteen `Diag` codes gate 9 joins against, in 13:1281-1295's printed order.

13:2118 defines the Injector set as *"**one per `Diag` code in `ABSENCE_BLOCKING_DIAGS`**"* and
names thirteen, so the two counts are one count and this tuple is the population
`degradation_detection == 1.000` is a claim about. The order is the injector table's: the charter's
eight first, then the five 13:1279 adds *"so the set is total"*.

Members, not a set of `Diag` objects: `Diag` is `omniweave_core.model`'s (03:1800) and a join
against `diag.code` compares TEXT. A code that is not a member is a diagnostic that does not block
an absence claim, which is a different and equally deliberate fact.
"""


class VerdictState(StrEnum):
    """07:1983's four, *"referenced, not redefined"* -- and this module is where they are defined.

    `ok | low_confidence | absent | degraded`. The ladder in `build_verdict()` is the only producer
    and `citable_as_absence` is the only consumer that licenses anything.
    """

    OK = "ok"
    LOW_CONFIDENCE = "low_confidence"
    ABSENT = "absent"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class DegradeCause:
    """07:1989. ONE per gate that failed -- *"NEVER a summary of several"*.

    `gate` is a member of `ABSENCE_GATES` and not free text (07:1990), which `__post_init__`
    enforces: the field is what `ow why absent` keys its ladder by and what the paired-damage suite
    asserts *"in precedence order"*, and a typo there is a row nobody can find.

    `diag_codes` is *"`ABSENCE_BLOCKING_DIAGS` members behind it. Gate 9 only"* and `where` is
    `(doc_ord, page_lo, page_hi)` INCLUSIVE -- the only gate that can name pages, because it is the
    only one whose read is a join that knows which document it was reading.

    `fix` is *"THE EXACT COMMAND THAT CLEARS IT"*, empty only where no command does. D265 is that
    the gate table's reads do not supply the arguments such a command needs for thirteen of the
    fifteen; the knob or the count goes in `detail` instead, which is the line `ow why absent`
    prints verbatim.
    """

    gate: str
    detail: str
    diag_codes: tuple[str, ...] = ()
    where: tuple[tuple[int, int, int], ...] = ()
    fix: str = ""

    def __post_init__(self) -> None:
        if self.gate not in ABSENCE_GATES:
            msg = (
                f"{self.gate!r} is not one of the fifteen absence gates: 07:1990 makes "
                f"DegradeCause.gate a member of ABSENCE_GATES and NOT free text, because the "
                f"ladder is keyed by it -- fix: name one of {ABSENCE_GATES}"
            )
            raise ValueError(msg)
        for code in self.diag_codes:
            if code not in ABSENCE_BLOCKING_DIAGS:
                msg = (
                    f"{code!r} is not one of the thirteen ABSENCE_BLOCKING_DIAGS: a diagnostic "
                    f"outside that set does not block an absence claim, so carrying it here "
                    f"would make a non-blocking code look like a blocking one -- fix: join "
                    f"`diag.code` against ABSENCE_BLOCKING_DIAGS before building the cause"
                )
                raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Verdict:
    """07:2000. Twenty-two fields: the charter's twenty, plus `generated_share` and `degradations`.

    The field ORDER is the charter's so the two prints diff cleanly, and both additions are last
    with real defaults -- 07:2043: *"so a positional construction written against the charter's
    shape still type-checks"*.

    `build_verdict()` is the only constructor (07:2038). Nothing here validates the counts, because
    a `Verdict` a caller assembled by hand is exactly what the one-constructor rule exists to
    prevent and a validator would make hand-assembly look supported.

    **`fusion_kind` is `rrf` or `rank_merge`, and the charter's printed `"exact"` is superseded**
    (07:2042): `"exact"` is already one of the five `CHANNELS`, so a reader seeing
    `fusion_kind = "exact"` beside `channels["exact"]` has to decide which sense is meant on every
    read, and it describes no fusion this document performs.

    **The closed key sets.** 07:2068: *"Every key below is always present when its map is; an
    absent key is a bug, not a zero, because "we did not measure" and "we measured zero" are the
    distinction this whole type exists to preserve."* `channels` carries all five members of
    `CHANNELS` always, `scanned` its four, and `withheld` always carries `rows` -- the reserved key
    gate 10 reads and no other, and 07:2079 says why: *"a block carrying two bits must not count
    twice"*.
    """

    state: VerdictState
    gates: tuple[str, ...]
    degraded_because: tuple[DegradeCause, ...]
    scanned: Mapping[str, int]
    best_score: float | None
    score_ceiling: float
    confidence: float | None
    scorer_version: int
    plan_digest: str
    channels: Mapping[str, ChannelStatus]
    freshness: Literal["fresh", "refreshing", "stale", "unknown", "not_tracked"]
    coverage: Coverage
    withheld: Mapping[str, int]
    matches_before_packing: int
    space: Mapping[str, str] | None
    snapshot_gen: int
    federated: bool
    shards_contributed: str | None
    fusion_kind: Literal["rrf", "rank_merge"]
    did_you_mean: tuple[str, ...]
    generated_share: float = 0.0
    degradations: tuple[str, ...] = ()

    @property
    def citable_as_absence(self) -> bool:
        """07:2036: THE ONE GATE. NEVER A SECOND RULE.

        INV-11's whole mechanism is that this is an identity comparison against a state only one
        `return` can produce. A predicate that also asked "and were there no gaps?" would be a
        second citability rule, and the ladder above would stop being the whole of the argument.
        """
        return self.state is VerdictState.ABSENT


@dataclass(frozen=True, slots=True)
class _Evidence:
    """What the fifteen predicates read, assembled once by `build_verdict()`.

    Private and un-exported: the gates are not a second entry point, and a public evidence shape
    would be a way to ask "would this fire?" without building the record that discloses it.
    """

    results: tuple[ChannelResult, ...]
    coverage: Coverage
    freshness: str
    withheld: Mapping[str, int]
    degradations: tuple[str, ...]
    pack_k: int
    fused_n: int
    returned: int
    snapshot_gen: int
    generation_at_pack: int
    snapshot_expired: bool
    requested: frozenset[str]
    space: Mapping[str, str] | None
    configured_model_key: str
    federated: bool
    shards_expected: int
    shards_contributed: str | None

    def named(self, name: str) -> ChannelResult | None:
        return next((result for result in self.results if result.name == name), None)


# ---------------------------------------------------------------------------
# Gates 1-3: did the search happen?
# ---------------------------------------------------------------------------


def _timed_out(ev: _Evidence) -> DegradeCause | None:
    """Gate 1. 07:2181: any Channel `UNAVAILABLE(timeout)`, or the snapshot expired.

    *"A Channel at `OFF(query_deadline)` is **not** this gate"* -- that is the two-deadline split's
    whole point (07:1791), and reading the `reason` is the only thing that tells the two apart.
    First in the ladder because a Channel that ran out of time did not look, so every later gate
    would describe a corpus that was never searched.
    """
    late = [
        r.name
        for r in ev.results
        if r.status == ChannelStatus.UNAVAILABLE and r.reason == "timeout"
    ]
    if not late and not ev.snapshot_expired:
        return None
    parts = [f"{name} exceeded its own budget_ms" for name in late]
    if ev.snapshot_expired:
        parts.append("the snapshot expired (OW-S-010)")
    return DegradeCause(gate="timed_out", detail="; ".join(parts))


def _channel_unavailable(ev: _Evidence) -> DegradeCause | None:
    """Gate 2. 07:2182: `UNAVAILABLE` for any reason but timeout, or an `OFF` the caller asked for.

    The third disjunct -- *"a Channel raised"* -- has no representation here and needs none: INV-12
    forbids a bare `except` under `retrieve/`, so a Channel that raised propagates and there is no
    verdict to degrade. Separated from gate 1 *"only by the reason, so it reads second"*.
    """
    broken = [
        r for r in ev.results if r.status == ChannelStatus.UNAVAILABLE and r.reason != "timeout"
    ]
    refused = [r for r in ev.results if r.status == ChannelStatus.OFF and r.name in ev.requested]
    if not broken and not refused:
        return None
    parts = [f"{r.name} is unavailable: {r.reason}" for r in broken]
    parts += [f"{r.name} was requested and reports off({r.reason})" for r in refused]
    return DegradeCause(gate="channel_unavailable", detail="; ".join(parts), fix="ow doctor")


def _store_changed_mid_query(ev: _Evidence) -> DegradeCause | None:
    """Gate 3. 07:2183: `index_state.generation` at plan against the same read at pack.

    *"One counter answers both "the index changed" and "rows moved during the scan", because the
    `.owstore` has one writer."* `fix` is empty by the document's own naming (07:1997): the fix is
    to retry, and a retry is not a command that clears anything.
    """
    if ev.snapshot_gen == ev.generation_at_pack:
        return None
    return DegradeCause(
        gate="store_changed_mid_query",
        detail=(
            f"index_state.generation was {ev.snapshot_gen} when the plan was built and "
            f"{ev.generation_at_pack} when the answer was packed; retry the query"
        ),
    )


# ---------------------------------------------------------------------------
# Gates 4-9: was the corpus the search ran over whole?
# ---------------------------------------------------------------------------


def _coverage_incomplete(ev: _Evidence) -> DegradeCause | None:
    """Gate 4. 07:2184: `scope_rows == 0` OR `discovered > indexed` OR `complete` is false.

    *"**No row means coverage UNKNOWN, never clean**"* -- the disjunct that stops "we found
    nothing" reading as "there is nothing", and the reason `Coverage.scope_rows` exists at all.
    First corpus-shape gate because *"the scan never finished"* subsumes every narrower per-unit
    claim below it.
    """
    cov = ev.coverage
    if cov.scope_rows and cov.discovered <= cov.indexed and cov.complete:
        return None
    if not cov.scope_rows:
        detail = "no ingest_scope row is in view, so coverage is UNKNOWN rather than clean"
    else:
        detail = (
            f"ingest_scope: discovered {cov.discovered}, indexed {cov.indexed}, "
            f"complete={int(cov.complete)}"
        )
    return DegradeCause(
        gate="coverage_incomplete", detail=detail, fix="ow corpora --detail coverage"
    )


def _pending_work_in_scope(ev: _Evidence) -> DegradeCause | None:
    """Gate 5. 07:2185: `work.status IN ('pending','claimed')` for units inside the scope --
    and, since W7.3w, every unit in scope rostered and not yet indexed (D567,
    `store.reader.IN_FLIGHT_UNIT_STATES`).

    *"A queued unit is a coverage hole with a completion date"* -- narrower than gate 4, and its
    remedy is *"wait or raise the budget"*, which is not a command, so `fix` is empty and the count
    goes in `detail`.
    """
    if ev.coverage.pending_work <= 0:
        return None
    return DegradeCause(
        gate="pending_work_in_scope",
        detail=(
            f"{ev.coverage.pending_work} unit(s) or work row(s) in scope are not indexed yet; "
            f"run ow ingest, wait for it, or raise [limits] the run budget"
        ),
    )


def _source_edited_unindexed(ev: _Evidence) -> DegradeCause | None:
    """Gate 6. 07:2186: a source moved under a corpus that is complete and idle.

    `Coverage.stale_units` is the carrier for section 11.3 fact 5's `stat_fresh` predicate --
    *"`st_mtime_ns + MTIME_GRANULARITY_NS > indexed_at_ns` ... the racily-clean window, 2 s"*.
    Below gate 5 because *"a `work` row is a KNOWN hole and an edited source is an INFERRED one"*.
    """
    if ev.coverage.stale_units <= 0:
        return None
    return DegradeCause(
        gate="source_edited_unindexed",
        detail=(
            f"{ev.coverage.stale_units} tracked source(s) changed after they were indexed; "
            f"re-add them to pick the edits up"
        ),
    )


def _freshness_unknown(ev: _Evidence) -> DegradeCause | None:
    """Gate 7. 07:2187: `freshness == "unknown"`, and `not_tracked` is DELIBERATELY not a failure.

    *"an untracked source is disclosed, not refused"*. Below gate 6 because *"6 is a positive
    finding and 7 is an absence of evidence"* -- we could not even ask question 6.
    """
    if ev.freshness != "unknown":
        return None
    return DegradeCause(
        gate="freshness_unknown",
        detail="a tracked source could not be stat()ed, so its freshness is unknown",
        fix="ow doctor",
    )


def _inputs_unreadable(ev: _Evidence) -> DegradeCause | None:
    """Gate 8. 07:2188: `Coverage.unreadable_units > 0`.

    *"Names a specific unit the scan should have read and could not"*, so it ranks below the
    not-knowing of gate 7 and above the parse-level detail of gate 9.
    """
    if ev.coverage.unreadable_units <= 0:
        return None
    return DegradeCause(
        gate="inputs_unreadable",
        detail=f"{ev.coverage.unreadable_units} unit(s) in scope could not be read",
        fix="ow doctor",
    )


def _parse_gap_in_scope(ev: _Evidence) -> DegradeCause | None:
    """Gate 9. **The one nobody else has.** 07:2189: `Coverage.gaps != ()`.

    The gaps arrive as `DegradeCause`s already grouped by `(doc, page range)`, built by the join
    that had the document in hand -- which is why this is the only gate that can name pages and
    print a command (07:1962's `fix="ow add 2024-appendix.pdf --allow-cost 40000"`).

    **Several gaps become ONE cause, and D266 is that nothing says how.** 07:1989 makes it one
    entry per failed gate and *"NEVER a summary of several"*; `Coverage.gaps`
    is plural by construction. Shipped: the codes and the page ranges of every gap, merged in the
    order the join produced them, with the FIRST gap's `fix` -- which is exact when the gaps share
    a document and a guess when they do not.
    """
    gaps = ev.coverage.gaps
    if not gaps:
        return None
    codes: list[str] = []
    for gap in gaps:
        codes += [code for code in gap.diag_codes if code not in codes]
    where = tuple(span for gap in gaps for span in gap.where)
    detail = gaps[0].detail if len(gaps) == 1 else f"{len(gaps)} parse gaps: {gaps[0].detail}"
    return DegradeCause(
        gate="parse_gap_in_scope",
        detail=detail,
        diag_codes=tuple(codes),
        where=where,
        fix=gaps[0].fix,
    )


# ---------------------------------------------------------------------------
# Gates 10-12: was the answer that came back whole?
# ---------------------------------------------------------------------------


def _restricted_withheld(ev: _Evidence) -> DegradeCause | None:
    """Gate 10. 07:2190: `withheld["rows"] > 0`. **Counted, never silent.**

    `rows` and no other key: 07:2079 is *"Gate 10 reads this key and no other"*, because a
    block carrying two bits must not count twice. First
    result-shape gate: the corpus is sound and the answer is short because POLICY removed rows --
    07:2190, a fact the caller can learn no other way.
    """
    rows = ev.withheld.get("rows", 0)
    if rows <= 0:
        return None
    bits = sorted(name for name in ev.withheld if name != "rows")
    named = f" ({', '.join(bits)})" if bits else ""
    return DegradeCause(
        gate="restricted_withheld",
        detail=f"{rows} block(s) removed by deny_restriction_bits{named}",
    )


def _filter_starved(ev: _Evidence) -> DegradeCause | None:
    """Gate 11. 07:2191: a Channel that could not push its filter down, starved by post-filtering.

    *"Vacuous where pushdown is available or no ANN ran."* The `pushdown_unavailable` kind is the
    carrier for the first conjunct -- `ChannelResult` has no `degradations` field (D248), so it
    arrives on the `Verdict`'s own tuple, which is where 07:1785 puts it.

    **The third conjunct is not evaluated, and D263 is why.** 07:2191's *"hit the over-fetch
    cap"* reads
    either as "the clamp returned 64" or as "the fetch filled", the two fire on different queries,
    and the reading that actually detects starvation has no carrier: `ChannelResult` has no fetch
    count and 15:992 closes the `Degradation` kinds at twenty-seven. Leaving it out makes this gate
    fire MORE often, which is the safe direction -- over-disclosing degrades an answer that was
    whole; under-disclosing presents a starved one as whole.
    """
    if "pushdown_unavailable" not in ev.degradations:
        return None
    semantic = ev.named("semantic")
    survivors = 0 if semantic is None else len(semantic.ranked)
    if survivors >= ev.pack_k:
        return None
    return DegradeCause(
        gate="filter_starved",
        detail=(
            f"the vector backend declared no pushdown, so the filter ran after ranking and left "
            f"{survivors} candidate(s) against k={ev.pack_k}"
        ),
    )


def _truncated_by_packing(ev: _Evidence) -> DegradeCause | None:
    """Gate 12. 07:2192: `matches_before_packing > 0 and len(hits) == 0`.

    **AN EMPTY RESPONSE IS NOT AN EMPTY SEARCH.** Last result-shape gate because *"the loss
    happened after ranking, at the last bound the caller controls"*.
    """
    if ev.fused_n <= 0 or ev.returned > 0:
        return None
    return DegradeCause(
        gate="truncated_by_packing",
        detail=(
            f"{ev.fused_n} block(s) matched and packing returned none; raise --max-chars or "
            f"--max-blocks"
        ),
    )


# ---------------------------------------------------------------------------
# Gates 13-15: was the machinery the one the caller configured?
# ---------------------------------------------------------------------------


def _space_mismatch(ev: _Evidence) -> DegradeCause | None:
    """Gate 13. 07:2193: `vec_manifest.model_key` against the configured `embed/1` Driver's tuple.

    *"the same comparison that raises `OW-S-020` on the build path, so a mismatch degrades the
    SEARCH rather than only refusing the build."* Vacuous at `vectors = "off"`, where there is no
    space to mismatch.

    The `corpus_id` half never reaches here: `SqliteReader._read_vec_manifest` already ignores a
    sidecar whose `corpus_id` is another corpus's, so that disagreement presents as a semantic
    Channel that did not run. The `model_key` half needs the configured Driver's identity, which
    D250 records as having no carrier -- an empty `configured_model_key` is that absence, and it
    makes the comparison vacuous rather than false.
    """
    if ev.space is None or not ev.configured_model_key:
        return None
    ran = ev.space.get("model_key", "")
    if ran == ev.configured_model_key:
        return None
    return DegradeCause(
        gate="space_mismatch",
        detail=(
            f"the index was built with model_key {ran!r} and the configured embed Driver is "
            f"{ev.configured_model_key!r} (OW-S-020)"
        ),
        diag_codes=("OW_INDEX_MODEL_CHANGED",),
    )


def _shard_unreachable(ev: _Evidence) -> DegradeCause | None:
    """Gate 14. 07:2194: federated, and fewer shards contributed than were configured.

    T4 only and vacuous at T1-T3, *"so checking it late costs nothing on the store every reader
    actually has"*. `fix` is empty by 07:1997's naming: the fix is to wait.
    """
    if not ev.federated or ev.shards_expected <= 0:
        return None
    named = () if not ev.shards_contributed else tuple(ev.shards_contributed.split(","))
    if len(named) >= ev.shards_expected:
        return None
    return DegradeCause(
        gate="shard_unreachable",
        detail=(
            f"{len(named)} of {ev.shards_expected} shards contributed within federate_ms; "
            f"contributing: {ev.shards_contributed or 'none'}"
        ),
    )


def _similarity_only(ev: _Evidence) -> DegradeCause | None:
    """Gate 15. 07:2195: the only Channel with `status is OK` was `semantic`.

    **Checked last, and the order is the entire argument.** *"Every gate above names something the
    caller can fix; a cosine zero is a statement about the model, not about the corpus. Firing it
    earlier would mask a fixable cause behind an unfixable one."* `fix` is empty for that same
    reason: there is no command, and saying so is the disclosure.
    """
    ran = [r.name for r in ev.results if r.status == ChannelStatus.OK]
    if ran != ["semantic"]:
        return None
    return DegradeCause(
        gate="similarity_only",
        detail=(
            "the semantic Channel was the only one that returned hits, so the evidence is a "
            "similarity score and not a match in the corpus"
        ),
    )


_GATES: Final[tuple[tuple[str, Callable[[_Evidence], DegradeCause | None]], ...]] = (
    ("timed_out", _timed_out),
    ("channel_unavailable", _channel_unavailable),
    ("store_changed_mid_query", _store_changed_mid_query),
    ("coverage_incomplete", _coverage_incomplete),
    ("pending_work_in_scope", _pending_work_in_scope),
    ("source_edited_unindexed", _source_edited_unindexed),
    ("freshness_unknown", _freshness_unknown),
    ("inputs_unreadable", _inputs_unreadable),
    ("parse_gap_in_scope", _parse_gap_in_scope),
    ("restricted_withheld", _restricted_withheld),
    ("filter_starved", _filter_starved),
    ("truncated_by_packing", _truncated_by_packing),
    ("space_mismatch", _space_mismatch),
    ("shard_unreachable", _shard_unreachable),
    ("similarity_only", _similarity_only),
)
"""The fifteen, paired with their predicates, in `ABSENCE_GATES` order.

The names are repeated here rather than derived, so the pairing is checkable: a test asserts this
tuple's names ARE `ABSENCE_GATES`, which is the mechanical form of 07:2166's *"its order is
the precedence order"*. A dict keyed by gate name would have made the order an implementation
detail of whatever built it."""


def build_verdict(
    *,
    plan: QueryPlan,
    results: Sequence[ChannelResult],
    coverage: Coverage,
    narrowing: Narrowing,
    caps: IndexCaps,
    fused: Sequence[FusedHit],
    returned: int,
    freshness: Literal["fresh", "refreshing", "stale", "unknown", "not_tracked"],
    withheld: Mapping[str, int],
    snapshot_gen: int,
    generation_at_pack: int,
    scanned_segments: int = 0,
    scanned_docs: int = 0,
    snapshot_expired: bool = False,
    requested: frozenset[str] = frozenset(),
    space: Mapping[str, str] | None = None,
    configured_model_key: str = "",
    federated: bool = False,
    shards_expected: int = 0,
    shards_contributed: str | None = None,
    did_you_mean: tuple[str, ...] = (),
    generated_share: float = 0.0,
    degradations: tuple[str, ...] = (),
) -> Verdict:
    """07:2038. THE ONLY CONSTRUCTOR, and the only place the ladder is walked.

    Keyword-only, one parameter per fact the record carries or a gate reads: that is the typed form
    of the printed `build_verdict(**kw)`, and it is what makes a missing measurement a TypeError
    instead of a zero. The four values a caller cannot be trusted to have derived are derived here
    -- `channels`, `scanned`, the fusion arithmetic and `fusion_kind` -- so the honesty record
    cannot disagree with the evidence that produced it.

    **`channels` must name all five.** 07:2016: *"ALL FIVE members of `CHANNELS`, ALWAYS present. A
    missing key would be indistinguishable from `OFF`, which is the disclosure this exists to
    make."* A result set that does not name the five is refused here rather than silently
    completed, because completing it would invent the very disclosure the field exists for.

    **`scanned["segments"]` is a parameter and D267 is why.** 07:2076 makes it *"distinct
    `segment_id`s the semantic Channel touched"*, and `ChannelResult`'s ten fields carry no
    segment identifier, so the number cannot be derived from the evidence and has to arrive from
    whoever ran the Channel.
    `narrowed` and `blocks` ARE derivable and are derived.

    `best_score` is `fuse()[0].score` over the FUSED list, not the packed one: 07:2010 makes it
    *"None iff no Channel ranked"*, and packing that dropped every hit is gate 12's fact, not a
    claim that nothing matched.
    """
    ordered = tuple(results)
    names = {result.name for result in ordered}
    if names != set(CHANNELS):
        msg = (
            f"build_verdict got results for {sorted(names)} and Verdict.channels carries all five "
            f"of {CHANNELS} always (07:2043): a missing key is indistinguishable from OFF, which "
            f"is the disclosure the field exists to make -- fix: report every Channel the plan did "
            f"not run as OFF(not_in_plan)"
        )
        raise ValueError(msg)

    evidence = _Evidence(
        results=ordered,
        coverage=coverage,
        freshness=freshness,
        withheld=withheld,
        degradations=degradations,
        pack_k=plan.pack.k,
        fused_n=len(fused),
        returned=returned,
        snapshot_gen=snapshot_gen,
        generation_at_pack=generation_at_pack,
        snapshot_expired=snapshot_expired,
        requested=requested,
        space=space,
        configured_model_key=configured_model_key,
        federated=federated,
        shards_expected=shards_expected,
        shards_contributed=shards_contributed,
    )
    causes = tuple(
        cause for cause in (predicate(evidence) for _name, predicate in _GATES) if cause is not None
    )

    score_ceiling = ceiling(ordered, k=plan.fusion.k, weights=plan.fusion.weights)
    best_score = fused[0].score if fused else None
    ratio = confidence(best_score, score_ceiling)

    def state() -> VerdictState:
        """07:2135's four lines, inlined -- not a second entry point and not importable."""
        if causes:
            return VerdictState.DEGRADED
        if not fused:
            return VerdictState.ABSENT  # <- THE ONE SITE (INV-11, SV8)
        if ratio is None or ratio < plan.fusion.low_confidence:
            return VerdictState.LOW_CONFIDENCE
        return VerdictState.OK

    return Verdict(
        state=state(),
        gates=tuple(cause.gate for cause in causes),
        degraded_because=causes,
        scanned=MappingProxyType(
            {
                "narrowed": _narrowed(narrowing, caps),
                "blocks": len({block for result in ordered for block in result.ranked}),
                "segments": scanned_segments,
                "docs": scanned_docs,
            }
        ),
        best_score=best_score,
        score_ceiling=score_ceiling,
        confidence=ratio,
        scorer_version=plan.scorer_version,
        plan_digest=plan.plan_digest,
        channels=MappingProxyType({result.name: result.status for result in ordered}),
        freshness=freshness,
        coverage=coverage,
        withheld=MappingProxyType(dict(withheld)),
        matches_before_packing=len(fused),
        space=space,
        snapshot_gen=snapshot_gen,
        federated=federated,
        shards_contributed=shards_contributed,
        fusion_kind="rank_merge" if federated else "rrf",
        did_you_mean=did_you_mean[:MAX_DID_YOU_MEAN],
        generated_share=generated_share,
        degradations=degradations,
    )


def _narrowed(narrowing: Narrowing, caps: IndexCaps) -> int:
    """07:2058: `Narrowing.n` at `set`, `stat.live_blocks` at `all`, `0` at `empty`.

    The `all` row is why this is not just `narrowing.n`: above `PREFILTER_MAX` the probe's count is
    the cap and not the corpus, and reporting the cap as the number scanned would understate the
    search by however much bigger the true set was.
    """
    if narrowing.kind == "empty":
        return 0
    if narrowing.kind == "all":
        return caps.live_blocks
    return narrowing.n
