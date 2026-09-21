"""SV2, measured: what `tools/list` costs an agent, frozen, and checked for drift.

00:713's V01-12 is one sentence with four numbers in it -- *"`tools/list` for `profile=default,
compact_schemas=true` <= **1,900 tokens** (`tiktoken cl100k_base`, 5% drift), per-tool <= 700,
`instructions` <= 1,000 chars"* -- and until this module there was nothing in the repository that
could produce any of them. This is the counting half of `ow surface budget`;
`benchmarks/serve_schema_baseline.json` is what it freezes, and 10 section 12.1 is the
specification.

## THE TOKENIZER IS AN ARGUMENT, NOT AN IMPORT

10:2585 makes `tiktoken` *"a **dev-only dependency and never a runtime one**"*, and this module
ships inside `omniweave`, which is a runtime distribution. An `import tiktoken` here would make
that sentence false by the only mechanism that matters -- a wheel that resolves it -- so
`measure()` takes the encoder as a parameter and the one place the name appears is a test.

That is also what makes the module testable without one: a stand-in encoder measures the same
structure, and the tests that check the shape of a finding do not need a 1.7 MB merge table to run.

**And they must not need one, because acquiring it reaches the network.** `get_encoding` resolves
`cl100k_base` through `tiktoken.load.read_file_cached`, which looks in `TIKTOKEN_CACHE_DIR`, then
`DATA_GYM_CACHE_DIR`, then a `data-gym-cache` directory under the system temp -- and on a miss
fetches it over HTTPS from a host that has no row in `tools/egress.toml`. A fresh checkout on a
clean machine therefore cannot run the one check SV2 names without an egress G15 never blessed.
D371 is the entry, and it is why the tokenizer-free half of `findings()` is a separate pass.

## WHAT IS MEASURED IS THE SELECTION, NOT THE FILE

`schema/mcp-tools-v1.json` is every tool this build can render. What an agent pays for is
`mcp_tools.listing()` -- one profile's subset, compacted or not, with `corpus` promoted or not --
and the distance between the two is the entire point of the four-tool listing rule.

Two of the six combinations are unmeasurable today and report that rather than a number:
`omitted("full")` names five rows of 10:807's eighteen that nothing can render, so `full_compact`
and `full_full` stay `null`. That is 10:2593's instruction and its reason -- *"a frozen baseline
containing an arithmetic estimate fails CI on the day it is committed and teaches the team to
re-bless reflexively, which is how a drift gate stops meaning anything."*

## THE DRIFT CHECK IS SYMMETRIC, AND THE PLAN DOES NOT SAY SO

10:363's *"fails above `DRIFT_TOLERANCE = 0.05`"* gives a magnitude and no sign. Read as growth
only, a payload that lost a fifth of its description characters -- a truncation, a description
accidentally emptied, a tool that stopped rendering -- passes the one check built to notice the
payload changing. The budget is why the gate exists and the baseline is why it can fail, so this
compares magnitudes in both directions. D372.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave.gen.emit import REPO_ROOT
from omniweave.gen.instructions import FRONT_DOOR, instructions
from omniweave.gen.mcp_tools import listing, omitted
from omniweave.surface.registry import ACTIONS, DEFAULT_PROFILE, PROFILES

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BASELINE_DIR",
    "BASELINE_NAME",
    "CEILINGS",
    "DRIFT_TOLERANCE",
    "NO_CORPUS_SUFFIX",
    "RECIPE",
    "TOKENIZER",
    "Baseline",
    "Encoder",
    "Measurement",
    "baseline_path",
    "blessed",
    "drift",
    "findings",
    "measure",
    "read_baseline",
    "serialised",
    "tokens",
]


Encoder = Callable[[str], Sequence[int]]
"""What `measure()` needs of a tokenizer: text in, something countable out.

`tiktoken.Encoding.encode` satisfies it and so does `str.split`, which is the point -- see the
module docstring. Nothing here inspects a token, so the element type is the narrowest thing that
describes what a real encoder returns rather than the widest thing that would type-check.
"""

TOKENIZER: Final[str] = "cl100k_base"
"""10:319's encoding, and the baseline's own `tokenizer` field.

Compared, never chosen at runtime: a baseline counted with one encoding and rechecked with another
is two numbers under one name, and the field exists so that cannot happen quietly.
"""

RECIPE: Final[str] = "json.dumps(tool,separators=(',',':'),ensure_ascii=False)"
"""10:2586's `recipe` field, spelled as the baseline spells it.

`serialised()` below is this string executed and a test binds the two. `ensure_ascii=False` is the
load-bearing half (10:331): the descriptions carry an em dash and a middle dot, and escaping them
would inflate the count by a property of the serializer rather than of the wire.
"""

DRIFT_TOLERANCE: Final[float] = 0.05
"""10:363. Five per cent either way -- the module docstring argues the sign, and D372 records it."""

BASELINE_DIR: Final[str] = "benchmarks"
BASELINE_NAME: Final[str] = "serve_schema_baseline.json"
"""The frozen file, as a directory and a name rather than one joined path.

Two constants for `catalog.py`'s reason one distribution over: the path resolves against
`REPO_ROOT` and a wheel carries no repository, so the join is a function's job and not a literal.
The directory is named by three plan documents and appears in none of 11's trees. D373.
"""

NO_CORPUS_SUFFIX: Final[str] = "_no_corpus"
"""What `measure()` appends to a profile when `[serve] default_corpus` does not resolve.

The baseline's `instructions_chars` block has two keys, `default` and `no_corpus` (10:2596), and
they are not the same axis: the first names a profile and the second names a corpus state, so the
block has a slot for two of the four strings `instructions()` can produce. The two it has no slot
for are the two that breach the cap. D374, and this constant is how the other two get named.
"""

CEILINGS: Final[Mapping[str, int]] = MappingProxyType(
    {"default": 1900, "full": 4200, "per_tool": 700, "instructions_chars": 1000}
)
"""10:2597's `ceilings` block, verbatim.

Spelled here and in the baseline file, which is two homes for four integers and is deliberate in
the way `catalog.ANNOTATION_KEYS` is: the file is data a reviewer diffs and this is what a reader
greps, and `findings()` refuses a file whose block disagrees with it rather than preferring either
copy. `default` is 1,900 because L4 is a number (10:261); `full` is 4,200 because 10:831 derives it
from the eighteen-row roster rather than choosing it.
"""


@dataclass(frozen=True, slots=True)
class Measurement:
    """One counting pass over the live surface: every number the baseline freezes, and why."""

    per_tool_compact: Mapping[str, int]
    per_tool_full: Mapping[str, int]
    default_compact: int
    default_full: int
    default_compact_corpus_required: int
    full_compact: int
    full_full: int

    instructions_chars: Mapping[str, int]
    """All four of `instructions()`'s outputs, keyed by profile and by profile + `NO_CORPUS_SUFFIX`.

    Four and not the baseline's two, because the cap governs every string `initialize` can deliver
    and two of the four exceed it. D374.
    """

    omitted: Mapping[str, tuple[str, ...]]
    """Per profile, the listed `mcp_name`s nothing can render.

    Empty for `default`, which `_published_failures()` is what keeps true, and five for `full`.
    """

    def measured(self, profile: str) -> bool:
        """Whether this profile's totals cover the whole profile. 10:2593's `null` condition."""
        return not self.omitted.get(profile, ())


@dataclass(frozen=True, slots=True)
class Baseline:
    """The parsed frozen file. The `full` pair is `None` until it can honestly be counted."""

    path: Path
    tokenizer: str
    recipe: str
    release: str
    default_compact: int
    default_full: int
    default_compact_corpus_required: int
    full_compact: int | None
    full_full: int | None
    per_tool_compact: Mapping[str, int]
    per_tool_full: Mapping[str, int]
    instructions_chars: Mapping[str, int]
    ceilings: Mapping[str, int]
    drift_tolerance: float


def serialised(tool: Mapping[str, Any]) -> str:
    """`RECIPE`, executed. The half of 10:321 that needs no tokenizer.

    Separated from the counting so a test can bind the two, and so the bytes a reviewer counts by
    hand are producible without the encoding table.
    """
    return json.dumps(tool, separators=(",", ":"), ensure_ascii=False)


def tokens(tool: Mapping[str, Any], encode: Encoder) -> int:
    """One tool object's token count. 10:321's `tokens()`, with the encoder passed in."""
    return len(encode(serialised(tool)))


def measure(encode: Encoder) -> Measurement:
    """Count every combination the baseline freezes, from the live registry.

    Six token totals across two profiles and two compaction states, plus the `corpus`-promoted
    variant, plus four character counts. The `full` pair is counted even while it is partial,
    because `blessed()` is what decides to write `null` and a measurement that refused to produce a
    number would leave `findings()` unable to say how far the partial total is from its ceiling.

    The per-tool rows are the UNION over profiles rather than the default profile's four, because
    the 700-token cap is per tool and governs a narrow Action exactly as it governs a front-door
    one. The union is four today and eighteen when 10:807's roster renders; a tool object does not
    vary with the profile that selected it, so measuring it once is measuring it correctly.
    """
    per_tool: dict[bool, dict[str, int]] = {True: {}, False: {}}
    for profile in PROFILES:
        for compact_schemas in (True, False):
            for entry in listing(profile, compact_schemas=compact_schemas):
                per_tool[compact_schemas][str(entry["name"])] = tokens(entry, encode)
    totals: dict[tuple[str, bool], int] = {}
    for profile in PROFILES:
        for compact_schemas in (True, False):
            totals[(profile, compact_schemas)] = sum(
                tokens(entry, encode) for entry in listing(profile, compact_schemas=compact_schemas)
            )
    promoted = sum(
        tokens(entry, encode)
        for entry in listing(DEFAULT_PROFILE, compact_schemas=True, corpus_required=True)
    )
    chars: dict[str, int] = {}
    for profile in PROFILES:
        chars[profile] = len(instructions(profile=profile, default_corpus=True))
        chars[profile + NO_CORPUS_SUFFIX] = len(instructions(profile=profile, default_corpus=False))
    return Measurement(
        per_tool_compact=MappingProxyType(dict(per_tool[True])),
        per_tool_full=MappingProxyType(dict(per_tool[False])),
        default_compact=totals[(DEFAULT_PROFILE, True)],
        default_full=totals[(DEFAULT_PROFILE, False)],
        default_compact_corpus_required=promoted,
        full_compact=totals[("full", True)],
        full_full=totals[("full", False)],
        instructions_chars=MappingProxyType(chars),
        omitted=MappingProxyType({profile: omitted(profile) for profile in PROFILES}),
    )


def baseline_path() -> Path:
    """Where the frozen file lives. Resolved against the repository, which a wheel does not carry.

    A `pip install omniweave` reaches a path that does not exist and `read_baseline()` says which
    one by name. That is the honest outcome rather than a hidden one: the baseline is a reviewer's
    artefact and not something a server reads, and a packaged copy would be a second answer beside
    the committed one with no mechanism keeping them equal.
    """
    return REPO_ROOT / BASELINE_DIR / BASELINE_NAME


def read_baseline(path: Path | None = None) -> Baseline:
    """Parse the frozen file. Raises a `ValueError` naming the file, never a `KeyError`.

    Per-field tolerance rather than per-file: a malformed row becomes a zero or a `None` and then a
    finding, so a baseline with three defects costs one edit cycle. `catalog._tool()` is the same
    shape one distribution over and for the same reason.
    """
    located = path or baseline_path()
    try:
        raw = json.loads(located.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{located} is not a readable schema baseline: {exc}") from exc
    table = raw if isinstance(raw, dict) else None
    if table is None:
        raise ValueError(f"{located} holds a {type(raw).__name__}, not the baseline object")
    return Baseline(
        path=located,
        tokenizer=str(table.get("tokenizer", "")),
        recipe=str(table.get("recipe", "")),
        release=str(table.get("release", "")),
        default_compact=_int(table, "default_compact"),
        default_full=_int(table, "default_full"),
        default_compact_corpus_required=_int(table, "default_compact_corpus_required"),
        full_compact=_optional_int(table, "full_compact"),
        full_full=_optional_int(table, "full_full"),
        per_tool_compact=_ints(table, "per_tool_compact"),
        per_tool_full=_ints(table, "per_tool_full"),
        instructions_chars=_ints(table, "instructions_chars"),
        ceilings=_ints(table, "ceilings"),
        drift_tolerance=float(table.get("drift_tolerance", 0.0))
        if isinstance(table.get("drift_tolerance"), (int, float))
        else 0.0,
    )


def drift(frozen: int, now: int) -> float:
    """How far `now` is from `frozen`, as a magnitude in both directions.

    A frozen zero is a baseline nobody blessed, so it drifts by everything rather than dividing by
    nothing: any non-zero measurement against it is a finding, which is the right answer.
    """
    if frozen == 0:
        return 0.0 if now == 0 else 1.0
    return abs(now - frozen) / frozen


def findings(baseline: Baseline, measured: Measurement | None = None) -> tuple[str, ...]:
    """Everything wrong with the frozen file, and with the live surface when one is supplied.

    Two passes, separable on purpose. The first needs no tokenizer -- it checks the file against
    the constants, against `CEILINGS`, and against the arithmetic its own per-tool rows imply -- so
    a machine that cannot reach the encoding table still fails a baseline somebody edited by hand.
    The second is the drift check, and it is the one SV2 names.
    """
    out: list[str] = []
    out.extend(_declaration_findings(baseline))
    out.extend(_ceiling_findings(baseline))
    if measured is not None:
        out.extend(_drift_findings(baseline, measured))
        out.extend(_instruction_findings(baseline, measured))
    return tuple(out)


def blessed(measured: Measurement, *, release: str) -> str:
    """The baseline file's text, in 10:2589's key order. What `ow surface budget --bless` writes.

    The `full` totals go out as `null` while `omitted("full")` is non-empty. The per-tool blocks
    keep the front door's decision order rather than the artefact's sort, because 10:2594 prints
    them that way and a reviewer diffing the plan's block against this file should read one diff
    and not four reordered lines that mean nothing.
    """
    front = _row_order(measured.per_tool_compact)
    body: dict[str, Any] = {
        "tokenizer": TOKENIZER,
        "recipe": RECIPE,
        "release": release,
        "default_compact": measured.default_compact,
        "default_full": measured.default_full,
        "default_compact_corpus_required": measured.default_compact_corpus_required,
        "full_compact": measured.full_compact if measured.measured("full") else None,
        "full_full": measured.full_full if measured.measured("full") else None,
        "per_tool_compact": {name: measured.per_tool_compact[name] for name in front},
        "per_tool_full": {name: measured.per_tool_full[name] for name in front},
        "instructions_chars": {
            "default": measured.instructions_chars[DEFAULT_PROFILE],
            "no_corpus": measured.instructions_chars[DEFAULT_PROFILE + NO_CORPUS_SUFFIX],
        },
        "ceilings": dict(CEILINGS),
        "drift_tolerance": DRIFT_TOLERANCE,
    }
    text = json.dumps(body, indent=2, ensure_ascii=False, allow_nan=False, sort_keys=False)
    return text.replace("\r\n", "\n").replace("\r", "\n") + "\n"


def _row_order(rows: Mapping[str, int]) -> tuple[str, ...]:
    """The per-tool block's key order: the front door's decision ladder, then whatever else.

    `FRONT_DOOR` is 10:878's four in the order the instructions string argues them, which is the
    order 10:2594 prints the baseline's rows in and is not the order `tools()` sorts by -- that one
    is the Action name, because artefact 1's diff is read per tool and this file's is read against
    the plan. The tail keeps `listing()`'s order so a narrow Action landing later appends rather
    than reshuffling every row above it.
    """
    ladder = [
        name
        for action in FRONT_DOOR
        if action in ACTIONS and (name := ACTIONS[action].mcp_name) is not None
    ]
    ordered = [name for name in ladder if name in rows]
    return tuple(ordered) + tuple(name for name in rows if name not in ordered)


def _declaration_findings(baseline: Baseline) -> list[str]:
    """The file against the constants, and the file against its own arithmetic."""
    out: list[str] = []
    if baseline.tokenizer != TOKENIZER:
        out.append(f"tokenizer is {baseline.tokenizer!r}, not {TOKENIZER!r}")
    if baseline.recipe != RECIPE:
        out.append(f"recipe is {baseline.recipe!r}, not {RECIPE!r}")
    if baseline.drift_tolerance != DRIFT_TOLERANCE:
        out.append(f"drift_tolerance is {baseline.drift_tolerance}, not {DRIFT_TOLERANCE}")
    if dict(baseline.ceilings) != dict(CEILINGS):
        out.append(f"ceilings are {dict(baseline.ceilings)}, not {dict(CEILINGS)}")
    if set(baseline.per_tool_compact) != set(baseline.per_tool_full):
        out.append("per_tool_compact and per_tool_full name different tools")
    for label, total, column in (
        ("default_compact", baseline.default_compact, baseline.per_tool_compact),
        ("default_full", baseline.default_full, baseline.per_tool_full),
    ):
        rows = sum(column.values())
        if total != rows:
            out.append(f"{label} is {total} and its per-tool rows sum to {rows}")
    return out


def _ceiling_findings(baseline: Baseline) -> list[str]:
    """Every frozen number against the ceiling that governs it."""
    out: list[str] = []
    per_tool = baseline.ceilings.get("per_tool", CEILINGS["per_tool"])
    for label, column in (("compact", baseline.per_tool_compact), ("full", baseline.per_tool_full)):
        for name, value in column.items():
            if value > per_tool:
                out.append(f"{name} {label} is {value} tokens, over the {per_tool} per-tool cap")
    default_cap = baseline.ceilings.get(DEFAULT_PROFILE, CEILINGS[DEFAULT_PROFILE])
    for label, value in (
        ("default_compact", baseline.default_compact),
        ("default_full", baseline.default_full),
        ("default_compact_corpus_required", baseline.default_compact_corpus_required),
    ):
        if value > default_cap:
            out.append(f"{label} is {value} tokens, over the {default_cap} ceiling")
    full_cap = baseline.ceilings.get("full", CEILINGS["full"])
    for label, held in (("full_compact", baseline.full_compact), ("full_full", baseline.full_full)):
        if held is not None and held > full_cap:
            out.append(f"{label} is {held} tokens, over the {full_cap} ceiling")
    chars = baseline.ceilings.get("instructions_chars", CEILINGS["instructions_chars"])
    for label, value in baseline.instructions_chars.items():
        if value > chars:
            out.append(f"instructions {label} is {value} chars, over the {chars} cap")
    return out


def _drift_findings(baseline: Baseline, measured: Measurement) -> list[str]:
    """Each frozen number against its live twin, and each `null` against a bless condition."""
    out: list[str] = []
    for label, frozen, now in (
        ("default_compact", baseline.default_compact, measured.default_compact),
        ("default_full", baseline.default_full, measured.default_full),
        (
            "default_compact_corpus_required",
            baseline.default_compact_corpus_required,
            measured.default_compact_corpus_required,
        ),
    ):
        out.extend(_one_drift(baseline, label, frozen, now))
    for column, live in (
        ("compact", (baseline.per_tool_compact, measured.per_tool_compact)),
        ("full", (baseline.per_tool_full, measured.per_tool_full)),
    ):
        frozen_rows, live_rows = live
        for name, value in frozen_rows.items():
            out.extend(_one_drift(baseline, f"{name} {column}", value, live_rows.get(name)))
    out.extend(_full_findings(baseline, measured))
    return out


def _full_findings(baseline: Baseline, measured: Measurement) -> list[str]:
    """The two totals 10:2593 leaves `null`, and the three things that can be wrong with them."""
    out: list[str] = []
    complete = measured.measured("full")
    missing = ", ".join(measured.omitted.get("full", ()))
    for label, frozen, now in (
        ("full_compact", baseline.full_compact, measured.full_compact),
        ("full_full", baseline.full_full, measured.full_full),
    ):
        if frozen is None and complete:
            out.append(f"{label} is null and the full roster now renders: re-bless it")
        elif frozen is not None and not complete:
            out.append(f"{label} is {frozen} and {missing} do not render: it counts a subset")
        elif frozen is not None:
            out.extend(_one_drift(baseline, label, frozen, now))
    return out


def _one_drift(baseline: Baseline, label: str, frozen: int, now: int | None) -> list[str]:
    """One comparison, with an absent measurement reported rather than skipped."""
    if now is None:
        return [f"{label} is frozen at {frozen} and nothing renders it any more"]
    moved = drift(frozen, now)
    if moved > baseline.drift_tolerance:
        return [
            f"{label} drifted {moved:.1%} ({frozen} to {now}), over "
            f"{baseline.drift_tolerance:.0%}: re-bless {baseline.path.name} in the same change"
        ]
    return []


def _instruction_findings(baseline: Baseline, measured: Measurement) -> list[str]:
    """The live `instructions` strings against the cap, including the two with no frozen slot."""
    cap = baseline.ceilings.get("instructions_chars", CEILINGS["instructions_chars"])
    return [
        f"instructions {label} is {value} chars, over the {cap} cap (SV2)"
        for label, value in measured.instructions_chars.items()
        if value > cap
    ]


def _int(raw: Mapping[str, Any], key: str) -> int:
    """One integer field, with anything else reading as zero and becoming a finding."""
    value = raw.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _optional_int(raw: Mapping[str, Any], key: str) -> int | None:
    """One integer field where `null` is a declared value and not an absence."""
    value = raw.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _ints(raw: Mapping[str, Any], key: str) -> Mapping[str, int]:
    """One block of integers, dropping any row that is not one."""
    value = raw.get(key)
    if not isinstance(value, dict):
        return MappingProxyType({})
    return MappingProxyType(
        {
            str(name): number
            for name, number in value.items()
            if isinstance(number, int) and not isinstance(number, bool)
        }
    )
