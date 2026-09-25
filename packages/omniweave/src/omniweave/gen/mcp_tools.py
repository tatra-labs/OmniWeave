"""Artefact 1: `schema/mcp-tools-v1.json`, the `tools/list` payload. 10 section 2.3; 18 section 3.

10:208's row: generated from *"`mcp_name`, `listed_in`, `read_only`, `idempotent`, `open_world`,
`destructive`, `inp`, `summary`, `decision`, `example`, `advanced`"*, consumed by *"the MCP
server's `tools/list`"*. 18:1234 says the same from the other end: *"Everything in this section is
`T-GENERATED` from `ACTIONS` into `schema/mcp-tools-v1.json` and byte-diff gated (G25)."*

The file is the **payload and not a schema of one**, which is worth saying because it lives in a
directory of JSON Schemas. 01:562 fixes it: *"A violation looks like. A tool description edited in
`mcp-tools-v1.json`"* -- a description is data, and a schema of a tool object would not carry one.
The `inputSchema` values inside the payload are JSON Schemas, and those are what 18:2262's
`ow surface typescript` reads to emit `omniweave.d.ts`.

## WHAT IS DERIVED, AND WHAT IS TRANSCRIBED

Derived from `ACTIONS`, every time: `name` from `mcp_name`; all four `annotations` from the four
booleans; whether an `outputSchema` is declared, from `out`; the unlisted tools' steering clause,
from `summary` and `listed_in`.

**Which rows appear is not a profile decision.** A tool object carries no `listed_in` channel and
the file is one file, so the artefact is every tool this build can render and the server selects by
profile at `tools/list` time -- which is also what makes `[serve] compact_schemas` a transform over
this payload rather than a second committed file. Four rows today, and they coincide with the
`default` profile only because the narrow roster's schemas are unwritten. D318 records that 10:208
names `listed_in`, `decision`, `example` and `advanced` among this artefact's sources and omits
`out`, which is the field two of the four objects cannot be assembled without.

Transcribed: the `description` prose and the `inputSchema` bodies, both printed in full at 18:1250
and 18:1331-1362 and both **measured** -- 10:336 gives 608, 334, 481 and 303 description characters
and 411, 258, 189 and 173 full tokens per tool. Every one of those eight figures is reproduced
exactly by the objects this module builds, which is what a transcription is for: a generator that
rebuilt this prose would emit a payload nobody counted, and the count is half the specification.

They are transcribed because **reflection cannot produce them**, and that is structural rather than
a shortcut. `tools/schemagen.py`'s own inventory row for this file says it: *"a tool object is not
an `ActionSpec` -- it is a name, a description, four annotations and two JSON Schemas DERIVED from
one. Reflection cannot produce it."* Concretely, `QueryIn.corpus` is `str | None` and carries
neither the sentence *"ONE QUERY ADDRESSES ONE CORPUS."* nor the 4,096-character cap on its
neighbour: `surface/inputs.py`'s own docstring states that a dataclass field carries no bound,
because the generator prints bounds and the handler enforces them and neither wants an annotation.

So the bounds are **bound and not re-spelled**. Every numeric limit and every enum below is the
`Final` in `omniweave.surface.inputs`, and `max_chars`' `maximum` reaches `HARD_CEILING` through
it, which is 18:1729's *"one ceiling for every tool"* arriving in the published schema by
identity rather than by coincidence. The one exception is `route_hints`, and it is an exception for
a stated reason: 18:1276's three published fields are a NARROWING of `omniweave.route.RouteHints`
that this generator performs, so the narrowing's bounds are this module's.

## ORDER: SORTED, AND THE CONTRAST WITH ARTEFACT 2 IS DELIBERATE

10:225 requires *"Actions by `name`"*, which gives add, corpora, open, query. Artefact 2 is
published in the decision ladder instead -- query, open, corpora, add -- and D312 is the entry for
that, so the two artefacts of this package disagree about the order of the same four tools.

The distinction is which of them the plan prints WHOLE. 10:874 prints the instructions string
complete, in an order five other sites repeat, and reordering it would move the one writer to the
top of the first prose an agent reads. This artefact is never printed whole: 18 §3.1 prints one
tool object and §3.2 prints three more, as exposition of four tools rather than as a file. With no
printed artefact to contradict it, 10:225's rule applies unamended, and a `tools/list` array is a
catalog a host renders rather than prose an agent reads top to bottom.

## ALL FOUR ANNOTATION KEYS, ALWAYS -- AND THE PRINTED `ow_corpora` HAS THREE

10:216: *"Every annotation key is emitted for every tool, never conditionally on its value ...
because a pure generator reading four non-defaulted booleans cannot print a key for three tools and
drop it for a fourth -- a missing key would mean the generator branched, and G25's byte-diff would
be gating a shape nobody declared."* 10:221 gives the consequence that is not merely tidiness:
*"`destructiveHint` in particular is never omitted, because MCP reads an absent `destructiveHint`
as `true`."*

18:1345's printed `ow_corpora` omits it. Emitting it costs six tokens, and those six tokens move
five frozen figures -- D316 is the entry and the arithmetic is there. `annotations()` below cannot
express the omission: it iterates a four-member tuple of `(key, field)` pairs, so there is no
branch to take.
"""

from __future__ import annotations

import json
from dataclasses import fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import SurfaceError

from omniweave.surface.inputs import (
    CONTEXT_DEFAULT,
    CONTEXT_MAX,
    CONTEXT_MIN,
    CORPORA_DETAILS,
    HARD_CEILING,
    MAX_CHARS_MIN,
    QUERY_MAX_CHARS,
    REF_MAX,
    SOURCE_MAX,
    WANTS,
)
from omniweave.surface.registry import ACTIONS, DEFAULT_PROFILE, ActionSpec, listed
from omniweave.surface.schema import compact, with_required_corpus

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "ANNOTATIONS",
    "DEADLINE_MS_MAX",
    "DEADLINE_MS_MIN",
    "DESCRIPTIONS",
    "INPUT_SCHEMAS",
    "MAX_RUNG_MEMBERS",
    "OUTPUT_SCHEMAS",
    "PUBLISHED",
    "STEERING",
    "description",
    "hints",
    "listing",
    "omitted",
    "render",
    "tool",
    "tools",
]


# =============================================================================================
# 1. The four annotation keys, and the two bounds `inputs.py` does not own
# =============================================================================================

ANNOTATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("readOnlyHint", "read_only"),
    ("destructiveHint", "destructive"),
    ("idempotentHint", "idempotent"),
    ("openWorldHint", "open_world"),
)
"""Each published annotation key beside the `ActionSpec` field that produces it. 10:214.

A tuple of pairs rather than four lines of dict literal, because 10:216 forbids the generator from
branching on a value and a loop over a fixed tuple cannot. The ORDER is 18:1252's, which three of
the four printed tool objects agree on; 10:214 lists the same four keys in a different order, in
prose, where it is naming them rather than serializing them.

The second element is a field name resolved with `getattr`, so a renamed `ActionSpec` field fails
here at import rather than silently publishing `false` -- `_published_failures()` reads it too.
"""

MAX_RUNG_MEMBERS: Final[tuple[str, ...]] = (
    "gate",
    "decode",
    "repair",
    "page",
    "regen",
    "degrade",
    "enrich",
)
"""`route_hints.max_rung`'s seven members, 18:1284, lower case.

18:1300 fixes the casing and gives the reason a generator cares about: *"the lock's rule is that
the wire value is the lower-case member name and one byte-diff-gated generator cannot emit two
casing conventions without a special case nobody declared."*

**Spelled here and bound to `omniweave.route.rung.Rung` by a test rather than by an import**, which
is the one place this module copies a name that has a home. Importing it costs 47 modules and opens
`_socket`, measured -- the same charge D298 refused on the registry's front door, and a renderer
that reached the pricebook parser to read seven strings would put a socket in the emitter's import
set for no gain. The test imports `Rung` and asserts this tuple is `tuple(r.name.lower() for r in
Rung)`, so a member added to the ladder fails the build without the generator paying for the
router.
"""

DEADLINE_MS_MIN: Final[int] = 100
DEADLINE_MS_MAX: Final[int] = 120_000
"""`route_hints.deadline_ms`' published bounds, 18:1289.

The only two numeric limits in this file with no `Final` in `surface/inputs.py`, and the absence is
correct: `route_hints` is not a surface-declared parameter object. It is 18:1276's narrowing of
`RouteHints` to three of its five fields, performed by this generator, so its bounds belong to the
narrowing and there is no declaration for them to drift from.
"""

STEERING: Final[str] = "Prefer ow_query, which returns the passages themselves in one call."
"""10:851's clause, *"generated, not written"*, ending every unlisted tool's description.

18:1373 gives the reason and it is not politeness: *"so steering survives re-listing"*. A user who
sets `OMNIWEAVE_MCP_LISTED=all` gets a surface whose narrow Actions still point back at the
composite, which is why the clause is a property of the ACTION -- not in the `default` profile --
and not of the profile being served. codegraph's `tools.ts:1043` is the source of the rule.
"""


# =============================================================================================
# 2. The transcribed halves: four descriptions and four input schemas
# =============================================================================================

DESCRIPTIONS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ow_query": (
            "Answer a question from indexed documents. Returns the passages themselves — verbatim "
            "where the source allows it — grouped by document, each with a citation id, page and "
            "polygon provenance, a fidelity tier, and a verdict that says whether a zero result "
            "actually proves absence. Use this instead of opening, converting or grepping an "
            "indexed PDF/DOCX/PPTX/XLSX. If you already hold a `d7#412` citation, a `p14/3` "
            "address, a page range or a document path, use ow_open instead.\n"
            "\n"
            "Examples: 'parental leave accrual' · 'what does the MSA say about termination for "
            "convenience' · 'the table of per-region headcount'."
        ),
        "ow_open": (
            "Fetch exact passages you already have an address for: one or more `d7#412` citations, "
            "a `p14/3` address, a page range, or a whole document. Returns the same "
            "provenance-carrying blocks as ow_query, without ranking. Use it to resolve a "
            "citation, follow a cross-reference, or read a document you were told about — never "
            "re-Read the file."
        ),
        "ow_corpora": (
            "List the corpora this server can read — the deployment's [corpora] registry — and "
            "what is in each: document and page counts, formats, date range, languages, an outline "
            "sample, KNOWN GAPS (pages whose OCR failed, encrypted files, tables that timed out), "
            "freshness, the fraction of blocks that are byte-quotable, and the capability floor "
            "the indexed drivers actually achieved. Call it first when you do not know what "
            "exists, and read the gaps before you conclude something is absent."
        ),
        "ow_add": (
            "Index documents into a corpus so ow_query can cite them. Accepts files, directories "
            "and URLs. Free and local work runs immediately; anything that would spend money is "
            "NOT run — it returns as a pending cost with the exact command that approves it. Safe "
            "to call twice: identical bytes are never re-parsed."
        ),
    }
)
"""The four front-door descriptions, transcribed from 18:1250 and 18:1331-1362 and measured.

608, 334, 481 and 303 characters, which is 10:336's `description chars` column exactly. They are
not derived from `summary` and `decision`, and they cannot be: check 7 caps `summary` at 160
characters and `decision` at 90, and 250 characters of catalog row do not contain 608 characters of
prose. `ActionSpec` carries no `description` field in 10:124 or in the charter, so 10:208's source
column names no field that could produce this. **D317 is the entry**, and the completeness rule
below is what keeps the gap from widening: a fifth Action in the `default` profile fails at import.

The two channels are worth keeping separate rather than collapsing, which is the argument the
amendment should carry. A `decision` clause is read at PICK time inside a tool catalog and is
capped for a table; a `description` is read by a host at the same moment but is the only place the
verb can live (*"Never grep a PDF"*, *"never re-Read the file"*). 10:268 already protects this
text by name -- *"never shorten a description"* -- which is a rule about an artefact the field list
does not mention.
"""

INPUT_SCHEMAS: Final[Mapping[str, Mapping[str, Any]]] = MappingProxyType(
    {
        "ow_query": {
            "type": "object",
            "additionalProperties": False,
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "maxLength": QUERY_MAX_CHARS},
                "corpus": {
                    "type": "string",
                    "description": (
                        "From ow_corpora — a name in the deployment's [corpora] registry. Omit "
                        "for the default corpus. ONE QUERY ADDRESSES ONE CORPUS."
                    ),
                },
                "scope": {
                    "type": "string",
                    "description": (
                        "'policy.pdf' | 'policy.pdf#p12-40' | 'd7' | 'contracts/2025/**'"
                    ),
                },
                "want": {"type": "string", "enum": list(WANTS), "default": WANTS[0]},
                "route_hints": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": "RouteHints. Cannot widen budget, egress or licence policy.",
                    "properties": {
                        "lane": {"type": "string"},
                        "max_rung": {"type": "string", "enum": list(MAX_RUNG_MEMBERS)},
                        "deadline_ms": {
                            "type": "integer",
                            "minimum": DEADLINE_MS_MIN,
                            "maximum": DEADLINE_MS_MAX,
                        },
                    },
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": MAX_CHARS_MIN,
                    "maximum": HARD_CEILING,
                },
            },
        },
        "ow_open": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ref"],
            "properties": {
                "ref": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}, "maxItems": REF_MAX},
                    ],
                    "description": (
                        "'d7#412' | 'handbook:d7#412' | 'policy.pdf#p14/3' | "
                        "'policy.pdf#p12-18' | 'policy.pdf'"
                    ),
                },
                "corpus": {"type": "string"},
                "context": {
                    "type": "integer",
                    "minimum": CONTEXT_MIN,
                    "maximum": CONTEXT_MAX,
                    "default": CONTEXT_DEFAULT,
                },
                "layers": {"type": "array", "items": {"type": "string"}},
                "max_chars": {
                    "type": "integer",
                    "minimum": MAX_CHARS_MIN,
                    "maximum": HARD_CEILING,
                },
            },
        },
        "ow_corpora": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "corpus": {"type": "string"},
                "detail": {
                    "type": "string",
                    "enum": list(CORPORA_DETAILS),
                    "default": CORPORA_DETAILS[0],
                },
            },
        },
        "ow_add": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source"],
            "properties": {
                "source": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}, "maxItems": SOURCE_MAX},
                    ]
                },
                "corpus": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
            },
        },
    }
)
"""The four published `inputSchema` objects, 18:1257, 18:1334, 18:1350 and 18:1357.

Property order is the published order and 10:226 makes it load-bearing: *"schema properties in
declaration order (which is `dataclasses.fields` order, itself stable)"*. It is asserted rather
than assumed -- `_published_failures()` compares each object's property keys against
`dataclasses.fields(spec.inp)` name for name and position for position, so adding a field to
`QueryIn` without publishing it, or publishing one the dataclass does not declare, fails at import
rather than at the byte diff.

`ow_corpora` has no `required` key at all, which is not an omission: both of its parameters are
optional, and an empty `required: []` is a different document from an absent one.
"""

OUTPUT_SCHEMAS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "ow_corpora": "schema/corpora-out-v1.json",
        "ow_add": "schema/add-out-v1.json",
    }
)
"""The two tools that declare an `outputSchema`, 18:1348 and 18:1355, and their `$ref` targets.

18:1315 is the decision and it is a measurement, not a preference: *"There is deliberately no
`outputSchema` and no `structuredContent` on `ow_query` or `ow_open`: declaring one obliges
conforming structured content, which in hosts that also emit the serialized-JSON text block
DOUBLES a 22,000-character answer. `ow_corpora` and `ow_add` are small and row-shaped and do
declare one."*

The split is exactly *`out is Answer`* -- the two retrievers pack prose, the two row-shaped tools
return a report -- and `_published_failures()` asserts that correspondence rather than letting this
mapping be an independent opinion. 10:208's source column does not name `out`, which is the third
leg of D317: two of the four tool objects cannot be assembled without reading it.

`schema/open-out-v1.json` exists and is deliberately absent here. 18:1320: *"it is the `--render
json` shape for `ow open`, not an MCP `outputSchema`"*.
"""

PUBLISHED: Final[frozenset[str]] = frozenset(DESCRIPTIONS)
"""The tools this build can render. Four today, and the roster below names who is waiting."""


# =============================================================================================
# 3. What must hold for a published object to be assemblable at all
# =============================================================================================


def _by_mcp_name() -> Mapping[str, ActionSpec]:
    """`ACTIONS` re-keyed on `mcp_name`, excluding the five that have none.

    Check 2 of 10:184 has already guaranteed the keys are unique by the time this runs, which is
    why it is a dict comprehension and not a loop that reports collisions.
    """
    return {spec.mcp_name: spec for spec in ACTIONS.values() if spec.mcp_name is not None}


def _published_failures() -> tuple[str, ...]:
    """Every reason a published object could not be assembled, or would be assembled wrong.

    Five clauses, and each fails at IMPORT because each describes a defect in shipped source that
    no configuration can cause:

    1. a `DESCRIPTIONS` or `INPUT_SCHEMAS` key that is not any Action's `mcp_name` -- prose for a
       tool that does not exist, which is LEANN's manifest defect written the other way round;
    2. the two mappings disagreeing about which tools are published -- half a tool object;
    3. a published `inputSchema` whose property keys are not `dataclasses.fields(inp)`' names in
       `dataclasses.fields(inp)`' order, which is 10:226 asserted rather than trusted;
    4. an `OUTPUT_SCHEMAS` membership that disagrees with 18:1315's rule that the two prose
       retrievers declare none and the two row-shaped tools declare one;
    5. an Action listed in the `default` profile with nothing published for it -- the clause that
       makes a fifth front-door tool a build failure rather than a silently three-tool file.
    """
    by_name = _by_mcp_name()
    out: list[str] = []
    for tool_name in sorted(set(DESCRIPTIONS) | set(INPUT_SCHEMAS) | set(OUTPUT_SCHEMAS)):
        if tool_name not in by_name:
            out.append(f"{tool_name}: published here, but no Action declares that mcp_name")
            continue
        if (tool_name in DESCRIPTIONS) != (tool_name in INPUT_SCHEMAS):
            out.append(f"{tool_name}: needs both a description and an inputSchema; one is missing")
            continue
        spec = by_name[tool_name]
        if tool_name in INPUT_SCHEMAS:
            published = tuple(INPUT_SCHEMAS[tool_name]["properties"])
            declared = tuple(field.name for field in fields(spec.inp))
            if published != declared:
                out.append(
                    f"{tool_name}: published properties {list(published)} are not "
                    f"{spec.inp.__name__}'s fields in declaration order {list(declared)}"
                )
        row_shaped = spec.out is not ACTIONS["query"].out
        if row_shaped != (tool_name in OUTPUT_SCHEMAS):
            out.append(
                f"{tool_name}: out is {spec.out.__name__} and outputSchema is "
                f"{'declared' if tool_name in OUTPUT_SCHEMAS else 'absent'}; 18:1315 pairs them"
            )
    out.extend(
        f"{spec.mcp_name}: listed in {DEFAULT_PROFILE!r} and nothing is published for it"
        for spec in ACTIONS.values()
        if DEFAULT_PROFILE in spec.listed_in and spec.mcp_name not in PUBLISHED
    )
    return tuple(out)


_FAILURES: Final[tuple[str, ...]] = _published_failures()
if _FAILURES:  # pragma: no cover -- the shipped registry has no such row; the test builds one
    raise SurfaceError(
        "artefact 1 cannot be assembled from the registry: " + "; ".join(_FAILURES),
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix="reconcile gen/mcp_tools.py with surface/registry.py, or land the missing publication",
    )


def unpublished() -> tuple[str, ...]:
    """Tools with an `mcp_name` this build cannot render, sorted. Reported, never raised.

    Five today, all of them `full`-profile rows W7.1b landed: `ow_coverage`, `ow_diff`, `ow_doctor`,
    `ow_explain` and `ow_grid`. Their Actions exist and their input types exist; what does not
    exist is a published `inputSchema` for any of them, because no document prints one -- 10:807's
    roster gives each row a one-line *"what it adds over the front door"* and nothing else, and
    18 §3 prints objects for the front door only.

    This is `_unrostered_full()`'s shape one package over and for its reason: the distance between
    what the plan specifies and what this build can emit should be a number a test pins rather than
    something a reader reconstructs. Raising would instead make the artefact unemittable until
    every narrow schema is written, which would delay a gate over four correct tool objects on
    account of five that nothing can write yet.
    """
    return tuple(
        sorted(
            spec.mcp_name
            for spec in ACTIONS.values()
            if spec.mcp_name is not None and spec.mcp_name not in PUBLISHED
        )
    )


# =============================================================================================
# 4. Building one tool object
# =============================================================================================


def hints(spec: ActionSpec) -> dict[str, bool]:
    """The four MCP annotation hints for one Action. Always four keys, in 18:1252's order.

    10:216 is a rule about the GENERATOR and not only about the output: *"a pure generator reading
    four non-defaulted booleans cannot print a key for three tools and drop it for a fourth."* This
    reads a fixed tuple of pairs, so there is no branch that could omit one -- which is the only
    way to hold a rule like that rather than to remember it.

    **Named `hints` and not `annotations`**, although `annotations` is the published key and would
    read better. `from __future__ import annotations` binds that name at module scope in every file
    in this repository, so a module-level `def annotations` replaces the `__future__` feature object
    with a function -- the same shadowing hazard the package docstring records for `emit()` and
    `instructions()`, arrived at from a different direction. `hints` is what MCP calls the four
    fields anyway: every one of them ends in `Hint`.
    """
    return {key: bool(getattr(spec, field)) for key, field in ANNOTATIONS}


def description(spec: ActionSpec) -> str:
    """One Action's published description: the transcribed prose, or `summary` plus the clause.

    10:851 covers the second case -- *"Every unlisted tool's description ends with the same
    clause, generated, not written"* -- and `summary` is the only per-Action prose 10:208's source
    column names, so it is the body the clause is appended to. The stop is added here because check
    7 forbids a `summary` that ends in one, which makes the two sentences joinable without a test
    for whether the join produced two stops.

    `listed_in` rather than the profile being served: 18:1373's whole point is that the steering
    *"survives re-listing"*, so a `full`-profile tool carries the clause when `full` is served.
    """
    name = spec.mcp_name
    if name is not None and name in DESCRIPTIONS:
        return DESCRIPTIONS[name]
    return f"{spec.summary}. {STEERING}"


def tool(spec: ActionSpec) -> dict[str, Any]:
    """One `tools/list` entry, in 18:1250's key order.

    **No `outputSchema` goes on the wire, although 18:1348 and 18:1357 print one** (D549). The two
    printed objects are `{"$ref": "schema/corpora-out-v1.json"}` and `add-out-v1.json`'s: a path
    relative to this repository, which no MCP client can resolve. The reference client validates
    `structuredContent` against a listed `outputSchema` on every call, and fails either way:
    `jsonschema` raises `Unresolvable` on the reference, and a result without `structuredContent`
    is *"Tool ... has an output schema but did not return structured content"*. Both schemas'
    roots are also arrays, and MCP's `structuredContent` is an object. So the two row-shaped tools
    return their JSON as one text block, `OUTPUT_SCHEMAS` still records which tools are
    row-shaped (18:1315's pairing, and `llms.txt`'s `output` line), and the schema files remain
    the `--render json` contract.
    """
    name = spec.mcp_name
    if name is None or name not in PUBLISHED:
        raise KeyError(f"{spec.name}: nothing is published for it; see unpublished()")
    built: dict[str, Any] = {
        "name": name,
        "description": description(spec),
        "annotations": hints(spec),
    }
    built["inputSchema"] = json.loads(json.dumps(INPUT_SCHEMAS[name]))
    return built


def tools() -> tuple[dict[str, Any], ...]:
    """Every renderable tool object, sorted by Action `name`. 10:225.

    `ACTIONS` is insertion-ordered and its insertion order is the decision ladder, so this sort is
    a real reordering and not a no-op over a dict that happens to be alphabetical: it gives add,
    corpora, open, query. The module docstring argues why this artefact takes the rule and artefact
    2 does not.
    """
    return tuple(
        tool(ACTIONS[name]) for name in sorted(ACTIONS) if ACTIONS[name].mcp_name in PUBLISHED
    )


def omitted(profile: str = DEFAULT_PROFILE) -> tuple[str, ...]:
    """The `mcp_name`s `profile` lists and this build cannot render, sorted.

    `unpublished()` narrowed to one profile, and the two answer different questions. That one is
    the distance between the registry and the generator; this one is the distance between what an
    operator asked to see and what `tools/list` can send them. For `default` it is empty and
    `_published_failures()` is what keeps it so; for `full` it is five of 10:807's eighteen rows,
    and 10:2593 is the consequence -- the `full_*` totals stay unmeasured until it is empty.
    """
    return tuple(
        sorted(
            name
            for action in listed(profile)
            if (name := ACTIONS[action].mcp_name) is not None and name not in PUBLISHED
        )
    )


def listing(
    profile: str = DEFAULT_PROFILE,
    *,
    compact_schemas: bool = True,
    corpus_required: bool = False,
) -> tuple[dict[str, Any], ...]:
    """What `tools/list` sends for one profile: `tools()` selected, compacted and promoted.

    `tools()` is this module's docstring's *"every tool this build can render"*, and it is one
    file. What one request receives is three transforms over it -- select by `listed_in`, strip the
    `advanced` parameters under `[serve] compact_schemas` (10:495), and promote `corpus` into
    `required` when `[serve] default_corpus` does not resolve (10:525) -- and until now the three
    had no single caller, so nothing measured the thing an agent actually pays for.

    **The transform order is asserted rather than assumed.** Compaction removes properties and the
    promotion re-derives `required` in property order, so promoting first would let the strip
    remove a property that `required` now names -- a schema requiring a parameter it does not
    declare. It cannot happen today because no Action declares `corpus` advanced, and that is a
    property of the registry rather than of this order, so a test pins both.

    **This is the function `omniweave_serve` cannot reach.** 02:350 gives that distribution
    `["omniweave_core", "omniweave_ports"]`, so it holds the catalogue bytes and none of the three
    transforms. D340 was decided for route 2: `omniweave.gen.listing` renders each listed tool's
    transformed forms, with the same two functions this one applies, into
    `omniweave_serve/mcp-listing-v1.json`, and the server selects from that file.
    `test_gen_listing.py` binds its selection to this module's transforms.
    """
    built: list[dict[str, Any]] = []
    for action in listed(profile):
        spec = ACTIONS[action]
        if spec.mcp_name not in PUBLISHED:
            continue
        entry = tool(spec)
        if compact_schemas:
            entry = compact(entry)
        if corpus_required:
            entry = with_required_corpus(entry)
        built.append(entry)
    return tuple(built)


def render() -> bytes:
    """`schema/mcp-tools-v1.json`'s committed bytes. Artefact 1's entry in `emit.RENDERERS`.

    Two-space indent, `ensure_ascii=False`, no key sort, one trailing newline -- `schemagen.py`'s
    `render()` exactly, because a reviewer reading a diff across `schema/` should not have to hold
    two house styles. `ensure_ascii=False` is additionally load-bearing here and 10:332 says why:
    *"the descriptions contain `—` and `·`, and `ensure_ascii=True` would emit them as
    six-character `\\uXXXX` escapes, inflating the count by an artefact of the serializer rather
    than of the wire."*

    Returns `bytes` rather than text, so 10:228's *"`\\n`-terminated UTF-8 with no BOM"* is met
    structurally: there is no text-mode handle in the path and `emit.write()` is the only writer.
    `allow_nan=False` because NaN is not JSON, and nothing here can produce one.
    """
    text = json.dumps(list(tools()), indent=2, ensure_ascii=False, allow_nan=False, sort_keys=False)
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8") + b"\n"
