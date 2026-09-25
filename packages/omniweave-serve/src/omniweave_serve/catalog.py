"""The tool payload `tools/list` sends, loaded rather than built. 10:206 row 1; 11 section 2.6.

Artefact 1's `consumed by` cell is *"the MCP server's `tools/list`"*, so this module is that
consumer. It does not assemble a tool object and it must not: 02:255's row 31 gives the assembly to
`omniweave.gen`, G25 byte-diffs what that writes, and a second assembler here would be two homes
for one payload -- INV-20's defect with the server on the wrong side of it.

So this module locates the committed artefact, parses it, refuses one that is not servable, and
says -- out loud, in `unservable()` -- which parts of `tools/list` it cannot produce on its own.
Since D340 was decided, the profile selection, compaction and `corpus` promotion are read from
`mcp-listing-v1.json` by `omniweave_serve.listing`, and `unservable()` names only the input left.

## WHY A LOADER AT ALL, WHEN EVERY OTHER CONSUMER IMPORTS ITS SOURCE

Because this distribution may not import the one that holds it. 02:264's forbidden column for row
40 is *"running the Supervisor, and importing `omniweave` at all"*, 02:350's layers row is
`omniweave_serve = ["omniweave_core", "omniweave_ports"]`, and 02:361 spells out the consequence:
*"`import omniweave` anywhere under `omniweave_serve/` is a gate failure -- inside a function body
and behind a `TYPE_CHECKING` guard included."* G4 enforces it over `packages/*/src/**/*.py`.

A file read is the one channel left, and 11 section 2.6 governs it with three rules that are each a
recorded defect elsewhere: read through `importlib.resources.files()` and never `__file__`; read at
use time and memoised, never at import; and raise a NAMED `OwError` carrying the command that
clears it rather than a `KeyError`, a `FileNotFoundError` or a silent empty default.
`omniweave_core.errors.register_path()` already implements that shape for `codes.toml` and this is
the same shape one artefact over, deliberately -- two packaged-data readers that located their file
differently would be two answers to a question 11 section 2.6 settles once.

## WHAT THE PAYLOAD IS, AND WHAT IT IS NOT

`gen/mcp_tools.py`'s own docstring fixes both halves: *"a tool object carries no `listed_in`
channel and the file is one file, so the artefact is every tool this build can render and the
server selects by profile at `tools/list` time -- which is also what makes `[serve]
compact_schemas` a transform over this payload rather than a second committed file."*

Read literally that gives this module three jobs beyond loading, and it can do none of them:

* **select by profile** needs `ActionSpec.listed_in`, which is `omniweave.surface.registry`'s;
* **compact** needs `ActionSpec.advanced`, which 10:495 puts in `omniweave/surface/schema.py` as
  `_ADVANCED` and which that module derives from the registry;
* **promote `corpus` to required** (10 section 3.4) is `with_required_corpus()`, in the same module.

All three are in the distribution this one may not import, and all three change what `tools/list`
sends. D340 was the entry, and it was decided for route 2: `omniweave.gen.listing` renders the
three transformed forms of every listed tool into `mcp-listing-v1.json`, and `listing.py` selects.

## WHAT THIS MODULE REFUSES

A payload it cannot serve honestly. `check()`'s clauses are not schema validation for its own sake
-- each one is a property some other document requires of the bytes on the wire, and a payload
failing it would put a defect in front of an agent rather than in front of a reviewer. The sharpest
is the annotation clause: 10:216 requires all four keys on every tool *"never conditionally on its
value"*, and MCP reads an absent `destructiveHint` as `true`, so a tool that lost the key between
the generator and the wire would ship the most alarming annotation the protocol has.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.config import KEYS
from omniweave_core.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = [
    "ANNOTATION_KEYS",
    "CATALOGUE_NAME",
    "MCP_NAME_RE",
    "SCHEMA_DIR",
    "Catalogue",
    "Tool",
    "catalogue_path",
    "check",
    "load_catalogue",
    "payload",
    "unservable",
]


CATALOGUE_NAME: Final[str] = "mcp-tools-v1.json"
SCHEMA_DIR: Final[str] = "schema"
"""Artefact 1's filename and the directory 11:42 homes it in.

Two constants rather than one joined path, because the packaged copy and the workspace copy do not
agree on the directory: a wheel that carried this file would carry it beside the package, and a
checkout carries it under `schema/` at the repository root. `catalogue_path()` is where the two
spellings meet, and D341 is why there is no packaged copy to meet yet.
"""

ANNOTATION_KEYS: Final[tuple[str, ...]] = (
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
)
"""The four MCP annotation keys, in 18:1250's printed order.

Spelled here and in `omniweave.gen.mcp_tools.ANNOTATIONS`, which is two homes for four strings and
is the `MAX_RUNG_MEMBERS` pattern rather than an oversight: this distribution may not import that
one, so the constant is written and a TEST does the import and binds them. A test may reach across
a layers row because G4 scans `packages/*/src/**/*.py` and a test tree is not source.
"""

MCP_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^ow_[a-z][a-z0-9_]{1,30}$")
"""Check 3's grammar (10:188), which catches *"a name a host cannot address"*.

The registry holds the other copy and enforces it on the way in; this enforces it on the way out,
because the two ends of a file are two trust boundaries and the payload is the one an agent meets.
Bound to `registry.MCP_NAME_RE` by a test, for `ANNOTATION_KEYS`' reason.
"""

_PROFILE_KEY: Final[str] = "serve.profile"
_COMPACT_KEY: Final[str] = "serve.compact_schemas"
_CORPUS_KEY: Final[str] = "serve.default_corpus"


@dataclass(frozen=True, slots=True)
class Tool:
    """One tool object, typed. The wire form is `raw`, and `raw` is what goes out.

    Both are kept because they answer different questions. The fields are what this module
    checks and what a reader greps; `raw` is the bytes a reviewer counted -- 10:336 measures
    four tool objects at 411, 258, 189 and 173 tokens, and a server that rebuilt the object from
    its parts would send a payload nobody measured, in a different key order, for no gain.
    """

    name: str
    description: str
    annotations: Mapping[str, bool]
    input_schema: Mapping[str, Any]
    output_schema: str | None
    raw: str
    """The object's JSON text, verbatim from the file. `payload()` parses it back per call, so a
    caller that mutates what it receives cannot reach the memoised catalogue."""

    def wire(self) -> dict[str, Any]:
        """A fresh copy of the object as `tools/list` sends it, in the file's key order."""
        parsed: dict[str, Any] = json.loads(self.raw)
        return parsed


@dataclass(frozen=True, slots=True)
class Catalogue:
    """The whole parsed artefact: where it came from, and the tools in the file's order."""

    path: Path
    tools: tuple[Tool, ...]
    by_name: Mapping[str, Tool]


def catalogue_path() -> Path:
    """Locate `mcp-tools-v1.json`. 11 section 2.6 rule 1.

    Through `importlib.resources.files()` and never `__file__` or `__path__[0]`: a zipapp, a
    `pip install --target` layout and any `zipimport`er give a package with no usable filesystem
    path, and `__path__[0]` then either raises or names a directory that does not hold the file.

    The packaged location is checked first and does not exist in any distribution today, which is
    D341 -- so every resolution in this repository is the workspace fallback, and a
    `pip install omniweave-serve` reaches the `ConfigError` at the bottom. That is the honest
    outcome rather than a hidden one: the server cannot list a tool whose description it does not
    have, and a named error naming the file is what a missing payload should produce.
    """
    anchor = resources.files("omniweave_serve")
    packaged = anchor.joinpath(CATALOGUE_NAME)
    if packaged.is_file():
        return Path(str(packaged))
    for parent in _ancestors(anchor):
        candidate = parent / SCHEMA_DIR / CATALOGUE_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"{SCHEMA_DIR}/{CATALOGUE_NAME} is not readable: this install carries no MCP tool "
        f"payload, so `tools/list` has nothing to send",
        fix="pip install --force-reinstall omniweave-serve",
    )


def _ancestors(anchor: object) -> Iterator[Path]:
    """The directories above the package, when the package has a real filesystem path."""
    if not isinstance(anchor, Path):
        return
    yield from anchor.resolve().parents


def load_catalogue(path: Path | None = None) -> Catalogue:
    """Parse the payload. Read at use time, memoised, never at import. 11 section 2.6 rule 2.

    A missing or corrupt file must degrade one operation rather than brick module import --
    `graphify`'s own docstring states the reason and `omniweave_core.errors` follows it for
    `codes.toml`. Here the operation is `tools/list`, and a server whose import failed would take
    `ow doctor` down with it.
    """
    return _load_catalogue(path or catalogue_path())


@cache
def _load_catalogue(path: Path) -> Catalogue:
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(
            f"{path} is not a readable MCP tool payload: {exc}",
            fix="pip install --force-reinstall omniweave-serve",
        ) from exc
    entries = parsed if isinstance(parsed, list) else []
    tools = tuple(_tool(entry) for entry in entries)
    return Catalogue(
        path=path,
        tools=tools,
        by_name=MappingProxyType({tool.name: tool for tool in tools}),
    )


def _tool(entry: object) -> Tool:
    """One object to a `Tool`. Never raises; a malformed entry becomes a finding in `check()`.

    11 section 2.6 rule 3 at field granularity, the shape `errors._exit()` takes one artefact
    over: a reader that raised on a missing key would report the first defect and hide the rest,
    and a payload with three defects should cost one edit cycle.
    """
    table = entry if isinstance(entry, dict) else {}
    annotations = table.get("annotations")
    output = table.get("outputSchema")
    schema = table.get("inputSchema")
    return Tool(
        name=str(table.get("name", "")),
        description=str(table.get("description", "")),
        annotations=MappingProxyType(
            {key: value for key, value in annotations.items() if isinstance(value, bool)}
            if isinstance(annotations, dict)
            else {}
        ),
        input_schema=MappingProxyType(schema if isinstance(schema, dict) else {}),
        output_schema=str(output["$ref"])
        if isinstance(output, dict) and "$ref" in output
        else None,
        raw=json.dumps(table, ensure_ascii=False, sort_keys=False),
    )


def payload(path: Path | None = None) -> tuple[dict[str, Any], ...]:
    """Every tool object, in the file's order, as fresh dictionaries.

    The file's order and not a sort: `gen/mcp_tools.tools()` orders by ACTION name (10:225) and
    the mapping from Action name to `mcp_name` is not order-preserving in general, so re-sorting
    here would be this module inventing an order the generator did not choose. A test binds the
    two sequences.

    **This is not `tools/list`.** It is the whole payload; `tools/list` is a profile's selection
    out of it, compacted, with `corpus` promoted where the default does not resolve, and
    `unservable()` names the three transforms this distribution cannot apply.
    """
    return tuple(tool.wire() for tool in load_catalogue(path).tools)


def check(path: Path | None = None) -> tuple[str, ...]:
    """Every reason this payload could not be served honestly. `()` is servable.

    Six clauses, each a property some other document requires of the bytes an agent receives:

    1. **The payload is a non-empty array of objects.** An empty `tools/list` from a server that
       defines four tools is LEANN's manifest with the numbers at their limit.
    2. **Every name matches the MCP grammar** (10:188), because a name a host cannot address is a
       tool that cannot be called.
    3. **No name appears twice.** Check 2 in the registry catches it on the way in
       (*"the dispatcher would resolve to whichever won the dict"*, 10:184) and this catches a
       file that acquired a duplicate after it.
    4. **All four annotation keys on every tool, each a bool.** 10:216 requires them *"never
       conditionally on its value"*, and MCP reads an absent `destructiveHint` as `true` -- so a
       key lost between the generator and the wire ships the protocol's most alarming annotation
       by omission.
    5. **Every tool has a description and an object `inputSchema`.** A tool object missing either
       is not addressable by a model: the first is how it is picked and the second is how it is
       called.
    6. **`additionalProperties: false` on every input schema.** 10:516 makes it survive
       compaction, so a payload without it is one a host will not validate against.
    """
    catalogue = load_catalogue(path)
    findings: list[str] = []
    if not catalogue.tools:
        findings.append(f"{catalogue.path}: the payload declares no tools at all")
    seen: set[str] = set()
    for index, tool in enumerate(catalogue.tools):
        where = tool.name or f"[{index}]"
        if not MCP_NAME_RE.match(tool.name):
            findings.append(
                f"{where}: not shaped ow_[a-z][a-z0-9_]{{1,30}}, so no host can call it"
            )
        if tool.name in seen:
            findings.append(f"{where}: appears twice; a dispatcher resolves whichever won the dict")
        seen.add(tool.name)
        missing = [key for key in ANNOTATION_KEYS if key not in tool.annotations]
        if missing:
            findings.append(
                f"{where}: annotations omit {', '.join(missing)}; MCP reads an absent "
                f"destructiveHint as true, so an omitted key is a declaration"
            )
        if not tool.description:
            findings.append(f"{where}: no description, which is the channel a model picks with")
        if not tool.input_schema:
            findings.append(f"{where}: no inputSchema, so nothing can be validated against it")
        elif tool.input_schema.get("additionalProperties") is not False:
            findings.append(
                f"{where}: inputSchema is not a closed object; 10:516 makes "
                f"additionalProperties: false survive compaction"
            )
    return tuple(findings)


def unservable() -> tuple[str, ...]:
    """What `tools/list` still needs that no file this distribution reads can carry. D340.

    Three rows at W7.3a: selecting a profile, compacting and promoting `corpus` each needed data
    `omniweave` holds. D340 route 2 closed all three with `mcp-listing-v1.json`, which carries the
    transformed objects precomputed (`omniweave_serve.listing`). One input is left, and it is not
    data a file can hold: whether `[serve] default_corpus` resolves is a fact about the deployment
    at startup, decided by `omniweave.surface.startup.servable().resolves`. `listing.tools_list()`
    takes it as `corpus_resolves`, and this row names who owes it.
    """
    return (
        f"[{_CORPUS_KEY}] = {KEYS[_CORPUS_KEY].default!r}: whether it resolves is "
        f"omniweave.surface.startup.servable().resolves, which listing.tools_list() takes as "
        f"corpus_resolves from a caller this distribution does not have",
    )


def layers_row(repo: Path) -> tuple[str, ...]:
    """This distribution's `tools/layers.toml` row, read from the repository.

    Here rather than in a test because `unservable()`'s claim is *"in a distribution this one may
    not import"*, and the row is what makes that a fact rather than an assertion. A reader
    checking the claim should not have to find the gate that enforces it.
    """
    text = (repo / "tools" / "layers.toml").read_text(encoding="utf-8")
    row = tomllib.loads(text).get("omniweave_serve", ())
    return tuple(str(name) for name in row) if isinstance(row, list) else ()
