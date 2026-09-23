"""`PreToolUse`: five gates before a word, four more before a refusal, and text written as advice.

This is the only handler that can **stop** something, and 10:2011 is the whole of its caution:

> All five must hold before **any** nudge, and all five before **any** deny.

The five are a conjunction and they are ordered by what they cost, not by what they rule out: four
are decidable from the payload and the filesystem, and the fifth is a store read on a 400 ms budget.

## THE FIFTH GATE IS THE EXPENSIVE ONE AND ITS FAILURE MODE IS FIXED

10:2028:

> Gate 5 is a store read on the hook's 400 ms budget, so it is **one indexed lookup on the canonical
> uri and nothing else** -- no coverage scan, no card read, and **any failure yields "not indexed"
> so the hook allows rather than blocks.** jcodemunch's rule is the precedent: *"any failure yields
> [] so the hook silently allows the search rather than ever blocking it on a store hiccup."*

So `Lookup` is injected like `prompt.Probes` and for the same measured reason (D410), and a lookup
that raises is a lookup that said "not indexed". A hook that blocked a `Read` because SQLite was
busy would be the worst failure this framework can have: it would make the agent's own tools
unreliable in order to advertise ours.

## ADVISORY TEXT IS WRITTEN AS ADVICE, AND THAT IS A RULE ABOUT TONE

10:2032:

> **No `MANDATORY`, no all-caps imperatives, no warning glyph**, while the mode is `allow` -- text
> that opens with an imperative and then permits the action trains the agent to discount the next
> one.

Both strings come from `_ALTERNATIVES`, one constant, because 10:2034 asks for exactly that: *"two
shipped strings, from one constant so a deny and a nudge always name the same alternatives."* A
nudge that offered different tools from the deny would be two policies wearing one name.

## THE MODE THAT DENIES IS NOT NAMED IN THIS SECTION

Section 8.5 describes the strict deny in detail, names `advisory` as the default and
`OMNIWEAVE_ENFORCE=off` as the disable, and **never says which value turns the deny on**. The
vocabulary `off | advisory | steer` appears once in the whole plan, in 18-api-sketch.md section 4,
and `steer` is separately an `ow install --hooks` choice (10:1427) -- one word on two axes. D417.

## THE FOUR DENY GUARDS ARE FOUR DIFFERENT KINDS OF THING

10:2020 requires all four of graphify's guards before a refusal: once per session (an `O_EXCL`
claim), a stand-down for `OMNIWEAVE_HOOK_TTL` seconds after a real query, a softening to a nudge
when the corpus is stale, and the environment kill switch. Only the first is this module's to
perform; the second needs a fact the *server* writes, the third comes with the lookup, and the
fourth is an environment read. Three of the four therefore arrive as arguments, which is what makes
`decide()` a pure function and every row of the table a test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from omniweave.hooks.envelope import Advice
from omniweave.hooks.session import claim

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

__all__ = [
    "CLAIM_SUFFIX",
    "DEFAULT_TTL_S",
    "ENFORCE",
    "ENFORCE_ADVISORY",
    "ENFORCE_OFF",
    "ENFORCE_STEER",
    "HOOK_TTL",
    "MIN_SIZE_BYTES",
    "OPAQUE_DOC_EXTS",
    "Indexed",
    "Lookup",
    "Target",
    "advisory_text",
    "decide",
    "deny_text",
    "enforce_mode",
    "failing_gate",
    "handler",
    "run_pretool",
    "ttl_seconds",
    "unguarded",
]

# ---------------------------------------------------------------------------------------------
# The five gates. 10:2011-2018.
# ---------------------------------------------------------------------------------------------

OPAQUE_DOC_EXTS: Final[frozenset[str]] = frozenset(
    {"pdf", "docx", "pptx", "xlsx", "xls", "doc", "ppt", "epub", "rtf", "odt", "msg", "tif"}
)
"""10:2014's set, verbatim and in its own spelling -- `tif` and not `tiff`.

**What is absent is the deliberate part.** 10:2015: *"deliberately not `md`/`txt`/`html`/`csv`: the
agent can genuinely read those and denying is wrong."* A gate that fired on Markdown would be
telling an agent it cannot read a file it can read perfectly, which is the fastest way to have every
subsequent nudge ignored.
"""

MIN_SIZE_BYTES: Final[int] = 4_096
"""10:2016's gate 3. A document smaller than this is cheaper to read than to route."""

ENFORCE: Final[str] = "OMNIWEAVE_ENFORCE"
ENFORCE_OFF: Final[str] = "off"
ENFORCE_ADVISORY: Final[str] = "advisory"
ENFORCE_STEER: Final[str] = "steer"
_MODES: Final[frozenset[str]] = frozenset({ENFORCE_OFF, ENFORCE_ADVISORY, ENFORCE_STEER})
"""18:1748's three values. 10:2024: *"an unknown value falls back to `advisory`, because a typo must
never hard-block a tool."*"""

HOOK_TTL: Final[str] = "OMNIWEAVE_HOOK_TTL"
DEFAULT_TTL_S: Final[int] = 1_800
"""18:1749: *"how long the `PreToolUse` steer stands down after `ow_query` actually served this
corpus."*"""

_GATE_SOURCE: Final[str] = "outside-source"
_GATE_EXT: Final[str] = "readable-ext"
_GATE_SIZE: Final[str] = "small"
_GATE_TARGETED: Final[str] = "targeted-read"
_GATE_INDEX: Final[str] = "not-indexed"

_TIER_DENY: Final[str] = "deny"
_TIER_NUDGE: Final[str] = "nudge"
_TIER_OFF: Final[str] = "noop-off"
_TIER_STOOD_DOWN: Final[str] = "nudge-stood-down"
_TIER_STALE: Final[str] = "nudge-stale"
_TIER_UNCLAIMED: Final[str] = "nudge-unclaimed"

CLAIM_SUFFIX: Final[str] = ".steered"
"""`<key>.steered`, created with `O_EXCL`. 10:2020's *"once per session"*, as a file."""


@dataclass(frozen=True, slots=True)
class Indexed:
    """What gate 5's one lookup returns, or `None` for "not indexed". 10:2028.

    `stale` is here rather than beside it because 10:2022 makes staleness a *softening* and not a
    gate: a stale corpus still earns a nudge and never a deny, since the passages we would send are
    the ones the user has already changed.
    """

    corpus: str
    version: str = ""
    pages: int = 0
    blocks: int = 0
    stale: bool = False


@dataclass(frozen=True, slots=True)
class Target:
    """The four payload-and-filesystem facts, resolved before the store is touched at all.

    `inside_source` is gate 1 and arrives resolved because `[roots] source` is `config`'s, and D401
    measured what importing `config` costs a hook. The caller that already knows its roots answers
    it; this module does not guess.
    """

    name: str = ""
    size: int = 0
    extension: str = ""
    inside_source: bool = False
    targeted: bool = False


def failing_gate(target: Target, indexed: Indexed | None) -> str:
    """`""` when all five hold, else the name of the **first** that does not. 10:2011.

    Ordered by cost, cheapest first, so the store read is reached only by a payload that has already
    passed the other four. That ordering is not in the plan and is the only way gate 5's *"one
    indexed lookup"* stays one lookup per *qualifying* read rather than one per `Read`.
    """
    if not target.inside_source:
        return _GATE_SOURCE
    if target.extension.lower().lstrip(".") not in OPAQUE_DOC_EXTS:
        return _GATE_EXT
    if target.size < MIN_SIZE_BYTES:
        return _GATE_SIZE
    if target.targeted:
        return _GATE_TARGETED
    if indexed is None:
        return _GATE_INDEX
    return ""


class Lookup(Protocol):
    """Gate 5, as a seam. One indexed lookup on the canonical uri and nothing else."""

    def indexed(self, name: str) -> Indexed | None:
        """`None` for not indexed, and `None` for any failure at all. 10:2028."""
        ...


def lookup_or_none(lookup: Lookup | None, name: str) -> Indexed | None:
    """`lookup.indexed(name)`, with every failure turned into "not indexed". 10:2030's rule.

    *"Any failure yields [] so the hook silently allows the search rather than ever blocking it on a
    store hiccup."* A raise here would be caught by the envelope and become a silent exit 0 anyway;
    catching it here means the other four gates' work still produces an answer instead of an
    exception, and the counter says `not-indexed` rather than `noop-failure`.
    """
    if lookup is None:
        return None
    try:
        found = lookup.indexed(name)
    except Exception:
        return None
    return found if isinstance(found, Indexed) else None


# ---------------------------------------------------------------------------------------------
# The environment. 18:1748.
# ---------------------------------------------------------------------------------------------


def enforce_mode(env: Mapping[str, str]) -> str:
    """`off`, `advisory` or `steer`. Anything else -- including unset -- is `advisory`.

    10:2024 states the fallback and its reason in one clause: *"a typo must never hard-block a
    tool."* So the parse is a membership test and not a `StrEnum` lookup that could raise.
    """
    value = env.get(ENFORCE, "").strip().lower()
    return value if value in _MODES else ENFORCE_ADVISORY


def ttl_seconds(env: Mapping[str, str]) -> int:
    """`OMNIWEAVE_HOOK_TTL` in seconds, defaulting to 1,800. A bad value is the default.

    Negative is clamped to zero rather than rejected: `0` is a legible way to say *"never stand
    down"*, and a negative stand-down is the same thing spelled worse.
    """
    raw = env.get(HOOK_TTL, "").strip()
    if not raw:
        return DEFAULT_TTL_S
    try:
        return max(int(raw), 0)
    except ValueError:
        return DEFAULT_TTL_S


# ---------------------------------------------------------------------------------------------
# The two strings. 10:2034: two shipped strings, from one constant.
# ---------------------------------------------------------------------------------------------

_ALTERNATIVES: Final[str] = (
    "`ow_query` returns the passages with page and polygon provenance in one call, and "
    '`ow_open ref="{name}#p1"` returns page 1 exactly.'
)
"""The one constant both strings name their alternatives from. 10:2034.

The plan's examples say `#p14` of a 22-page document, which is illustrative; `#p1` is the page every
indexed document has. The shape is what is fixed -- an exact page address the agent can use without
guessing -- and a page number that might not exist would be worse advice than none.
"""

_ADVISORY_TEXT: Final[str] = (
    "omniweave hint: {name} is a {size} indexed {kind} ({corpus}{version}, {pages} pages, "
    "{blocks} blocks). " + _ALTERNATIVES + " Read is still fine when you need byte offsets "
    "for an Edit."
)

_DENY_TEXT: Final[str] = (
    "omniweave: {name} is indexed in `{corpus}` ({pages} pages, {blocks} blocks) and Read returns "
    "extracted text without provenance. Use ow_query for a question, or "
    'ow_open ref="{name}#p1" for a known page. For a pre-Edit read pass offset/limit and this '
    "will pass. (OMNIWEAVE_ENFORCE=advisory for warn-only, =off to disable.)"
)


_MB: Final[int] = 1_000_000
_KB: Final[int] = 1_000


def _humanise(size: int) -> str:
    """`2.1 MB`. The plan's own spelling in the advisory example, and its own base.

    Decimal and not binary: 10:2036 writes *"a 2.1 MB indexed PDF"*, which is 2,100,000 bytes and
    not 2,202,010. A file manager and a hook disagreeing about what MB means is a small thing that
    makes the number look wrong to the one person who checks it.
    """
    if size >= _MB:
        return f"{size / _MB:.1f} MB"
    if size >= _KB:
        return f"{size / _KB:.0f} kB"
    return f"{size} bytes"


def advisory_text(target: Target, indexed: Indexed) -> str:
    """10:2036's nudge. Advice, in the indicative, with no imperative opening and no glyph."""
    return _ADVISORY_TEXT.format(
        name=target.name,
        size=_humanise(target.size),
        kind=target.extension.lstrip(".").upper(),
        corpus=indexed.corpus,
        version=f"@{indexed.version}" if indexed.version else "",
        pages=indexed.pages,
        blocks=indexed.blocks,
    )


def deny_text(target: Target, indexed: Indexed) -> str:
    """10:2040's refusal, which names the same alternatives and how to turn itself off."""
    return _DENY_TEXT.format(
        name=target.name,
        corpus=indexed.corpus,
        pages=indexed.pages,
        blocks=indexed.blocks,
    )


# ---------------------------------------------------------------------------------------------
# The decision. Pure: every input is an argument.
# ---------------------------------------------------------------------------------------------


def decide(
    target: Target,
    indexed: Indexed | None,
    *,
    mode: str,
    may_claim: Callable[[], bool] | None = None,
    served_recently: bool = False,
) -> Advice:
    """10:2011's five gates, then 10:2020's four guards. The only place this hook says anything.

    The guards are checked in the order that makes the *cheapest* refusal of a deny first: the
    environment (a dict read), the stand-down (a boolean the caller resolved), the staleness (a
    field already in hand), and only then the `O_EXCL` claim -- which is a filesystem write and the
    one guard with a side effect. Claiming and then discovering the mode was `off` would spend a
    session's one deny on a hook that was never allowed to refuse.
    """
    if mode == ENFORCE_OFF:
        return Advice(counter=_TIER_OFF)
    gate = failing_gate(target, indexed)
    if gate or indexed is None:
        return Advice(counter=f"noop-{gate or _GATE_INDEX}")

    nudge = Advice(text=advisory_text(target, indexed), counter=_TIER_NUDGE)
    if mode != ENFORCE_STEER:
        return nudge
    return _refuse_or_soften(
        target,
        indexed,
        nudge,
        may_claim=may_claim,
        served_recently=served_recently,
    )


def _refuse_or_soften(
    target: Target,
    indexed: Indexed,
    nudge: Advice,
    *,
    may_claim: Callable[[], bool] | None,
    served_recently: bool,
) -> Advice:
    """10:2020's four guards, cheapest refusal first. Any one of them turns a deny into the nudge.

    The `O_EXCL` claim is last because it is the only guard with a side effect. Claiming and then
    discovering the corpus was stale would spend a session's one deny on a refusal never made.
    """
    if served_recently:
        return Advice(text=nudge.text, counter=_TIER_STOOD_DOWN)
    if indexed.stale:
        return Advice(text=nudge.text, counter=_TIER_STALE)
    if may_claim is None or not may_claim():
        return Advice(text=nudge.text, counter=_TIER_UNCLAIMED)
    return Advice(text=deny_text(target, indexed), deny=True, counter=_TIER_DENY)


def run_pretool(
    payload: Mapping[str, Any],
    *,
    target: Target,
    lookup: Lookup | None,
    env: Mapping[str, str],
    root: Path | None = None,
    key: str = "",
    served_recently: bool = False,
) -> Advice:
    """`decide()` with gate 5 taken and the claim wired, or a nudge when there is nowhere to claim.

    `root is None` or an empty `key` is D403's deployment again, and it **downgrades a deny to a
    nudge** rather than silencing the hook: the five gates still hold, the document is still opaque
    and indexed, and the only thing missing is the place to record that we have already refused
    once. Advice with no memory is still advice; a refusal with no memory would repeat every call.
    """
    mode = enforce_mode(env)
    if mode == ENFORCE_OFF:
        return Advice(counter=_TIER_OFF)
    gate = failing_gate(target, None if lookup is None else Indexed(corpus="?"))
    if gate and gate != _GATE_INDEX:
        return Advice(counter=f"noop-{gate}")

    indexed = lookup_or_none(lookup, target.name)
    claimer = None if root is None or not key else _claimer(root, key, payload)
    return decide(
        target,
        indexed,
        mode=mode,
        may_claim=claimer,
        served_recently=served_recently,
    )


def _claimer(root: Path, key: str, payload: Mapping[str, Any]) -> Callable[[], bool]:
    """A once-per-session `O_EXCL` claim, deferred so it runs only if every other guard passed."""

    def take() -> bool:
        return claim(root, f"{key}{CLAIM_SUFFIX}", {"tool": str(payload.get("tool_name", ""))})

    return take


def handler(
    *,
    target_of: Callable[[Mapping[str, Any]], Target],
    lookup: Lookup | None,
    env: Mapping[str, str],
    root: Path | None = None,
    key_of: Callable[[Mapping[str, Any]], str] | None = None,
    served_recently: bool = False,
) -> Callable[[Mapping[str, Any]], Advice]:
    """`run_pretool` bound to its seams, in the shape `envelope.run()` takes.

    `target_of` is a callable because resolving a path against `[roots] source` is `config`'s job
    and D401 measured what importing `config` costs here. The caller that already has a resolved
    configuration answers gate 1; this module asks.
    """

    def bound(payload: Mapping[str, Any]) -> Advice:
        return run_pretool(
            payload,
            target=target_of(payload),
            lookup=lookup,
            env=env,
            root=root,
            key="" if key_of is None else key_of(payload),
            served_recently=served_recently,
        )

    return bound


def unguarded() -> tuple[str, ...]:
    """What this gate decides against a reading rather than against a statement."""
    return (
        "which `OMNIWEAVE_ENFORCE` value denies. Section 8.5 describes the strict deny at length, "
        "names `advisory` as the default and `off` as the disable, and never names the third. The "
        "vocabulary `off | advisory | steer` appears once in the plan, in 18 section 4, and "
        "`steer` is separately an `ow install --hooks` choice (D417)",
        "how the stand-down is observed. 10:2022 stands the steer down for `OMNIWEAVE_HOOK_TTL` "
        "after `ow_query` *actually served this corpus*, which is a fact the server knows and the "
        "hook does not; nothing says where it is written. It arrives here as an argument (D418)",
        "what happens when there is nowhere to claim. 10:2020 makes the deny once-per-session via "
        "`O_EXCL`, and a deployment with no `<sessions>` (D403) has no such file. This module "
        "downgrades to a nudge rather than denying unrecorded or falling silent",
        "the order of the five gates. 10:2011 makes them a conjunction and gives no order, and the "
        "order is the whole cost: gate 5 is a store read, so it runs last and only for a payload "
        "the other four already passed",
        "the example page in both strings. The plan writes `#p14` of a 22-page document; this "
        "module writes `#p1`, which is the page every indexed document has",
    )
