"""`ow route propose` and `ow route promote`: the human-in-the-loop half of section 8.3.

Section 8.3's human-in-the-loop paragraph runs 05:2986-2996, and 05:2996 ends it: *"`ow route
promote` applies a reviewed diff. Neither writes without a commit."* The two commands share
exactly one artefact -- the diff -- so the thing that renders it (`fit.render_diff()`) and the
thing that reads it back are held together by a round-trip test rather than by two readings of a
format.

## What `bindings()` is for, and why nothing else could supply it

`fit()` takes a `direction` because a `[thresholds]` entry is a bare number: `[thresholds]` declares
`ink_coverage_min = 0.25` and nothing in that block says which side of it escalates. The comparison
lives in the rule, in `when`, as an operator -- 05:1525's `{ "ink.coverage" = { lt =
"@thresholds.ink_coverage_min" } }` -- and `Test.threshold` keeps the reference through
substitution, in `policy.py`'s own words, *"so that check 1 can resolve it and `ow route propose`
can find every rule that reads one threshold"*. `bindings()` is that walk: it is the only
place in the system where a `[thresholds]` name, the evidence key it is compared against and the
direction of the comparison are one record.

A threshold read only by `eq`, `ne`, `in`, `not_in` or `exists` is **unfittable** and says so. A fit
sweeps candidate thresholds along an ordering, and those five have none -- proposing a move to an
equality bound would be proposing a different rule, not a different number.

## The diff is applied by VALUE, not by text, and the shipped file is why

The `[thresholds]` block carries trailing marker comments that name the upstream file and line each
number was lifted from -- `ink_coverage_min = 0.25              # marker layout_coverage_threshold
(line.py:35-39)`. A patch applied by replacing the `-` line with the `+` line would delete that
provenance on every threshold it touched, and the numbers' provenance is the reason the block is
reviewable at all. It would also simply fail to apply: `render_diff()` formats with `%g`, so the
shipped `garble_escalate = 0.50` renders as `-garble_escalate = 0.5` and matches no line in the
file.

So `apply_patch()` reads the diff as an intent -- `name: old -> new` -- locates the key, checks that
the file's current value **equals the diff's `-` value**, and rewrites the value token in place.
That context check is what makes "a reviewed diff" mean the diff that was reviewed: a file edited
between the propose and the promote fails here rather than silently taking a number nobody compared
against the current one.

## `route.promote` is HUMAN_ONLY, and this module is where that begins

10-interfaces.md:143 puts `route.promote` in `HUMAN_ONLY`, which by 10:188's rule 4 means
`mcp_name is None` and `listed_in == frozenset()` -- the cost of the wrong answer being, at
10:149, *"an agent uninstalls omniweave, or promotes a routing policy it wrote"*. The registry
that enforces that is P7's. What this module can do until then is name the Action, so the row P7
generates has a constant to point at rather than a string retyped from a table.

Specified in 05-ingest-and-routing.md section 8.3; scheduled by 16-roadmap.md:607.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.card import MIN_SLICE_N
from omniweave_core.errors import RouteError

from omniweave.route.fit import DIRECTIONS, Proposal, fit
from omniweave.route.ledger import UNKNOWN, Log
from omniweave.route.policy import ORDERED_OPS

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

    from omniweave_core.drivers.card import MeasuredOn

    from omniweave.route.ledger import Rollup
    from omniweave.route.policy import RoutePolicy
    from omniweave.route.rung import Rung

__all__ = [
    "DIRECTION_BY_OP",
    "HUMAN_ONLY_ACTION",
    "Binding",
    "Change",
    "Outcome",
    "Patch",
    "apply_patch",
    "bindings",
    "parse_diff",
    "propose",
    "unfittable",
]

DIRECTION_BY_OP: Final[Mapping[str, str]] = {
    "lt": DIRECTIONS[1],
    "lte": DIRECTIONS[1],
    "gt": DIRECTIONS[0],
    "gte": DIRECTIONS[0],
}
"""`ORDERED_OPS`' four, mapped onto `fit.DIRECTIONS`. `s < t` and `s <= t` escalate the LOW end, so
`"below"`; `s > t` and `s >= t` escalate the high end, so `"above"`. The five remaining `OPS` are
absent rather than defaulted -- see `unfittable()`."""

HUMAN_ONLY_ACTION: Final[str] = "route.promote"
"""10-interfaces.md:143's member. Named here so P7's generated registry points at a constant."""

_FIX = "uv run ow route propose"
_VALUE_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<lead>\s*)(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<mid>\s*=\s*)"
    r"(?P<value>[-+0-9][^#\s]*)(?P<tail>.*)$"
)
_EPSILON: Final[float] = 1e-12


# --------------------------------------------------------------------------------------------
# 1. Which threshold is compared against which signal, and which way round.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Binding:
    """One `(threshold, signal, operator)` site: a rule reading a `[thresholds]` entry.

    One threshold may have several bindings -- `garble_escalate` is read by more than one rule --
    and they are kept separate rather than deduplicated, because two rules reading one number at
    two rungs are two populations and a fit over their union would be a fit over neither.
    """

    name: str
    signal: str
    op: str
    rule_id: str
    rung: Rung
    lane: str
    current: float

    @property
    def direction(self) -> str:
        """`"above"` or `"below"`. A `KeyError` here would be an unordered op reaching `Binding`,
        which `bindings()` filters, so the lookup is deliberately not defaulted."""
        return DIRECTION_BY_OP[self.op]

    @property
    def label(self) -> str:
        return f"{self.name}@{self.rule_id}"

    def render(self) -> str:
        return (
            f"{self.name} = {self.current:g}  <- {self.signal} {self.op} "
            f"({self.direction} escalates)  {self.rule_id} at {self.rung.name}/{self.lane}"
        )


def bindings(policy: RoutePolicy) -> tuple[Binding, ...]:
    """Every fittable `(threshold, signal, op)` site in the compiled policy, in rule order.

    Rule order and not sorted: the policy is first-match, so the order a reader sees in the file is
    the order the rules are consulted in, and a report that reordered them would be a report about
    a different document.
    """
    found: list[Binding] = []
    for rule in policy.rules:
        for clause in rule.when.clauses:
            for key, test in clause.tests:
                if not test.threshold or test.op not in ORDERED_OPS:
                    continue
                found.append(
                    Binding(
                        name=test.threshold,
                        signal=key,
                        op=test.op,
                        rule_id=rule.id,
                        rung=rule.rung,
                        lane=rule.lane,
                        current=float(policy.thresholds[test.threshold]),
                    )
                )
    return tuple(found)


def unfittable(policy: RoutePolicy) -> tuple[tuple[str, str], ...]:
    """The thresholds a fit cannot move, each with the reason. Sorted, because it is a footer.

    Two reasons, and they are different failures. A threshold **read by no rule** is declared and
    dead -- `ow route lint` check 1 already resolves the other direction (a reference with no
    declaration), and this is the unreferenced half, which is not an error because a profile layer
    may legitimately declare a number the base policy has not started reading yet. A threshold read
    only by an **unordered operator** is live and still unfittable: `eq`, `ne`, `in`, `not_in` and
    `exists` give a sweep nothing to sweep along.
    """
    fittable = {binding.name for binding in bindings(policy)}
    referenced = set(policy.threshold_keys())
    reasons: dict[str, str] = {}
    for name in policy.thresholds:
        if name in fittable:
            continue
        if name not in referenced:
            reasons[name] = "declared and read by no rule"
        else:
            reasons[name] = "read only by an operator with no ordering (eq/ne/in/not_in/exists)"
    return tuple(sorted(reasons.items()))


# --------------------------------------------------------------------------------------------
# 2. The pass: one binding against one slice.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Outcome:
    """One `(binding, slice)` pass. A `Proposal`, or the reason there is none. Never neither.

    Every refusal is a `refusal` string rather than an omitted row, because a propose run over a
    corpus that produced three proposals out of two hundred passes should read as three proposals
    out of two hundred passes -- 05:2995's *"no proposal at all rather than a proposal with no
    evidence"* is a refusal to publish a number, not a refusal to say that a slice was looked at.
    """

    binding: Binding
    slice_key: str
    state: str
    log: Log
    proposal: Proposal | None = None
    refusal: str = ""

    def render(self) -> str:
        head = f"{self.binding.label:<44} {self.slice_key:<28} {self.state:<9}"
        if self.proposal is not None:
            return f"{head} {self.proposal.render()}"
        return f"{head} no proposal: {self.refusal}  [{self.log.render()}]"


def propose(
    policy: RoutePolicy,
    slices: Sequence[Rollup],
    *,
    observe: Callable[[str, str], Log],
    measured_on: MeasuredOn,
    divergence_micros: float,
    min_n: int = MIN_SLICE_N,
) -> tuple[Outcome, ...]:
    """Fit every fittable threshold against every slice the scoreboard names. One pass each.

    `slices` comes from `route_scoreboard`, so `state` is the view's own column and this function
    never recomputes it (see `ledger`'s module docstring on INV-23). `UNKNOWN` short-circuits
    BEFORE `observe` is called: 05:2995 refuses the proposal, and reading a decision log to build
    observations nobody may publish would be work done to reach a conclusion already reached.

    `observe` is a callable rather than a connection, so this function is pure over its inputs and
    the store-facing query stays in `ledger.observations()`. The two arguments are the two things
    an observation is selected by -- `(slice_key, signal)`.

    Slices are deduplicated on `slice_key`. `route_scoreboard` rolls up per `(slice_key, rule_id,
    driver)`, so one slice appears once per rule that decided in it; a fit is per slice, and
    running one per rollup row would fit the same population several times and emit the same
    proposal several times. Where the rollup rows of one slice disagree on `state`, the WORST is
    taken -- `UNKNOWN` beats `REGRESSED` beats `OK` -- because a slice with any rollup row still
    short of `min_audit_n` has a population part of which cannot speak.
    """
    states = _worst_state(slices)
    outcomes: list[Outcome] = []
    for binding in bindings(policy):
        for slice_key in sorted(states):
            outcomes.append(
                _pass(
                    binding,
                    slice_key,
                    states[slice_key],
                    observe=observe,
                    measured_on=measured_on,
                    divergence_micros=divergence_micros,
                    min_n=min_n,
                )
            )
    return tuple(outcomes)


def _worst_state(slices: Iterable[Rollup]) -> dict[str, str]:
    """`{slice_key: state}` over the rollup, worst first. `STATES` is already worst-first."""
    from omniweave.route.ledger import STATES  # noqa: PLC0415 -- one constant, no cycle

    worst: dict[str, str] = {}
    for row in slices:
        rank = STATES.index(row.state) if row.state in STATES else 0
        if row.slice_key not in worst or rank < STATES.index(worst[row.slice_key]):
            worst[row.slice_key] = row.state
    return worst


def _pass(
    binding: Binding,
    slice_key: str,
    state: str,
    *,
    observe: Callable[[str, str], Log],
    measured_on: MeasuredOn,
    divergence_micros: float,
    min_n: int,
) -> Outcome:
    if state == UNKNOWN:
        return Outcome(
            binding=binding,
            slice_key=slice_key,
            state=state,
            log=Log(),
            refusal="the slice is UNKNOWN, which yields no proposal at all (05:2995)",
        )
    log = observe(slice_key, binding.signal)
    proposal = fit(
        log.observations,
        name=binding.name,
        current=binding.current,
        slice_key=slice_key,
        measured_on=measured_on,
        divergence_micros=divergence_micros,
        direction=binding.direction,  # type: ignore[arg-type]
        state=state,
        min_n=min_n,
    )
    if proposal is not None:
        return Outcome(
            binding=binding, slice_key=slice_key, state=state, log=log, proposal=proposal
        )
    return Outcome(
        binding=binding, slice_key=slice_key, state=state, log=log, refusal=_why(log, min_n)
    )


def _why(log: Log, min_n: int) -> str:
    """Which of `fit()`'s three remaining refusals fired. Reconstructed, and it has to be.

    `fit()` returns `None` and not a reason, which is right for a fitter -- a `Proposal | None` is
    the type a caller can use without unpacking an enum -- and wrong for a report, so the three
    cases are separated here from the log the fitter was handed. They are mutually exclusive and
    exhaustive given that `state != UNKNOWN` was already checked, so nothing is guessed.
    """
    if log.n < min_n:
        return f"n = {log.n} is below min_n = {min_n}"
    if len({one.signal for one in log.observations}) < 2:  # noqa: PLR2004 -- "varies at all"
        return "the signal takes one distinct value, so no threshold separates the population"
    return "the current value IS the fit; there is nothing to diff"


# --------------------------------------------------------------------------------------------
# 3. `ow route promote`: the diff, read back and applied.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Change:
    """One `-`/`+` pair from the diff: a threshold, the value it had, the value it should have."""

    name: str
    old: float
    new: float

    def render(self) -> str:
        return f"{self.name}: {self.old:g} -> {self.new:g}"


@dataclass(frozen=True, slots=True)
class Patch:
    """A parsed `render_diff()` output. `path` is the file the diff names; comments are carried.

    The comment lines are kept rather than dropped because they are the INV-19 provenance --
    `(n, ci95, method, slice_key, corpus_digest, MeasuredOn, witness)` for every number -- and a
    promote that printed what it applied without them would print a number with no evidence, which
    is the shape 05:2995 refuses in the other direction.
    """

    path: str
    changes: tuple[Change, ...] = ()
    comments: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(change.name for change in self.changes)


def parse_diff(lines: Iterable[str]) -> Patch:
    """`render_diff()`'s output, read back. Refuses anything it did not produce.

    A `+` with no `-`, two `-` lines for one `+`, a `-` whose value is not a number, or a `+` whose
    name differs from its `-`: each is a refusal rather than a best effort. This parser's whole job
    is to be the thing that cannot silently misread the artefact a human approved, so every shape
    it does not recognise is one it declines to interpret.
    """
    path = ""
    changes: list[Change] = []
    comments: list[str] = []
    pending: tuple[str, float] | None = None
    for line in lines:
        text = line.rstrip("\n")
        if text.startswith("--- a/"):
            path = text[len("--- a/") :]
            continue
        if text.startswith("+++ b/") or text.startswith(" "):
            continue
        if text.startswith("#"):
            comments.append(text.lstrip("# ").rstrip())
            continue
        if text.startswith("-"):
            if pending is not None:
                raise RouteError(
                    f"two removed lines for one threshold: {pending[0]!r} then {text!r}", fix=_FIX
                )
            pending = _pair(text[1:], side="-")
            continue
        if text.startswith("+"):
            if pending is None:
                raise RouteError(f"an added line with no removed line: {text!r}", fix=_FIX)
            name, new = _pair(text[1:], side="+")
            if name != pending[0]:
                raise RouteError(
                    f"the diff removes {pending[0]!r} and adds {name!r}; a threshold move is one "
                    "name, and two names is a rename this command does not perform",
                    fix=_FIX,
                )
            changes.append(Change(name=name, old=pending[1], new=new))
            pending = None
            continue
        if text.strip():
            raise RouteError(f"not a line `ow route propose` emits: {text!r}", fix=_FIX)
    if pending is not None:
        raise RouteError(f"a removed line with no added line: {pending[0]!r}", fix=_FIX)
    if not path:
        raise RouteError("the diff names no file; its first line is `--- a/<path>`", fix=_FIX)
    return Patch(path=path, changes=tuple(changes), comments=tuple(comments))


def _pair(body: str, *, side: str) -> tuple[str, float]:
    name, _, raw = body.partition("=")
    try:
        return name.strip(), float(raw.strip())
    except ValueError as exc:
        raise RouteError(
            f"the {side} line {body.strip()!r} is not `<name> = <number>`", fix=_FIX
        ) from exc


def apply_patch(text: str, patch: Patch) -> str:
    """The file's text with each change applied to its value token. Line endings preserved.

    Three refusals, and each is the check that makes "a REVIEWED diff" mean something:

    1. **The name is not in the file.** `ow route propose` proposes, it does not introduce
       (`render_diff()` says so from the other side), so a `+` for a key the file does not declare
       is a diff against a different file.
    2. **The file's value is not the diff's `-` value.** Somebody edited the threshold between the
       propose and the promote, and applying anyway would install a number nobody compared against
       the one now there.
    3. **The name appears twice.** A `[thresholds]` key declared twice is a TOML error this command
       will not silently pick a side in.

    Everything after the value -- the alignment and the trailing marker comment naming the upstream
    file and line the number came from -- is preserved byte for byte. That is the substantive
    difference from `git apply`, and it is the reason this is a rewriter rather than a patcher.
    """
    wanted = {change.name: change for change in patch.changes}
    if not wanted:
        return text
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        match = _VALUE_RE.match(line.rstrip("\r\n"))
        change = wanted.get(match.group("name")) if match else None
        if match is None or change is None:
            out.append(line)
            continue
        if change.name in seen:
            raise RouteError(
                f"{change.name!r} is declared twice in {patch.path}; a promote will not choose "
                "which declaration is the live one",
                fix=_FIX,
            )
        seen.add(change.name)
        current = _number(match.group("value"), change.name, patch.path)
        if abs(current - change.old) > _EPSILON:
            raise RouteError(
                f"{patch.path} has {change.name} = {current:g} and the diff was reviewed against "
                f"{change.old:g}; the file moved between the propose and the promote",
                fix=_FIX,
            )
        ending = line[len(line.rstrip("\r\n")) :]
        body = (
            f"{match.group('lead')}{match.group('name')}{match.group('mid')}"
            f"{_same_shape(match.group('value'), change.new)}{match.group('tail')}"
        )
        out.append(body + ending)
    missing = tuple(sorted(set(wanted) - seen))
    if missing:
        raise RouteError(
            f"{patch.path} declares no {', '.join(missing)}; `ow route propose` proposes a move "
            "and never introduces a threshold",
            fix=_FIX,
        )
    return "".join(out)


def _number(raw: str, name: str, path: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise RouteError(
            f"{path} has {name} = {raw!r}, which is not a number; every threshold is a number",
            fix=_FIX,
        ) from exc


def _same_shape(current: str, value: float) -> str:
    """The new value, at the decimal places the file already used. `0.25` -> `0.10`, not `0.1`.

    A `[thresholds]` block written by hand is aligned and consistently formatted, and a promote
    that rewrote `0.25` as `0.1` would make the one line it touched the only line in the block
    with a different shape -- a diff a reviewer reads as a formatting change on top of a value
    change. An integer stays an integer for the same reason: `blank_page_tiles = 4` is a count.
    """
    places = len(current.partition(".")[2]) if "." in current else 0
    if places == 0 and float(value).is_integer():
        return f"{int(value)}"
    text = f"{value:.{max(places, 1)}f}"
    return text if float(text) == value else f"{value!r}"
