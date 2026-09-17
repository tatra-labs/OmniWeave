"""`compact_schemas`: what is stripped, what is still honoured. 10 section 3.3, 10 section 3.4.

10:495 prints this module's first two names and 10:530 prints its third. It holds the three
transformations a published tool object goes through between the registry and the wire, and it
holds the snapshot that makes the first of them safe:

    _ADVANCED             per tool, the parameters `[serve] compact_schemas = true` removes
    _DECLARED_ARG_KEYS    per tool, every parameter the handler honours -- taken BEFORE the strip
    compact()             the strip plus the enum demotion
    with_required_corpus()  section 3.4's promotion, on a copy

## WHAT THIS MODULE IS NOT

It does not BUILD a tool object. 02:254's row 30 gives this package the registry and forbids it
*"emitting the artefacts (row 31's job)"*, and a tool object is six keys -- `name`, `description`,
`annotations`, `inputSchema`, sometimes `outputSchema` -- derived from an `ActionSpec` rather than
read off one. 10:530's signature is the boundary written down: `with_required_corpus(tool: dict)`
takes a tool that already exists. `omniweave/gen/` builds them, W7.2 owns it, and G25 byte-diffs
what it writes.

So every function here is a `Mapping -> dict` transformation over a tool object somebody else
assembled, and the two module constants are the only things here derived from `ACTIONS`.

## THE SNAPSHOT IS THE WHOLE POINT

10:505 states the rule as a recorded bug fix: *"`_DECLARED_ARG_KEYS` is snapshotted **before** the
strip. A hidden-but-honoured parameter must never be reported as an unknown argument. The
dispatcher validates against the snapshot; the schema is what the strip produced."*

It is snapshotted before the strip **because it is not built from a schema at all.** It reads
`ActionSpec.inp`'s fields, which is the declaration, and the strip operates on a published tool
object, which is downstream of it. The ordering the plan states as a discipline is therefore
structural here: there is no code path by which the strip could reach this mapping, because the
strip takes a `tool` and this takes `ACTIONS`.

10:516 is the sentence that makes the pair coherent, and it reads like a contradiction until the
two channels are separated: *"`additionalProperties: false` survives compaction. That is not a
contradiction: the schema declares a closed object while the dispatcher validates against
`_DECLARED_ARG_KEYS`, which is the pre-strip set. A host that validates client-side will reject an
advanced parameter it cannot see -- which is correct behaviour for a host that only knows the
compact schema -- while a host that forwards it unvalidated reaches a handler that honours it.
Neither path silently drops the value."*

## `_ADVANCED` IS DERIVED, AND 10:495 WRITES IT AS A LITERAL

10:495's code block writes the mapping out by hand, three rows, with the comment
`# == ActionSpec.advanced, per Action` beside it. Taken literally that is a second home for a field
10:137 puts on `ActionSpec`, and INV-21 gives a name one home -- so a hand-written copy would be a
place for `ow_query`'s advanced set to disagree with `ACTIONS["query"].advanced` in exactly the way
INV-20 exists to prevent one document disagreeing with a server. It is derived. The comment is
read as the specification and the literal as its illustration. D308 is the entry.

The derivation also explains an absence the plan states separately: `ow_corpora` has no row here,
because it declares no advanced parameters, which is 10:356's *"the one listed tool compaction does
not change"*.

## KEYED ON `mcp_name`, WHICH EXCLUDES FIVE ACTIONS BY CONSTRUCTION

Both mappings are keyed on the tool name rather than the Action name, because both are read by a
dispatcher holding a `tools/call` request whose `name` is an `mcp_name`. The consequence is that
`HUMAN_ONLY`'s five never appear: `mcp_name is None` is 10:1540's *"structural, not a denylist"*,
so an Action no agent can dispatch has no argument set an agent could be told about. The CLI does
not read these mappings -- argparse already knows every parameter, because `omniweave/gen/`
generated the parser from the same `inp`.
"""

from __future__ import annotations

from dataclasses import MISSING, fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import SurfaceError

from omniweave.surface.registry import ACTIONS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


__all__ = [
    "CORPUS_PARAM",
    "CORPUS_SCOPED",
    "ENUM_DEMOTE_MAX",
    "KNOWN_TOOLS",
    "advanced_args",
    "compact",
    "declared_arg_keys",
    "unknown_args",
    "with_required_corpus",
]


ENUM_DEMOTE_MAX: Final[int] = 12
"""The member count above which a compact schema demotes an enum instead of printing it. 10:507.

*"Where a parameter's enum exceeds 12 members it becomes a free-form string with the members named
in the description -- jcodemunch's `_COMPACT_DEMOTE_ENUM_PARAMS` reclaimed ~200 tokens from a
76-value `language` enum this way, and the parameter stayed fully usable."*

**Exceeds, so twelve members keep their enum and thirteen do not.** The saving is structural rather
than textual: a JSON enum member costs its own quotes, its own comma and its own indented line,
while a member named in a description costs the word and a separator. That is why the demotion is a
saving at all, and why demoting a five-member enum would not be worth the loss of client-side
validation.

10:510 says the only candidate in omniweave today is `route_hints.lane`, *"an open registry, which
is a free string in the schema for exactly this reason"* -- so it is already demoted at the
declaration and this rule never fires on it. `want` (5) and `max_rung` (7) are closed and small and
keep their enums. The rule ships ahead of a parameter that needs it because the alternative is
discovering the ceiling from a budget failure.
"""

CORPUS_PARAM: Final[str] = "corpus"
"""The parameter 10:525 promotes into `required` when `[serve] default_corpus` does not resolve."""


def _snapshot_before_strip(actions: Mapping[str, Any]) -> Mapping[str, frozenset[str]]:
    """10:500's spelling, and the function name is the specification.

    Every published parameter of every agent-reachable Action, read from `ActionSpec.inp`'s fields
    rather than from any schema. A mapping built from the declaration cannot be downstream of a
    transformation applied to a document, which is what makes *"snapshotted before the strip"* a
    property of the code rather than a rule someone has to keep.
    """
    return MappingProxyType(
        {
            spec.mcp_name: frozenset(field.name for field in fields(spec.inp))
            for spec in actions.values()
            if spec.mcp_name is not None
        }
    )


_DECLARED_ARG_KEYS: Final[Mapping[str, frozenset[str]]] = _snapshot_before_strip(ACTIONS)
"""Per tool, every parameter the handler honours. 10:500, and 18:1310 spells it the same way."""

_ADVANCED: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        spec.mcp_name: spec.advanced
        for spec in ACTIONS.values()
        if spec.mcp_name is not None and spec.advanced
    }
)
"""Per tool, the parameters the strip removes. 10:495, DERIVED from `ActionSpec.advanced`.

A tool with no advanced parameters has no row, which is how 10:495's own literal writes it: three
rows for four listed tools, because `ow_corpora` declares none.
"""

KNOWN_TOOLS: Final[frozenset[str]] = frozenset(_DECLARED_ARG_KEYS)
"""Every `mcp_name` in the registry. The set `compact()` looks a tool up in.

A tool object whose `name` is not in here compacts to an equal copy of itself, and that is not a
hole. The tool array is generated from `ACTIONS` by `omniweave/gen/` and byte-diff gated by G25, so
a name this set does not carry cannot survive `ow surface emit --check` -- and refusing here would
mean choosing an `OW-A-*` code for a condition no document describes, which is how a register grows
a row nobody can cite.
"""


def _unsatisfiable_rows() -> tuple[str, ...]:
    """Actions whose `advanced` set names a REQUIRED parameter, which the strip cannot honour.

    Stripping a required property from an object that also declares `additionalProperties: false`
    publishes a schema no document can satisfy: the property is demanded and cannot be supplied.
    Nothing in 10 section 2.2's eleven forbids it -- check 11 asks only that every `advanced` member
    be a field of `inp`, and a field with no default is a field -- so the combination is
    representable and would ship as a tool no host could call. D309 is the entry.

    Raised rather than reported, and at import rather than at generation, because it is the one
    condition in this module that makes a PUBLISHED artefact wrong rather than merely large.
    """
    out: list[str] = []
    for name, spec in ACTIONS.items():
        required = {
            field.name
            for field in fields(spec.inp)
            if field.default is MISSING and field.default_factory is MISSING
        }
        clash = sorted(spec.advanced & required)
        if clash:
            out.append(f"{name}: advanced names the required parameter(s) {', '.join(clash)}")
    return tuple(out)


_UNSATISFIABLE: Final[tuple[str, ...]] = _unsatisfiable_rows()
if _UNSATISFIABLE:  # pragma: no cover -- the shipped registry has no such row; the test builds one
    raise SurfaceError(
        "an advanced parameter is required, so the compact schema would be unsatisfiable: "
        + "; ".join(_UNSATISFIABLE),
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix="give the parameter a default, or drop it from `advanced` in surface/registry.py",
    )


def declared_arg_keys(tool_name: str) -> frozenset[str]:
    """Every parameter `tool_name` honours, advanced ones included. The dispatcher's set.

    A public reader over `_DECLARED_ARG_KEYS`, because 10:500's spelling carries the leading
    underscore and a second module reaching a private name would be worse than the name.
    """
    return _DECLARED_ARG_KEYS.get(tool_name, frozenset())


def advanced_args(tool_name: str) -> frozenset[str]:
    """The parameters `compact()` removes from `tool_name`'s published schema."""
    return _ADVANCED.get(tool_name, frozenset())


def unknown_args(tool_name: str, supplied: Iterable[str]) -> tuple[str, ...]:
    """The supplied keys `tool_name` does not declare, sorted. 10:506's *"validates against"*.

    **An advanced parameter is never in the answer**, which is the whole reason the snapshot is
    taken where it is: a host that only ever saw the compact schema cannot send one, and a host
    that forwards a client's arguments unvalidated can, and the second must reach a handler that
    honours it rather than a refusal that calls it unknown.

    Returns the names and raises nothing. No document allocates a code for an unknown argument --
    10:299 owns the `OW-A-0xx` block and 10 section 3.3 describes the check without naming its
    refusal -- so the refusal is the dispatcher's to raise once that code exists, and D310 is the
    entry. Sorted, because the message a caller reads must not depend on dict order.
    """
    return tuple(sorted(set(supplied) - declared_arg_keys(tool_name)))


def _demote(schema: Mapping[str, Any]) -> dict[str, Any]:
    """One property's schema with any over-long enum demoted, recursively. 10:507.

    An enum becomes a free-form string and its members move into the description, so the parameter
    stays fully usable and the client loses only local validation. Recursive over `properties` and
    `items`, because `route_hints` is an object with three of its own and a rule that only looked
    one level deep would be a rule that stops working the first time a parameter grows a shape.

    The separator is `", "` and not the `·` the plan's own descriptions use. 10:332 makes
    `ensure_ascii=False` load-bearing -- the payload is real UTF-8 -- so a multi-byte separator
    would be paid for once per member, on a mechanism whose entire purpose is to spend fewer bytes.
    """
    out = dict(schema)
    members = out.get("enum")
    if isinstance(members, list) and len(members) > ENUM_DEMOTE_MAX:
        del out["enum"]
        out["type"] = "string"
        named = "one of: " + ", ".join(str(member) for member in members)
        existing = out.get("description")
        out["description"] = f"{existing} {named}" if existing else named
    properties = out.get("properties")
    if isinstance(properties, dict):
        out["properties"] = {key: _demote(value) for key, value in properties.items()}
    items = out.get("items")
    if isinstance(items, dict):
        out["items"] = _demote(items)
    return out


def compact(tool: Mapping[str, Any]) -> dict[str, Any]:
    """`[serve] compact_schemas = true`, applied to one tool object. Returns a COPY.

    Two rules, each a recorded bug fix (10:503):

    - the `advanced` parameters are removed from `inputSchema.properties`;
    - an enum above `ENUM_DEMOTE_MAX` members is demoted, never deleted.

    **`additionalProperties: false` is not touched**, and neither is `required`, `description`,
    `annotations` or `outputSchema`. 10:516 argues the first at length and the argument is the
    module docstring's; the rest follow from what compaction is for. `ow_corpora` declares no
    advanced parameters and no long enum, so this function returns an equal copy of it -- 10:356's
    *"the one listed tool compaction does not change"*, which is a property of the row rather than
    a special case here.

    Measured, at 10:349: the strip saves **181 tokens of 1,031, or 17.6%** across the four listed
    tools -- *"not thousands. The mechanism matters for a different reason: it is the fix the
    budget takes INSTEAD of shaving a description."*
    """
    out = dict(tool)
    schema = out.get("inputSchema")
    if not isinstance(schema, dict):
        return out
    hidden = advanced_args(str(out.get("name", "")))
    inner = dict(schema)
    properties = inner.get("properties")
    if isinstance(properties, dict):
        inner["properties"] = {
            key: _demote(value) for key, value in properties.items() if key not in hidden
        }
    out["inputSchema"] = inner
    return out


def with_required_corpus(tool: Mapping[str, Any]) -> dict[str, Any]:
    """`corpus` promoted into `inputSchema.required`. 10:530. **A COPY; the shared array is never
    touched.**

    10:531's own docstring is the argument and it is a measurement rather than a preference: *"A
    `required` field is a high-salience channel -- MCP clients surface it and often validate it --
    whereas the instructions text is the channel codegraph's own reporter found too weak to stop an
    agent omitting the parameter (tools.ts:1240-1262, withRequiredProjectPath)."* The measured cost
    is **+15 tokens on the compact payload, 850 to 865** (10:536), which is the entire price of the
    difference between an argument error the agent must recover from and one its host prevents.

    A tool with no `corpus` property is not corpus-scoped -- `ow_doctor` and `ow_explain` read no
    store at all -- so it comes back as an equal copy. That is a no-op and not a refusal, because
    10:525 scopes the promotion to *"every corpus-scoped listed tool"* and the property is what
    makes a tool one.

    `required` is re-derived in PROPERTY order rather than appended to, so the result does not
    depend on where the promotion happened. 10:231 fixes property order as the declaration's, and a
    `required` array ordered by anything else would make G25's byte-diff depend on a call sequence.
    """
    out = dict(tool)
    schema = out.get("inputSchema")
    if not isinstance(schema, dict):
        return out
    inner = dict(schema)
    properties = inner.get("properties")
    if not isinstance(properties, dict) or CORPUS_PARAM not in properties:
        out["inputSchema"] = inner
        return out
    existing = inner.get("required")
    wanted: set[str] = {CORPUS_PARAM}
    if isinstance(existing, list):
        wanted |= {str(key) for key in existing}
    inner["required"] = [key for key in properties if key in wanted]
    out["inputSchema"] = inner
    return out


def _tools_with(parameter: str) -> tuple[str, ...]:
    """Every tool declaring `parameter`, sorted. Used by the corpus-scoped assertions."""
    return tuple(sorted(name for name, keys in _DECLARED_ARG_KEYS.items() if parameter in keys))


CORPUS_SCOPED: Final[tuple[str, ...]] = _tools_with(CORPUS_PARAM)
"""The tools `with_required_corpus()` changes. 10:525's *"every corpus-scoped listed tool"*.

Derived rather than listed, because the predicate IS the parameter: a tool is corpus-scoped when it
declares `corpus`, and there is no second fact that could disagree with the first.
"""
