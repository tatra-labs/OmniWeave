"""`retrieve()`: the planner, the Channels, fusion and the Verdict, run in order. 07:2248.

Every part it composes shipped in P6 -- `plan()` (W6.1), the five Channels behind `Reader.channel()`
(W6.2), `fuse()` and `ceiling()` (W6.3), the narrowing (W6.4), `build_verdict()` (W6.5) -- and
nothing called them in order. 02:251 gives row 27 exactly one public interface,
`retrieve(Reader, Query, RetrievalPolicy) -> Response`, and 16:92's skeleton milestone draws the
arrow `L4 retrieve() -> identity + lexical channels over block_fts, fuse(), ceiling()`. This is
that arrow, for all five.

## THE FOUR PHASES, AND WHERE THE SNAPSHOT IS

07:1126-1129:

    phase 1  sanitise + lift refs + plan()          pure, µs, memoised
    phase 2  embed the query (semantic only)        embed_ms = 120, OUTSIDE query_ms,
                                                    OUTSIDE the snapshot
    phase 3  snapshot → narrow → channels → hydrate → coverage      query_ms = 250
    phase 4  fuse, build_verdict, pack, encode      after the snapshot closes

Fusion is run inside phase 3 as well as being listed in phase 4, and that is not a reordering:
hydration needs to know WHICH ids to hydrate, which is the fused order, and 07:2327 puts the text
read inside the snapshot so the payload is the generation that was ranked. `fuse()` is pure and
microseconds, so running it before `hydrate()` costs the held transaction nothing.

**Phase 2 does not exist in this build.** The query embedding is an `embed/1` Driver call and
`omniweave_core` holds no embed driver, so `ChannelInput.q_sig` is never set. On a store with no
vector backend -- `[retrieval] vectors = "off"`, the permanent v1 default (07:2596) -- the semantic
Channel reports `OFF(vectors)`, an operator choice that costs the ceiling nothing. On a store that
HAS a backend, the Channel is called and says `unavailable` itself, which degrades: a deployment
that turned vectors on and got none should hear it.

## THE TWO DEADLINES (07:1789)

`time.monotonic_ns` is read between Channels, which are 07:1805's cancellation points, and
nowhere else:

* a Channel whose own `ran_ms` exceeds its `budget_ms` becomes `UNAVAILABLE(timeout)`, keeping what
  it ranked (fusion reads only `OK`), which is gate 1;
* once the query as a whole has spent `QueryBudget.schedulable_ms`, every Channel not yet run
  reports `OFF(query_deadline)`, the one ceiling-BEARING reason, so a runtime shortfall cannot
  raise `confidence`;
* a snapshot held past `snapshot_ms` stops the Channels the same way and sets
  `snapshot_expired`, which is gate 1's second disjunct. `Reader` has no `interrupt()`, so the
  WAL-valve deadline is honoured between statements and not inside one.

## PACKING (07:2349)

*"`k = 20` bounds fusion output; `max_blocks = 60` bounds hydration; `max_chars = 24_000` bounds
the text hydration reads, applied per response, in `hits` order, so the drop is deterministic and
the cut is at a block boundary."* So: the first `k` fused hits that some non-structural Channel
ranked, plus the structural-only neighbours in fused order up to `max_blocks` in all (a neighbour
is *"a `Hit` whose `channel_ranks` contains `"structural"` and nothing else"*, 07:2283), hydrated,
then cut at the first block whose text would carry the response past `max_chars`.

## WHAT IS DECIDED HERE BECAUSE NOTHING ELSE DECIDES IT

Each one is a ledger entry; the docstring of the function that does it says which.

* the DSL's eight fields onto `Filters` (`channels.DSL_FIELDS`' docstring hands it here) -- D516;
* `freshness` from `Coverage`, which carries no freshness field -- D517;
* a structural Channel with no `Expand` on the query -- D518;
* a short-circuit's remaining Channels, for which `OffReason` has no member -- D519;
* `Response.cost`, whose type lives where core may not import -- D520.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, TypeVar

from omniweave_core.errors import UsageError
from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust
from omniweave_core.model.spans import SERIALIZER_CAPS, TextSpan
from omniweave_core.operator import SpendVector
from omniweave_core.retrieve.channels import IDENTITY_LADDER, Sanitized, sanitize
from omniweave_core.retrieve.fuse import fuse
from omniweave_core.retrieve.plan import bind_overfetch, plan
from omniweave_core.retrieve.types import (
    CHANNELS,
    ChannelResult,
    ChannelStatus,
    FusedHit,
    OffReason,
    Query,
    QueryBudget,
    QueryPlan,
    RetrievalPolicy,
)
from omniweave_core.retrieve.verdict import Verdict, build_verdict
from omniweave_core.store.types import (
    ChannelInput,
    ChannelSpec,
    Coverage,
    Filters,
    Narrowing,
    Snapshot,
)

if TYPE_CHECKING:
    from omniweave_core.store import Reader
    from omniweave_core.store.reader import HydratedRow

__all__ = ["ANSWER_FORMAT", "Hit", "Response", "byte_exact", "retrieve"]

ANSWER_FORMAT: Final[str] = "md"
"""The serializer format `byte_exact()`'s fourth conjunct is evaluated for. 07:2551's predicate
takes `fmt`, and `retrieve()`'s printed signature has none; the Answer is markdown (10 section
3.5), and all five `SERIALIZER_CAPS` entries are `True` today, so the conjunct cannot yet change a
value -- it is kept so that the day one format is `False`, this is the line that says which."""

_SCORING: Final[frozenset[str]] = frozenset({"identity", "exact", "lexical", "semantic"})
_SEEDING: Final[tuple[str, ...]] = ("identity", "exact")
_NS_PER_MS: Final[int] = 1_000_000
_PAGE_RANGE: Final[re.Pattern[str]] = re.compile(r"^(\d+)(?:-(\d+))?$")
_CLAUSE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<name>[a-z_]+)\s*(?P<op>>=|=)\s*(?P<value>@thresholds\.[a-z_]+|[A-Za-z0-9_.]+)$"
)
_FIX: Final[str] = "ow query --help"
_LINT: Final[str] = "uv run ow route lint --strict"

_Named = TypeVar("_Named", Kind, Layer)
_Ranked = TypeVar("_Ranked", Trust, Quote)


@dataclass(frozen=True, slots=True)
class Hit:
    """07:2250. One returned block: the charter's thirteen fields plus `text`. Fourteen.

    `score`, `channel_contributions` and `channel_ranks` are the `FusedHit`'s; the rest are the
    hydrated row's, except `identity_grade` (the identity Channel's measured tier for this block,
    `""` when identity did not rank it), `span` (the first Channel in run order that had one) and
    `byte_exact` (section 8.2's predicate, evaluated once, in `byte_exact()`).
    """

    block_id: int
    cite: str
    addr: str
    score: float
    text: str | None
    span: TextSpan | None
    channel_contributions: Mapping[str, float]
    channel_ranks: Mapping[str, int]
    identity_grade: str
    segment_id: int | None
    trust: Trust
    quote: Quote
    byte_exact: bool
    restriction_bits: int


@dataclass(frozen=True, slots=True)
class Response:
    """07:2268. Exactly three fields; everything else is on `Hit`, on `Verdict`, or a named read.

    `cost` is `SpendVector | None` where 07:2271 prints `Spend`, and D520 is why: `Spend` is
    `omniweave.route`'s (02 row 35), a distribution core may not import, and `operator.SpendVector`
    is the structural stand-in core already uses for exactly that reason. The query path in this
    build spends no billable unit -- no embedding, no model -- so `None` is what it measured.
    """

    hits: tuple[Hit, ...]
    verdict: Verdict
    cost: SpendVector | None = None


def byte_exact(row: HydratedRow, fmt: str = ANSWER_FORMAT) -> bool:
    """07:2551 / 18:652, SV13: THE predicate, at its one call site in `retrieve()`.

    `quote is VERBATIM and doc.achieved.origin_span == "exact" and "citation" not in
    doc.achieved.forfeits and SERIALIZER_CAPS[fmt]`. It reads `achieved` -- what the driver
    delivered on this document -- off the hydrated row, where 07:2315 says it rides for this.

    **It is false on every block this build can store.** `store/doc.py`'s `_achieved()` concludes
    at most `origin_span = "normalized"`, because `"exact"` needs the conformance re-verification
    `omniweave-conform` owns (03:524). So no hit is labelled exact, which is the safe direction:
    07:2547, *"Reconstructed text is always returnable and never labelled exact"*.
    """
    if row.quote is not Quote.VERBATIM:
        return False
    try:
        achieved = json.loads(row.achieved)
    except json.JSONDecodeError:
        return False
    if not isinstance(achieved, dict) or achieved.get("origin_span") != "exact":
        return False
    forfeits = achieved.get("forfeits", ())
    if isinstance(forfeits, list | tuple) and "citation" in forfeits:
        return False
    return bool(SERIALIZER_CAPS.get(fmt, False))


# ---------------------------------------------------------------------------------------------
# Phase 1: the query text, the refs, and the DSL fields onto Filters
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Material:
    """Phase 1's output: the query as `plan()` sees it, and the Channel input `retrieve()` binds."""

    query: Query
    bound: ChannelInput


def _material(q: Query) -> _Material:
    """Sanitise the text and each ref, merge the DSL fields into `Filters`, and bind nothing yet.

    `Query.refs` are addresses a caller already holds (07:2339). Each is run through the same
    sanitiser the text is, so `§4.2(b)` reaches `exact` and `d7#412` reaches `identity` by one
    path; a ref the sanitiser lifts nothing from is kept as an identity candidate verbatim, which
    is what the ladder's title tiers compare against.
    """
    text = sanitize(q.text)
    refs: list[tuple[str, str]] = list(text.refs)
    idents: list[str] = list(text.idents)
    for ref in q.refs:
        lifted = sanitize(ref)
        refs.extend(lifted.refs)
        idents.extend(lifted.idents)
        if not lifted.refs and not lifted.idents and ref.strip():
            idents.append(ref.strip())
    refs = list(dict.fromkeys(refs))
    idents = list(dict.fromkeys(idents))
    filters = _filters(q.filters, text)
    named = tuple(dict.fromkeys((*q.refs, *idents, *(name for name, _ in refs))))
    query = dataclasses.replace(q, filters=filters, refs=named)
    bound = ChannelInput(
        terms=text.terms,
        refs=tuple(refs),
        idents=tuple(idents),
        expand=q.expand,
        filters=filters,
    )
    return _Material(query=query, bound=bound)


def _filters(base: Filters, text: Sanitized) -> Filters:
    """The DSL's eight fields onto `Filters`, each validated against its enum. D516.

    `channels.DSL_FIELDS`' docstring gives this job to `retrieve()` by name, and 07:1324 gives the
    rule: *"each validated against its enum; an invalid value is a usage error naming the legal
    set, never a silent drop"*. A field the caller ALSO set on `Query.filters` to a different value
    is a usage error rather than a precedence: two statements of one filter in one query is a
    mistake, and choosing between them silently is how one of them stops applying.

    `doc:` has no `Filters` field of its own name and no document says which one it is. It is read
    as `uri_prefix`, the one field a caller can spell as text. `lang:` maps to `Filters.lang`,
    which `narrow()` refuses (the store has no language column), so it parses here and refuses
    there -- `DSL_FIELDS`' own docstring predicts exactly that.
    """
    changes: dict[str, object] = {}
    for name, value in text.fields.items():
        field_name, parsed = _field(name, value)
        current = getattr(base, field_name)
        default = getattr(Filters(), field_name)
        if current not in (default, parsed):
            raise UsageError(
                f"{name}:{value} and Query.filters.{field_name} = {current!r} both set the same "
                f"filter to different values",
                fix=_FIX,
            )
        changes[field_name] = parsed
    return dataclasses.replace(base, **changes) if changes else base


def _pages(value: str) -> range:
    found = _PAGE_RANGE.match(value)
    if found is None:
        raise UsageError(f"page:{value} is not N or N-M", fix=_FIX)
    first = int(found[1])
    last = int(found[2] or found[1])
    if last < first:
        raise UsageError(f"page:{value} ends before it starts", fix=_FIX)
    return range(first, last + 1)


_FIELDS: Final[Mapping[str, tuple[str, Callable[[str, str], object]]]] = MappingProxyType(
    {
        "kind": ("kinds", lambda value, name: frozenset({_member(Kind, value, name)})),
        "page": ("pages", lambda value, _name: _pages(value)),
        "doc": ("uri_prefix", lambda value, _name: value),
        "layer": ("layers", lambda value, name: frozenset({_member(Layer, value, name)})),
        "trust": ("min_trust", lambda value, name: _ordered(Trust, value, name)),
        "quote": ("min_quote", lambda value, name: _ordered(Quote, value, name)),
        "sec": ("sec_path_prefix", lambda value, _name: value),
        "lang": ("lang", lambda value, _name: value),
    }
)
"""`channels.DSL_FIELDS`, in its order, each to its `Filters` field and its parser. A test binds
the key set to `DSL_FIELDS`, so a ninth field cannot reach the sanitiser without a mapping here."""


def _field(name: str, value: str) -> tuple[str, object]:
    """One DSL field to `(Filters field, value)`. Raises `UsageError` naming the legal set."""
    field_name, parse = _FIELDS[name]
    return field_name, parse(value, name)


def _member(enum: type[_Named], value: str, name: str) -> _Named:
    try:
        return enum(value.lower())
    except ValueError:
        legal = ", ".join(member.value for member in enum)
        raise UsageError(f"{name}:{value} is not one of {legal}", fix=_FIX) from None


def _ordered(enum: type[_Ranked], value: str, name: str) -> _Ranked:
    try:
        return enum[value.upper()]
    except KeyError:
        legal = ", ".join(member.name.lower() for member in enum)
        raise UsageError(f"{name}:{value} is not one of {legal}", fix=_FIX) from None


# ---------------------------------------------------------------------------------------------
# Phase 3: the Channels, in plan order, between two deadlines
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Run:
    """What phase 3 accumulates. Mutable, private, and gone when `retrieve()` returns."""

    results: dict[str, ChannelResult]
    spans: dict[int, TextSpan]
    degradations: list[str]
    expired: bool = False


def _off(name: str, reason: OffReason) -> ChannelResult:
    return ChannelResult(name=name, status=ChannelStatus.OFF, reason=reason.value)


def _seeds(run: _Run, spec_names: Sequence[str]) -> tuple[int, ...]:
    """07:1327-1332's ladder: identity and exact, else the scoring Channels before it, else `()`.

    `()` is the last rung, *"from `tmp_narrow` itself"*, which the `Narrowing` already carries --
    `ChannelInput.seeds`' docstring: *"an empty `seeds` means fall through to `tmp_narrow`"*.
    """
    first = [b for name in _SEEDING if name in run.results for b in run.results[name].ranked]
    if first:
        return tuple(dict.fromkeys(first))
    before = [
        block
        for name in spec_names
        if name in run.results and name in _SCORING
        for block in run.results[name].ranked
    ]
    return tuple(dict.fromkeys(before))


def _short_circuit(
    expression: str | None, run: _Run, q: Query, thresholds: Mapping[str, float]
) -> bool:
    """07:1813's first row: the plan's expression, true after a Channel completes.

    The grammar is the one the shipped rules use (07:1733): clauses joined by ` and `, each
    `<channel> >= <number>` -- the best identity tier value that Channel measured -- or
    `mode = <mode>`. `@thresholds.<name>` is substituted from the policy here, because 07:1770
    makes it compile-time and no compiler reaches core (D235). Anything else is refused, as
    `plan.py` refuses a clause form it cannot evaluate.
    """
    if not expression:
        return False
    for clause in expression.split(" and "):
        found = _CLAUSE.match(clause.strip())
        if found is None:
            raise UsageError(
                f"short_circuit clause {clause!r} is not a form retrieve() evaluates", fix=_LINT
            )
        name, op, raw = found["name"], found["op"], found["value"]
        if name == "mode" and op == "=":
            if q.mode != raw:
                return False
            continue
        value = _threshold(raw, thresholds)
        if value is None or op != ">=":
            raise UsageError(f"short_circuit clause {clause!r} names nothing to compare", fix=_LINT)
        result = run.results.get(name)
        if result is None or result.status != ChannelStatus.OK:
            return False
        best = max((IDENTITY_LADDER.get(grade, 0) for grade in result.grades.values()), default=0)
        if best < value:
            return False
    return True


def _threshold(raw: str, thresholds: Mapping[str, float]) -> float | None:
    """A number, or `@thresholds.<name>` looked up in the policy; `None` for a name it lacks."""
    if raw.startswith("@thresholds."):
        return thresholds.get(raw.removeprefix("@thresholds."))
    try:
        return float(raw)
    except ValueError:
        return None


def _channels(
    r: Reader,
    s: Snapshot,
    query_plan: QueryPlan,
    material: _Material,
    budget: QueryBudget,
    *,
    thresholds: Mapping[str, float],
    started_ns: int,
    opened_ns: int,
    monotonic_ns: Callable[[], int],
    n: Narrowing,
) -> _Run:
    """Run the plan's Channels in its order, and name the reason for every one that did not run."""
    run = _Run(results={}, spans={}, degradations=[])
    names = query_plan.channel_names
    stop: OffReason | None = None
    for index, spec in enumerate(query_plan.channels):
        now = monotonic_ns()
        if stop is None and (now - opened_ns) // _NS_PER_MS > budget.snapshot_ms:
            run.expired = True
            stop = OffReason.QUERY_DEADLINE
        if stop is None and (now - started_ns) // _NS_PER_MS >= budget.schedulable_ms:
            stop = OffReason.QUERY_DEADLINE
        if stop is not None:
            run.results[spec.name] = _off(spec.name, stop)
            continue
        run.results[spec.name] = _one(
            r, s, spec, material, run, before=names[:index], n=n, monotonic_ns=monotonic_ns
        )
        if _short_circuit(query_plan.short_circuit, run, material.query, thresholds):
            stop = OffReason.NOT_IN_PLAN
    for name in CHANNELS:
        run.results.setdefault(name, _off(name, OffReason.NOT_IN_PLAN))
    return run


def _one(
    r: Reader,
    s: Snapshot,
    spec: ChannelSpec,
    material: _Material,
    run: _Run,
    *,
    before: Sequence[str],
    n: Narrowing,
    monotonic_ns: Callable[[], int],
) -> ChannelResult:
    """One Channel: the two refusals that are `retrieve()`'s, then the `Reader`, then the timer."""
    if spec.name == "semantic" and material.bound.q_sig is None and _no_backend(r):
        return _off(spec.name, OffReason.VECTORS)
    if spec.name == "structural" and material.bound.expand is None:
        return _off(spec.name, OffReason.NOT_IN_PLAN)
    bind = material.bound
    if spec.name == "structural":
        bind = dataclasses.replace(bind, seeds=_seeds(run, before))
    began = monotonic_ns()
    outcome = r.channel(s, dataclasses.replace(spec, bind=bind), n)
    ran_ms = (monotonic_ns() - began) // _NS_PER_MS
    run.degradations.extend(outcome.degradations)
    for block, span in outcome.spans.items():
        run.spans.setdefault(block, span)
    status = ChannelStatus(outcome.status)
    reason = outcome.reason
    if ran_ms > spec.budget_ms and status in (ChannelStatus.OK, ChannelStatus.EMPTY):
        status, reason = ChannelStatus.UNAVAILABLE, "timeout"
    return ChannelResult(
        name=spec.name,
        status=status,
        ranked=outcome.ranked,
        rank_of=outcome.rank_of,
        spans=outcome.spans,
        grades=outcome.grades,
        weight=spec.weight,
        reason=reason,
        truncated_at_limit=outcome.truncated_at_limit,
        ran_ms=int(ran_ms),
    )


def _no_backend(r: Reader) -> bool:
    """`[retrieval] vectors = "off"` as the store reports it: no backend, so `OFF(vectors)`."""
    return r.capabilities().vec_backend is None


# ---------------------------------------------------------------------------------------------
# Packing and the four facts the Verdict needs that no Channel measured
# ---------------------------------------------------------------------------------------------


def _selected(fused: Sequence[FusedHit], k: int, max_blocks: int) -> list[int]:
    """The first `k` primaries, then structural-only neighbours: fused order, `max_blocks` cap."""
    primaries = 0
    chosen: list[int] = []
    for hit in fused:
        if len(chosen) >= max_blocks:
            break
        neighbour = set(hit.channel_ranks) == {"structural"}
        if not neighbour:
            if primaries >= k:
                continue
            primaries += 1
        chosen.append(hit.block_id)
    return chosen


def _freshness(
    coverage: Coverage,
) -> Literal["fresh", "refreshing", "stale", "unknown", "not_tracked"]:
    """`Verdict.freshness` from `Coverage`, which has no freshness field. D517.

    07:2187 calls it *"`Reader.coverage()`'s freshness roll-up"* and 07:2945 defines it from the
    `unit` roster's `stat_fresh` predicate; `Coverage` carries the roster's three counts and no
    roll-up. The order is the gates' own, most specific first: nothing tracked is `not_tracked`
    (disclosed, never a gate); an unreadable unit is `unknown` (gate 7's *"could not be
    stat()ed"*); a changed source is `stale`; queued work is `refreshing`; otherwise `fresh`.
    """
    if coverage.discovered == 0 and coverage.indexed == 0 and coverage.scope_rows == 0:
        return "not_tracked"
    if coverage.unreadable_units > 0:
        return "unknown"
    if coverage.stale_units > 0:
        return "stale"
    if coverage.pending_work > 0:
        return "refreshing"
    return "fresh"


def _pack(
    fused: Sequence[FusedHit],
    rows: Sequence[HydratedRow],
    run: _Run,
    max_chars: int,
    *,
    hydrate_text: bool,
) -> tuple[tuple[Hit, ...], float]:
    """Hits in fused order, cut at the first block past `max_chars`; and `generated_share`."""
    by_id = {row.block_id: row for row in rows}
    identity = run.results.get("identity")
    grades = identity.grades if identity is not None else {}
    hits: list[Hit] = []
    spent = generated = 0
    for fused_hit in fused:
        row = by_id.get(fused_hit.block_id)
        if row is None:
            continue
        chars = row.chars or 0
        if spent + chars > max_chars:
            break
        spent += chars
        if row.method is Method.ROUNDTRIP:
            generated += chars
        hits.append(
            Hit(
                block_id=row.block_id,
                cite=row.cite,
                addr=row.addr,
                score=fused_hit.score,
                text=row.text if hydrate_text else None,
                span=run.spans.get(row.block_id),
                channel_contributions=fused_hit.channel_contributions,
                channel_ranks=fused_hit.channel_ranks,
                identity_grade=grades.get(row.block_id, ""),
                segment_id=row.segment_id,
                trust=row.trust,
                quote=row.quote,
                byte_exact=byte_exact(row),
                restriction_bits=row.restriction_bits,
            )
        )
    return tuple(hits), (generated / spent if spent else 0.0)


def retrieve(
    r: Reader,
    q: Query,
    pol: RetrievalPolicy,
    *,
    monotonic_ns: Callable[[], int] = time.monotonic_ns,
) -> Response:
    """07:2248. One `Reader`, one `Query`, one policy; one snapshot; one `Response`.

    `monotonic_ns` is keyword-only and not in the printed signature, for the reason
    `sqlite.snapshot()` takes the same parameter: a test spends the budgets without spending the
    wall time. Every other input is the three the plan prints.
    """
    material = _material(q)
    caps = r.capabilities()
    query_plan = plan(material.query, caps, pol)
    budget = material.query.budget or pol.budget or QueryBudget()
    started = monotonic_ns()
    with r.snapshot() as s:
        narrowing = r.narrow(s, material.bound.filters or Filters())
        query_plan = bind_overfetch(query_plan, narrowing, caps)
        run = _channels(
            r,
            s,
            query_plan,
            material,
            budget,
            thresholds=pol.thresholds,
            started_ns=started,
            opened_ns=s.opened_ns,
            monotonic_ns=monotonic_ns,
            n=narrowing,
        )
        results = tuple(run.results[name] for name in CHANNELS)
        fused = fuse(results, k=query_plan.fusion.k, weights=query_plan.fusion.weights)
        ids = _selected(fused, query_plan.pack.k, query_plan.pack.max_blocks)
        rows = r.hydrate(s, ids)
        coverage = r.coverage(s, material.bound.filters or Filters())
        snapshot_gen = s.generation
    with r.snapshot() as after:
        generation_at_pack = after.generation
    hits, generated_share = _pack(
        fused,
        rows,
        run,
        query_plan.pack.max_chars,
        hydrate_text=query_plan.pack.hydrate_text,
    )
    verdict = build_verdict(
        plan=query_plan,
        results=results,
        coverage=coverage,
        narrowing=narrowing,
        caps=caps,
        fused=fused,
        returned=len(hits),
        freshness=_freshness(coverage),
        withheld=MappingProxyType({"rows": 0}),
        snapshot_gen=snapshot_gen,
        generation_at_pack=generation_at_pack,
        snapshot_expired=run.expired,
        requested=frozenset({"structural"}) if q.expand is not None else frozenset(),
        generated_share=generated_share,
        degradations=tuple(dict.fromkeys(run.degradations)),
    )
    return Response(hits=hits, verdict=verdict)
