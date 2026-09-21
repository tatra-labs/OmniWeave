"""Who may call what, and what a client is shown: 10 section 3.8's four mechanisms, resolved.

`assert_sv1()` in `registry.py` takes two collections and checks one invariant over them. **Nothing
computed either collection.** Its own docstring names the missing piece -- *"10:790 has the resolver
accept either the bare name or the `mcp_name` and normalise before this runs"* -- and this module is
that resolver. 02:723 puts its output at startup step 5, `SurfaceError` and exit 1, *"before the
transport opens"*, which is also why it can be written now: it runs before the part that awaits.

## TWO KEYS, TWO OWNERS, AND THE ORDER IS LOAD-BEARING

10:780's table, lowest precedence first:

| mechanism | answers |
|---|---|
| `[serve] profile` | which named listed-set is the default |
| `[serve] listed` | a deployment's explicit listing, overriding the profile |
| `OMNIWEAVE_MCP_LISTED` | one session's debugging |
| `[serve] enabled` | the deployment's **authority** decision |
| `OMNIWEAVE_MCP_ENABLED` | an operator granting authority |

`enabled` resolves **first** and `listed` second (10:785), so SV1 is a single check at startup
rather than a per-request one. 14:655 is why the two are separate at all: `enabled` is an authority
property and `listed` is a presentation one, and collapsing them would make the host's only control
over a corpus of untrusted third-party documents a display setting.

## AN UNLISTED ACTION IS SERVED; A DISABLED ONE IS REFUSED, AND THE PLAN'S REFUSAL BRICKS STARTUP

10:795 is unambiguous about the first half and `refusal()` below implements the second, with one
deviation recorded rather than absorbed. The sentence is:

> A client that remembers `ow_route_explain` from a previous session and dispatches it gets the
> result when the Action is enabled, and `OW-A-003 / OW_TOOL_NOT_LISTED` -- naming the config key
> *and* the env var that would list it -- only when it is not.

The condition is *not enabled*; the fix named is the pair that would **list** it. Following that fix
adds the Action to `listed` without adding it to `enabled`, which is `listed` exceeding `enabled` --
SV1 -- and the server then refuses to start. 10:799 criticises codegraph in the next breath for a
refusal that is *"a dead end rather than a fix instruction"*, and a fix instruction that bricks
startup is the worse of the two. So `refusal()` keeps 10:797's symbol and names the **enabling**
pair, `test_following_the_plans_fix_breaches_sv1` proves why, and D376 is the entry.

## THE PRESET VOCABULARY AND THE ADDITIVE OPERATOR SHARE A CHARACTER

The presets are `all`, `read_only` and `read_only+add`; the additive form is `+name`. So
`read_only+add` is parseable two ways and `add` is a real Action name, which makes the
collision live rather than theoretical. The rule here is **exact preset match wins**,
checked before the grammar, so `read_only+add` is the preset and `read_only,+add` reaches
the same set by a different road. D377.

## WHAT `all` HAS TO MEAN

Every Action with an `mcp_name`, and not every Action. 10:858 grants `ow_ingest` through
`enabled = "all"`, and SV1's second clause forbids `HUMAN_ONLY` in `enabled` at all -- so an `all`
that included the five would make its own preset a startup error. That is forced by the invariant
rather than chosen here, and `test_the_all_preset_cannot_breach_sv1` is where it is held.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import UsageError, edit_distance

from omniweave.surface.registry import (
    ACTIONS,
    DEFAULT_PROFILE,
    HUMAN_ONLY,
    PROFILES,
    assert_sv1,
    listed,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

__all__ = [
    "ADDITIVE",
    "ALL",
    "ENABLED_ENV",
    "ENABLED_KEY",
    "LISTED_ENV",
    "LISTED_KEY",
    "NEAREST",
    "PRESETS",
    "PROFILE_KEY",
    "READ_ONLY",
    "READ_ONLY_ADD",
    "Resolution",
    "agent_reachable",
    "entries",
    "human_only_named",
    "nearest",
    "normalise",
    "preset",
    "refusal",
    "resolve",
]


PROFILE_KEY: Final[str] = "serve.profile"
LISTED_KEY: Final[str] = "serve.listed"
ENABLED_KEY: Final[str] = "serve.enabled"
LISTED_ENV: Final[str] = "OMNIWEAVE_MCP_LISTED"
ENABLED_ENV: Final[str] = "OMNIWEAVE_MCP_ENABLED"
"""The five names 10:780's table carries, spelled once.

The two env vars are also `omniweave_core.config.ENV_OVERRIDES`' two rows -- *"the twins no
mechanical rule produces"* -- and a test binds the four spellings to that mapping, because a
refusal naming a variable the loader does not read is D327 and it has happened here before.
"""

ALL: Final[str] = "all"
READ_ONLY: Final[str] = "read_only"
READ_ONLY_ADD: Final[str] = "read_only+add"
PRESETS: Final[tuple[str, ...]] = (ALL, READ_ONLY, READ_ONLY_ADD)
"""10:780's three presets, in the order the row prints them.

`omniweave_core.config.KEYS["serve.enabled"].choices` carries the same three and a test binds them.
Two homes, and the config registry's copy is the one a `[serve] enabled` value is validated against
while this one is what an env var is resolved through -- the same string reached by two loaders,
which is exactly the `MAX_RUNG_MEMBERS` shape.
"""

ADDITIVE: Final[str] = "+"
"""10:781's *"`+name` adds to the profile's set"*. See the module docstring on the collision."""

NEAREST: Final[int] = 3
"""How many near matches an unknown entry's refusal names. `errors._NEAREST`'s number, for its
reason: 18:232 fixes three for `codes.toml` and a second count here would make two registers
disagree about how much help a typo earns."""


@dataclass(frozen=True, slots=True)
class Resolution:
    """What the four mechanisms resolved to, and which one won each half.

    The two `*_from` fields exist so a refusal, `ow doctor` and the startup log can say *which key*
    produced the set rather than only what the set is. A server that cannot name the mechanism
    behind its own surface makes every listing question a bisection.
    """

    profile: str
    enabled: frozenset[str]
    listed: tuple[str, ...]
    enabled_from: str
    listed_from: str

    def serves(self, action: str) -> bool:
        """Whether a `tools/call` for this Action is answered. Authority, never presentation.

        10:795's *"an unlisted Action is still served, and is never refused for being unlisted"*,
        as one line: this reads `enabled` and never `listed`.
        """
        return action in self.enabled

    def shows(self, action: str) -> bool:
        """Whether `tools/list` carries this Action. Presentation, and a subset of `serves()`."""
        return action in self.listed


def agent_reachable() -> frozenset[str]:
    """Every Action an agent surface can address: the ones with an `mcp_name`.

    `HUMAN_ONLY`'s five have `mcp_name = None` and are excluded by that fact rather than by being
    subtracted, which is 10:1540's *"structural, not a denylist"* observed one layer up: there is
    no filter here to forget.
    """
    return frozenset(name for name, spec in ACTIONS.items() if spec.mcp_name is not None)


def preset(value: str) -> frozenset[str] | None:
    """One of the three preset names to the Action set it grants, or `None` if it is not a preset.

    `read_only` is every read-only Action an agent can address, and `read_only+add` is that plus
    `add` -- 10:842's *"the shipped `[serve] enabled = "read_only+add"` grants exactly the read-only
    Actions plus `add`"*, which is the sentence the `full` roster's read-only-ness is forced by.
    """
    reachable = agent_reachable()
    if value == ALL:
        return reachable
    read_only = frozenset(name for name in reachable if ACTIONS[name].read_only)
    if value == READ_ONLY:
        return read_only
    if value == READ_ONLY_ADD:
        return read_only | ({"add"} & reachable)
    return None


def entries(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """One mechanism's raw value to its entries, blanks dropped, order kept.

    A string is comma-separated (both env vars and `[serve] enabled`'s scalar form); a sequence is
    already split (`[serve] listed`, and `[serve] enabled`'s list form). `None` is *not set*, which
    is different from an empty list: an empty `[serve] listed` falls through to the profile and an
    empty `OMNIWEAVE_MCP_LISTED` is a deliberate empty listing.
    """
    if value is None:
        return ()
    raw = value.split(",") if isinstance(value, str) else list(value)
    return tuple(item.strip() for item in raw if item.strip())


def normalise(entry: str) -> str | None:
    """One entry to an Action name, or `None` when it names nothing.

    10:790: *"Both accept the bare Action name (`route.explain`) and the MCP name
    (`ow_route_explain`)"*. A `HUMAN_ONLY` Action normalises to itself and is **not** rejected here,
    because rejecting it here would report it as an unknown name; `assert_sv1()` refuses it by the
    right symbol, `OW_HUMAN_ONLY_ACTION`, and 10:792 requires that refusal to be the startup error.
    """
    candidate = entry.strip()
    if candidate in ACTIONS:
        return candidate
    for name, spec in ACTIONS.items():
        if spec.mcp_name == candidate:
            return name
    return None


def nearest(entry: str, *, count: int = NEAREST) -> tuple[str, ...]:
    """The closest known spellings to `entry` by edit distance, in the form it was written in.

    An entry shaped like an `mcp_name` is ranked against `mcp_name`s and a bare one against Action
    names, because suggesting `route.explain` to somebody who typed `ow_route_explian` is a worse
    answer than suggesting `ow_route_explain`. `errors._nearest()` makes the same distinction over
    `codes.toml`'s two spellings, and both call one `edit_distance()`.
    """
    mcp_form = entry.startswith("ow_")
    known = [
        spec.mcp_name if mcp_form and spec.mcp_name is not None else name
        for name, spec in ACTIONS.items()
        if spec.mcp_name is not None or not mcp_form
    ]
    return tuple(
        sorted(known, key=lambda known_name: (edit_distance(entry, known_name), known_name))[:count]
    )


def refusal(action: str, resolution: Resolution) -> UsageError:
    """The `tools/call` refusal for an Action this deployment does not enable. 10:797.

    Keeps that line's symbol and **does not keep its fix.** The fix it names -- the pair that would
    *list* the Action -- adds it to `listed` without adding it to `enabled`, which breaches SV1 and
    refuses the next start. This names the enabling pair instead. D376, and the module docstring
    carries the argument.

    18:1443 requires the message to name *"the config key **and** the env var that would change the
    answer"*, and both are here for that reason rather than for symmetry.
    """
    return UsageError(
        f"{action} is defined and dispatchable and this deployment has not enabled it; "
        f"{len(resolution.enabled)} Actions are enabled, from {resolution.enabled_from}",
        symbol="OW_TOOL_NOT_LISTED",
        fix=(
            f"add {action} to [serve] enabled in omniweave.toml, "
            f"or set {ENABLED_ENV}={action} for one session"
        ),
    )


def resolve(
    *,
    profile: str = DEFAULT_PROFILE,
    listed_key: Sequence[str] | None = None,
    enabled_key: str | Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Resolution:
    """The four mechanisms, in 10:780's precedence order, with SV1 asserted at the end.

    Pure: the config values and the environment arrive as arguments. That is what makes every
    combination of the four testable without a process, and it is the same shape every module in
    `omniweave_serve` took this phase -- the policy is an object and the ambient state is the
    caller's.

    Raises `UsageError` (exit 1) for an unknown entry in either variable, and `assert_sv1()` raises
    it for the two invariant clauses. There is no repair-and-continue path anywhere in here: 10:787
    forbids one, because *"a server that quietly narrowed its own listing would disagree with the
    `llms.txt` it ships"*.
    """
    environment = env or {}
    if profile not in PROFILES:
        raise UsageError(
            f"{profile!r} is not a profile; the two are {', '.join(PROFILES)}",
            symbol="OW_TOOL_NOT_LISTED",
            fix=f"set [serve] profile to one of: {', '.join(PROFILES)}",
        )

    enabled, enabled_from = _resolve_enabled(enabled_key, environment)
    granted, listed_from = _resolve_listed(profile, listed_key, environment)

    assert_sv1(granted, enabled)
    return Resolution(
        profile=profile,
        enabled=frozenset(enabled),
        listed=tuple(sorted(granted)),
        enabled_from=enabled_from,
        listed_from=listed_from,
    )


def _resolve_enabled(
    key: str | Sequence[str] | None, env: Mapping[str, str]
) -> tuple[frozenset[str], str]:
    """`OMNIWEAVE_MCP_ENABLED` over `[serve] enabled` over the shipped default. Resolved first.

    Both levels take the preset grammar, which the config registry already says:
    `KEYS["serve.enabled"]` is a `str_or_list` whose `choices` are the three preset names, so a
    scalar is a preset and a list is names. `KEYS["serve.listed"]` is a plain list with no choices,
    which is why `_resolve_listed()` does not expand a preset out of the config file.

    The additive form is not honoured here and 10:780's table is why: `+name` is defined on the
    `listed` row as adding *"to the profile's set"*, and `enabled` has no profile to add to. An
    operator reaching for it gets the entry treated as a name and an unknown-entry refusal naming
    it. D378.
    """
    raw = env.get(ENABLED_ENV)
    if raw is not None:
        return _members(entries(raw), source=ENABLED_ENV), ENABLED_ENV
    if key is not None:
        return _members(entries(key), source="[serve] enabled"), f"[serve] {ENABLED_KEY[6:]}"
    return _members((READ_ONLY_ADD,), source="the default"), f"[serve] {ENABLED_KEY[6:]} default"


def _resolve_listed(
    profile: str, key: Sequence[str] | None, env: Mapping[str, str]
) -> tuple[frozenset[str], str]:
    """`OMNIWEAVE_MCP_LISTED` over `[serve] listed` over the profile's set.

    **The additive base is the level below, not always the profile.** 10:781 writes *"adds to the
    profile's set"*, which would make an explicit `[serve] listed` invisible to a `+` one level up
    -- an override discarded by a single character. Everywhere else in this config system an
    override composes with the value it overrides, so `+ow_why` adds to `[serve] listed` when that
    is set and to the profile's set when it is not. D379.

    A bare entry alongside a `+` one **replaces** rather than adds, because a value that both
    replaced and added would make the order of two entries significant and nothing declares one.
    A variable that is SET and names nothing is an empty listing rather than a fall-through: an
    operator who writes `OMNIWEAVE_MCP_LISTED=` has said something, and restoring the profile there
    would be the silent narrowing 10:787 forbids, seen from the other end.
    """
    explicit = entries(key)
    under = (
        frozenset(_named(explicit, source=f"[serve] {LISTED_KEY[6:]}"))
        if explicit
        else frozenset(listed(profile))
    )
    under_from = f"[serve] {LISTED_KEY[6:]}" if explicit else f"[serve] {PROFILE_KEY[6:]}={profile}"

    raw = env.get(LISTED_ENV)
    if raw is None:
        return under, under_from

    additions: list[str] = []
    replacements: list[str] = []
    for entry in entries(raw):
        target = additions if entry.startswith(ADDITIVE) else replacements
        target.append(entry.removeprefix(ADDITIVE))
    added = _members(tuple(additions), source=LISTED_ENV)
    if additions and not replacements:
        return under | added, LISTED_ENV
    return _members(tuple(replacements), source=LISTED_ENV) | added, LISTED_ENV


def _members(values: Iterable[str], *, source: str) -> frozenset[str]:
    """Entries to Action names, expanding a preset where one is named exactly.

    Exact match first, which is the whole rule for the `read_only+add` collision: a value equal to a
    preset is that preset, and anything else goes through the grammar. See D377.
    """
    out: set[str] = set()
    plain: list[str] = []
    for value in values:
        members = preset(value)
        if members is None:
            plain.append(value)
        else:
            out |= members
    return frozenset(out | set(_named(tuple(plain), source=source)))


def _named(values: Collection[str], *, source: str) -> tuple[str, ...]:
    """Entries to Action names, refusing the first unknown one with its near matches.

    10:790 fixes the symbol and the help: *"reports an unknown entry as `OW-A-004 /
    OW_ACTION_NOT_ENABLED` listing near matches by edit distance"*. The refusal names the source so
    an operator holding two variables and a config file knows which one to edit.
    """
    resolved: list[str] = []
    for value in values:
        action = normalise(value)
        if action is None:
            suggestions = ", ".join(nearest(value))
            raise UsageError(
                f"{source} names {value!r}, which is not an Action. Nearest: {suggestions}",
                symbol="OW_ACTION_NOT_ENABLED",
                fix=f"use one of the names above, or drop {value!r} from {source}",
            )
        resolved.append(action)
    return tuple(resolved)


def human_only_named(values: Iterable[str]) -> tuple[str, ...]:
    """The `HUMAN_ONLY` Actions an entry list names, sorted. Reported, never raised here.

    `assert_sv1()` owns the refusal and owns its symbol. This exists so `ow doctor` and a startup
    log can say which of the five a variable named without reproducing the invariant's message.
    """
    return tuple(sorted({name for value in values if (name := normalise(value)) in HUMAN_ONLY}))
