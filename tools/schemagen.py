"""`ow schema emit` before `ow` exists: the generator behind the thirteen `schema/*.json`.

`schema/` is the **language-neutral contract** -- the only artefact a second-language reader (a
TypeScript `.owdoc` reader, the JSON-Schema-validating conformance kit, `ow surface typescript`'s
generated client) is allowed to read instead of the Python. There is deliberately no IDL and no
schema compiler: the Python definitions are the source of truth and JSON Schema is emitted from
them, committed, and byte-diff gated. Specified in 02-architecture.md section 2 row 49,
03-document-model.md section 3 and 11-repo-layout.md sections 1.7 and 3.1.

The tier is **T-GENERATED**: "never hand-written; byte-identical to its generator's output"
(02-architecture.md section 2, the stability-tier table). That word *byte-identical* is the whole
contract of `--check`, which is a **byte diff and not a semantic comparison** -- two JSON documents
that parse equal but differ in key order or indentation are a failure, because a reviewer reads the
diff and a diff of reordered keys is unreadable.

Why a `tools/` script and not `ow schema emit`
----------------------------------------------
16-roadmap.md section 4's P1 exit criteria spells this gate `uv run ow schema emit --check`, and
that spelling is **not available at P1**. There is no `[project.scripts]` in
`packages/omniweave/pyproject.toml`, and INV-20 forbids hand-writing one: every CLI verb is
*generated* from `omniweave/surface/registry.py`, which lands at P7 W7.1/W7.2 (16-roadmap.md
section 10). A hand-written `ow` shipped now would make the registry's arrival a reconciliation
between two surfaces that already disagree. So the generator is the artefact and the verb is
deferred: run it as `uv run tools/schemagen.py emit --check`. The `ow schema emit` spelling is
W7.2's to add, over this module, and G6 does not change meaning when it does.

Scope honesty: thirteen declared, and what exists now
----------------------------------------------------
16-roadmap.md W1.8 prices this item at "13 generated schema files from Python declarations". Three
documents enumerate those thirteen and all three agree, name for name and in the same order --
02-architecture.md section 2 row 49, 11-repo-layout.md section 1.7 and 18-api-sketch.md section 8's
`T-GENERATED` row. `INVENTORY` below is that list, transcribed.

Most of the thirteen are wire and artefact schemas whose **declaring Python type lands in a later
phase**. A generator that emitted a placeholder for those would produce a file that looks generated
and is not, which is the one thing T-GENERATED forbids. So each row carries the module and symbol it
is generated from and the roadmap item that lands them, and an entry resolves to one of three
states:

* `LIVE`       -- the declaration imports. The schema is emitted and `--check` byte-diffs it.
* `PENDING`    -- the declaration does not exist yet. `--check` **passes** and prints the row, so
                  the gate is honest today and becomes binding on the day the source lands.
* `UNRESOLVED` -- this file's declaring type is named nowhere in the plan. `--check` **fails**,
                  because a row that can never fire is how a byte-diff gate stops meaning anything.

A `PENDING` row with a committed file also fails: a file under `schema/` whose generator cannot have
written it is hand-written by definition.

CRLF, which is the whole of W1.8's stated subtlety
--------------------------------------------------
"CRLF normalisation is the only subtlety and it is the one that bites on Windows" (16-roadmap.md
W1.8). Six of the nine `test` cells run on Windows or macOS and a developer's `core.autocrlf`
rewrites committed text at checkout, so a generator emitting LF and a working tree holding CRLF
disagree byte-for-byte for reasons that have nothing to do with the code. Three rules close it and
all three are needed (11-repo-layout.md section 1.9):

1. `.gitattributes` pins `schema/** text eol=lf`. That row exists.
2. **Every generator writes the line ending explicitly.** This module never opens a file in text
   mode: `render()` builds `bytes` and `Path.write_bytes()` writes them, so the platform's
   line-ending translation is not in the path at all.
3. **Every `--check` normalises CRLF before comparing.** `_normalise()` is that step.

Specified in 16-roadmap.md section 4 W1.8, 11-repo-layout.md sections 1.7 and 1.9, and
02-architecture.md section 2 row 49. Gate G6 (11-repo-layout.md section 6.4).
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import importlib
import json
import os
import sys
import types
import typing
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BLESS_ENV",
    "DIALECT",
    "EXPECTED_DIR",
    "INDENT",
    "INVENTORY",
    "RENDERS",
    "REPO_ROOT",
    "SCHEMA_DIR",
    "Resolution",
    "SchemaSource",
    "State",
    "UnsupportedDeclarationError",
    "bless",
    "build_schema",
    "check",
    "emit",
    "main",
    "render",
    "resolutions",
    "resolve",
]

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
"""The workspace root -- the parent of `tools/`, which holds `schema/` and `packages/`."""

SCHEMA_DIR: Path = REPO_ROOT / "schema"
"""Where the thirteen land. `.gitattributes` pins `schema/** text eol=lf` over exactly this tree."""

EXPECTED_DIR: Path = SCHEMA_DIR / "expected"
"""`schema/expected/` -- golden renders, `--bless` to update, never a bypass flag.

11-repo-layout.md section 1.7 reserves the directory and names `--bless` as its only writer;
`.gitattributes` marks it `-diff` so a golden does not double the readable diff a schema change
already produces. **What a render's content is, the plan does not say** -- it says only that these
are renders rather than schemas, that they are committed, that they are never cached ("caching a
golden is caching the answer", 11-repo-layout.md section 6.3) and that changing one needs a `Bless:`
footer of at least 20 characters in the same commit (section 8.3). `RENDERS` is therefore an empty
registry at P1 and the mechanism around it is complete: the day a render is registered, `--bless`
writes it and `--check` refuses anything in the directory that no registered render wrote.
"""

DIALECT: str = "https://json-schema.org/draft/2020-12/schema"
"""The `$schema` every emitted file carries, printed at 03-document-model.md section 3.2.

Note this is **wider** than the closed 2020-12 subset of 18-api-sketch.md section 7.2. That
subset (`type`, `enum`, `required`, `additionalProperties: false`, `minimum`/`maximum`,
`minItems`/`maxItems`, `pattern`, `maxLength`, nullable leaves) constrains a **user-supplied**
schema handed to `ow add --fields`, validated by the ~200-line first-party validator. The
framework's own generated schemas use `$defs`, `$ref`, `oneOf` and `const` --
03-document-model.md section 3.2 prints `oneOf` and `const` inside `os`, and
07-store-and-retrieval.md section 6.7's table `$ref`s `degradation` from the MCP Answer schema.
Collapsing the two would forbid the plan's own printed output.
"""

BLESS_ENV: str = "OMNIWEAVE_BLESS"
"""The environment variable `--bless` refuses to run without.

13-quality.md section 5.5 requirement 1: `OMNIWEAVE_BLESS=1` in the environment, with
`test_bless_flag_is_off()` -- docling's `tests/test_data_gen_flag.py` adopted whole -- asserting the
flag is off in CI, "so a contributor who leaves it exported locally cannot land a self-blessing PR".
The flag is a **precondition**, never a bypass: `--bless` rewrites goldens and never silences a
`--check` failure over `schema/*.json`.
"""

INDENT: int = 2
"""Two spaces, the indentation every JSON Schema the plan prints uses.

It is part of the byte contract: `--check` is a byte diff, so indentation is as load-bearing as key
order and neither may change without regenerating all thirteen in one commit.
"""


class UnsupportedDeclarationError(Exception):
    """A declaration schemagen cannot reflect, raised naming the field and the type.

    Silence here would be the worst failure mode available: a schema that quietly omits a field a
    second-language reader needs is a contract that lies. There is no fallback encoding and no
    `Any`-shaped escape hatch for a type the reflector does not understand -- the same reasoning
    `omniweave_core.canonical` gives for having no `str()` fallback.
    """


class State(enum.Enum):
    """What an inventory row resolved to. The three cases the module docstring names."""

    LIVE = "live"
    PENDING = "pending"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class SchemaSource:
    """One of the thirteen: the file, the Python declaration it comes from, and its plan locus.

    `symbol` is `None` only where the plan names the file but names **no declaring type** for it;
    such a row resolves `UNRESOLVED` as soon as its module exists, which is the moment somebody must
    settle it rather than the moment the gate quietly stops checking.

    `root` is `"object"` unless the plan says the wire form is a sequence of the declared type, in
    which case it is `"array"` and the declaration is emitted into `$defs` under `items`.

    `deferred` is non-empty only where the plan gives the file a DIFFERENT emitter. Such a row is
    `PENDING` whatever its module declares, because resolving it here would make this generator
    race the other one, and the string says which emitter and which work item owns it. The
    `PENDING` branch of `_check_one` still refuses a committed file, so a deferred row cannot be
    used to smuggle a hand-written schema past G6.
    """

    file: str
    module: str
    symbol: str | None
    landed_by: str
    locus: str
    root: str = "object"
    note: str = ""
    deferred: str = ""

    @property
    def path(self) -> Path:
        return SCHEMA_DIR / self.file


INVENTORY: tuple[SchemaSource, ...] = (
    SchemaSource(
        file="document-v1.json",
        module="omniweave_core.model",
        symbol="Doc",
        landed_by="P2 W2.1",
        locus="02-architecture.md section 2 row 24; 03-document-model.md section 3.1",
    ),
    SchemaSource(
        file="fragment-v1.json",
        module="omniweave_core.model",
        symbol="BlockDraft",
        landed_by="P2 W2.1",
        locus="03-document-model.md section 3.1; 04-driver-system.md section 9 step 3",
        note=(
            "the `owdoc-fragment/1` wire, whose keys are long and spelled out because a third "
            "party authors them, and deliberately disjoint in spelling from document-v1's short "
            "archive keys so a record cannot be misread as the other format"
        ),
    ),
    SchemaSource(
        file="job-v1.json",
        module="omniweave_core.out.job",
        symbol="Job",
        landed_by="P9 W9.1",
        locus="02-architecture.md section 2 row 29 and section 5 row 2",
    ),
    SchemaSource(
        file="receipt-v1.json",
        module="omniweave_core.out",
        symbol="Receipt",
        landed_by="P9 W9.1",
        locus="02-architecture.md section 2 row 29",
    ),
    SchemaSource(
        file="event-v1.json",
        module="omniweave_core.events",
        symbol="Event",
        landed_by="P4 W4.8",
        locus="02-architecture.md section 2 row 21; 15-observability.md section 8.1",
        note=(
            "the closed vocabulary is `tools/events.toml` (append-only, G20); the envelope is "
            "`Event`, and 15-observability.md section 8 requires both regenerated in one change"
        ),
    ),
    SchemaSource(
        file="driver-card-v1.json",
        module="omniweave_core.drivers.card",
        symbol="DriverCard",
        landed_by="P1 W1.5",
        locus="02-architecture.md section 2 row 13; 16-roadmap.md section 4 W1.5",
        note="the only one of the thirteen whose declaration is itself a P1 work item",
    ),
    SchemaSource(
        file="run-manifest-v1.json",
        module="omniweave.run.manifest",
        symbol="RunManifest",
        landed_by="P4 W4.8",
        locus="02-architecture.md section 4.1 row 19; glossary.md `RunManifest`",
    ),
    SchemaSource(
        file="answer-v1.json",
        module="omniweave_core.answer",
        symbol="Answer",
        landed_by="P6 W6.6",
        locus="02-architecture.md section 2 row 28; 18-api-sketch.md section 1.3",
    ),
    SchemaSource(
        file="verdict-v1.json",
        module="omniweave_core.retrieve.verdict",
        symbol="Verdict",
        landed_by="P6 W6.5",
        locus="07-store-and-retrieval.md section 6.7",
        note=(
            "the plan's one fully explicit source attribution: `Verdict` is defined once, in "
            "`omniweave_core.retrieve.verdict`, and is the Python source this file is generated "
            "from and byte-diff gated by G6"
        ),
    ),
    SchemaSource(
        file="mcp-tools-v1.json",
        module="omniweave.surface",
        symbol="ACTIONS",
        landed_by="P7 W7.2",
        locus="02-architecture.md section 2 rows 30 and 31; 10-interfaces.md section 4.1",
        root="array",
        note=(
            "DOUBLE-OWNED IN THE PLAN: row 49 lists it among the thirteen `ow schema emit` files "
            "(G6) and row 31 lists it among `ow surface emit`'s seven agent-facing artefacts "
            "(G25). Its declaration is `ACTIONS`, a mapping of `ActionSpec` and not a single "
            "type, and a tool object is not an `ActionSpec` -- it is a name, a description, four "
            "annotations and two JSON Schemas DERIVED from one. Reflection cannot produce it"
        ),
        deferred=(
            "emitted by `ow surface emit` (G25), not by this generator; W7.1 landed `ACTIONS` "
            "and W7.2 lands the emitter that reconciles the two gates"
        ),
    ),
    SchemaSource(
        file="open-out-v1.json",
        module="omniweave_core.answer",
        symbol="Answer",
        landed_by="P7 W7.1",
        locus="18-api-sketch.md section 3.2",
        note=(
            "SETTLED AT W7.1, and the settlement is that there is one shape. The plan states "
            "what this file is -- 'the --render json shape for ow open, not an MCP "
            "outputSchema' -- and names no declaring type anywhere. `ow open` returns an "
            "`Answer`, `ActionSpec['open'].out` is `Answer`, and `Answer.surface` is already "
            "`Literal['query', 'open']`, so the two surfaces are one type discriminated by a "
            "field. Two files, one declaration: they regenerate together and cannot drift. "
            "D296 records the plan's silence"
        ),
    ),
    SchemaSource(
        file="corpora-out-v1.json",
        module="omniweave.sdk",
        symbol="CorpusCard",
        landed_by="P7 W7.1",
        locus="18-api-sketch.md section 1.4; 10-interfaces.md sections 4.2 and 8.3",
        root="array",
        note="18-api-sketch.md section 1.4: it 'is the wire form of a tuple of these'",
    ),
    SchemaSource(
        file="add-out-v1.json",
        module="omniweave.sdk",
        symbol="AddReport",
        landed_by="P7 W7.1",
        locus="18-api-sketch.md section 3.5",
    ),
)
"""The thirteen, in the order all three enumerations print them.

02-architecture.md section 2 row 49, 11-repo-layout.md section 1.7 and 18-api-sketch.md section 8
list the same thirteen names in the same order; this tuple is that list with each row's declaring
module, symbol and landing work item attached. `schema/il-digest-v1.md` is deliberately absent: it
is the one hand-written file in the directory and is prose, not generated (18-api-sketch.md section
8), and `schema/migrations/` is DDL owned by W2.2.

Three further `schema/*.json` are named under G6 elsewhere in the plan and are **not** among the
thirteen: `schema/drivers-check-out-v1.json` (04-driver-system.md sections 4.5 and 10, from
`LicencePosture`), `schema/metric-v1.json` and `schema/degradation-v1.json` (15-observability.md
sections 5 and 7). They belong to later phases, and the count that governs W1.8 is thirteen.
"""

RENDERS: tuple[tuple[str, str], ...] = ()
"""`(filename, content)` pairs `--bless` writes into `schema/expected/`. Empty at P1.

See `EXPECTED_DIR` for why: the plan reserves the directory and its bless discipline but never says
what a render's content is, and every report type a candidate render would be built from lands at
P6/P7. An empty registry with a working `--bless` is the honest state; a golden invented here would
be a fact with no source.
"""

_PRIMITIVES: Mapping[object, str] = {
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
}
"""The four JSON scalar types. `bytes` is absent on purpose: it is not JSON, and a base64 convention
invented here would be a wire decision made for a reflector's convenience."""


# ---------------------------------------------------------------------------
# The reflector
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Ctx:
    """The `$defs` table being accumulated, the field path for error messages, and the vocabulary.

    `vocabulary` is the declaring module's namespace, and it is what closes the forward references
    the plan creates on purpose. `Verdict.coverage` is a `Coverage`, `Coverage.gaps` is a
    `tuple["DegradeCause", ...]`, and `DegradeCause`'s home is
    `omniweave_core.retrieve.verdict` (18-api-sketch.md:840) while `Coverage` is declared beside
    the `Reader` Protocol that returns it -- which may not import the query path, because
    `retrieve.types` already imports `store.types` and the edge back would be a cycle. So the name
    is unresolvable in the module that writes it and resolvable in the module the schema is rooted
    at, which is the one this passes as `localns`. Within one JSON document `DegradeCause` is
    defined, so resolving it against the document's own root is the honest reading rather than a
    workaround.
    """

    defs: dict[str, object]
    where: str
    vocabulary: Mapping[str, object] = types.MappingProxyType({})

    def at(self, step: str) -> _Ctx:
        return _Ctx(defs=self.defs, where=f"{self.where}.{step}", vocabulary=self.vocabulary)

    def hints(self, cls: type) -> dict[str, object]:
        """`get_type_hints(cls)`, with the root module's names available to the evaluator."""
        return typing.get_type_hints(cls, localns=dict(self.vocabulary))


def _summary(obj: type) -> str | None:
    """The first paragraph of `obj`'s own docstring, whitespace-collapsed.

    `obj.__dict__["__doc__"]` rather than `inspect.getdoc`, because getdoc walks the MRO and a
    dataclass with no docstring inherits an auto-generated `ClassName(field=...)` signature that
    carries no information and would churn the emitted bytes on any field rename.
    """
    doc = obj.__dict__.get("__doc__")
    if not isinstance(doc, str) or not doc.strip():
        return None
    if doc.lstrip().startswith(f"{obj.__name__}("):
        return None
    paragraph = doc.strip().split("\n\n", 1)[0]
    return " ".join(paragraph.split())


def _schema_any(annotation: object, _ctx: _Ctx) -> dict[str, object] | None:
    """`Any` and bare `object` become the empty schema -- every instance validates."""
    if annotation is typing.Any or annotation is object:
        return {}
    return None


def _schema_none(annotation: object, _ctx: _Ctx) -> dict[str, object] | None:
    if annotation is None or annotation is type(None):
        return {"type": "null"}
    return None


_JSON_VALUE_BODY = "bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue] | None"
"""`omniweave_core.canonical.JsonValue`'s alias body, verbatim.

Matched as text because that is the only form the *inner* references survive in. `JsonValue` is a
string `TypeAlias`, so resolving `Mapping[str, JsonValue]` evaluates the outer string and leaves
each recursive occurrence inside it an unevaluated `ForwardRef` carrying exactly these characters.
There is no object to compare against: evaluating it again would just build a second union whose
inner references are the same unresolved strings.
"""

_JSON_VALUE_SCHEMA: dict[str, object] = {
    "description": (
        "Any JSON value. The recursive arms point back at this definition, "
        "so an array or object nests to any depth."
    ),
    "oneOf": [
        {"type": ["boolean", "integer", "number", "string", "null"]},
        {"type": "array", "items": {"$ref": "#/$defs/JsonValue"}},
        {"type": "object", "additionalProperties": {"$ref": "#/$defs/JsonValue"}},
    ],
}
"""The one `$defs` entry every `JsonValue` occurrence refs.

`integer` alongside `number` is redundant under the dialect -- every integer is a number -- and is
written anyway, because the declaration says `bool | int | float` and a reader comparing the schema
to the Python line should find three arms where the Python has three. The arms are in declaration
order for the same reason.
"""


def _squash(text: str) -> str:
    """`text` with all whitespace removed, so a re-wrapped alias still matches."""
    return "".join(text.split())


def _is_json_value(annotation: object) -> bool:
    """True for either spelling of `JsonValue`: the `ForwardRef`, or the evaluated union.

    Both spellings occur in one traversal of a single declaration. `DriverCard.compile_capability`
    is `Mapping[str, JsonValue]`, whose value resolves to the *union*; the `Sequence` and `Mapping`
    arms inside that union hold the *`ForwardRef`*. Recognising only one of the two either fails on
    the inner reference or emits the outer union inline and the inner one as a `$ref`, which are two
    different encodings of one type -- INV-21's second home, in JSON.
    """
    if isinstance(annotation, typing.ForwardRef):
        return _squash(annotation.__forward_arg__) == _squash(_JSON_VALUE_BODY)
    if typing.get_origin(annotation) not in (typing.Union, types.UnionType):
        return False
    args = list(typing.get_args(annotation))
    # The five scalar arms must all be present. Structural rather than by-name because a union is
    # unordered and `int | str` is `str | int`, so there is no text to compare.
    if not {bool, int, float, str, type(None)}.issubset({a for a in args if isinstance(a, type)}):
        return False
    # ...and at least one container arm must close the recursion back onto this same alias.
    # Without this conjunct a hand-written `bool | int | float | str | None` -- five scalars and
    # no recursion -- would be mistaken for `JsonValue` and lose its arms to a `$ref`.
    containers = [a for a in args if typing.get_origin(a) in (Sequence, list, Mapping, dict)]
    return any(
        isinstance(param, typing.ForwardRef) and _is_json_value(param)
        for container in containers
        for param in typing.get_args(container)
    )


def _schema_new_type(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    """A `NewType` reflects as its supertype, and carries its own name as the description.

    `BlockId = NewType("BlockId", int)`, `Addr = NewType("Addr", str)` and
    `Cite = NewType("Cite", str)` are 03-document-model.md section 2.2's identities. On the wire
    they ARE an int and two strings -- a `NewType` has no runtime representation of its own, which
    is the entire point of it -- so the schema is the supertype's. The name is kept in
    `description` because it is the only place the wire can say WHICH string this is, and a reader
    comparing `schema/fragment-v1.json` to `03` section 2.2's table needs that to line the two up.

    `__supertype__` is the documented attribute for this and is stable across 3.10-3.13; the
    `hasattr` guard is what keeps a plain class from being mistaken for one.
    """
    supertype = getattr(annotation, "__supertype__", None)
    if supertype is None:
        return None
    inner = _schema_for(supertype, ctx)
    name = getattr(annotation, "__name__", None)
    return {**inner, "description": name} if name and "description" not in inner else inner


def _schema_bytes(annotation: object, _ctx: _Ctx) -> dict[str, object] | None:
    """`bytes` is a 16-byte `ow128` rendered as 32 lowercase hex characters.

    03-document-model.md:665 is the wire mapping and states it exactly: the `cd` field is
    "string | 32 hex chars (a 16-byte `ow128`)". `:1057-1058` gives both carriers --
    `content_digest` and `layout_digest` -- as `16 B`, and those are the only two `bytes` fields
    in the wire types, so the pattern is not a generalisation from one case.

    THE PATTERN IS DELIBERATELY EXACT AND WILL REFUSE A DIFFERENT DIGEST. A `bytes` field holding
    a sha256 renders as 64 characters and fails this pattern loudly at validation, which is the
    correct outcome: `sha256_canonical` returns `str` already (see `omniweave_core.canonical`), so
    a `bytes`-typed sha256 would be a declaration error. A future non-`ow128` `bytes` field must
    extend this handler rather than silently inherit a wrong length -- there is no JSON type for
    octets, so every such field is a decision about its encoding and none of them is automatic.
    """
    if annotation is not bytes:
        return None
    return {
        "type": "string",
        "pattern": "^[0-9a-f]{32}$",
        "description": "a 16-byte ow128 as 32 lowercase hex characters",
    }


def _schema_json_value(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    """`JsonValue` becomes one `$defs` entry that refers to itself.

    It must be reached BEFORE `_schema_union`, which would otherwise expand the outer union and
    recurse into arms it cannot terminate. This is `_schema_dataclass`'s trick applied to a type
    alias: a name in `$defs` is what turns an infinitely deep type into a finite document.
    """
    if not _is_json_value(annotation):
        return None
    ctx.defs.setdefault("JsonValue", _JSON_VALUE_SCHEMA)
    return {"$ref": "#/$defs/JsonValue"}


def _schema_primitive(annotation: object, _ctx: _Ctx) -> dict[str, object] | None:
    name = _PRIMITIVES.get(annotation)
    return None if name is None else {"type": name}


def _enum_schema(values: list[object]) -> dict[str, object]:
    """`{"type": t, "enum": [...]}` when the members share one JSON scalar type, else `{"enum"}`.

    Declaration order, never sorted: 03-document-model.md section 3.2's `k` enum is printed in the
    `Kind` declaration order, and a sorted copy would be a different diff for no reason.

    An `Enum` member is replaced by its `value` first. A `Literal` may be written over the members
    themselves -- `omniweave_core.events.TimedStage` is, so that renaming a `Stage` is a `NameError`
    rather than a silent divergence -- and the wire carries the value, not the member. `json.dumps`
    would emit the right bytes for a `StrEnum` by accident, because it is a `str`; an `IntEnum` in
    the same position would not, and neither would a repr in an error message.
    """
    values = [value.value if isinstance(value, enum.Enum) else value for value in values]
    if all(isinstance(value, str) for value in values):
        return {"type": "string", "enum": values}
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return {"type": "integer", "enum": values}
    return {"enum": values}


def _schema_literal(annotation: object, _ctx: _Ctx) -> dict[str, object] | None:
    if typing.get_origin(annotation) is not typing.Literal:
        return None
    return _enum_schema(list(typing.get_args(annotation)))


def _schema_enum(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    """An `Enum` subclass is **inlined**, not `$ref`'d -- 03-document-model.md section 3.2's shape.

    A closed value list is short, and reading it at the property is what a second-language
    implementer needs; a `$ref` would send them to the bottom of the file for four words.
    """
    if not (isinstance(annotation, type) and issubclass(annotation, enum.Enum)):
        return None
    values = [member.value for member in annotation]
    schema = _enum_schema(values)
    if "type" not in schema:
        message = (
            f"{ctx.where}: enum {annotation.__name__} mixes JSON types across its members "
            f"({values!r}); a wire enum must be all-string or all-integer"
        )
        raise UnsupportedDeclarationError(message)
    return schema


def _nullable(inner: dict[str, object]) -> dict[str, object]:
    """The nullable form of a leaf: `{"type": ["string", "null"]}`, per 03 section 3.2's `pa`.

    A schema that is a `$ref`, an `enum` or already a `oneOf` cannot take a second entry in its
    `type` list, so those get an explicit null arm under `oneOf` instead of being flattened.
    """
    kind = inner.get("type")
    if isinstance(kind, str) and "enum" not in inner and "$ref" not in inner:
        widened = dict(inner)
        widened["type"] = [kind, "null"]
        return widened
    return {"oneOf": [inner, {"type": "null"}]}


def _schema_union(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    origin = typing.get_origin(annotation)
    if origin is not typing.Union and origin is not types.UnionType:
        return None
    args = list(typing.get_args(annotation))
    nullable = type(None) in args
    rest = [arg for arg in args if arg is not type(None)]
    if not rest:
        return {"type": "null"}
    if len(rest) == 1:
        inner = _schema_for(rest[0], ctx)
        return _nullable(inner) if nullable else inner
    arms: list[object] = [_schema_for(arg, ctx.at(f"[{i}]")) for i, arg in enumerate(rest)]
    if nullable:
        arms.append({"type": "null"})
    return {"oneOf": arms}


def _property_names(key: object, ctx: _Ctx) -> dict[str, object] | None:
    """The `propertyNames` constraint a mapping key carries, or `None` for an unconstrained `str`.

    A JSON object key is always a string, so `Mapping[str, X]` needs no constraint and gets none.
    A key typed as a **closed string vocabulary** -- a `Literal[...]` of strings, or a `str`-valued
    `Enum` -- is a stronger statement, and dropping it on the way to JSON would drop the only thing
    bounding the document it appears in: 15-observability.md section 1.1 bounds the run manifest by
    calling `degradations` and `failures_by_class` *"dicts keyed by a closed vocabulary"*, and a
    schema with a bare `"type": "object"` there publishes a contract in which the manifest is
    unbounded. So the vocabulary is emitted as `propertyNames.enum`, which is 2020-12's spelling for
    "these keys and no others".

    Anything else raises, with the message this function replaced: a JSON object key must be a
    string, and a `Mapping[int, X]` is a type whose wire form the declaration has not decided.
    """
    if key is str:
        return None
    schema: dict[str, object] | None = None
    if typing.get_origin(key) is typing.Literal:
        schema = _enum_schema(list(typing.get_args(key)))
    elif isinstance(key, type) and issubclass(key, enum.Enum):
        schema = _enum_schema([member.value for member in key])
    if schema is None or schema.get("type") != "string":
        message = (
            f"{ctx.where}: a JSON object key must be `str` or a closed string vocabulary "
            f"(a Literal of strings, or a str-valued Enum), not {key!r}"
        )
        raise UnsupportedDeclarationError(message)
    return {"enum": schema["enum"]}


def _schema_mapping(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    if typing.get_origin(annotation) not in (Mapping, dict):
        return None
    key, value = typing.get_args(annotation)
    schema: dict[str, object] = {"type": "object"}
    names = _property_names(key, ctx)
    if names is not None:
        schema["propertyNames"] = names
    schema["additionalProperties"] = _schema_for(value, ctx.at("value"))
    return schema


def _fixed_tuple(args: list[object], ctx: _Ctx) -> dict[str, object]:
    """`tuple[int, int]` -> one `items` plus `minItems`/`maxItems`, per 03 section 3.2's `ts`.

    Heterogeneous arms fall back to `prefixItems`, which is 2020-12's spelling for positional
    items; `items` as an array is draft-07's and would not validate under this dialect.
    """
    arms = [_schema_for(arg, ctx.at(f"[{i}]")) for i, arg in enumerate(args)]
    count = len(arms)
    if all(arm == arms[0] for arm in arms):
        return {"type": "array", "items": arms[0], "minItems": count, "maxItems": count}
    return {"type": "array", "prefixItems": arms, "minItems": count, "maxItems": count}


def _schema_sequence(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    """Arrays. A fixed-length tuple carries `minItems`/`maxItems`; `tuple[X, ...]` does not."""
    origin = typing.get_origin(annotation)
    if origin not in (tuple, list, set, frozenset, Sequence, Set):
        return None
    args = list(typing.get_args(annotation))
    if origin is tuple and Ellipsis not in args:
        return _fixed_tuple(args, ctx)
    return {"type": "array", "items": _schema_for(args[0], ctx.at("item"))}


def _schema_named_tuple(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    """A `NamedTuple` is an ARRAY on the wire, not an object, because a tuple is.

    `Quad(NamedTuple)` is eight ints and 03-document-model.md:665's mapping renders it exactly that
    way -- `q` is "8 ints | null", never `{"x0": ..., "y0": ...}`. Reflecting it as an object would
    invent a JSON shape the plan does not use, and would do it for the one type whose positional
    reading is load-bearing: the `quad` column is "8 x i32 LE, or NULL" (charter.md:1039) and
    `Quad(*ints)` is the store's decode path.

    `typing.get_origin` returns `None` for a `NamedTuple` SUBCLASS, so `_schema_sequence` never
    sees it -- hence a handler of its own rather than a row in that one. The field types come from
    `__annotations__` in declaration order, which for a `NamedTuple` is `_fields` order, and that
    order is the wire order.

    Detected by `_fields` rather than by `issubclass(annotation, NamedTuple)`, which is not a legal
    runtime check: `typing.NamedTuple` is a factory, not a base class.
    """
    if not (isinstance(annotation, type) and issubclass(annotation, tuple)):
        return None
    fields = getattr(annotation, "_fields", None)
    if fields is None:
        return None
    hints = ctx.hints(annotation)
    where = ctx.at(annotation.__name__)
    arms = [hints[name] for name in fields]
    schema = _fixed_tuple(list(arms), where)
    summary = _summary(annotation)
    return {**schema, "description": summary} if summary else schema


def _schema_dataclass(annotation: object, ctx: _Ctx) -> dict[str, object] | None:
    """A nested dataclass becomes a `$ref` into `$defs`, registered **before** recursing.

    Registering the placeholder first is what makes a self-referential type -- a `Block` whose
    children are `Block`s -- terminate instead of recursing until the stack goes.
    """
    if not (isinstance(annotation, type) and dataclasses.is_dataclass(annotation)):
        return None
    name = annotation.__name__
    if name not in ctx.defs:
        ctx.defs[name] = {}
        ctx.defs[name] = _object_schema(annotation, ctx)
    return {"$ref": f"#/$defs/{name}"}


_HANDLERS = (
    _schema_any,
    _schema_none,
    _schema_json_value,
    # BEFORE `_schema_primitive`, which would otherwise claim `bytes` if it ever gained a row, and
    # before `_schema_dataclass`, because a `NewType` over a dataclass must unwrap rather than
    # `$ref`. `_schema_new_type` recurses into `_schema_for`, so its supertype still reaches the
    # right handler.
    _schema_new_type,
    _schema_bytes,
    _schema_primitive,
    _schema_literal,
    _schema_union,
    _schema_enum,
    _schema_mapping,
    # BEFORE `_schema_sequence`, which claims `tuple` by origin and would miss a NamedTuple
    # subclass entirely, and before `_schema_dataclass` so a NamedTuple never becomes an
    # object. 03-document-model.md:665 renders `Quad` as `8 ints`.
    _schema_named_tuple,
    _schema_sequence,
    _schema_dataclass,
)
"""The dispatch, in order. Each returns `None` for an annotation it does not own, and the first
that does not is the answer. A table rather than a chain of `if`s so that adding a shape is one
row and so no branch counter decides how the wire is encoded."""


def _schema_for(annotation: object, ctx: _Ctx) -> dict[str, object]:
    """The JSON Schema of one annotation. Raises rather than guessing."""
    for handler in _HANDLERS:
        result = handler(annotation, ctx)
        if result is not None:
            return result
    message = (
        f"{ctx.where}: schemagen cannot reflect {annotation!r}. Add a handler to "
        f"tools/schemagen.py, or change the declaration -- the wire is JSON and this type is not."
    )
    raise UnsupportedDeclarationError(message)


def _object_schema(cls: type, ctx: _Ctx) -> dict[str, object]:
    """The object schema of a dataclass: every field required, no additional properties.

    **Every field is `required`, including one carrying a Python default.** 18-api-sketch.md section
    3.5 prints `schema/add-out-v1.json` in full with all eleven of `AddReport`'s fields required,
    and `Verdict.degradations` -- which carries `default ()` (07-store-and-retrieval.md section 6.7
    open question 16) -- is `$ref`'d as a present field by the MCP Answer schema. A default is a
    Python construction convenience; a producer of a wire record always writes the key.

    `additionalProperties: false` is likewise the plan's, printed at 03-document-model.md section
    3.2 and 18-api-sketch.md section 3.5. An open record would let a typo through as an extension.

    What this reflector does **not** emit is per-property `maxLength`, `pattern`, `minimum` and
    `description`, all of which the plan's printed schemas carry. None of them is reflectable from a
    bare dataclass field, and the plan names no carrier for them; that gap is real and belongs to
    whichever work item lands the first `LIVE` declaration.
    """
    hints = ctx.hints(cls)
    fields = dataclasses.fields(cls)
    properties = {
        field.name: _schema_for(hints[field.name], ctx.at(field.name)) for field in fields
    }
    schema: dict[str, object] = {"type": "object", "additionalProperties": False}
    summary = _summary(cls)
    if summary is not None:
        schema["description"] = summary
    schema["required"] = [field.name for field in fields]
    schema["properties"] = properties
    return schema


def build_schema(entry: SchemaSource, declaration: object) -> dict[str, object]:
    """The complete document for one inventory row, `$defs` and all.

    `$schema` precedes `$id`. The plan prints both orders -- 03-document-model.md section 3.2 has
    `$schema` first, 18-api-sketch.md section 3.5 has `$id` first -- and because `--check` is a byte
    diff one of them has to be chosen here. `$id` takes the relative `schema/<file>` form of
    18-api-sketch.md section 3.5 rather than 03-document-model.md's absolute
    `https://omniweave.dev/...`, because the file is resolved out of the repository and a URL that
    nothing serves is a promise nobody keeps.
    """
    if not (isinstance(declaration, type) and dataclasses.is_dataclass(declaration)):
        message = (
            f"{entry.file}: {entry.module}.{entry.symbol} is a "
            f"{type(declaration).__name__}, not a dataclass. schemagen reflects dataclasses; "
            f"see this row's `note` in INVENTORY."
        )
        raise UnsupportedDeclarationError(message)
    module = sys.modules.get(entry.module)
    ctx = _Ctx(
        defs={},
        where=f"{entry.module}.{entry.symbol}",
        vocabulary=types.MappingProxyType(dict(vars(module)) if module else {}),
    )
    document: dict[str, object] = {"$schema": DIALECT, "$id": f"schema/{entry.file}"}
    document["title"] = declaration.__name__
    if entry.root == "array":
        ctx.defs[declaration.__name__] = _object_schema(declaration, ctx)
        document["type"] = "array"
        document["items"] = {"$ref": f"#/$defs/{declaration.__name__}"}
    else:
        document.update(_object_schema(declaration, ctx))
    if ctx.defs:
        document["$defs"] = {name: ctx.defs[name] for name in sorted(ctx.defs)}
    return document


# ---------------------------------------------------------------------------
# Bytes
# ---------------------------------------------------------------------------


def render(document: Mapping[str, object]) -> bytes:
    """The committed bytes of one schema: UTF-8, two-space indent, LF, one trailing newline.

    Rule 2 of 11-repo-layout.md section 1.9 -- every generator writes its line ending explicitly --
    is met structurally rather than by a keyword argument: this returns `bytes`, and the only writer
    is `Path.write_bytes()`, so there is no text-mode line-ending translation left to get wrong. The
    explicit fold covers the one remaining path, a carriage return arriving inside a docstring on a
    Windows checkout and reaching the output through `description`.

    `sort_keys` is off: property order is **declaration order**, which is the order a
    second-language implementer reads the record in and what makes a field addition a one-line diff.
    `ensure_ascii=False` keeps text as text; `allow_nan=False` because NaN is not JSON.
    """
    text = json.dumps(document, indent=INDENT, ensure_ascii=False, allow_nan=False, sort_keys=False)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.encode("utf-8") + b"\n"


def _normalise(raw: bytes) -> bytes:
    """CRLF-normalise committed bytes before comparing. Rule 3 of section 1.9, and G6's wording.

    G6 is spelled "`ow schema emit --check`, CRLF-normalised" (11-repo-layout.md section 6.4). A
    Windows checkout under `core.autocrlf=true` holds CRLF even though `.gitattributes` says
    otherwise, and failing that developer's build over a line ending teaches nothing.
    """
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


# ---------------------------------------------------------------------------
# Resolving the inventory
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Resolution:
    """One inventory row resolved against the tree that is actually installed."""

    entry: SchemaSource
    state: State
    declaration: object | None
    detail: str

    @property
    def label(self) -> str:
        return f"{self.entry.module}:{self.entry.symbol or '<no declaring type>'}"


def resolve(entry: SchemaSource) -> Resolution:
    """Import `entry`'s declaration if it exists, and say which of the three states holds.

    `importlib.import_module` is used here and is not the banned call: the ban is on
    `omniweave_core` outside `host/` (INV-4, G11 -- discovery must never import a driver). This is a
    `tools/` generator whose entire job is to read Python declarations, it runs in CI and never
    inside a driver resolution, and it imports nothing that is not named in `INVENTORY`.

    A missing module is `PENDING`; a present module with a missing symbol is **also** `PENDING`,
    because the eight empty subpackage homes (`omniweave_core.model`, `omniweave_core.out`, ...)
    exist as docstring-only files already and would otherwise report every P2 type as broken today.
    The cost of that choice is that a wrong symbol name in this table stays quiet, which is why
    every run prints the pending table -- module, symbol and landing item, one row each -- rather
    than a count.
    """
    if entry.deferred:
        return Resolution(entry, State.PENDING, None, entry.deferred)
    if entry.symbol is None:
        try:
            importlib.import_module(entry.module)
        except ImportError as exc:
            return Resolution(entry, State.PENDING, None, f"{entry.module} not importable: {exc}")
        return Resolution(
            entry,
            State.UNRESOLVED,
            None,
            f"{entry.module} exists but the plan names no declaring type for {entry.file}",
        )
    try:
        module = importlib.import_module(entry.module)
    except ImportError as exc:
        return Resolution(entry, State.PENDING, None, f"{entry.module} not importable: {exc}")
    declaration = getattr(module, entry.symbol, None)
    if declaration is None:
        return Resolution(
            entry, State.PENDING, None, f"{entry.module} imports but declares no {entry.symbol} yet"
        )
    return Resolution(entry, State.LIVE, declaration, "declaration present")


def resolutions() -> tuple[Resolution, ...]:
    """Every inventory row, resolved, in `INVENTORY` order."""
    return tuple(resolve(entry) for entry in INVENTORY)


# ---------------------------------------------------------------------------
# The three modes
# ---------------------------------------------------------------------------


def _write(path: Path, payload: bytes) -> bool:
    """Write `payload` if it differs. Returns whether the file changed.

    Skipping an identical write keeps mtimes stable, which matters because `driver_card_cache`'s
    validity key is mtime plus size (02-architecture.md section 2 row 12) and a build tool that
    touches files for no reason invalidates caches for no reason.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and _normalise(path.read_bytes()) == payload:
        return False
    path.write_bytes(payload)
    return True


def _report(out: typing.TextIO) -> tuple[Resolution, ...]:
    """Print every row and its state. The pending table is the honest half of this gate."""
    items = resolutions()
    counts = {state: sum(1 for item in items if item.state is state) for state in State}
    out.write(
        f"schemagen: {len(INVENTORY)} declared"
        f" | {counts[State.LIVE]} live"
        f" | {counts[State.PENDING]} pending"
        f" | {counts[State.UNRESOLVED]} unresolved\n"
    )
    for item in items:
        out.write(
            f"  {item.state.value:<10} {item.entry.file:<22} {item.label:<42}"
            f" lands with {item.entry.landed_by}\n"
        )
    return items


def emit(out: typing.TextIO) -> int:
    """Write every `LIVE` schema to `schema/`. Never writes a placeholder for a pending row."""
    written = 0
    for item in resolutions():
        if item.state is not State.LIVE:
            continue
        if _write(item.entry.path, render(build_schema(item.entry, item.declaration))):
            written += 1
            out.write(f"  wrote  schema/{item.entry.file}\n")
    _report(out)
    out.write(f"emit: {written} file(s) written\n")
    return 0


def _stray_files() -> tuple[str, ...]:
    """Committed `schema/*.json` that no inventory row claims. Hand-written by definition."""
    if not SCHEMA_DIR.is_dir():
        return ()
    declared = {entry.file for entry in INVENTORY}
    return tuple(sorted(p.name for p in SCHEMA_DIR.glob("*.json") if p.name not in declared))


def _check_one(item: Resolution) -> str | None:
    """The failure message for one row, or `None` when it is in order."""
    entry = item.entry
    exists = entry.path.is_file()
    if item.state is State.UNRESOLVED:
        return f"{entry.file}: UNRESOLVED -- {item.detail} (lands with {entry.landed_by})"
    if item.state is State.PENDING:
        if exists:
            return (
                f"{entry.file}: committed, but its declaration {item.label} does not exist. "
                f"A file no generator can have written is hand-written (T-GENERATED)."
            )
        return None
    payload = render(build_schema(entry, item.declaration))
    if not exists:
        return (
            f"{entry.file}: {item.label} has landed and the schema is absent. "
            f"Run `uv run tools/schemagen.py emit`."
        )
    if _normalise(entry.path.read_bytes()) != payload:
        return (
            f"{entry.file}: byte diff against the output of {item.label}. "
            f"Run `uv run tools/schemagen.py emit`; never edit a T-GENERATED file by hand."
        )
    return None


def _check_renders() -> list[str]:
    """`schema/expected/` holds exactly the registered renders and nothing else."""
    registered = {name for name, _ in RENDERS}
    if not EXPECTED_DIR.is_dir():
        return [f"schema/expected/ is missing; {len(registered)} render(s) are registered"]
    present = {path.name for path in EXPECTED_DIR.iterdir() if path.is_file()}
    return [
        f"schema/expected/{name}: no registered render writes it. `--bless` is the only writer."
        for name in sorted(present - registered - {".gitkeep"})
    ]


def check(out: typing.TextIO) -> int:
    """G6: a byte diff, plus the two shape rules a byte diff alone cannot state.

    Passes on a `PENDING` row and fails the moment its declaration lands and its schema is stale or
    missing -- which is what makes this gate honest at P1 and binding thereafter without anyone
    remembering to arm it.
    """
    items = _report(out)
    failures = [message for message in (_check_one(item) for item in items) if message is not None]
    failures.extend(
        f"schema/{name}: not one of the thirteen. `schema/` is T-GENERATED and the only "
        f"hand-written file in it is il-digest-v1.md, which is prose."
        for name in _stray_files()
    )
    failures.extend(_check_renders())
    if failures:
        out.write("\nG6 FAILED:\n")
        for message in failures:
            out.write(f"  - {message}\n")
        return 1
    out.write("\nG6 ok: every landed declaration matches its committed schema, byte for byte.\n")
    return 0


def bless(out: typing.TextIO) -> int:
    """Rewrite `schema/expected/`. Refuses without `OMNIWEAVE_BLESS=1` in the environment.

    13-quality.md section 5.5 requirement 1. The refusal is the point: a bless that runs by default
    is a bypass flag, and 11-repo-layout.md section 1.7 says these goldens are updated by `--bless`,
    "never a bypass flag". It rewrites goldens only -- it can neither create nor silence a
    `schema/*.json` byte diff, which is `emit`'s to fix and a reviewer's to read.
    """
    if os.environ.get(BLESS_ENV) != "1":
        out.write(
            f"--bless refuses: {BLESS_ENV}=1 is not in the environment (13-quality.md section "
            f"5.5). A `Bless:` footer of at least 20 characters is required in the same commit.\n"
        )
        return 1
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in RENDERS:
        _write(EXPECTED_DIR / name, content.encode("utf-8"))
        out.write(f"  blessed  schema/expected/{name}\n")
    out.write(f"bless: {len(RENDERS)} render(s)\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """`emit` | `emit --check` | `emit --bless` -- 11-repo-layout.md section 1.7's three modes.

    The `emit` verb is optional so that `uv run tools/schemagen.py --check` and the plan's
    `... emit --check` are the same invocation. Exit 0 on success, 1 on a gate failure.
    """
    parser = argparse.ArgumentParser(
        prog="schemagen",
        description="Generate schema/*.json from the Python declarations. Gate G6.",
    )
    parser.add_argument("verb", nargs="?", default="emit", choices=("emit",))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="byte diff, CRLF-normalised. G6.")
    mode.add_argument("--bless", action="store_true", help="rewrite schema/expected/ goldens.")
    args = parser.parse_args(argv)
    if args.check:
        return check(sys.stdout)
    if args.bless:
        return bless(sys.stdout)
    return emit(sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
