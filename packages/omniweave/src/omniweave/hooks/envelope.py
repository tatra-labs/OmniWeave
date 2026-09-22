"""What all six handlers share: the channel, the caps, the key, the kill switches and the deadline.

A hook is the one component in this framework whose **every failure path is a silent exit 0**
(10:1842, 02:255 row 34). That single sentence decides the shape of this module twice over.

## A COMPONENT WHOSE FAILURES LOOK LIKE SUCCESS HAS TO BE OBSERVABLE FROM INSIDE

From outside a hook process there is nothing to see: exit 0 and an empty stdout is what a working
silent tier produces and also what a crash, a deadline breach, a missing corpus and a kill switch
produce. 16:718 says so in the estimate itself -- *"a silent exit-0 deadline breach turns the
adoption lever off with no symptom, so half of this item is the instrumentation that makes the
breach visible"*.

So `run()` returns an `Outcome` rather than calling `sys.exit`. The process always exits 0 and the
caller is a four-line `__main__`; everything a test or a counter needs -- which tier fired, how long
it took, whether the deadline was missed, which exception class ended it -- is on the value. That is
the whole reason this module exists as something other than six independent scripts.

**`Outcome.exit_code()` is a method that returns a constant and takes no argument.** Not a field
with a default, because a field can be passed `1` by a caller having a bad day and the rule 10:1842
states is not a default.

## THE OUTPUT CHANNEL, WHICH 10:1859 CALLS THE MOST IMPORTANT UNDOCUMENTED FACT IN THIS LAYER

> a hook that exits 0 reaches the model **only** through
> `hookSpecificOutput.additionalContext`. Both stderr and a top-level `systemMessage` surface to
> the *user* instead, so steering text written to either is silently inert.

`emission()` is therefore the only way this package produces stdout, it writes exactly that key,
and it **refuses an event that has no channel**: `PreCompact`, `PostToolUse` and `SessionEnd`
return `""` whatever they are handed. 10:1929 records what the alternative costs -- jcodemunch
shipped a `PreCompact` handler that emitted its briefing into a field hosts discard, for a whole
release line.

## THE DEADLINE IS MEASURED AND CHECKED, NEVER ENFORCED

A handler cannot be preempted from inside its own process without a thread or a signal, and both
cost more than the 400 ms they would police. What a self-deadline can buy is different and is
enough: a late answer is **not injected**. `run()` reads the clock after the handler returns and
drops the emission if the budget is gone, which is the decision `-noop-deadline` records.

**And the budget does not fit the gate it is measured by.** 10:1844 sets G26 at *"p95 <= 250 ms warm
and <= 1 s cold"* and 10:1842 sets the self-deadline at 400 ms. Every cold invocation between 400 ms
and 1 s is inside the gate and past the deadline -- so on the run that matters most, a hook that G26
calls healthy emits nothing. D394.

## WHAT IT IMPORTS AT RUN TIME: NOTHING

Four stdlib modules and no first-party import at all. G17 exists so `import omniweave_core` stays
cheap and this module does not even pay that -- the `Clock` it measures with arrives as an argument,
the environment arrives as an argument, and a test asserts the import list over the AST. A cold
start is the budget G26 doubles for, and the cheapest import is the one not written.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from omniweave_core.clock import Clock

__all__ = [
    "CHANNEL",
    "COUNTER_PREFIX",
    "DECISION_CHANNEL",
    "DECISION_REASON",
    "DENY",
    "EVENTS",
    "EXIT_OK",
    "KILL_SWITCH",
    "KILL_VALUE",
    "SELF_DEADLINE_MS",
    "Advice",
    "EventSpec",
    "Outcome",
    "counter",
    "emission",
    "run",
    "session_key",
    "silent_because",
    "unmeasured",
]


EXIT_OK: Final[int] = 0
"""The only exit code a hook has. 10:1842: *"every failure path is a silent exit 0."*

Exit 2 does reach the model through stderr and it also **blocks the call**, which 10:1862 refuses
for an advisory nudge. There is no third option: a hook that exits anything else is a hook whose
host shows the user an error for something the user did not ask for.
"""

SELF_DEADLINE_MS: Final[int] = 400
"""10:1842's budget, and D394 is the fact that it is smaller than the gate that measures it."""

KILL_SWITCH: Final[str] = "OMNIWEAVE_HOOK"
KILL_VALUE: Final[str] = "0"
"""10:1996's kill switch, and the value that trips it.

`OMNIWEAVE_ENFORCE` and `OMNIWEAVE_HOOK_TTL` are both in `config.NON_KEY_ENV_VARS` and this one is
not, although all three are read only by this package and none of them twins a declared key. D395.
"""

CHANNEL: Final[str] = "additionalContext"
DECISION_CHANNEL: Final[str] = "permissionDecision"
DECISION_REASON: Final[str] = "permissionDecisionReason"
DENY: Final[str] = "deny"
"""The three keys inside `hookSpecificOutput`, and the one decision value this framework emits.

There is no `allow`: 10:2043 makes the default `advisory` and an unknown `OMNIWEAVE_ENFORCE` fall
back to it, so the framework either says nothing or says `deny`, and a hook that emitted `allow`
would be spending the channel to permit what was already permitted.
"""

COUNTER_PREFIX: Final[str] = "ow-hook"
"""10:1990's prefix. `ow-hook-ups-high-cite` is the worked example and the slug is the middle
part."""


@dataclass(frozen=True, slots=True)
class EventSpec:
    """One row of 10:1849's handler table: what fires it, what it may say, and how much.

    `cap` of `0` means **no model-facing channel at all**, which is three of the six. It is spelled
    as a cap rather than as a separate boolean because the two would be one fact in two fields, and
    the one that decides whether `emission()` speaks is the same one that decides how much.
    """

    name: str
    slug: str
    matcher: str
    cap: int

    def speaks(self) -> bool:
        """Whether this event reaches the model at all."""
        return self.cap > 0


EVENTS: Final[Mapping[str, EventSpec]] = MappingProxyType(
    {
        spec.name: spec
        for spec in (
            EventSpec("SessionStart", "start", "compact|resume|fork", 4_000),
            EventSpec("PreCompact", "precompact", "", 0),
            EventSpec("UserPromptSubmit", "ups", "", 8_000),
            EventSpec("PreToolUse", "pretool", "Read|Grep|Glob", 1_200),
            EventSpec("PostToolUse", "posttool", "Edit|Write", 0),
            EventSpec("SessionEnd", "end", "", 0),
        )
    }
)
"""10:1849's six rows, closed. An event outside this table is a host sending something this build
does not handle, which is an exit 0 and a counter and never an error.

**The slugs are this module's and only one of the six is the plan's.** 10:1990 names seven counters
and all seven are `ups`; the other five events have none. The obvious rule -- initials -- collides
on `PreToolUse` and `PostToolUse`, so it is not the rule, and D396 is the entry.
"""

_SILENT_KILL: Final[str] = "noop-killed"
_SILENT_TTY: Final[str] = "noop-tty"
_SILENT_EVENT: Final[str] = "noop-event"
_SILENT_DEADLINE: Final[str] = "noop-deadline"
_SILENT_FAILURE: Final[str] = "noop-failure"


@dataclass(frozen=True, slots=True)
class Advice:
    """What a handler produced: text to inject, a decision, and the tier that produced them.

    `counter` is a **tier name** and never prompt text -- 10:1990 states the rule and this is where
    it is kept, because a handler returning a message here is the one way user input could reach a
    counter file.
    """

    text: str = ""
    deny: bool = False
    counter: str = ""


@dataclass(frozen=True, slots=True)
class Outcome:
    """Everything one hook invocation did. The process exits 0; this is what it knows.

    `failed` is an exception **class name** and never `str(exc)`: a message carries paths, queries
    and occasionally the prompt, and 10:1990's rule is that a counter records that something
    happened and never what the user typed.
    """

    stdout: str = ""
    counters: tuple[str, ...] = ()
    elapsed_ms: int = 0
    breached: bool = False
    failed: str = ""

    def exit_code(self) -> int:
        """`EXIT_OK`, always, and it takes no argument that could make it otherwise."""
        return EXIT_OK

    def spoke(self) -> bool:
        """Whether anything reached the model."""
        return bool(self.stdout)


def session_key(payload: Mapping[str, Any]) -> str:
    """10:1899's derivation, verbatim. `""` means no session identity, which means dedup is off.

    Hashing is not cosmetic and 10:1907 says why in two clauses: *"a transcript path is not a safe
    filename on any platform, and it embeds the user's directory layout in a file the whole
    deployment can read."* `surrogatepass` is the plan's error handler and it is load-bearing on
    Windows, where a path can carry unpaired surrogates that `strict` would raise on -- and a raise
    here would be a hook failing on exactly the deployments least able to report it.
    """
    raw = str(payload.get("session_id") or payload.get("transcript_path") or "")
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def silent_because(env: Mapping[str, str], *, tty: bool) -> str:
    """The counter suffix for a hook that must not run at all, or `""`. 10:1996.

    Two kill switches and they are not the same kind of thing. `OMNIWEAVE_HOOK=0` is an operator
    turning the feature off; a TTY on stdin means a human is running `ow hook` by hand, where a
    handler would block on a read that never completes. Both exit 0 with no output and both are
    counted, because a deployment whose hooks are all silent should be able to find out why.
    """
    if env.get(KILL_SWITCH, "") == KILL_VALUE:
        return _SILENT_KILL
    return _SILENT_TTY if tty else ""


def counter(slug: str, tier: str) -> str:
    """`ow-hook-<slug>-<tier>`. 10:1990's grammar, and the only string this package records."""
    return f"{COUNTER_PREFIX}-{slug}-{tier}"


def emission(event: str, advice: Advice) -> str:
    """The stdout a host reads on exit 0, or `""`. The only place this package writes the channel.

    Three properties, each of which is a defect somewhere else if it is missing:

    1. **An event with no channel emits nothing**, whatever it was handed. `PreCompact`,
       `PostToolUse` and `SessionEnd` have `cap = 0`, and 10:1929 records a shipped handler that
       wrote a briefing into a `PreCompact` `systemMessage` hosts discard.
    2. **The text is capped at the event's own number**, and the cap is on the field rather than on
       the payload: 10:1970 charges the `<ow:untrusted>` wrapper *"against the same field"*, so a
       caller that wrapped first and capped after would ship a torn frame. Truncation is a slice
       and not an ellipsis, because the field is read by a model and not by a person.
    3. **A deny carries its reason in the decision channel**, not in `additionalContext`. 10:2049
       requires the decision be emitted *"with exit code 0, so the harness reads the decision rather
       than a crash"*.
    """
    spec = EVENTS.get(event)
    if spec is None or not spec.speaks():
        return ""
    body: dict[str, Any] = {"hookEventName": event}
    if advice.deny:
        body[DECISION_CHANNEL] = DENY
        body[DECISION_REASON] = advice.text[: spec.cap]
    elif advice.text:
        body[CHANNEL] = advice.text[: spec.cap]
    else:
        return ""
    return json.dumps({"hookSpecificOutput": body}, ensure_ascii=False, allow_nan=False)


def run(
    event: str,
    payload: Mapping[str, Any],
    handler: Callable[[Mapping[str, Any]], Advice],
    *,
    clock: Clock,
    env: Mapping[str, str],
    tty: bool = False,
    deadline_ms: int = SELF_DEADLINE_MS,
) -> Outcome:
    """Run one handler under the envelope. Never raises, never exits, never blocks.

    The order is the one the budget dictates: the two kill switches and the event lookup are three
    dictionary reads and happen before the clock matters, the handler is the only expensive thing,
    and the deadline is read **after** it because that is the only point at which the number is
    known. A breach drops the emission and keeps the counter, which is 10:1842's silent exit 0 and
    16:718's visible breach at the same time -- the process says nothing and the `Outcome` says
    everything.

    `except Exception` and not `except BaseException`: a `KeyboardInterrupt` or a `SystemExit` is
    the host taking the process away, and swallowing those to report an `Outcome` nobody will read
    would be this module deciding it outranks its caller.
    """
    started = clock.monotonic_ns()
    spec = EVENTS.get(event)
    if spec is None:
        return Outcome(counters=(counter("unknown", _SILENT_EVENT),))
    reason = silent_because(env, tty=tty)
    if reason:
        return Outcome(counters=(counter(spec.slug, reason),))

    try:
        advice = handler(payload)
    except Exception as exc:  # 10:1842: EVERY failure path is a silent exit 0.
        return Outcome(
            counters=(counter(spec.slug, _SILENT_FAILURE),),
            elapsed_ms=_elapsed_ms(started, clock),
            failed=type(exc).__name__,
        )

    elapsed = _elapsed_ms(started, clock)
    tier = advice.counter or _SILENT_EVENT
    if elapsed > deadline_ms:
        return Outcome(
            counters=(counter(spec.slug, _SILENT_DEADLINE),),
            elapsed_ms=elapsed,
            breached=True,
        )
    return Outcome(
        stdout=emission(event, advice),
        counters=(counter(spec.slug, tier),),
        elapsed_ms=elapsed,
    )


def unmeasured() -> tuple[str, ...]:
    """What the instrumentation owes and this envelope cannot settle on its own.

    `catalog.unservable()`, `stdio.uninstructable()` and `http.unroutable()` name what another
    distribution holds; this names what the plan has not decided. Both kinds are reported rather
    than raised, for the same reason: the code runs correctly under a reading, and the reading is
    not the code's to fix.
    """
    return (
        f"the self-deadline is {SELF_DEADLINE_MS} ms and G26's cold budget is 1,000 ms, so a cold "
        f"invocation inside the gate can be outside the deadline (D394)",
        "counters are 10:1992's single counters.json, read-modify-written, described as having "
        "the journal's append discipline -- which a read-modify-write of one object cannot have "
        "when 10:2060 guarantees N simultaneous hook processes (D397)",
        "five of the six events have no counter names in the plan, and the one worked slug does "
        "not generalise: PreToolUse and PostToolUse share their initials (D396)",
    )


def _elapsed_ms(started: int, clock: Clock) -> int:
    """Milliseconds since `started`, from the monotonic reading and never the wall clock.

    Rounded up, so a handler that took 400.4 ms is reported as having taken 401 and a deadline
    comparison cannot be won by a rounding rule. `clock.py`'s own docstring fixes the source:
    *"`monotonic_ns()` is the only source for a duration."*
    """
    return -(-(clock.monotonic_ns() - started) // 1_000_000)
