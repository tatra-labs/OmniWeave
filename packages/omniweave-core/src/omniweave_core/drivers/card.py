"""The `driver.toml` grammar: the closed table set, the tombstone branch, and the four digests.

A DriverCard is a **contract**, not configuration, and this module is the only site that turns
the bytes of a third party's `driver.toml` into one. It parses with `tomllib` and imports
nothing a card names: INV-4 makes discovery import-free, so every fact `resolve()` filters on
has to be readable as data or it does not exist.

**The closed/open asymmetry is the whole shape of the validator** (04-driver-system.md section
2.1). An unknown top-level table or top-level key is a hard error. An unknown key inside
`[capability.<port>]` is ignored and recorded, because every key there is an ordered ladder or a
set-valued floor, so an unrecognised one can only make a driver look *less* capable. An unknown
key in a `[<port>]` sibling is a hard error again, because those declarations are not monotone
and an older core silently dropping `dim = 384` would corrupt an index with no symptom. There is
exactly one exception and it is `forfeits`: it is the single inverted comparison on the card, so
an ignored unknown member would make a driver look **more** capable — the member is therefore a
match failure, and a proposed second exception is a reason to reject the PR (section 2.2).

**`[tombstone]` branches before anything else is validated** (sections 2.1 and 7.5). A tombstone
has no `entrypoint`, no `schema_version`, no `granularity` and no `replay_class` — all
non-optional on `DriverCard` — so validating one as a driver card was a guaranteed spurious
`CARD_INVALID` on a file whose only job is to explain a refusal. `Tombstone` is its own type
here, never a `DriverCard` with holes.

**The caps are hardening, not shape** (section 4.5, erratum E6): this parses attacker-adjacent
TOML in a process INV-3 holds to 80 ms. `read_card_bytes()` reads `MAX_CARD_BYTES + 1` bytes so
a card bomb is never allocated, and every other cap is `take(N + 1)`-then-check so the memory is
never spent before the refusal. Each breach names the key AND the cap.

**Two of the four digests of section 2.8 live here** and their difference is deliberate:
`card_sha256()` is over the RAW BYTES, so a comment-only edit moves it, and `attestation_of()`
is over the canonical card with the `attestation` key deleted, so a comment-only edit does NOT
move it. That is why both exist — `ow drivers verify` fails on the first (the installed bytes
are not the locked bytes) while `card.attested` stays true (the contract did not change).

**The `[config]` closed JSON-Schema subset is validated here too** (section 2.7) because INV-2
forbids a `jsonschema` dependency and the validator's output feeds `config_digest`, which is a
cache key: two callers passing the same values in a different order must share a worker.

Specified in 04-driver-system.md sections 2.1 through 2.8, 3, 4.5, 5.3, 5.4 and 7.5.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from types import MappingProxyType
from typing import Final, NoReturn, TypeAlias

from omniweave_ports.types import (
    ArtifactKind,
    CostClass,
    DriverMetrics,
    Isolation,
    Port,
    ReplayClass,
)

from omniweave_core.canonical import JsonValue, sha256_canonical
from omniweave_core.errors import ConfigError, DriverHostError
from omniweave_core.limits import (
    MAX_CARD_BENCHMARKS,
    MAX_CARD_BINARIES,
    MAX_CARD_BYTES,
    MAX_CARD_CONFIG_PROPERTIES,
    MAX_CARD_DEPTH,
    MAX_CARD_FORMATS,
    MAX_CARD_PINS,
    MAX_ENTRY_BYTES,
    MAX_ENTRY_COUNT,
)

__all__ = [
    "CARDS_SUPPORTED",
    "CARD_CAPABILITY_UNKNOWN",
    "CARD_ORIGINS",
    "CONFIG_KEYWORDS",
    "CONFIG_MAX_DEPTH",
    "CONFIG_REJECTED_KEYWORDS",
    "CONFIG_TYPES",
    "COST_SHAPES",
    "COST_UNITS",
    "DEPRECATION_MIN_MINORS",
    "DRIVER_ID_RE",
    "ENTRYPOINT_RE",
    "FORBIDDEN_REVISION",
    "FORMAT_TOKEN_RE",
    "GRANULARITIES",
    "MEASURED_ON_FIELDS",
    "MIN_SLICE_N",
    "PARSE_BOOLS",
    "PARSE_LADDERS",
    "PARSE_SETS",
    "QUALITY_SUITES",
    "QUALITY_VERDICTS",
    "SHELL_METACHARACTERS",
    "SPEND_DIMENSIONS",
    "TOP_LEVEL_KEYS",
    "TOP_LEVEL_TABLES",
    "WITNESSES",
    "AcquireCapability",
    "AcquireSibling",
    "Benchmark",
    "Capability",
    "CardDegradation",
    "CardLimits",
    "CardOrigin",
    "ConfigSchema",
    "CostMeasured",
    "CostModel",
    "CostScaling",
    "Deprecation",
    "Deps",
    "DeriveCapability",
    "DeriveSibling",
    "DriverCard",
    "DriverIdentity",
    "EmbedCapability",
    "EmbedSibling",
    "FormatTokenPair",
    "Hardware",
    "IsolationSpec",
    "LicenceFacts",
    "MeasuredOn",
    "ParseCapability",
    "Quality",
    "Tombstone",
    "attestation_of",
    "card_sha256",
    "load_card",
    "pins_digest",
    "read_card_bytes",
    "served_tokens",
]


# --------------------------------------------------------------------------------------------
# 1. The grammar, as constants. Every one of these is a closed set the plan prints; a card
#    naming something outside one is refused, and nothing here is a default a card may widen.
# --------------------------------------------------------------------------------------------

CardOrigin: TypeAlias = str
"""One of `CARD_ORIGINS`. A `str` rather than an enum because `origin` is discovery's fact about
WHERE a card was found, never a card field, and 04-driver-system.md section 4.1 prints the four
as bare words in a table it owns."""

CARD_ORIGINS: Final[frozenset[str]] = frozenset(
    {"entry_point", "driver_path", "project", "tombstone"}
)
"""The four discovery origins of 04-driver-system.md section 4.1, and there is no fifth.

`origin` is what `[driver] exec` is gated on — `exec` is legal only for `driver_path` and
`project`, which is what keeps an `exec` driver permanently `trust = local` and unable to reach
`inproc` or satisfy `require_lock = true`."""

CARDS_SUPPORTED: Final[frozenset[int]] = frozenset({1})
"""Every `card_schema` this build accepts. P1 ends at `card_schema = 1` (16-roadmap.md line 64).

`card_schema` is the FIRST key read, before the tombstone branch and before any table, because a
card from a newer grammar must be refused as `CARD_SCHEMA_TOO_NEW` rather than misread as
malformed (04-driver-system.md section 5.3). Adding a top-level table or key to the grammar
bumps it; adding a key inside `[capability.<port>]` does not — that is the safe asymmetry
(section 5.2)."""

TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset({"card_schema", "attestation"})
"""The only two bare keys legal at a card's top level (04-driver-system.md section 2.1).

`attestation` MUST be written before the first table header: TOML scopes a bare key to the most
recent header, so an `attestation = "..."` line after `[quality.suites]` parses as
`quality.suites.attestation` and the loader's recomputation reads nothing. The position is
asserted textually rather than inferred from where the parse happened to put the key."""

TOP_LEVEL_TABLES: Final[frozenset[str]] = frozenset(
    {
        "driver",
        "capability",
        "acquire",
        "parse",
        "derive",
        "embed",
        "compile",
        "hardware",
        "isolation",
        "limits",
        "licence",
        "deps",
        "config",
        "cost",
        "deprecation",
        "quality",
        "tombstone",
    }
)
"""The closed top-level table set of 04-driver-system.md section 2.1, and it is complete.

Five of the seventeen are the `[<port>]` siblings, one per `Port` member: they hold the
non-monotone identity, limits and switches that charter section 5 X37 keeps OUT of
`[capability.<port>]` precisely so an unknown key in them can fail closed. A loader implementing
this set needs no other name, and a PR adding a row bumps `card_schema`."""

DRIVER_ID_RE: Final = re.compile(
    r"^(acquire|parse|derive|embed|compile)\.[a-z0-9_]{1,32}\.[a-z0-9_]{1,32}$"
)
"""The `DriverId` grammar of charter section 5 X35, printed in 04-driver-system.md section 5.1.

The id is versionless and its FIRST SEGMENT IS THE PORT, which is why the loader cross-checks it
against `[driver] port` instead of trusting either alone: `origin_operator` is the first two
segments and `origin_driver` is all three, and both are stamped on every row a driver
produces."""

PORT_RE: Final = re.compile(r"^(acquire|parse|derive|embed|compile)/([1-9][0-9]*)$")
"""`<name>/<MAJOR>` — the Port major a card binds (04-driver-system.md section 5.1).

A major is a Protocol signature and a wire stream shape; both majors coexist and `resolve()`
filters on `port major supported`, so the integer is parsed rather than string-compared."""

ENTRYPOINT_RE: Final = re.compile(r"^[^:/]+:[^:/]+$")
"""`<dotted.module>:<Attr>` — exactly one colon and no slash.

The card's `entrypoint` and the ENTRY-POINT VALUE are two names with two grammars and they are
not the same name: `setuptools._entry_points.validate` raises at build time on a path-shaped
entry-point value, so that one is a colon-FREE dotted package path, while `activate()` must
assert the loaded CLASS's `PORT` and `SCHEMA_VERSION` and a package has no such attributes. A
breach here is `CARD_ENTRYPOINT_MALFORMED`, not `CARD_INVALID` (04-driver-system.md sections 4.1
and 5.3)."""

FORMAT_TOKEN_RE: Final = re.compile(r"^[a-z0-9]{1,16}$")
"""A `format_tokens` member's `token` (04-driver-system.md section 2.2).

The token side of a `{media_type, token}` pair is what a routing rule's `unit.format` clause
matches, and that domain is computed — core's forty-eight tokens union the tokens every enabled
card contributes — so a token outside this shape would widen a policy domain with something no
rule could be written against."""

GRANULARITIES: Final[tuple[str, ...]] = ("document", "part", "corpus")
"""What one `INVOKE` addresses (charter section 5 C10, 04-driver-system.md section 2.5).

Not a ladder and not a floor: it is why a 500-page 10-K is a few hundred part-granularity
decisions instead of one, and why `[budget.per_part]` can bite at all."""

FORBIDDEN_REVISION: Final = "main"
"""`revision = "main"` is forbidden framework-wide and is `CARD_INVALID` wherever it appears.

Three card sites carry the same hazard and all three are refused: `[embed] model_revision`,
`[licence.weights] weights_revision` and `MeasuredOn.weights_revision`. The receipt is docling's
model `revision`, which defaults to `"main"` at six declaration sites in `layout_model_specs.py`
while the field's own annotation says it names a Git revision for reproducibility
(04-driver-system.md section 2.4; RT14; 13-quality.md P-22)."""

SHELL_METACHARACTERS: Final[frozenset[str]] = frozenset("|&;<>()$`\\\"'\n\r\t*?[]{}!~# ")
"""What no element of `[driver] exec`'s argv may contain (04-driver-system.md section 4.1).

The host spawns with `shell=False`, so a metacharacter cannot reach a shell — this refuses the
card anyway, because an argv element that only makes sense to a shell is evidence the author
believed one was there, and the next reader of that card will believe it too."""

MIN_SLICE_N: Final = 30
"""`n` below which a `[[quality.benchmark]]` row is refused at load, not rendered with a caveat.

The same number as `min_audit_n`, reused rather than reinvented (04-driver-system.md section
2.6). A point estimate over fewer than thirty slices is not a measurement a router may rank."""

DEPRECATION_MIN_MINORS: Final = 2
"""The minimum `[deprecation]` window, in `RELEASE` MINORs (04-driver-system.md section 5.4).

It matches G16's two-release compatibility promise, which loads the previous two releases'
conformance-template drivers against HEAD — a shorter window would promise an author a window
the gate does not keep."""

SPEND_DIMENSIONS: Final[frozenset[str]] = frozenset(
    f.name for f in dataclasses.fields(DriverMetrics)
)
"""The nine physical dimensions a `Spend` vector may name, taken from `DriverMetrics` itself.

Derived rather than re-listed: `Spend` is the router's type (02-architecture.md section 2 row
35) and `DriverMetrics` is the driver-facing shape of the same nine dimensions, so a tenth
dimension must not need editing here as well (INV-21). PHYSICAL UNITS ONLY — there is no
`cost_micros`, because only the operator's `PriceBook` converts a `Spend` to money (INV-15)."""

COST_SHAPES: Final[tuple[str, ...]] = (
    "constant",
    "linear_per_part",
    "linear_per_byte",
    "linear_per_token",
)
"""`[cost.model] shape` — the reservation formula (04-driver-system.md section 2.5).

`constant` is the one shape naming no scaling dimension; each of the other three names one, and
04-driver-system.md section 3 note 4 makes a shape that names a dimension with an EMPTY
`scaling` table `CARD_INVALID` — the byte term of `linear_per_byte` is carried by `scaling`, not
by `unit`."""

COST_UNITS: Final[tuple[str, ...]] = ("document", "part", "page", "token", "byte")
"""`[cost.model] unit` — the denominator of `per_part` (04-driver-system.md section 2.5)."""

QUALITY_SUITES: Final[tuple[str, ...]] = (
    "card",
    "purity",
    "contract",
    "capability",
    "idempotence",
    "determinism",
    "limits",
    "sandbox",
    "cost",
    "licence",
    "fuzz",
    "quality",
)
"""The twelve conformance suites, as `[quality.suites]` names them.

04-driver-system.md section 3's worked card prints all twelve and section 8.2 specifies them.
`[quality.suites]` is a closed table like any other: an unknown key in it is a hard error, which
is also what stops an `attestation` line written after its header from being silently absorbed
as `quality.suites.attestation`."""

QUALITY_VERDICTS: Final[tuple[str, ...]] = ("pass", "fail", "unknown")
"""A suite's three states. `unknown` is a VALUE, not a skipped state: the terminology lock
strikes the skip vocabulary outright and `ow eval release-check` refuses on `unknown`
(04-driver-system.md section 3 note 5)."""

WITNESSES: Final[tuple[str, ...]] = ("ci", "third_party", "self")
"""Who measured a `[[quality.benchmark]]` row.

`self` is the floor and the fallback: a `witness != "ci"` row is displayed and never ranked, and
the card loader DOWNGRADES anything it does not recognise rather than refusing the card, because
an unrecognised witness claim is exactly a self-report (04-driver-system.md section 8.4)."""

MEASURED_ON_FIELDS: Final[tuple[str, ...]] = (
    "weights",
    "weights_revision",
    "runtime",
    "runtime_version",
    "sampling",
    "prompt_version",
    "hardware",
    "corpus",
    "corpus_digest",
    "harness_version",
)
"""The ten fields of `MeasuredOn`, in the order 04-driver-system.md section 2.6 prints them.

`MeasuredOn` is frozen with NO DEFAULTS, so a card supplying seven of them raises `TypeError` at
construction rather than writing a blank cell (DR14). A pure-code path writes the literal
`"n/a"` where a field does not apply — a None-equivalent that is still a value."""

CARD_CAPABILITY_UNKNOWN: Final = "card_capability_unknown"
"""The kind recorded when an unknown key inside `[capability.<port>]` is ignored.

The one safe asymmetry of 04-driver-system.md section 2.1. It is recorded on the card as a
`CardDegradation` and NOT as an observability `Degradation`: 15-observability.md is that type's
sole home (charter erratum E15) and its `DegradationKind` literal is closed at twenty-seven
members with no `card_capability_unknown` among them, so constructing one here would either
invent a twenty-eighth member or misfile the record under a kind that means something else."""

CONFIG_TYPES: Final[tuple[str, ...]] = (
    "object",
    "string",
    "integer",
    "number",
    "boolean",
    "array",
)
"""`type`'s domain in the closed `[config]` subset — exactly one of these, never a list of types
and never `null` (04-driver-system.md section 2.7)."""

CONFIG_KEYWORDS: Final[tuple[str, ...]] = (
    "type",
    "additionalProperties",
    "properties",
    "required",
    "default",
    "enum",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
    "items",
    "minItems",
    "maxItems",
)
"""Every keyword legal anywhere in the `[config]` subset.

04-driver-system.md section 2.7's table has ELEVEN ROWS and fourteen keyword spellings, because
three rows pair two: `minimum, maximum`, `minLength, maxLength` and `minItems, maxItems`.
Counting rows and counting spellings give different numbers and the table is the authority."""

CONFIG_REJECTED_KEYWORDS: Final[tuple[str, ...]] = (
    "$ref",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "if",
    "then",
    "patternProperties",
    "dependentSchemas",
    "format",
)
"""The ten keywords named for rejection, so the error NAMES the keyword rather than saying
"unknown". The rejection is not a taste judgement: `$ref` alone turns a sixty-line validator
into a resolver with a cycle detector, and a driver's static config has never needed one
(04-driver-system.md section 2.7)."""

CONFIG_MAX_DEPTH: Final = 3
"""The depth at which `properties` stops being legal in the `[config]` subset.

`config.properties.<name>` is depth 3 and is the deepest the subset admits, so a `properties`
table under a property is `CARD_INVALID` naming the keyword. `additionalProperties`,
`properties` and `required` are ROOT-ONLY for the same reason (04-driver-system.md section
2.7)."""

MAX_ENUM_MEMBERS: Final = 32
MAX_PATTERN_CHARS: Final = 200
MAX_STRING_LENGTH: Final = 4096
MAX_ARRAY_ITEMS: Final = 256
"""The four numeric bounds inside the `[config]` subset (04-driver-system.md section 2.7): an
`enum` of at most 32 scalars, a `pattern` of at most 200 characters compiled at load, a
`maxLength` of at most 4096 and a `maxItems` of at most 256."""

PARSE_LADDERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "spatial": ("none", "page_bbox", "block_bbox", "line_bbox", "char_bbox"),
        "origin_span": ("none", "normalized", "exact"),
        "reading_order": ("raster", "learned", "model_emitted", "char_stream", "source"),
        "sections": ("none", "markdown_only", "outline_from_source", "typed_levels"),
        "tables": ("none", "flat_html", "cells", "cells_with_spans"),
        "assets": ("none", "refs", "bytes"),
        "notes": ("none", "inline", "linked"),
        "confidence": ("none", "document", "page", "element"),
        "furniture": ("destroyed", "flagged", "separated"),
        "round_trip": ("none", "text", "structure", "passthrough"),
    }
)
"""The ten ORDERED ladders of `[capability.parse]`, least capable first, compared `>=`.

The order is load-bearing and is 04-driver-system.md section 2.2's, verbatim — `reading_order`
in particular is ordered by marker's own measured 75%-versus-56% char-stream-over-learned-head
result (`marker/builders/line.py:80-82`), not by how the words sound. An absent key reads as
element 0, the least capable rung, which is the only default that cannot over-claim."""

PARSE_BOOLS: Final[tuple[str, ...]] = ("text_span", "marks", "asset_origin")
"""The three boolean floors of `[capability.parse]`, compared `>=` with `False < True`."""

PARSE_SETS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "math": frozenset({"latex", "mathml"}),
        "forfeits": frozenset({"blocks", "spatial", "text_span", "citation", "round_trip"}),
    }
)
"""The two SET-valued keys of `[capability.parse]` and their closed member vocabularies.

`math` is compared `⊇` and is a notation choice, not a quality rung. `forfeits` is compared
`⊆` — **the only inverted comparison on the whole card** — which is why an unknown MEMBER of it
is a match failure rather than an ignore: ignoring one would make the driver look MORE capable
(04-driver-system.md section 2.2)."""

ACQUIRE_LADDERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "listing": ("none", "flat", "recursive"),
        "revision": ("none", "mtime", "etag", "content_hash"),
        "addressing": ("path", "uri", "uri_with_cursor"),
        "deletes": ("none", "tombstone", "authoritative"),
    }
)
"""`[capability.acquire]`'s ordered ladders (04-driver-system.md section 2.4, erratum E1).

`deletes` is the one a coverage claim rests on and `addressing` is the one resumability rests
on, which is why neither is a boolean."""

DERIVE_LADDERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "grounding": ("none", "offsets", "quote", "quote_verified"),
        "relations": ("none", "closed_vocab", "declares_vocab"),
        "schema": ("none", "json_schema"),
        "confidence": ("none", "item", "field"),
    }
)
"""`[capability.derive]`'s ordered ladders (04-driver-system.md section 2.4)."""

DERIVE_ITEMS: Final[frozenset[str]] = frozenset(
    {
        "segment",
        "anchor",
        "xref",
        "entity",
        "alias",
        "mention",
        "edge",
        "claim",
        "summary",
        "field",
    }
)
"""The ten item kinds `[capability.derive] items` is a set over, compared `⊇`.

Eight are `owgraph-items/1` frame kinds that carry an item — `cover`, `cover_empty`, `more` and
`diag` are control frames and are NOT items — plus `segment` and `summary`, which D7's ladder
produces and the graph wire does not print. `field` is reserved for an extraction driver and has
no first-party producer at release 1 (04-driver-system.md section 2.4)."""

EMBED_LADDERS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {"truncation": ("error", "head", "window_pool")}
)
"""`[capability.embed]`'s one ordered ladder (04-driver-system.md section 2.4)."""

EMBED_INPUTS: Final[frozenset[str]] = frozenset({"text", "image", "table_text"})
EMBED_QUANTIZATIONS: Final[frozenset[str]] = frozenset({"f32", "int8", "binary"})
EMBED_METRICS: Final[tuple[str, ...]] = ("cosine", "ip", "l2")
EMBED_NORMALIZATIONS: Final[tuple[str, ...]] = ("none", "l2")
ACQUIRE_AUTHN: Final[frozenset[str]] = frozenset({"token", "basic", "oauth2", "mtls"})
"""The four closed member vocabularies of the acquire and embed capability sets, and the two
`[embed]` sibling enumerations. `dim`, `metric` and `normalization` live in the SIBLING and not
in `[capability.embed]` because "dim >= 768" is not a capability floor: a larger dimension is
not strictly better, and an older core silently dropping `dim = 384` from an
unknown-key-tolerant table would corrupt an index with no symptom (04-driver-system.md section
2.4)."""

GPU_REQUIREMENTS: Final[tuple[str, ...]] = ("none", "optional", "required")
"""`[hardware] gpu`.

04-driver-system.md prints only `"none"` — in section 3's card and in section 6.1's `inproc`
conjunct `hardware.gpu == "none"` — and never enumerates the rest. These three are this module's
reading of a field whose only load-bearing use is the `== "none"` test; the departure is
reported rather than hidden."""

REDISTRIBUTIONS: Final[tuple[str, ...]] = ("allowed", "restricted", "forbidden")
"""`[licence.code] redistribution`.

04-driver-system.md section 7.1 reads only `redistribution != "allowed"` and section 3's card
writes only `"allowed"`; the other two spellings are this module's, and are reported as a
departure. `compute_tier()` (another cluster's) reads the fact, never this vocabulary."""


# --------------------------------------------------------------------------------------------
# 2. Refusals. Three symbols, and the choice between them is 04-driver-system.md section 5.3's:
#    a malformed `entrypoint` is its own code because `activate()` is the only site that resolves
#    the colon form, and a grammar from the future is its own code because upgrading clears it
#    while editing the card does not.
# --------------------------------------------------------------------------------------------


def _card_invalid(source: str, message: str) -> NoReturn:
    """`CARD_INVALID` — the card is refused, and the message names the offending subject.

    Never a `ResourceLimit`, even for a cap breach: a card is a contract and a malformed one is
    refused rather than clamped, which is why `omniweave_core.limits`' own docstring sends the
    seven card caps here (04-driver-system.md section 4.5).
    """
    raise DriverHostError(
        f"{source}: {message}",
        symbol="OW_CARD_INVALID",
        fix=f"ow drivers check {source}",
    )


def _entrypoint_malformed(source: str, message: str) -> NoReturn:
    """`CARD_ENTRYPOINT_MALFORMED` — `entrypoint` is not `<dotted.module>:<Attr>`."""
    raise DriverHostError(
        f"{source}: {message}",
        symbol="OW_CARD_ENTRYPOINT_MALFORMED",
        fix=f"ow drivers check {source}",
    )


def _schema_too_new(source: str, declared: int) -> NoReturn:
    """`CARD_SCHEMA_TOO_NEW` — the card is from a grammar this build does not implement.

    The fix is an upgrade and not an edit: the card is well-formed, and telling its author to
    change it would be telling them to un-write a key a newer core requires.
    """
    raise DriverHostError(
        f"{source}: card_schema = {declared} is newer than this build's "
        f"{max(CARDS_SUPPORTED)}; the card grammar it is written in is not implemented here",
        symbol="OW_CARD_SCHEMA_TOO_NEW",
        fix="pip install --upgrade omniweave-core",
    )


# --------------------------------------------------------------------------------------------
# 3. The sub-records. All frozen and slotted: a card is read once and compared thereafter, and a
#    mutable capability floor is a router that answers differently on the second call.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CardDegradation:
    """One thing the loader ignored rather than refused, with enough detail to act on.

    The only producer at P1 is the `[capability.<port>]` unknown-key rule, whose `kind` is
    `CARD_CAPABILITY_UNKNOWN`. It is a card-load record and deliberately not an observability
    `Degradation`: that type's `DegradationKind` is closed at twenty-seven members and none of
    them is this (04-driver-system.md section 2.1; 15-observability.md, which is that type's
    sole home).
    """

    kind: str
    table: str
    key: str
    detail: str


@dataclass(frozen=True, slots=True)
class FormatTokenPair:
    """One `{media_type, token}` member of `[capability.parse] format_tokens`.

    **The key is pair-shaped and that is the whole point of it** (04-driver-system.md section
    2.2). A card declaring bare tokens would carry two unpaired lists — `[capability] formats`
    holds media types, `format_tokens` would hold tokens — and supply no association between
    them, leaving routing's `format_token_for(media_type)` undefined and `OW-D-024`
    undecidable. Nothing infers a pairing from list order, list length or string similarity.
    """

    media_type: str
    token: str


@dataclass(frozen=True, slots=True)
class MeasuredOn:
    """The ten-field provenance of one benchmark number. **Frozen with NO defaults** (DR14).

    A card supplying nine of the ten raises `TypeError` at construction rather than writing a
    blank cell, which is the whole mechanism: a missing field is a measurement nobody can
    reproduce, and a default would turn it into one nobody notices. A pure-code path writes the
    literal `"n/a"` where a field does not apply — a None-equivalent that is still a value.

    `corpus_digest` lives here and **has no row-level twin**: two fields that must agree are one
    field plus a bug (04-driver-system.md section 2.6).

    Specified in 04-driver-system.md section 2.6 and 13-quality.md P-22.
    """

    weights: str
    weights_revision: str
    runtime: str
    runtime_version: str
    sampling: str
    prompt_version: str
    hardware: str
    corpus: str
    corpus_digest: str
    harness_version: str

    def __post_init__(self) -> None:
        """Every field is a string, and `weights_revision` is never `"main"`.

        13-quality.md P-22 requires both halves at CONSTRUCTION: a proper subset of the ten
        raises `TypeError` (the dataclass does that by having no defaults) and
        `weights_revision = "main"` raises here. docling's own layout-model `revision` defaults
        to `"main"` at six declaration sites while its field annotation says the field exists
        for reproducibility, which is the receipt this check was written against.
        """
        for name in MEASURED_ON_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"MeasuredOn.{name} must be a non-empty string, not {value!r}")
        if self.weights_revision == FORBIDDEN_REVISION:
            raise ValueError(
                "MeasuredOn.weights_revision must be an exact sha; "
                f"{FORBIDDEN_REVISION!r} is forbidden framework-wide (RT14, 13-quality.md P-22)"
            )


@dataclass(frozen=True, slots=True)
class Benchmark:
    """One `[[quality.benchmark]]` row — the only place a card carries an accuracy number.

    Written by `ow conform`; author values are rejected. Four keys are required beyond the
    metric and its value — `n`, `ci95`, `witness` and a COMPLETE `measured_on` — and a row with
    `n < MIN_SLICE_N` is refused at load rather than rendered with a caveat.

    `witness` is downgraded, never refused: DR24 treats a row whose `measured_on.corpus_digest`
    is not a digest in the omniweave release manifest as `witness = "self"` regardless of what
    it declares, and a `witness != "ci"` row is displayed, never ranked, and never read by
    `ow route propose`. The cautionary case is on the record: HunyuanOCR's TensorRT-measured
    94.10 against a repo shipping Transformers and vLLM.

    Specified in 04-driver-system.md sections 2.6 and 8.4.
    """

    metric: str
    value: float
    n: int
    ci95: tuple[float, float]
    witness: str
    measured_on: MeasuredOn
    method: str = ""
    slice_key: str = ""

    def __post_init__(self) -> None:
        """`n >= MIN_SLICE_N`, a real interval, and a witness inside `WITNESSES`."""
        if self.n < MIN_SLICE_N:
            raise ValueError(
                f"[[quality.benchmark]] {self.metric!r} has n = {self.n}, below "
                f"min_slice_n = {MIN_SLICE_N}: a row under the floor is refused, not caveated"
            )
        low, high = self.ci95
        if low > high:
            raise ValueError(f"[[quality.benchmark]] {self.metric!r} ci95 {self.ci95} is inverted")
        if self.witness not in WITNESSES:
            raise ValueError(f"[[quality.benchmark]] witness {self.witness!r} is not in WITNESSES")


@dataclass(frozen=True, slots=True)
class Quality:
    """`[quality]`, `[quality.suites]` and the `[[quality.benchmark]]` rows.

    Every value here is written by `ow conform` and **author values are rejected**: the card is
    the test plan, so a driver that writes its own suite results has written its own report
    card. `unknown` is a value and not a skipped state (04-driver-system.md sections 2.1 and 3
    note 5).
    """

    kit_version: str = ""
    kit_run: str = ""
    suites: Mapping[str, str] = MappingProxyType({})
    benchmarks: tuple[Benchmark, ...] = ()


@dataclass(frozen=True, slots=True)
class CostScaling:
    """`[cost.model] scaling` — one evidence key, one exponent, one reference value.

    It carries the term `unit` cannot: `shape = "linear_per_byte"` with `unit = "document"`
    makes `per_part = { wall_ms = 3 }` "3 ms for a document of `reference` bytes", and this
    table supplies the byte term (04-driver-system.md section 3 note 4).
    """

    key: str
    exponent: float
    reference: float


@dataclass(frozen=True, slots=True)
class CostModel:
    """`[cost.model]` — AUTHOR-declared because it is structural, not measured (charter X10).

    Only the author knows whether the driver loads a model once per session, which is what
    `per_session` records and what `inproc_bulk_threshold` exists to amortise.

    `cost_class` is spelled out because the card key is `class`, which is a Python keyword; the
    card's spelling is authoritative and the field name is this module's necessity, not a
    rename. `max_retries` accepts exactly `0`: a driver never retries internally, because retry
    is the runtime's, with the runtime's budget and the runtime's ledger — the receipt being
    Unlimited-OCR's `REQUEST_TIMEOUT = 1200` seconds times `MAX_RETRIES = 5`, a 100-minute worst
    case per document with no ledger anywhere (04-driver-system.md section 1.5 obligation 4).

    `tokens_out_p95_multiple` earns its slot from charter measurement gap F6: the only two
    published anchors for a page VLM's output-token p95 are 3.4x apart, so a reservation model
    built on a mean is wrong by that factor on every billed page.
    """

    cost_class: CostClass
    shape: str
    unit: str
    per_part: Mapping[str, float] = MappingProxyType({})
    per_session: Mapping[str, float] = MappingProxyType({})
    scaling: CostScaling | None = None
    tokens_out_p95_multiple: float = 1.0
    max_retries: int = 0


@dataclass(frozen=True, slots=True)
class CostMeasured:
    """`[cost.measured]` — written by `ow conform`; author values are rejected.

    The field is `timing_basis` and NOT `measured_on`: on a card `measured_on` is always the
    frozen ten-field `MeasuredOn` of `[[quality.benchmark]]`, so a loader reading the wrong one
    gets a missing key rather than a `str` where it expects a record (04-driver-system.md
    section 3).
    """

    p50_ms_per_unit: float = 0.0
    p95_ms_per_unit: float = 0.0
    spend_per_unit: Mapping[str, float] = MappingProxyType({})
    hardware: str = ""
    hardware_spawn: str = ""
    timing_basis: str = ""


@dataclass(frozen=True, slots=True)
class Deprecation:
    """`[deprecation]` — the driver's own retirement schedule (erratum E8).

    **Absent means "not scheduled". An EMPTY table is a different statement and is
    `CARD_INVALID`**, for the same reason `[licence.weights]` is omitted rather than emptied
    when a driver ships no weights (04-driver-system.md section 3 note 6).

    `since <= RELEASE < removed_in` records a `deprecation` degradation naming the replacement
    and still runs the driver; `RELEASE >= removed_in` is `DEPRECATED_REMOVED`. The window is at
    least `DEPRECATION_MIN_MINORS` MINORs, and `replaced_by` may be omitted only when there is
    no successor — in which case `reason` must say so (section 5.4).
    """

    since: str
    removed_in: str
    reason: str
    replaced_by: str | None = None


@dataclass(frozen=True, slots=True)
class Deps:
    """`[deps] pins` and the digest over them.

    The pins digest enters the cache key **only** for `cost.model.class = "free"` (section 5.1):
    a free driver's output is cheap to recompute, so invalidating it on a dependency bump costs
    nothing, while a billed driver's is not, so a pdfium or tokenizer bump must not silently
    re-bill the fleet.
    """

    pins: tuple[str, ...] = ()

    @property
    def digest(self) -> str:
        """`sha256(canonical(sorted(pins)))` — 04-driver-system.md section 2.8's fourth digest."""
        return pins_digest(self.pins)


@dataclass(frozen=True, slots=True)
class LicenceFacts:
    """`[licence.code]` or `[licence.weights]` — **facts only**. The tier is COMPUTED.

    An author cannot mislabel: `compute_tier()` reads these and `ow drivers check` exits
    non-zero when a stored tier differs from the computed one (DR15). `requires_credential` is
    here rather than anywhere else because "this licence requires a purchased credential" is a
    fact about the same text `licence_sha256` covers, and putting it elsewhere would give
    `compute_tier` an input outside the hash the acknowledgement is bound to (erratum E10).

    `weights_revision` is legal only on `[licence.weights]` and must be an exact sha:
    `"main"` is `CARD_INVALID` and is banned framework-wide (section 7.1).

    Every field name matches its `Restriction` member by casing and nothing else
    (`territory_excluded` -> `TERRITORY_EXCLUDED`), which is why the runner's fact-to-bit map
    special-cases no name (section 7.2).
    """

    spdx: str = ""
    licence_sha256: str = ""
    licence_url: str = ""
    notice_path: str = ""
    redistribution: str = "allowed"
    output_share_alike: bool = False
    competitor_bar: bool = False
    requires_credential: bool = False
    revenue_gate_usd: int = 0
    mau_gate: int = 0
    territory_excluded: tuple[str, ...] = ()
    field_of_use_excluded: tuple[str, ...] = ()
    attribution_per_output: bool = False
    no_model_training: bool = False
    remote_kill_switch: bool = False
    clause_refs: tuple[str, ...] = ()
    weights_revision: str = ""


@dataclass(frozen=True, slots=True)
class Hardware:
    """`[hardware]` — everything about the environment, readable without importing the driver.

    `needs_binaries` is capped at `MAX_CARD_BINARIES` and that is not only a shape cap: every
    declared binary costs one `shutil.which` plus one `os.stat` inside `env_digest`, which is on
    the probe-cache key path (04-driver-system.md sections 4.5 and 4.7).

    `services` NAMES Services and never routes them: a Service has no unit and no cost-per-unit,
    so it is not a Driver and never enters `resolve()` (charter section 5 C5).
    """

    gpu: str = "none"
    vram_gb_min: float = 0.0
    ram_gb_min: float = 0.0
    cpu_arch: tuple[str, ...] = ()
    os: tuple[str, ...] = ()
    needs_network: bool = False
    needs_binaries: tuple[str, ...] = ()
    imports_torch: bool = False
    install_bytes: int = 0
    services: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IsolationSpec:
    """`[isolation]` — a REQUEST, which the host may only tighten (DR9).

    A card asking for `inproc` that fails any of section 6.1's six conjuncts runs `subproc` with
    an `isolation_shortfall` degradation and is not refused; a card asking for `subproc` can
    never be relaxed to `inproc` by config. `wasm` is in the vocabulary and not built at v1;
    `container` is not in the vocabulary at all — one is a mode you cannot run, the other is a
    mode you cannot ship.
    """

    requires: Isolation = Isolation.SUBPROC
    memory_mb: int = 0
    progress_ms: int = 0
    wall_ms_hard: int = 0
    batch_max_units: int = 0


@dataclass(frozen=True, slots=True)
class CardLimits:
    """`[limits]` — the driver DECLARES; the table in section 2.5 says who ENFORCES.

    `effective = min(tenant_cap, declared, HOST_MAX)` and a declaration above `HOST_MAX` is
    `CARD_INVALID` (DR20). The split matters because a limit with two enforcers drifts and a
    limit with none is decoration: `max_input_bytes` is the HOST's, refused before `INVOKE` is
    ever sent, and `max_parts` is the DRIVER's, at its own read boundary, because only the
    driver can count container members.
    """

    max_input_bytes: int = MAX_ENTRY_BYTES
    max_parts: int = MAX_ENTRY_COUNT


@dataclass(frozen=True, slots=True)
class Capability:
    """`[capability]` — `formats`, `consumes` and `produces`.

    `formats` holds MEDIA TYPES while a routing rule's `unit.format` clause holds TOKENS, which
    is why the two cannot be compared directly and why `served_tokens()` exists.
    `consumes`/`produces` are sets over the closed thirteen-member artifact-kind vocabulary, and
    `diag` may never be the sole member of `produces` — a driver that only ever emits a
    diagnostic has produced nothing (04-driver-system.md sections 2.2 and 2.3).
    """

    formats: tuple[str, ...] = ()
    consumes: frozenset[ArtifactKind] = frozenset()
    produces: frozenset[ArtifactKind] = frozenset()


@dataclass(frozen=True, slots=True)
class ParseCapability:
    """`[capability.parse]` — the fifteen monotone floors, plus the sixteenth key.

    The fifteen are `omniweave_core.model.Capabilities`, this table and `doc.declared` /
    `doc.achieved`: **one field set, three homes** (charter section 5 C2). A card DECLARES;
    `doc.achieved` records what the driver delivered on one document, may be lower and may never
    be higher, and serve reads `achieved`, never a card.

    `format_tokens` is the sixteenth and is NOT one of the fifteen: it is card-only, never
    appears on a `Doc`, and is the key that makes a format a third party invented reachable at
    all.

    Every default is the least capable value the field admits, which is the only default that
    cannot over-claim. `forfeits` is the exception in the other direction and defaults empty,
    because "forfeits nothing" is what an absent forfeits list says.
    """

    spatial: str = "none"
    origin_span: str = "none"
    text_span: bool = False
    marks: bool = False
    reading_order: str = "raster"
    sections: str = "none"
    tables: str = "none"
    math: frozenset[str] = frozenset()
    assets: str = "none"
    asset_origin: bool = False
    notes: str = "none"
    confidence: str = "none"
    furniture: str = "destroyed"
    round_trip: str = "none"
    forfeits: frozenset[str] = frozenset()
    format_tokens: tuple[FormatTokenPair, ...] = ()


@dataclass(frozen=True, slots=True)
class AcquireCapability:
    """`[capability.acquire]` — ordered ladders and set floors only (erratum E1).

    `trust_class_declared = false` means the host defaults `unit.trust_class` to
    `untrusted_external`, which RAISES `audit.rate`: the driver has not lied, it has declined to
    say, and the framework pays for the silence rather than assuming.
    """

    schemes: frozenset[str] = frozenset()
    listing: str = "none"
    revision: str = "none"
    addressing: str = "path"
    deletes: str = "none"
    ranges: bool = False
    streaming: bool = False
    authn: frozenset[str] = frozenset()
    trust_class_declared: bool = False


@dataclass(frozen=True, slots=True)
class AcquireSibling:
    """`[acquire]` — NON-MONOTONE. An unknown key here is a HARD ERROR (charter X37).

    `cursor_opaque = false` means the host may not persist a cursor across runs, which is the
    kind of switch that must never be silently dropped by an older core.
    """

    implemented: bool = False
    max_units_per_call: int = 0
    rate_limit_rps: int = 0
    cursor_opaque: bool = False


@dataclass(frozen=True, slots=True)
class DeriveCapability:
    """`[capability.derive]` (erratum E1).

    `scope_honoured = false` is the one capability value that makes a driver permanently
    UNACTIVATABLE rather than merely unselected: scope containment is the layer that survives a
    fully successful prompt injection, so `resolve()` rejects such a card for every requirement
    and `ow drivers check` reports it as a card defect rather than a limitation
    (04-driver-system.md sections 2.4 and 6.6).
    """

    items: frozenset[str] = frozenset()
    grounding: str = "none"
    relations: str = "none"
    schema: str = "none"
    confidence: str = "none"
    coreference: bool = False
    scripts: tuple[str, ...] = ()
    scope_honoured: bool = False


@dataclass(frozen=True, slots=True)
class DeriveSibling:
    """`[derive]` — NON-MONOTONE. An unknown key here is a HARD ERROR.

    **`phase` lives here and this table is its only home on the card.** It orders Passes WITHIN
    one `cost_rank` and is neither ordered-as-a-floor nor set-valued — a higher `phase` is not a
    more capable driver — so it is exactly the declaration X37 sends to the sibling. Under
    `[capability.derive]` an unrecognised key is IGNORED, which is correct for a floor and wrong
    for a key whose default sits in the middle of its range (ADR-8 D8.4; erratum E71 supersedes
    the charter's `:4893` parenthetical).
    """

    implemented: bool = False
    phase: int = 50
    max_items_per_segment: int = 0
    prompt_version: str = ""
    schema_path: str = ""


@dataclass(frozen=True, slots=True)
class EmbedCapability:
    """`[capability.embed]` (erratum E1)."""

    inputs: frozenset[str] = frozenset()
    quantization: frozenset[str] = frozenset()
    truncation: str = "error"
    instructions: bool = False
    multi_vector: bool = False


@dataclass(frozen=True, slots=True)
class EmbedSibling:
    """`[embed]` — IDENTITY AND LIMITS. An unknown key here is a HARD ERROR.

    `dim`, `metric` and `normalization` are here and not in `[capability.embed]` because
    "dim >= 768" is not a capability floor: a larger dimension is not strictly better, and an
    older core silently dropping `dim = 384` from an unknown-key-tolerant table would corrupt an
    index with no symptom. `model_revision` must be an EXACT sha (04-driver-system.md section
    2.4).
    """

    implemented: bool = False
    model_id: str = ""
    model_revision: str = ""
    dim: int = 0
    metric: str = "cosine"
    normalization: str = "none"
    max_tokens: int = 0
    max_units: int = 0


@dataclass(frozen=True, slots=True)
class ConfigSchema:
    """`[config]` — the CLOSED JSON-Schema subset, already validated (erratum E3).

    Core ships this validator rather than importing one: INV-2 forbids a `jsonschema`
    dependency, core validates a driver's config BEFORE construction, and the validator's output
    feeds `config_digest`, which is the worker key `(driver_id, config_digest)`. Two callers
    passing the same values in a different order must therefore share a worker, which is what
    `canonical()`'s sorted keys buy and why `effective()` fills defaults before digesting rather
    than after.

    `properties` holds the per-property sub-schema exactly as the card wrote it, with every
    keyword already checked against `CONFIG_KEYWORDS` and every rejected keyword already refused
    BY NAME. `required` is the card's `required` array.

    Config values arrive from `omniweave.toml [drivers."<id>"] config` and from nowhere else,
    and DR19 holds absolutely: a config value may name a registered `DriverId` and may never
    name an import path. marker's `--converter_cls` reaching `import_module` on a
    caller-supplied string is the anti-pattern — remote code execution the moment config arrives
    in a request body.

    Specified in 04-driver-system.md sections 2.7 and 2.8.
    """

    properties: Mapping[str, Mapping[str, JsonValue]] = MappingProxyType({})
    required: frozenset[str] = frozenset()

    def defaults(self) -> dict[str, JsonValue]:
        """Every property's `default`, which is required for every property not in `required`."""
        return {
            name: schema["default"]
            for name, schema in self.properties.items()
            if "default" in schema
        }

    def effective(self, values: Mapping[str, JsonValue] | None = None) -> dict[str, JsonValue]:
        """Defaults filled, caller values overlaid, every value checked. The `__init__` input.

        Raises `ConfigError` for an unknown key (`additionalProperties` is `false` and must be),
        for a required key with neither a value nor a default, and for a value outside its
        declared type, enum, bound, length, pattern or item count.
        """
        supplied = dict(values or {})
        unknown = sorted(set(supplied) - set(self.properties))
        if unknown:
            raise ConfigError(
                f"config keys {unknown} are not declared by this driver's [config] schema, "
                f"whose additionalProperties is false",
                fix=f"ow show-config --driver <id>   # the declared keys are "
                f"{sorted(self.properties)}",
            )
        effective = self.defaults() | supplied
        missing = sorted(self.required - set(effective))
        if missing:
            raise ConfigError(
                f"config keys {missing} are required by this driver's [config] schema and have "
                f"neither a supplied value nor a default",
                fix=f"ow config set drivers.<id>.config.{missing[0]} <value>",
            )
        for name in sorted(effective):
            _check_config_value(name, effective[name], self.properties[name])
        return effective

    def config_digest(self, values: Mapping[str, JsonValue] | None = None) -> str:
        """`sha256(canonical(effective_config))` — 64 hex chars, the worker key's second half.

        Bare hex and not `sha256:`-prefixed: this is a cache-key component like
        `sha256_canonical()`'s other callers, never a value written on a card or in a lockfile
        (04-driver-system.md section 2.8).
        """
        return sha256_canonical(self.effective(values))


@dataclass(frozen=True, slots=True)
class DriverIdentity:
    """`[driver]` — identity, Port, versions, the entry point and the two streaming axes.

    `exec` and `entrypoint` are **mutually exclusive and exactly one is required**; a tombstone
    has neither, which is one of the four reasons the tombstone branch has to come first.
    `exec` is legal only for `origin in {driver_path, project}`, so such a driver is always
    `trust = local` and can never reach `inproc` or satisfy `require_lock = true` (erratum E7).

    `port_major` is parsed rather than string-compared because both majors coexist and
    `resolve()` filters on "port major supported". `schema_version` is **the only driver version
    that enters a cache key**, and forgetting to bump it is the most expensive single mistake
    available in the whole design: it serves stale billed output forever with no symptom
    (04-driver-system.md section 5.1).

    `id` and `exec` shadow builtins and are named for the card keys anyway: the card's spelling
    is the contract, and renaming a field here would put a second spelling of one fact in the
    framework (INV-21).
    """

    id: str
    port: Port
    port_major: int
    version: str
    schema_version: int
    granularity: str
    replay_class: ReplayClass
    title: str = ""
    summary: str = ""
    homepage: str = ""
    entrypoint: str | None = None
    exec: tuple[str, ...] | None = None
    detects: bool = False


@dataclass(frozen=True, slots=True)
class DriverCard:
    """One validated `driver.toml`. Everything `resolve()` filters on, and nothing it imports.

    Built only by `load_card()`. `trust` is deliberately NOT a field written here: it is
    "COMPUTED BY THE LOADER, NEVER SELF-REPORTED" from `origin`, the release manifest and the
    lockfile (erratum E13), none of which this module may read without making the card grammar
    depend on installation state — so `origin` is carried and the tier is computed by the
    discovery layer that has those inputs.

    `attested` is `False` when the recomputed `attestation` does not match the declared one, and
    that is **not** a rejection: attestation is tamper-evidence, not authentication, and a card
    whose `[capability.parse]` disagrees with its code is the `capability` conformance suite's
    problem rather than the loader's (04-driver-system.md sections 4.5 and 8.3).

    Specified in 04-driver-system.md sections 2.1 through 2.8 and 3.
    """

    card_schema: int
    identity: DriverIdentity
    capability: Capability
    origin: CardOrigin
    source: str
    card_sha256: str
    attestation: str | None = None
    attested: bool = False
    parse: ParseCapability | None = None
    acquire: AcquireCapability | None = None
    acquire_sibling: AcquireSibling | None = None
    derive: DeriveCapability | None = None
    derive_sibling: DeriveSibling | None = None
    embed: EmbedCapability | None = None
    embed_sibling: EmbedSibling | None = None
    compile_capability: Mapping[str, JsonValue] = MappingProxyType({})
    compile_sibling: Mapping[str, JsonValue] = MappingProxyType({})
    hardware: Hardware = Hardware()
    isolation: IsolationSpec = IsolationSpec()
    limits: CardLimits = CardLimits()
    licence_code: LicenceFacts = LicenceFacts()
    licence_weights: LicenceFacts | None = None
    deps: Deps = Deps()
    config: ConfigSchema = ConfigSchema()
    cost_model: CostModel | None = None
    cost_measured: CostMeasured | None = None
    quality: Quality = Quality()
    deprecation: Deprecation | None = None
    degradations: tuple[CardDegradation, ...] = ()


@dataclass(frozen=True, slots=True)
class Tombstone:
    """A framework-shipped refusal. **Its own type, never a `DriverCard` with holes.**

    DR22: a removed or forbidden driver resolves to a QUOTED REASON and a NAMED REPLACEMENT,
    never to "unknown driver". A test asserts every vetoed id has a tombstone with a non-empty
    reason and a future `review_by`, and CI fails a tombstone past that date, so the refusal set
    cannot silently ossify.

    The licence hashes are the second job: `compute_tier()` returns `forbidden` for any card
    whose `[licence.code].licence_sha256` **or** `[licence.weights].licence_sha256` matches a
    shipped tombstone's. That is hash-keyed, so it **survives renaming** — a third party
    wrapping the same weights under a different driver id computes `forbidden` too — and it
    absorbs the two separate licence-denylist mechanisms D4 carried, both of which are struck.

    Specified in 04-driver-system.md section 7.5 and section 10.4.
    """

    id: str
    port: Port
    port_major: int
    reason: str
    review_by: str
    origin: CardOrigin
    source: str
    card_sha256: str
    card_schema: int = 1
    title: str = ""
    replaced_by: str | None = None
    licence_code: LicenceFacts | None = None
    licence_weights: LicenceFacts | None = None
    attestation: str | None = None
    attested: bool = False


# --------------------------------------------------------------------------------------------
# 4. The digests (04-driver-system.md section 2.8, erratum E14). `canonical()` is
#    `omniweave_core.canonical`'s and is never re-declared here: section 2.8 prints exactly the
#    `json.dumps` keyword arguments that module implements (INV-21).
# --------------------------------------------------------------------------------------------

_SHA256_PREFIX: Final = "sha256:"
"""The form a card and a lockfile write a digest in — `card_sha256 = "sha256:8367cd..."`
(04-driver-system.md section 5.5). Cache-key digests are bare hex; a digest a human diffs in
version control carries its algorithm."""


def card_sha256(raw: bytes) -> str:
    """`sha256:` over the RAW BYTES of `driver.toml` as read from disk.

    Over bytes and not over meaning, for two reasons: the lockfile and G12 pin *bytes*, so a
    comment-only edit must be visible, and a raw-byte digest needs no canonicaliser on the
    discovery path — which is the path INV-3 holds to 80 ms.

    Its counterpart is `attestation_of()`, which a comment-only edit does NOT move. Both exist
    so `ow drivers verify` can fail (the installed bytes are not the locked bytes) while
    `card.attested` stays true (the contract did not change).
    """
    return _SHA256_PREFIX + hashlib.sha256(raw).hexdigest()


def attestation_of(card: Mapping[str, JsonValue]) -> str:
    """`sha256:` over `canonical(card_dict)` with the `attestation` key DELETED.

    Pins MEANING, so reformatting a card does not invalidate a conformance run. Floats are
    serialised by `float.__repr__`, which is round-trip-exact for IEEE-754 doubles, and
    `allow_nan=False` plus a card grammar that forbids `nan` and `inf` removes the only
    remaining ambiguity (04-driver-system.md section 2.8).

    The key must be deleted rather than blanked: `attestation = ""` is a different card from a
    card with no `attestation`, and hashing the second while the first is on disk is a digest
    nothing can reproduce.
    """
    body = {key: value for key, value in card.items() if key != "attestation"}
    return _SHA256_PREFIX + sha256_canonical(body)


def pins_digest(pins: Iterable[str]) -> str:
    """`sha256(canonical(sorted(pins)))` — 64 bare hex characters.

    Enters the cache key **only** for `cost.model.class = "free"` (04-driver-system.md section
    5.1): a free driver's output is cheap to recompute, so invalidating it on a dependency bump
    costs nothing, while a billed driver's is not, so a pdfium or tokenizer bump does not
    silently re-bill the fleet. Bare hex because it is a cache-key component and never a value
    written on a card.
    """
    return sha256_canonical(sorted(pins))


def read_card_bytes(path: Path) -> bytes:
    """Read at most `MAX_CARD_BYTES + 1` bytes of a `driver.toml`. **The bounded read itself.**

    `take(N + 1)`-then-check, at the read boundary, so a card bomb is never allocated: discovery
    parses attacker-adjacent TOML in a process INV-3 holds to 80 ms, and an unbounded read there
    is a denial of service against `ow --version`. The extra byte is what lets `load_card()`
    tell "exactly at the cap" from "over it" without having read the rest of the file
    (04-driver-system.md section 4.5).
    """
    with path.open("rb") as handle:
        return handle.read(MAX_CARD_BYTES + 1)


def served_tokens(
    card: DriverCard,
    format_token_for: object = None,
) -> frozenset[str]:
    """A driver's **served token set** — this section's derived set, not routing's.

    04-driver-system.md section 2.2 defines exactly two derived sets over `format_tokens` and
    gives each one owner. The **computed format-token domain** is over every enabled card at
    once, is `unit.format`'s domain, and belongs to 05-ingest-and-routing.md section 5.1. This
    one is over ONE card: `{ format_token_for(m) for m in [capability] formats }` union
    `{ p.token for p in [capability.parse] format_tokens }`, with `None` results dropped. It
    exists because `formats` holds media types while a rule's `unit.format` clause holds tokens,
    so the two cannot be compared directly, and it is what `ow route lint` check 11 compares a
    rule's format literals against.

    `format_token_for` is the TOTAL media-type-to-token lookup and is routing's — core's
    forty-eight-row table union one row per pair in the enabled cards. It is a parameter rather
    than an import because `omniweave_core.drivers` may not depend on the router, and because
    the lookup is a function of the whole enabled set rather than of this card. Passing `None`
    means "no domain table available here", and the result is then exactly the card's own pair
    tokens — honest rather than silently partial.
    """
    tokens = {pair.token for pair in card.parse.format_tokens} if card.parse else set()
    if callable(format_token_for):
        for media_type in card.capability.formats:
            token = format_token_for(media_type)
            if token is not None:
                tokens.add(str(token))
    return frozenset(tokens)


# --------------------------------------------------------------------------------------------
# 5. Reading one value out of a table. Every getter names WHERE it was reading, because a card
#    error a third party has to act on is only actionable if it names the key.
# --------------------------------------------------------------------------------------------


def _table(doc: Mapping[str, object], name: str, source: str) -> Mapping[str, object]:
    """A required table. A missing one names the table rather than raising `KeyError`."""
    value = doc.get(name)
    if not isinstance(value, dict):
        _card_invalid(source, f"[{name}] is required and must be a table")
    return value


def _sub(table: Mapping[str, object], name: str) -> Mapping[str, object] | None:
    """An optional sub-table, or `None` when absent."""
    value = table.get(name)
    return value if isinstance(value, dict) else None


def _as_str(value: object, where: str, source: str) -> str:
    if not isinstance(value, str):
        _card_invalid(source, f"{where} must be a string, not {type(value).__name__}")
    return value


def _as_bool(value: object, where: str, source: str) -> bool:
    if not isinstance(value, bool):
        _card_invalid(source, f"{where} must be true or false, not {value!r}")
    return value


def _as_int(value: object, where: str, source: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        _card_invalid(source, f"{where} must be an integer, not {value!r}")
    return value


def _as_number(value: object, where: str, source: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _card_invalid(source, f"{where} must be a number, not {value!r}")
    return float(value)


def _as_strings(value: object, where: str, source: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _card_invalid(source, f"{where} must be an array of strings, not {value!r}")
    return tuple(_as_str(item, f"{where}[{i}]", source) for i, item in enumerate(value))


def _one_of(value: object, domain: Sequence[str], where: str, source: str) -> str:
    """A closed vocabulary. The error PRINTS the domain, so the fix needs no second lookup."""
    text = _as_str(value, where, source)
    if text not in domain:
        _card_invalid(source, f"{where} = {text!r} is not one of {list(domain)}")
    return text


def _capped(items: Iterable[object], cap: int, where: str, source: str) -> list[object]:
    """`take(N + 1)`-then-check, so the refusal never costs more memory than the cap plus one.

    The extra element is what distinguishes "exactly at the cap" from "over it"; the breach
    names the key AND the cap, because a message that names only one of them leaves the author
    guessing at the other (04-driver-system.md section 4.5).
    """
    head = list(islice(iter(items), cap + 1))
    if len(head) > cap:
        _card_invalid(source, f"{where} has more than {cap} members, its cap")
    return head


def _reject_unknown(
    table: Mapping[str, object], known: Iterable[str], where: str, source: str
) -> None:
    """A hard error naming every unknown key. Used everywhere the asymmetry does NOT apply."""
    unknown = sorted(set(table) - set(known))
    if unknown:
        _card_invalid(
            source,
            f"{where} carries unknown key{'s' if len(unknown) > 1 else ''} "
            f"{unknown}; a card is a contract and this table is closed",
        )


def _ignore_unknown(
    table: Mapping[str, object], known: Iterable[str], where: str
) -> tuple[dict[str, object], list[CardDegradation]]:
    """The ONE safe asymmetry: an unknown key in `[capability.<port>]` is ignored and recorded.

    Safe only because every key in such a table is an ordered ladder or a set-valued floor, so
    an unrecognised one can only make a driver look LESS capable (04-driver-system.md section
    2.1). Returns the recognised keys and one `CardDegradation` per ignored one.
    """
    recognised = {key: value for key, value in table.items() if key in set(known)}
    ignored = [
        CardDegradation(
            kind=CARD_CAPABILITY_UNKNOWN,
            table=where,
            key=key,
            detail=f"{where} {key} is not a key this build knows; the floor it declares is "
            f"ignored, which can only make the driver look less capable",
        )
        for key in sorted(set(table) - set(recognised))
    ]
    return recognised, ignored


def _ladder(
    table: Mapping[str, object],
    key: str,
    ladders: Mapping[str, tuple[str, ...]],
    source: str,
    where: str,
) -> str:
    """One ordered-ladder value, defaulting to the least capable rung when the key is absent.

    An out-of-domain VALUE is `CARD_INVALID` and is not ignored. The asymmetry of section 2.1 is
    stated over unknown *keys*, and section 2.2 narrows its one exception to "keys and members"
    — a ladder value is neither, and a rung this build cannot order is a rung `resolve()` cannot
    compare, so accepting it would make the comparison arbitrary rather than merely
    conservative.
    """
    rungs = ladders[key]
    if key not in table:
        return rungs[0]
    return _one_of(table[key], rungs, f"{where} {key}", source)


def _member_set(
    table: Mapping[str, object],
    key: str,
    vocabulary: frozenset[str],
    source: str,
    where: str,
    *,
    keep_unknown: bool = False,
) -> tuple[frozenset[str], list[CardDegradation]]:
    """One set-valued key, with the `forfeits` exception carried by `keep_unknown`.

    Every set on a card except `forfeits` is a FLOOR compared `⊇`, so an unknown member only
    shrinks it and is dropped. `forfeits` is compared `⊆` and is **the only inverted comparison
    on the whole card**: dropping an unknown member there would make the driver look MORE
    capable, so the member is KEPT and `resolve()` fails the match with detail
    `forfeits_unknown_member`. This narrows the asymmetry from keys to keys-and-members; it is
    the only exception, and a proposed second one is a reason to reject the PR (section 2.2).
    """
    if key not in table:
        return frozenset(), []
    members = _as_strings(table[key], f"{where} {key}", source)
    unknown = sorted(set(members) - vocabulary)
    recorded = [
        CardDegradation(
            kind=CARD_CAPABILITY_UNKNOWN,
            table=where,
            key=key,
            detail=f"{where} {key} names {member!r}, which is not in this build's vocabulary "
            + (
                "and is KEPT, because forfeits is inverted and dropping it would make the "
                "driver look more capable"
                if keep_unknown
                else "and is dropped, which can only shrink the floor"
            ),
        )
        for member in unknown
    ]
    kept = set(members) if keep_unknown else set(members) & vocabulary
    return frozenset(kept), recorded


# --------------------------------------------------------------------------------------------
# 6. The `[config]` closed JSON-Schema subset (04-driver-system.md section 2.7, erratum E3).
# --------------------------------------------------------------------------------------------

_CONFIG_ROOT_ONLY: Final[frozenset[str]] = frozenset(
    {"additionalProperties", "properties", "required"}
)
_CONFIG_PROPERTY_KEYWORDS: Final[frozenset[str]] = frozenset(CONFIG_KEYWORDS) - _CONFIG_ROOT_ONLY
_CONFIG_KEYWORD_TYPES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "enum": frozenset({"string", "integer"}),
        "minimum": frozenset({"integer", "number"}),
        "maximum": frozenset({"integer", "number"}),
        "minLength": frozenset({"string"}),
        "maxLength": frozenset({"string"}),
        "pattern": frozenset({"string"}),
        "items": frozenset({"array"}),
        "minItems": frozenset({"array"}),
        "maxItems": frozenset({"array"}),
    }
)
"""Which `type` each keyword is legal under, from 04-driver-system.md section 2.7's "where
legal" column. A `pattern` on an integer is not a stricter integer, it is a schema whose author
believed something false about it."""


def _reject_config_keyword(keyword: str, where: str, source: str) -> NoReturn:
    """`CARD_INVALID` **naming the keyword** — the whole point of a closed subset.

    A rejected keyword is named rather than reported as "unknown" because the author has to know
    which of the ten they reached for. `$ref` alone turns a sixty-line validator into a resolver
    with a cycle detector, and a driver's static config has never needed one.
    """
    _card_invalid(
        source,
        f"{where} uses the JSON-Schema keyword {keyword!r}, which is outside the closed subset "
        f"of 04-driver-system.md section 2.7; the subset is {list(CONFIG_KEYWORDS)}",
    )


def _check_config_keywords(
    table: Mapping[str, object], legal: Iterable[str], where: str, source: str
) -> None:
    """Every keyword present is legal HERE, and a rejected one is named as itself."""
    legal_set = set(legal)
    for keyword in sorted(table):
        if keyword in legal_set:
            continue
        if keyword in CONFIG_REJECTED_KEYWORDS or keyword in CONFIG_KEYWORDS:
            _reject_config_keyword(keyword, where, source)
        _card_invalid(source, f"{where} carries unknown [config] keyword {keyword!r}")


def _config_bounds(schema: Mapping[str, object], declared: str, where: str, source: str) -> None:
    """The four numeric ceilings of the subset, plus each keyword's `type` gate."""
    for keyword, types in _CONFIG_KEYWORD_TYPES.items():
        if keyword in schema and declared not in types:
            _card_invalid(
                source,
                f"{where} {keyword} is legal only for type {sorted(types)}, not {declared!r}",
            )
    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list):
            _card_invalid(source, f"{where} enum must be an array of at most 32 scalars")
        _capped(enum, MAX_ENUM_MEMBERS, f"{where} enum", source)
    if "maxLength" in schema and _as_int(schema["maxLength"], f"{where} maxLength", source) > (
        MAX_STRING_LENGTH
    ):
        _card_invalid(source, f"{where} maxLength is above {MAX_STRING_LENGTH}, its cap")
    if "maxItems" in schema and _as_int(schema["maxItems"], f"{where} maxItems", source) > (
        MAX_ARRAY_ITEMS
    ):
        _card_invalid(source, f"{where} maxItems is above {MAX_ARRAY_ITEMS}, its cap")


def _config_pattern(schema: Mapping[str, object], where: str, source: str) -> None:
    """`pattern` is at most 200 characters and is **compiled at load**, not at first use.

    Compiling here is what makes an unparseable regex a card error rather than a crash on the
    first request that happens to reach it.
    """
    if "pattern" not in schema:
        return
    pattern = _as_str(schema["pattern"], f"{where} pattern", source)
    if len(pattern) > MAX_PATTERN_CHARS:
        _card_invalid(source, f"{where} pattern is longer than {MAX_PATTERN_CHARS} characters")
    try:
        re.compile(pattern)
    except re.error as exc:
        _card_invalid(source, f"{where} pattern {pattern!r} does not compile: {exc}")


def _config_property(
    name: str, schema: object, required: frozenset[str], source: str
) -> Mapping[str, JsonValue]:
    """One `[config.properties.<name>]` sub-table, fully checked.

    `default` is REQUIRED for every property not in `required`, because `effective_config` has
    to be total before it can be digested and a cache key over a partial mapping is a cache key
    that changes when a caller omits a key they were entitled to omit.
    """
    where = f"[config.properties.{name}]"
    if not isinstance(schema, dict):
        _card_invalid(source, f"{where} must be a table")
    _check_config_keywords(schema, _CONFIG_PROPERTY_KEYWORDS, where, source)
    declared = _one_of(schema.get("type", ""), CONFIG_TYPES, f"{where} type", source)
    _config_bounds(schema, declared, where, source)
    _config_pattern(schema, where, source)
    if "items" in schema:
        _config_items(schema["items"], where, source)
    if name not in required and "default" not in schema:
        _card_invalid(
            source,
            f"{where} is not in [config] required and declares no default; every optional "
            f"property needs one, or config_digest is not computable",
        )
    if "default" in schema:
        try:
            _check_config_value(name, schema["default"], schema)
        except ConfigError as exc:
            _card_invalid(source, f"{where} default is outside its own declared domain: {exc}")
    return MappingProxyType(dict(schema))


def _config_items(items: object, where: str, source: str) -> None:
    """`items` is ONE `{type, ...}` table; **arrays of objects are not in the subset**."""
    if not isinstance(items, dict):
        _card_invalid(source, f"{where} items must be one table, not {type(items).__name__}")
    _check_config_keywords(items, _CONFIG_PROPERTY_KEYWORDS - {"default", "items"}, where, source)
    member = _one_of(items.get("type", ""), CONFIG_TYPES, f"{where} items.type", source)
    if member == "object":
        _card_invalid(
            source, f"{where} items.type is 'object'; arrays of objects are not in the subset"
        )


def _config_schema(doc: Mapping[str, object], source: str) -> ConfigSchema:
    """`[config]` — root-only keywords, at most `MAX_CARD_CONFIG_PROPERTIES` properties."""
    table = doc.get("config")
    if table is None:
        return ConfigSchema()
    if not isinstance(table, dict):
        _card_invalid(source, "[config] must be a table")
    _check_config_keywords(
        table, ("type", "additionalProperties", "properties", "required"), "[config]", source
    )
    _one_of(table.get("type", ""), ("object",), "[config] type", source)
    if table.get("additionalProperties") is not False:
        _card_invalid(
            source,
            "[config] additionalProperties must be present and must be false; an open config "
            "table cannot be validated before construction and its digest would not be a key",
        )
    properties = table.get("properties", {})
    if not isinstance(properties, dict):
        _card_invalid(source, "[config] properties must be a table")
    _capped(list(properties), MAX_CARD_CONFIG_PROPERTIES, "[config] properties", source)
    required = frozenset(_as_strings(table.get("required", []), "[config] required", source))
    unknown_required = sorted(required - set(properties))
    if unknown_required:
        _card_invalid(source, f"[config] required names undeclared properties {unknown_required}")
    return ConfigSchema(
        properties=MappingProxyType(
            {
                name: _config_property(name, schema, required, source)
                for name, schema in properties.items()
            }
        ),
        required=required,
    )


_CONFIG_PYTHON_TYPES: Final[Mapping[str, tuple[type, ...]]] = MappingProxyType(
    {
        "string": (str,),
        "integer": (int,),
        "number": (int, float),
        "boolean": (bool,),
        "array": (list, tuple),
        "object": (dict,),
    }
)


def _check_config_value(name: str, value: object, schema: Mapping[str, object]) -> None:
    """One effective config value against its declared property schema.

    Raises `ConfigError`, not a card error: by the time this runs the card has already been
    validated, and what is wrong is the operator's `omniweave.toml [drivers."<id>"] config`.
    """
    declared = str(schema.get("type", ""))
    allowed = _CONFIG_PYTHON_TYPES.get(declared, ())
    if isinstance(value, bool) != (declared == "boolean") or not isinstance(value, allowed):
        raise ConfigError(
            f"config value {name} = {value!r} is not a {declared}",
            fix=f"ow config set drivers.<id>.config.{name} <a {declared}>",
        )
    _check_config_domain(name, value, schema)


def _check_config_domain(name: str, value: object, schema: Mapping[str, object]) -> None:
    """`enum`, `minimum`/`maximum`, `minLength`/`maxLength`, `pattern`, `minItems`/`maxItems`."""
    checks: tuple[tuple[str, bool], ...] = (
        ("enum", "enum" in schema and value not in schema["enum"]),
        ("minimum", "minimum" in schema and value < schema["minimum"]),
        ("maximum", "maximum" in schema and value > schema["maximum"]),
        ("minLength", "minLength" in schema and len(str(value)) < schema["minLength"]),
        ("maxLength", "maxLength" in schema and len(str(value)) > schema["maxLength"]),
        ("pattern", "pattern" in schema and re.match(str(schema["pattern"]), str(value)) is None),
        ("minItems", "minItems" in schema and len(value) < schema["minItems"]),
        ("maxItems", "maxItems" in schema and len(value) > schema["maxItems"]),
    )
    for keyword, failed in checks:
        if failed:
            raise ConfigError(
                f"config value {name} = {value!r} violates {keyword} = {schema[keyword]!r}",
                fix=f"ow config set drivers.<id>.config.{name} <a value satisfying {keyword}>",
            )


# --------------------------------------------------------------------------------------------
# 7. The tables, one builder each.
# --------------------------------------------------------------------------------------------

_SEMVER_RE: Final = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DRIVER_KEYS: Final = (
    "id",
    "port",
    "version",
    "schema_version",
    "title",
    "summary",
    "homepage",
    "entrypoint",
    "exec",
    "granularity",
    "replay_class",
    "detects",
)
_TOMBSTONE_DRIVER_KEYS: Final = ("id", "port", "title")
"""Only three keys are legal in a TOMBSTONE's `[driver]` table (04-driver-system.md section
7.5). Section 2.1 additionally says a tombstone's `version` "is a wildcard, which is not
semver"; the two statements disagree, and section 7.5's explicit enumeration is taken as the
grammar because it is the tombstone section's own normative sentence. Reported as a departure."""
_TOMBSTONE_KEYS: Final = ("reason", "replaced_by", "review_by")
_TOMBSTONE_TABLES: Final = frozenset({"driver", "tombstone", "licence"})


def _semver(value: object, where: str, source: str) -> tuple[int, int, int]:
    text = _as_str(value, where, source)
    match = _SEMVER_RE.match(text)
    if match is None:
        _card_invalid(source, f"{where} = {text!r} is not a MAJOR.MINOR.PATCH semver")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _port_of(value: object, where: str, source: str) -> tuple[Port, int]:
    text = _as_str(value, where, source)
    match = PORT_RE.match(text)
    if match is None:
        _card_invalid(source, f"{where} = {text!r} is not <name>/<MAJOR> over the five Ports")
    return Port(match.group(1)), int(match.group(2))


def _driver_id(value: object, port: Port, where: str, source: str) -> str:
    """The `DriverId` grammar, cross-checked against `[driver] port`.

    The first segment IS the Port (charter section 5 X35), so an id and a port that disagree are
    two statements of one fact that cannot both be true — and `origin_operator`, stamped on
    every row the driver produces, is read out of the id rather than out of the port key.
    """
    text = _as_str(value, where, source)
    if DRIVER_ID_RE.match(text) is None:
        _card_invalid(source, f"{where} = {text!r} does not match the DriverId grammar")
    if text.split(".", 1)[0] != port.value:
        _card_invalid(
            source,
            f"{where} = {text!r} names Port {text.split('.', 1)[0]!r} in its first segment "
            f"while [driver] port declares {port.value!r}; the first segment IS the Port",
        )
    return text


def _exec_argv(value: object, origin: CardOrigin, source: str) -> tuple[str, ...]:
    """`[driver] exec` — argv RELATIVE to the card's own directory (erratum E7).

    Four rules, all `CARD_INVALID` on breach: the origin must be `driver_path` or `project`, so
    such a driver is always `trust = local`; `argv[0]` must resolve, after `realpath`, INSIDE
    the card's directory, which is what rules out a `..` escape, an absolute path and a `PATH`
    lookup at once; and no element may carry a shell metacharacter, since the host spawns with
    `shell=False` and an element that only makes sense to a shell is evidence of a belief that
    the next reader will inherit.
    """
    argv = _as_strings(value, "[driver] exec", source)
    if origin not in ("driver_path", "project"):
        _card_invalid(
            source,
            f"[driver] exec is legal only for origin driver_path or project, not {origin!r}: an "
            f"exec driver is always trust = local and can never satisfy require_lock",
        )
    if not argv:
        _card_invalid(source, "[driver] exec is an argv and may not be empty")
    for i, element in enumerate(argv):
        bad = sorted(set(element) & SHELL_METACHARACTERS)
        if bad:
            _card_invalid(source, f"[driver] exec[{i}] carries shell metacharacters {bad}")
    _exec_inside_card_dir(argv[0], source)
    return argv


def _exec_inside_card_dir(argv0: str, source: str) -> None:
    """`realpath(argv[0])` is under the card's own directory, or the card is refused."""
    if Path(argv0).is_absolute():
        _card_invalid(source, f"[driver] exec[0] {argv0!r} is absolute; argv is card-relative")
    root = Path(source).resolve().parent
    target = (root / argv0).resolve()
    if not target.is_relative_to(root):
        _card_invalid(
            source,
            f"[driver] exec[0] {argv0!r} resolves to {target}, outside the card's own "
            f"directory {root}",
        )


def _driver_identity(
    table: Mapping[str, object], origin: CardOrigin, source: str
) -> DriverIdentity:
    """`[driver]`, with the entrypoint/exec exclusive-or that a tombstone is exempt from."""
    _reject_unknown(table, _DRIVER_KEYS, "[driver]", source)
    port, major = _port_of(table.get("port"), "[driver] port", source)
    entrypoint = table.get("entrypoint")
    raw_exec = table.get("exec")
    if (entrypoint is None) == (raw_exec is None):
        _card_invalid(
            source,
            "[driver] must carry exactly one of entrypoint and exec; they are mutually "
            "exclusive and exactly one is required (only a tombstone has neither)",
        )
    where_ep = "[driver] entrypoint"
    declared_entrypoint = None if entrypoint is None else _as_str(entrypoint, where_ep, source)
    if declared_entrypoint is not None and ENTRYPOINT_RE.match(declared_entrypoint) is None:
        _entrypoint_malformed(
            source,
            f"[driver] entrypoint = {entrypoint!r} is not <dotted.module>:<Attr>: it must "
            f"contain exactly one ':' and no '/'",
        )
    _semver(table.get("version"), "[driver] version", source)
    return DriverIdentity(
        id=_driver_id(table.get("id"), port, "[driver] id", source),
        port=port,
        port_major=major,
        version=_as_str(table.get("version"), "[driver] version", source),
        schema_version=_as_int(table.get("schema_version"), "[driver] schema_version", source),
        granularity=_one_of(
            table.get("granularity"), GRANULARITIES, "[driver] granularity", source
        ),
        replay_class=ReplayClass(
            _one_of(
                table.get("replay_class"),
                tuple(member.value for member in ReplayClass),
                "[driver] replay_class",
                source,
            )
        ),
        title=_as_str(table.get("title", ""), "[driver] title", source),
        summary=_as_str(table.get("summary", ""), "[driver] summary", source),
        homepage=_as_str(table.get("homepage", ""), "[driver] homepage", source),
        entrypoint=declared_entrypoint,
        exec=None if raw_exec is None else _exec_argv(raw_exec, origin, source),
        detects=_as_bool(table.get("detects", False), "[driver] detects", source),
    )


def _artifact_kinds(value: object, where: str, source: str) -> frozenset[ArtifactKind]:
    """A `consumes` / `produces` set over the CLOSED thirteen-member vocabulary.

    The vocabulary has no experimental namespace: an experimental one reintroduces the
    spelling-dependent DAG a closed vocabulary exists to prevent, and adding a member bumps
    `card_schema` (04-driver-system.md section 2.3).
    """
    members = _as_strings(value, where, source)
    known = {kind.value for kind in ArtifactKind}
    outside = sorted(set(members) - known)
    if outside:
        _card_invalid(source, f"{where} names {outside}, outside the closed artifact-kind set")
    return frozenset(ArtifactKind(member) for member in members)


def _capability(table: Mapping[str, object], source: str) -> Capability:
    """`[capability]` — media types, and the two artifact-kind sets."""
    _reject_unknown(
        table,
        ("formats", "consumes", "produces", *(port.value for port in Port)),
        "[capability]",
        source,
    )
    formats = _as_strings(table.get("formats", []), "[capability] formats", source)
    _capped(formats, MAX_CARD_FORMATS, "[capability] formats", source)
    produces = _artifact_kinds(table.get("produces", []), "[capability] produces", source)
    if produces == frozenset({ArtifactKind.DIAG}):
        _card_invalid(
            source,
            "[capability] produces is exactly ['diag']; a diagnostic is never the sole member "
            "of produces, because a driver that only ever emits one has produced nothing",
        )
    return Capability(
        formats=formats,
        consumes=_artifact_kinds(table.get("consumes", []), "[capability] consumes", source),
        produces=produces,
    )


def _format_token_pairs(
    value: object, formats: Sequence[str], source: str
) -> tuple[FormatTokenPair, ...]:
    """`format_tokens` — pair-shaped, and both halves are this document's validations.

    A member whose `token` fails `[a-z0-9]{1,16}`, or whose `media_type` is absent from the same
    card's `[capability] formats`, is `CARD_INVALID`. The CROSS-CARD collision — two enabled
    cards pairing one `media_type` with different `token`s — is `OW-D-024` and is an ACTIVATION
    error, not a load-time one, because it is a property of the enabled set rather than of any
    one card (04-driver-system.md section 2.2).
    """
    if not isinstance(value, list):
        _card_invalid(source, "[capability.parse] format_tokens must be an array of tables")
    pairs: list[FormatTokenPair] = []
    for i, member in enumerate(value):
        where = f"[capability.parse] format_tokens[{i}]"
        if not isinstance(member, dict):
            _card_invalid(source, f"{where} must be an inline table {{ media_type, token }}")
        _reject_unknown(member, ("media_type", "token"), where, source)
        token = _as_str(member.get("token"), f"{where}.token", source)
        media_type = _as_str(member.get("media_type"), f"{where}.media_type", source)
        if FORMAT_TOKEN_RE.match(token) is None:
            _card_invalid(source, f"{where}.token = {token!r} does not match [a-z0-9]{{1,16}}")
        if media_type not in formats:
            _card_invalid(
                source,
                f"{where}.media_type = {media_type!r} is not in this card's [capability] "
                f"formats, so the pair associates a token with a format the card does not serve",
            )
        pairs.append(FormatTokenPair(media_type=media_type, token=token))
    return tuple(pairs)


def _parse_capability(
    table: Mapping[str, object], formats: Sequence[str], source: str
) -> tuple[ParseCapability, list[CardDegradation]]:
    """`[capability.parse]` — the fifteen floors plus `format_tokens`."""
    known = (*PARSE_LADDERS, *PARSE_BOOLS, *PARSE_SETS, "format_tokens")
    recognised, degradations = _ignore_unknown(table, known, "[capability.parse]")
    math, math_notes = _member_set(
        recognised, "math", PARSE_SETS["math"], source, "[capability.parse]"
    )
    forfeits, forfeit_notes = _member_set(
        recognised,
        "forfeits",
        PARSE_SETS["forfeits"],
        source,
        "[capability.parse]",
        keep_unknown=True,
    )
    ladders = {
        key: _ladder(recognised, key, PARSE_LADDERS, source, "[capability.parse]")
        for key in PARSE_LADDERS
    }
    bools = {
        key: _as_bool(recognised.get(key, False), f"[capability.parse] {key}", source)
        for key in PARSE_BOOLS
    }
    capability = ParseCapability(
        math=math,
        forfeits=forfeits,
        format_tokens=_format_token_pairs(recognised.get("format_tokens", []), formats, source),
        **ladders,
        **bools,
    )
    return capability, [*degradations, *math_notes, *forfeit_notes]


def _acquire_capability(
    table: Mapping[str, object], source: str
) -> tuple[AcquireCapability, list[CardDegradation]]:
    known = (*ACQUIRE_LADDERS, "schemes", "ranges", "streaming", "authn", "trust_class_declared")
    recognised, degradations = _ignore_unknown(table, known, "[capability.acquire]")
    schemes = frozenset(
        _as_strings(recognised.get("schemes", []), "[capability.acquire] schemes", source)
    )
    authn, authn_notes = _member_set(
        recognised, "authn", ACQUIRE_AUTHN, source, "[capability.acquire]"
    )
    ladders = {
        key: _ladder(recognised, key, ACQUIRE_LADDERS, source, "[capability.acquire]")
        for key in ACQUIRE_LADDERS
    }
    capability = AcquireCapability(
        schemes=schemes,
        authn=authn,
        ranges=_as_bool(recognised.get("ranges", False), "[capability.acquire] ranges", source),
        streaming=_as_bool(
            recognised.get("streaming", False), "[capability.acquire] streaming", source
        ),
        trust_class_declared=_as_bool(
            recognised.get("trust_class_declared", False),
            "[capability.acquire] trust_class_declared",
            source,
        ),
        **ladders,
    )
    return capability, [*degradations, *authn_notes]


def _acquire_sibling(table: Mapping[str, object], source: str) -> AcquireSibling:
    where = "[acquire]"
    _reject_unknown(
        table,
        ("implemented", "max_units_per_call", "rate_limit_rps", "cursor_opaque"),
        where,
        source,
    )
    return AcquireSibling(
        implemented=_as_bool(table.get("implemented", False), f"{where} implemented", source),
        max_units_per_call=_as_int(
            table.get("max_units_per_call", 0), f"{where} max_units_per_call", source
        ),
        rate_limit_rps=_as_int(table.get("rate_limit_rps", 0), f"{where} rate_limit_rps", source),
        cursor_opaque=_as_bool(table.get("cursor_opaque", False), f"{where} cursor_opaque", source),
    )


def _derive_capability(
    table: Mapping[str, object], source: str
) -> tuple[DeriveCapability, list[CardDegradation]]:
    known = (*DERIVE_LADDERS, "items", "coreference", "scripts", "scope_honoured")
    recognised, degradations = _ignore_unknown(table, known, "[capability.derive]")
    items, item_notes = _member_set(
        recognised, "items", DERIVE_ITEMS, source, "[capability.derive]"
    )
    ladders = {
        key: _ladder(recognised, key, DERIVE_LADDERS, source, "[capability.derive]")
        for key in DERIVE_LADDERS
    }
    capability = DeriveCapability(
        items=items,
        coreference=_as_bool(
            recognised.get("coreference", False), "[capability.derive] coreference", source
        ),
        scripts=_as_strings(recognised.get("scripts", []), "[capability.derive] scripts", source),
        scope_honoured=_as_bool(
            recognised.get("scope_honoured", False), "[capability.derive] scope_honoured", source
        ),
        **ladders,
    )
    return capability, [*degradations, *item_notes]


def _derive_sibling(table: Mapping[str, object], source: str) -> DeriveSibling:
    where = "[derive]"
    _reject_unknown(
        table,
        ("implemented", "phase", "max_items_per_segment", "prompt_version", "schema_path"),
        where,
        source,
    )
    return DeriveSibling(
        implemented=_as_bool(table.get("implemented", False), f"{where} implemented", source),
        phase=_as_int(table.get("phase", 50), f"{where} phase", source),
        max_items_per_segment=_as_int(
            table.get("max_items_per_segment", 0), f"{where} max_items_per_segment", source
        ),
        prompt_version=_as_str(table.get("prompt_version", ""), f"{where} prompt_version", source),
        schema_path=_as_str(table.get("schema_path", ""), f"{where} schema_path", source),
    )


def _embed_capability(
    table: Mapping[str, object], source: str
) -> tuple[EmbedCapability, list[CardDegradation]]:
    known = (*EMBED_LADDERS, "inputs", "quantization", "instructions", "multi_vector")
    recognised, degradations = _ignore_unknown(table, known, "[capability.embed]")
    inputs, input_notes = _member_set(
        recognised, "inputs", EMBED_INPUTS, source, "[capability.embed]"
    )
    quantization, quant_notes = _member_set(
        recognised, "quantization", EMBED_QUANTIZATIONS, source, "[capability.embed]"
    )
    capability = EmbedCapability(
        inputs=inputs,
        quantization=quantization,
        truncation=_ladder(recognised, "truncation", EMBED_LADDERS, source, "[capability.embed]"),
        instructions=_as_bool(
            recognised.get("instructions", False), "[capability.embed] instructions", source
        ),
        multi_vector=_as_bool(
            recognised.get("multi_vector", False), "[capability.embed] multi_vector", source
        ),
    )
    return capability, [*degradations, *input_notes, *quant_notes]


def _embed_sibling(table: Mapping[str, object], source: str) -> EmbedSibling:
    where = "[embed]"
    _reject_unknown(
        table,
        (
            "implemented",
            "model_id",
            "model_revision",
            "dim",
            "metric",
            "normalization",
            "max_tokens",
            "max_units",
        ),
        where,
        source,
    )
    revision = _as_str(table.get("model_revision", ""), f"{where} model_revision", source)
    if revision == FORBIDDEN_REVISION:
        _card_invalid(
            source,
            f"{where} model_revision = {FORBIDDEN_REVISION!r} is forbidden framework-wide: a "
            f"branch name is not a pinned model, and an index built against a moving revision "
            f"is corrupt with no symptom (RT14)",
        )
    return EmbedSibling(
        implemented=_as_bool(table.get("implemented", False), f"{where} implemented", source),
        model_id=_as_str(table.get("model_id", ""), f"{where} model_id", source),
        model_revision=revision,
        dim=_as_int(table.get("dim", 0), f"{where} dim", source),
        metric=_one_of(table.get("metric", "cosine"), EMBED_METRICS, f"{where} metric", source),
        normalization=_one_of(
            table.get("normalization", "none"),
            EMBED_NORMALIZATIONS,
            f"{where} normalization",
            source,
        ),
        max_tokens=_as_int(table.get("max_tokens", 0), f"{where} max_tokens", source),
        max_units=_as_int(table.get("max_units", 0), f"{where} max_units", source),
    )


@dataclass(frozen=True, slots=True)
class _PortTables:
    """The one `[capability.<port>]` / `[<port>]` pair a card is allowed to carry."""

    parse: ParseCapability | None = None
    acquire: AcquireCapability | None = None
    acquire_sibling: AcquireSibling | None = None
    derive: DeriveCapability | None = None
    derive_sibling: DeriveSibling | None = None
    embed: EmbedCapability | None = None
    embed_sibling: EmbedSibling | None = None
    compile_capability: Mapping[str, JsonValue] = MappingProxyType({})
    compile_sibling: Mapping[str, JsonValue] = MappingProxyType({})


def _reject_foreign_ports(
    doc: Mapping[str, object], cap_table: Mapping[str, object], port: Port, source: str
) -> None:
    """A card implements exactly ONE Port, so it may declare exactly one Port's tables.

    A `[capability.embed]` on a `parse/1` card is a capability claim about a Port the driver does
    not implement; `resolve()` would never read it and `activate()` would never assert it, so it
    is a statement nothing can falsify. 04-driver-system.md section 1.1 makes a Driver "one
    implementation of exactly one of five Ports"; the refusal is this module's reading of that
    sentence and is reported as a departure.
    """
    for other in Port:
        if other is port:
            continue
        if other.value in cap_table:
            _card_invalid(
                source,
                f"[capability.{other.value}] is declared on a {port.value}/1 card; a driver "
                f"implements exactly one Port",
            )
        if other.value in doc:
            _card_invalid(
                source,
                f"[{other.value}] is declared on a {port.value}/1 card; a driver implements "
                f"exactly one Port",
            )


def _port_tables(
    doc: Mapping[str, object],
    cap_table: Mapping[str, object],
    port: Port,
    formats: Sequence[str],
    source: str,
) -> tuple[_PortTables, list[CardDegradation]]:
    """The card's own `[capability.<port>]` and `[<port>]` sibling, and nobody else's.

    `compile` is carried verbatim: `[capability.compile]` and `[compile]` are
    09-generation.md's grammar, printed in 18-api-sketch.md section 8 rather than here, so this
    module preserves them rather than inventing their key sets. Reported as unfinished.
    """
    _reject_foreign_ports(doc, cap_table, port, source)
    capability = _sub(cap_table, port.value) or {}
    sibling = _sub(doc, port.value)
    if port is Port.PARSE:
        parse, notes = _parse_capability(capability, formats, source)
        _reject_unknown(sibling or {}, (), "[parse]", source)
        return _PortTables(parse=parse), notes
    if port is Port.ACQUIRE:
        acquire, notes = _acquire_capability(capability, source)
        built = None if sibling is None else _acquire_sibling(sibling, source)
        return _PortTables(acquire=acquire, acquire_sibling=built), notes
    if port is Port.DERIVE:
        derive, notes = _derive_capability(capability, source)
        built = None if sibling is None else _derive_sibling(sibling, source)
        return _PortTables(derive=derive, derive_sibling=built), notes
    if port is Port.EMBED:
        embed, notes = _embed_capability(capability, source)
        built = None if sibling is None else _embed_sibling(sibling, source)
        return _PortTables(embed=embed, embed_sibling=built), notes
    return (
        _PortTables(
            compile_capability=MappingProxyType(dict(capability)),
            compile_sibling=MappingProxyType(dict(sibling or {})),
        ),
        [],
    )


def _hardware(doc: Mapping[str, object], source: str) -> Hardware:
    table = doc.get("hardware")
    if table is None:
        return Hardware()
    if not isinstance(table, dict):
        _card_invalid(source, "[hardware] must be a table")
    where = "[hardware]"
    _reject_unknown(
        table,
        (
            "gpu",
            "vram_gb_min",
            "ram_gb_min",
            "cpu_arch",
            "os",
            "needs_network",
            "needs_binaries",
            "imports_torch",
            "install_bytes",
            "services",
        ),
        where,
        source,
    )
    binaries = _as_strings(table.get("needs_binaries", []), f"{where} needs_binaries", source)
    _capped(binaries, MAX_CARD_BINARIES, f"{where} needs_binaries", source)
    return Hardware(
        gpu=_one_of(table.get("gpu", "none"), GPU_REQUIREMENTS, f"{where} gpu", source),
        vram_gb_min=_as_number(table.get("vram_gb_min", 0), f"{where} vram_gb_min", source),
        ram_gb_min=_as_number(table.get("ram_gb_min", 0), f"{where} ram_gb_min", source),
        cpu_arch=_as_strings(table.get("cpu_arch", []), f"{where} cpu_arch", source),
        os=_as_strings(table.get("os", []), f"{where} os", source),
        needs_network=_as_bool(table.get("needs_network", False), f"{where} needs_network", source),
        needs_binaries=binaries,
        imports_torch=_as_bool(table.get("imports_torch", False), f"{where} imports_torch", source),
        install_bytes=_as_int(table.get("install_bytes", 0), f"{where} install_bytes", source),
        services=_as_strings(table.get("services", []), f"{where} services", source),
    )


def _isolation(doc: Mapping[str, object], source: str) -> IsolationSpec:
    table = doc.get("isolation")
    if table is None:
        return IsolationSpec()
    if not isinstance(table, dict):
        _card_invalid(source, "[isolation] must be a table")
    where = "[isolation]"
    _reject_unknown(
        table,
        ("requires", "memory_mb", "progress_ms", "wall_ms_hard", "batch_max_units"),
        where,
        source,
    )
    return IsolationSpec(
        requires=Isolation(
            _one_of(
                table.get("requires", Isolation.SUBPROC.value),
                tuple(member.value for member in Isolation),
                f"{where} requires",
                source,
            )
        ),
        memory_mb=_as_int(table.get("memory_mb", 0), f"{where} memory_mb", source),
        progress_ms=_as_int(table.get("progress_ms", 0), f"{where} progress_ms", source),
        wall_ms_hard=_as_int(table.get("wall_ms_hard", 0), f"{where} wall_ms_hard", source),
        batch_max_units=_as_int(
            table.get("batch_max_units", 0), f"{where} batch_max_units", source
        ),
    )


def _limits(doc: Mapping[str, object], source: str) -> CardLimits:
    """`[limits]` — declared, and refused outright above `HOST_MAX` (DR20).

    `omniweave_core.limits.effective()` takes a three-way minimum, so an over-declaration would
    be harmless THERE; it is refused HERE because a card that declares a ceiling it may not have
    is a contract stating something false, and the caller that must refuse it still has to. The
    module docstring of `limits.py` names this validator as the enforcer.
    """
    table = doc.get("limits")
    if table is None:
        return CardLimits()
    if not isinstance(table, dict):
        _card_invalid(source, "[limits] must be a table")
    _reject_unknown(table, ("max_input_bytes", "max_parts"), "[limits]", source)
    declared = CardLimits(
        max_input_bytes=_as_int(
            table.get("max_input_bytes", MAX_ENTRY_BYTES), "[limits] max_input_bytes", source
        ),
        max_parts=_as_int(table.get("max_parts", MAX_ENTRY_COUNT), "[limits] max_parts", source),
    )
    for key, value, host_max in (
        ("max_input_bytes", declared.max_input_bytes, MAX_ENTRY_BYTES),
        ("max_parts", declared.max_parts, MAX_ENTRY_COUNT),
    ):
        if value > host_max:
            _card_invalid(
                source,
                f"[limits] {key} = {value} is above its HOST_MAX of {host_max}; a ceiling is "
                f"clampable down and never widenable (DR20, INV-22)",
            )
    return declared


_LICENCE_KEYS: Final = tuple(f.name for f in dataclasses.fields(LicenceFacts))


def _licence_facts(table: Mapping[str, object], where: str, source: str) -> LicenceFacts:
    """One `[licence.*]` table. FACTS ONLY — nothing here names a tier."""
    _reject_unknown(table, _LICENCE_KEYS, where, source)
    strings = ("spdx", "licence_sha256", "licence_url", "notice_path", "weights_revision")
    bools = (
        "output_share_alike",
        "competitor_bar",
        "requires_credential",
        "attribution_per_output",
        "no_model_training",
        "remote_kill_switch",
    )
    values: dict[str, object] = {
        key: _as_str(table.get(key, ""), f"{where} {key}", source) for key in strings
    }
    values.update({key: _as_bool(table.get(key, False), f"{where} {key}", source) for key in bools})
    values.update(
        {
            key: _as_int(table.get(key, 0), f"{where} {key}", source)
            for key in ("revenue_gate_usd", "mau_gate")
        }
    )
    values.update(
        {
            key: _as_strings(table.get(key, []), f"{where} {key}", source)
            for key in ("territory_excluded", "field_of_use_excluded", "clause_refs")
        }
    )
    values["redistribution"] = _one_of(
        table.get("redistribution", "allowed"), REDISTRIBUTIONS, f"{where} redistribution", source
    )
    return LicenceFacts(**values)  # type: ignore[arg-type]


def _licences(doc: Mapping[str, object], source: str) -> tuple[LicenceFacts, LicenceFacts | None]:
    """`[licence.code]` and the optional `[licence.weights]`.

    `[licence.weights]` is **omitted entirely** when a driver ships no weights: an empty table is
    not the same statement as an absent one, so an empty one is `CARD_INVALID` — the same rule
    `[deprecation]` carries and for the same reason (04-driver-system.md sections 3 note 6 and
    7.1). RT14 additionally refuses a `weights_revision` that is absent or `"main"`, because a
    branch name is not a pinned model.

    `[licence.code]` is REQUIRED. The plan lists it as an author-written table and never says a
    card may omit it; `compute_tier()` reads facts and cannot compute a tier from an absent fact
    set, and defaulting to `open` would let a card reach the shipped `allow_tiers = ["open"]`
    default by saying nothing. Reported as a filled silence.
    """
    table = doc.get("licence")
    if table is None:
        _card_invalid(
            source,
            "[licence.code] is required: the card carries licence FACTS and the tier is "
            "computed from them, so a card that says nothing would compute as `open`",
        )
    if not isinstance(table, dict):
        _card_invalid(source, "[licence] must hold [licence.code] and optionally [licence.weights]")
    _reject_unknown(table, ("code", "weights"), "[licence]", source)
    code_table = _sub(table, "code")
    if code_table is None:
        _card_invalid(source, "[licence.code] is required and must be a table")
    code = _licence_facts(code_table, "[licence.code]", source)
    if code.weights_revision:
        _card_invalid(
            source, "[licence.code] weights_revision is a [licence.weights] fact and not a code one"
        )
    if "weights" not in table:
        return code, None
    weights_table = _sub(table, "weights")
    if not weights_table:
        _card_invalid(
            source,
            "[licence.weights] is empty; a driver that ships no weights OMITS the table, "
            "because an empty table is a different statement from an absent one",
        )
    weights = _licence_facts(weights_table, "[licence.weights]", source)
    if not weights.weights_revision or weights.weights_revision == FORBIDDEN_REVISION:
        _card_invalid(
            source,
            f"[licence.weights] weights_revision is {weights.weights_revision!r}; it must be an "
            f"exact sha and never {FORBIDDEN_REVISION!r} (RT14, forbidden framework-wide)",
        )
    return code, weights


def _tombstone_licences(
    doc: Mapping[str, object], source: str
) -> tuple[LicenceFacts | None, LicenceFacts | None]:
    """A tombstone's licence facts, where BOTH tables are optional.

    A tombstone is not a driver: it declares no capability and asks for no activation, so it has
    no tier of its own to compute. What it carries is the hash SEED — `compute_tier()` returns
    `forbidden` for any card whose `[licence.code].licence_sha256` or
    `[licence.weights].licence_sha256` matches a shipped tombstone's, which is hash-keyed and
    therefore SURVIVES RENAMING (04-driver-system.md section 7.5). Some shipped tombstones carry
    only the weights hash and some only the code hash, so requiring `[licence.code]` here — as a
    driver card does — would refuse the very files that seed the set.
    """
    table = doc.get("licence")
    if table is None:
        return None, None
    if not isinstance(table, dict):
        _card_invalid(source, "[licence] must hold [licence.code] and/or [licence.weights]")
    _reject_unknown(table, ("code", "weights"), "[licence]", source)
    code_table = _sub(table, "code")
    weights_table = _sub(table, "weights")
    code = None if code_table is None else _licence_facts(code_table, "[licence.code]", source)
    weights = (
        None
        if weights_table is None
        else _licence_facts(weights_table, "[licence.weights]", source)
    )
    return code, weights


def _deps(doc: Mapping[str, object], source: str) -> Deps:
    table = doc.get("deps")
    if table is None:
        return Deps()
    if not isinstance(table, dict):
        _card_invalid(source, "[deps] must be a table")
    _reject_unknown(table, ("pins",), "[deps]", source)
    pins = _as_strings(table.get("pins", []), "[deps] pins", source)
    _capped(pins, MAX_CARD_PINS, "[deps] pins", source)
    return Deps(pins=pins)


def _spend(value: object, where: str, source: str) -> Mapping[str, float]:
    """A `Spend` vector: physical dimensions only, over `DriverMetrics`' own nine field names."""
    if not isinstance(value, dict):
        _card_invalid(source, f"{where} must be a table of physical dimensions")
    outside = sorted(set(value) - SPEND_DIMENSIONS)
    if outside:
        _card_invalid(
            source,
            f"{where} names {outside}, which are not physical dimensions; a Spend carries "
            f"{sorted(SPEND_DIMENSIONS)} and there is no cost_micros (INV-15)",
        )
    return MappingProxyType(
        {key: _as_number(item, f"{where}.{key}", source) for key, item in value.items()}
    )


def _scaling(value: object, source: str) -> CostScaling | None:
    where = "[cost.model] scaling"
    if not isinstance(value, dict):
        _card_invalid(source, f"{where} must be a table {{ key, exponent, reference }}")
    if not value:
        return None
    _reject_unknown(value, ("key", "exponent", "reference"), where, source)
    return CostScaling(
        key=_as_str(value.get("key"), f"{where}.key", source),
        exponent=_as_number(value.get("exponent"), f"{where}.exponent", source),
        reference=_as_number(value.get("reference"), f"{where}.reference", source),
    )


def _cost_model(doc: Mapping[str, object], source: str) -> CostModel | None:
    cost = _sub(doc, "cost")
    if cost is None:
        return None
    _reject_unknown(cost, ("model", "measured"), "[cost]", source)
    table = _sub(cost, "model")
    if table is None:
        return None
    where = "[cost.model]"
    _reject_unknown(
        table,
        (
            "class",
            "shape",
            "unit",
            "per_part",
            "per_session",
            "scaling",
            "tokens_out_p95_multiple",
            "max_retries",
        ),
        where,
        source,
    )
    model = CostModel(
        cost_class=CostClass(
            _one_of(
                table.get("class"),
                tuple(member.value for member in CostClass),
                f"{where} class",
                source,
            )
        ),
        shape=_one_of(table.get("shape"), COST_SHAPES, f"{where} shape", source),
        unit=_one_of(table.get("unit"), COST_UNITS, f"{where} unit", source),
        per_part=_spend(table.get("per_part", {}), f"{where} per_part", source),
        per_session=_spend(table.get("per_session", {}), f"{where} per_session", source),
        scaling=_scaling(table.get("scaling", {}), source),
        tokens_out_p95_multiple=_as_number(
            table.get("tokens_out_p95_multiple", 1.0), f"{where} tokens_out_p95_multiple", source
        ),
        max_retries=_as_int(table.get("max_retries", 0), f"{where} max_retries", source),
    )
    _check_cost_model(model, source)
    return model


def _check_cost_model(model: CostModel, source: str) -> None:
    """The three rules a `[cost.model]` table has to satisfy once its shape is known.

    A `shape` naming a scaling dimension with an EMPTY `scaling` table is `CARD_INVALID`
    (04-driver-system.md section 3 note 4): `constant` is the one shape that names none, and
    each `linear_per_*` names one, so an empty `scaling` there leaves the cost curve
    unreconciled. `max_retries` accepts exactly `0` — a driver never retries internally
    (section 1.5 obligation 4) — and `tokens_out_p95_multiple` is at least 1.0, because a
    reservation uses p95 and never the mean.
    """
    if model.shape != "constant" and model.scaling is None:
        _card_invalid(
            source,
            f"[cost.model] shape = {model.shape!r} names a scaling dimension and the scaling "
            f"table is empty; the term shape declares has to be carried by scaling, not by unit",
        )
    if model.max_retries != 0:
        _card_invalid(
            source,
            f"[cost.model] max_retries = {model.max_retries}; 0 is the only value a first "
            f"release accepts, because retry is the runtime's with the runtime's ledger",
        )
    if model.tokens_out_p95_multiple < 1.0:
        _card_invalid(
            source,
            f"[cost.model] tokens_out_p95_multiple = {model.tokens_out_p95_multiple} is below "
            f"1.0; a p95 below the mean is not a p95",
        )


def _cost_measured(doc: Mapping[str, object], source: str) -> CostMeasured | None:
    cost = _sub(doc, "cost")
    table = None if cost is None else _sub(cost, "measured")
    if table is None:
        return None
    where = "[cost.measured]"
    _reject_unknown(
        table,
        (
            "p50_ms_per_unit",
            "p95_ms_per_unit",
            "spend_per_unit",
            "hardware",
            "hardware_spawn",
            "timing_basis",
        ),
        where,
        source,
    )
    return CostMeasured(
        p50_ms_per_unit=_as_number(table.get("p50_ms_per_unit", 0), f"{where} p50", source),
        p95_ms_per_unit=_as_number(table.get("p95_ms_per_unit", 0), f"{where} p95", source),
        spend_per_unit=_spend(table.get("spend_per_unit", {}), f"{where} spend_per_unit", source),
        hardware=_as_str(table.get("hardware", ""), f"{where} hardware", source),
        hardware_spawn=_as_str(table.get("hardware_spawn", ""), f"{where} hardware_spawn", source),
        timing_basis=_as_str(table.get("timing_basis", ""), f"{where} timing_basis", source),
    )


def _measured_on(value: object, where: str, source: str) -> MeasuredOn:
    """The ten-field record, constructed by keyword so a short one raises `TypeError` (DR14)."""
    if not isinstance(value, dict):
        _card_invalid(source, f"{where} measured_on must be a ten-field table")
    _reject_unknown(value, MEASURED_ON_FIELDS, f"{where} measured_on", source)
    try:
        return MeasuredOn(**value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        _card_invalid(source, f"{where} measured_on is incomplete or out of domain: {exc}")


def _benchmark(row: object, index: int, source: str) -> Benchmark:
    where = f"[[quality.benchmark]][{index}]"
    if not isinstance(row, dict):
        _card_invalid(source, f"{where} must be a table")
    _reject_unknown(
        row,
        ("metric", "value", "n", "ci95", "witness", "measured_on", "method", "slice_key"),
        where,
        source,
    )
    interval = tuple(_as_number(x, f"{where}.ci95", source) for x in row.get("ci95", ()))
    if len(interval) != 2:  # noqa: PLR2004 - an interval has two ends and no other count.
        _card_invalid(source, f"{where}.ci95 must be a two-element [low, high] interval")
    witness = _as_str(row.get("witness", "self"), f"{where}.witness", source)
    try:
        return Benchmark(
            metric=_as_str(row.get("metric", ""), f"{where}.metric", source),
            value=_as_number(row.get("value"), f"{where}.value", source),
            n=_as_int(row.get("n"), f"{where}.n", source),
            ci95=(interval[0], interval[1]),
            witness=witness if witness in WITNESSES else "self",
            measured_on=_measured_on(row.get("measured_on"), where, source),
            method=_as_str(row.get("method", ""), f"{where}.method", source),
            slice_key=_as_str(row.get("slice_key", ""), f"{where}.slice_key", source),
        )
    except ValueError as exc:
        _card_invalid(source, f"{where} is refused: {exc}")


def _quality(doc: Mapping[str, object], source: str) -> Quality:
    table = doc.get("quality")
    if table is None:
        return Quality()
    if not isinstance(table, dict):
        _card_invalid(source, "[quality] must be a table")
    _reject_unknown(table, ("kit_version", "kit_run", "suites", "benchmark"), "[quality]", source)
    suites = _sub(table, "suites") or {}
    _reject_unknown(suites, QUALITY_SUITES, "[quality.suites]", source)
    rows = table.get("benchmark", [])
    if not isinstance(rows, list):
        _card_invalid(source, "[[quality.benchmark]] must be an array of tables")
    _capped(rows, MAX_CARD_BENCHMARKS, "[[quality.benchmark]]", source)
    return Quality(
        kit_version=_as_str(table.get("kit_version", ""), "[quality] kit_version", source),
        kit_run=_as_str(table.get("kit_run", ""), "[quality] kit_run", source),
        suites=MappingProxyType(
            {
                name: _one_of(value, QUALITY_VERDICTS, f"[quality.suites] {name}", source)
                for name, value in suites.items()
            }
        ),
        benchmarks=tuple(_benchmark(row, i, source) for i, row in enumerate(rows)),
    )


def _deprecation(doc: Mapping[str, object], source: str) -> Deprecation | None:
    """`[deprecation]` — absent means "not scheduled"; EMPTY is `CARD_INVALID`."""
    table = doc.get("deprecation")
    if table is None:
        return None
    if not isinstance(table, dict):
        _card_invalid(source, "[deprecation] must be a table")
    if not table:
        _card_invalid(
            source,
            "[deprecation] is empty; an ABSENT table means 'not scheduled for retirement' and "
            "an empty one is a different statement with no content",
        )
    _reject_unknown(
        table, ("since", "removed_in", "replaced_by", "reason"), "[deprecation]", source
    )
    since = _semver(table.get("since"), "[deprecation] since", source)
    removed_in = _semver(table.get("removed_in"), "[deprecation] removed_in", source)
    reason = _as_str(table.get("reason", ""), "[deprecation] reason", source)
    replaced_by = table.get("replaced_by")
    _check_deprecation_window(since, removed_in, source)
    if not reason:
        _card_invalid(source, "[deprecation] reason is empty; a retirement without one is a hole")
    if replaced_by is not None:
        text = _as_str(replaced_by, "[deprecation] replaced_by", source)
        if DRIVER_ID_RE.match(text) is None:
            _card_invalid(source, f"[deprecation] replaced_by = {text!r} is not a DriverId")
        replaced_by = text
    return Deprecation(
        since=_as_str(table["since"], "[deprecation] since", source),
        removed_in=_as_str(table["removed_in"], "[deprecation] removed_in", source),
        reason=reason,
        replaced_by=replaced_by,
    )


def _check_deprecation_window(
    since: tuple[int, int, int], removed_in: tuple[int, int, int], source: str
) -> None:
    """`removed_in > since`, and at least `DEPRECATION_MIN_MINORS` MINORs of window.

    The minimum matches G16's two-release compatibility promise. A window that crosses a MAJOR
    is accepted without arithmetic: a MAJOR bump is at least as long a wait as two MINORs, and
    comparing minors across majors would compare two different counters.
    """
    if removed_in <= since:
        _card_invalid(source, f"[deprecation] removed_in {removed_in} is not after since {since}")
    if removed_in[0] == since[0] and removed_in[1] - since[1] < DEPRECATION_MIN_MINORS:
        _card_invalid(
            source,
            f"[deprecation] window is {removed_in[1] - since[1]} MINOR(s); the minimum is "
            f"{DEPRECATION_MIN_MINORS}, matching G16's two-release compatibility promise",
        )


# --------------------------------------------------------------------------------------------
# 8. The loader. Order matters and is 04-driver-system.md sections 2.1, 4.5 and 5.3's:
#    bound the read, parse, bound the shape, read `card_schema`, branch on `[tombstone]`, and
#    only then validate a driver card.
# --------------------------------------------------------------------------------------------

_HEADER_RE: Final = re.compile(r"^[ \t]*\[")
_ATTESTATION_RE: Final = re.compile(r"^[ \t]*attestation[ \t]*=")
_JSON_SCALARS: Final = (str, int, float, bool, type(None))


def _parse(raw: bytes, source: str) -> dict[str, object]:
    """`tomllib` — the C parser: no `eval`, no object hooks, no callable a card can name."""
    try:
        return tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        _card_invalid(source, f"the card is not UTF-8: {exc}")
    except tomllib.TOMLDecodeError as exc:
        _card_invalid(source, f"the card is not parseable TOML: {exc}")


def _check_shape(doc: Mapping[str, object], source: str) -> None:
    """Nesting depth and the value grammar, walked ITERATIVELY and refused at the cap.

    Iterative because the cap exists to bound *this* walk: `tomllib` will happily build a
    thousand-deep mapping, and the validator that walks it is what would exhaust the stack
    (`MAX_CARD_DEPTH`'s own docstring). The walk stops descending the moment the cap is crossed,
    so the refusal costs one level, not the whole tree.

    The value grammar is `canonical()`'s: TOML's native date, time and datetime types parse
    happily and have no JSON encoding, so a card carrying one would produce a `TypeError` from
    inside `attestation_of()` instead of a named refusal here.
    """
    stack: list[tuple[object, str, int]] = [(doc, "", 0)]
    while stack:
        value, path, depth = stack.pop()
        if isinstance(value, dict):
            if depth > MAX_CARD_DEPTH:
                _card_invalid(
                    source, f"{path or 'the card'} nests deeper than {MAX_CARD_DEPTH} tables"
                )
            stack.extend(
                (item, f"{path}.{key}" if path else key, depth + 1) for key, item in value.items()
            )
        elif isinstance(value, list):
            stack.extend((item, f"{path}[{i}]", depth) for i, item in enumerate(value))
        else:
            _check_scalar(value, path, source)


def _check_scalar(value: object, path: str, source: str) -> None:
    if not isinstance(value, _JSON_SCALARS):
        _card_invalid(
            source,
            f"{path} is a {type(value).__name__}; a card value must be a string, integer, "
            f"float or boolean, because every card value has to reach a digest",
        )
    if isinstance(value, float) and not math.isfinite(value):
        _card_invalid(source, f"{path} is {value!r}; nan and inf have no canonical encoding")


def _card_schema_of(doc: Mapping[str, object], source: str) -> int:
    """`card_schema` — the FIRST key read, before the tombstone branch and before any table."""
    if "card_schema" not in doc:
        _card_invalid(source, "card_schema is required and is the first key a loader reads")
    declared = _as_int(doc["card_schema"], "card_schema", source)
    if declared > max(CARDS_SUPPORTED):
        _schema_too_new(source, declared)
    if declared not in CARDS_SUPPORTED:
        _card_invalid(source, f"card_schema = {declared} is not one of {sorted(CARDS_SUPPORTED)}")
    return declared


def _check_attestation_position(raw: bytes, source: str) -> None:
    """`attestation` is a top-level key and is written BEFORE the first table header.

    This is not cosmetic and it is not inferable from the parse: TOML scopes a bare key to the
    most recent header, so `attestation = "…"` after `[quality.suites]` becomes
    `quality.suites.attestation` — a well-formed card whose recomputation reads nothing. Writing
    it on line 2 makes the key unambiguously top-level, which is what "a sha256 over the
    canonical card minus the `attestation` key" requires; `ow conform` writes it there and the
    `card` suite asserts the position (04-driver-system.md section 2.1).
    """
    header = -1
    for index, line in enumerate(raw.decode("utf-8", errors="replace").splitlines()):
        if header < 0 and _HEADER_RE.match(line):
            header = index
        elif _ATTESTATION_RE.match(line) and header >= 0:
            _card_invalid(
                source,
                f"attestation is written on line {index + 1}, after the table header on line "
                f"{header + 1}; TOML scopes it to that table and the recomputation would read "
                f"nothing. It is a TOP-LEVEL key and belongs before the first header",
            )


def _attestation(doc: Mapping[str, object], source: str) -> tuple[str | None, bool]:
    """The declared attestation and whether it reproduces. A mismatch is NOT a rejection.

    Attestation is tamper-evidence, not authentication: a card whose recomputed digest does not
    match sets `attested = False` and still loads, because the alternative is a loader that
    refuses a card for a reason the author cannot see and the operator cannot override
    (04-driver-system.md sections 4.5 and 8.3).
    """
    declared = doc.get("attestation")
    if declared is None:
        return None, False
    text = _as_str(declared, "attestation", source)
    return text, text == attestation_of(doc)


def _check_top_level(doc: Mapping[str, object], source: str) -> None:
    """An unknown TOP-LEVEL table or bare key is a HARD ERROR: a card is a contract, not config."""
    _reject_unknown(doc, TOP_LEVEL_KEYS | TOP_LEVEL_TABLES, "the card's top level", source)


def _load_tombstone(
    doc: Mapping[str, object], card_schema: int, origin: CardOrigin, source: str, digest: str
) -> Tombstone:
    """A refusal, in its own grammar (04-driver-system.md section 7.5)."""
    _reject_unknown(doc, TOP_LEVEL_KEYS | _TOMBSTONE_TABLES, "a tombstone's top level", source)
    driver = _table(doc, "driver", source)
    _reject_unknown(driver, _TOMBSTONE_DRIVER_KEYS, "a tombstone's [driver]", source)
    table = _table(doc, "tombstone", source)
    _reject_unknown(table, _TOMBSTONE_KEYS, "[tombstone]", source)
    port, major = _port_of(driver.get("port"), "[driver] port", source)
    reason = _as_str(table.get("reason", ""), "[tombstone] reason", source)
    if not reason:
        _card_invalid(
            source,
            "[tombstone] reason is empty; DR22 exists so a removed or forbidden driver resolves "
            "to a QUOTED REASON and a named replacement, never to 'unknown driver'",
        )
    review_by = _as_str(table.get("review_by", ""), "[tombstone] review_by", source)
    if _DATE_RE.match(review_by) is None:
        _card_invalid(
            source,
            f"[tombstone] review_by = {review_by!r} is not a YYYY-MM-DD date; CI fails a "
            f"tombstone past it, so the refusal set is re-read rather than inherited",
        )
    attestation, attested = _attestation(doc, source)
    code, weights = _tombstone_licences(doc, source)
    return Tombstone(
        id=_driver_id(driver.get("id"), port, "[driver] id", source),
        port=port,
        port_major=major,
        reason=reason,
        review_by=review_by,
        origin=origin,
        source=source,
        card_sha256=digest,
        card_schema=card_schema,
        title=_as_str(driver.get("title", ""), "[driver] title", source),
        replaced_by=_tombstone_replacement(table, source),
        licence_code=code,
        licence_weights=weights,
        attestation=attestation,
        attested=attested,
    )


def _tombstone_replacement(table: Mapping[str, object], source: str) -> str | None:
    """`replaced_by` may be omitted only when there is no successor; then `reason` says so."""
    value = table.get("replaced_by")
    if value is None:
        return None
    text = _as_str(value, "[tombstone] replaced_by", source)
    if DRIVER_ID_RE.match(text) is None:
        _card_invalid(source, f"[tombstone] replaced_by = {text!r} is not a DriverId")
    return text


def _load_driver_card(
    doc: Mapping[str, object], card_schema: int, origin: CardOrigin, source: str, digest: str
) -> DriverCard:
    """Everything else, in the order 04-driver-system.md section 5.3 step 1 lists it."""
    _check_top_level(doc, source)
    identity = _driver_identity(_table(doc, "driver", source), origin, source)
    cap_table = _table(doc, "capability", source)
    capability = _capability(cap_table, source)
    ports, degradations = _port_tables(doc, cap_table, identity.port, capability.formats, source)
    isolation = _isolation(doc, source)
    _check_exec_isolation(identity, isolation, source)
    licence_code, licence_weights = _licences(doc, source)
    attestation, attested = _attestation(doc, source)
    return DriverCard(
        card_schema=card_schema,
        identity=identity,
        capability=capability,
        origin=origin,
        source=source,
        card_sha256=digest,
        attestation=attestation,
        attested=attested,
        parse=ports.parse,
        acquire=ports.acquire,
        acquire_sibling=ports.acquire_sibling,
        derive=ports.derive,
        derive_sibling=ports.derive_sibling,
        embed=ports.embed,
        embed_sibling=ports.embed_sibling,
        compile_capability=ports.compile_capability,
        compile_sibling=ports.compile_sibling,
        hardware=_hardware(doc, source),
        isolation=isolation,
        limits=_limits(doc, source),
        licence_code=licence_code,
        licence_weights=licence_weights,
        deps=_deps(doc, source),
        config=_config_schema(doc, source),
        cost_model=_cost_model(doc, source),
        cost_measured=_cost_measured(doc, source),
        quality=_quality(doc, source),
        deprecation=_deprecation(doc, source),
        degradations=tuple(degradations),
    )


def _check_exec_isolation(identity: DriverIdentity, isolation: IsolationSpec, source: str) -> None:
    """An `exec` driver's `[isolation] requires` must be `"subproc"` (erratum E7).

    `activate()` imports nothing for such a driver — the `PORT` and `SCHEMA_VERSION` assertions
    come from `HELLO_ACK` alone, which is exactly why `HELLO_ACK` carries them — so there is no
    in-process object for `inproc` to be, and a card asking for one has asked for something that
    cannot exist.
    """
    if identity.exec is not None and isolation.requires is not Isolation.SUBPROC:
        _card_invalid(
            source,
            f"[driver] exec requires [isolation] requires = 'subproc', not "
            f"{isolation.requires.value!r}: activate() imports nothing for an exec driver, so "
            f"there is no in-process object for inproc to be",
        )


def load_card(raw: bytes, *, origin: CardOrigin, source: str) -> DriverCard | Tombstone:
    """Parse and validate one `driver.toml`. **The only constructor of `DriverCard`.**

    Args:
        raw: the card's bytes as read from disk, ideally through `read_card_bytes()` so the
            `MAX_CARD_BYTES` cap is applied at the read rather than after it.
        origin: one of `CARD_ORIGINS` — discovery's fact about where the card was found. It
            gates `[driver] exec` and it is the input `trust` is later computed from; it is NOT
            a card field, because a card that could name its own origin could name its own
            trust.
        source: the path or identifier the card came from. Every refusal names it, and an
            `exec` driver's `argv[0]` is resolved against its parent directory.

    Returns:
        A `DriverCard`, or a `Tombstone` when the card carries `[tombstone]`.

    Raises:
        DriverHostError: `OW_CARD_INVALID`, `OW_CARD_ENTRYPOINT_MALFORMED` or
            `OW_CARD_SCHEMA_TOO_NEW`. Never a `ResourceLimit`, even for a cap breach: a card is
            a contract and a malformed one is refused rather than clamped.

    The ORDER is the specification (04-driver-system.md sections 2.1, 4.5 and 5.3). The byte cap
    and the shape walk come first because they are hardening against a file nobody has decided
    to trust yet. `card_schema` is read next, so a card from a newer grammar is refused as
    `CARD_SCHEMA_TOO_NEW` rather than misread as malformed. `[tombstone]` branches BEFORE
    anything else is validated, because a tombstone has no `entrypoint`, no `schema_version`, no
    `granularity` and no `replay_class` and validating one as a driver card was a guaranteed
    spurious `CARD_INVALID` on a file whose only job is to explain a refusal.
    """
    if origin not in CARD_ORIGINS:
        raise DriverHostError(
            f"{source}: origin {origin!r} is not one of {sorted(CARD_ORIGINS)}",
            symbol="OW_CARD_INVALID",
            fix="ow doctor --deep --render json   # attach the report to the issue",
        )
    if len(raw) > MAX_CARD_BYTES:
        _card_invalid(
            source,
            f"the card is larger than MAX_CARD_BYTES = {MAX_CARD_BYTES} bytes, its cap",
        )
    doc = _parse(raw, source)
    _check_shape(doc, source)
    card_schema = _card_schema_of(doc, source)
    _check_attestation_position(raw, source)
    digest = card_sha256(raw)
    if "tombstone" in doc:
        return _load_tombstone(doc, card_schema, origin, source, digest)
    return _load_driver_card(doc, card_schema, origin, source, digest)
