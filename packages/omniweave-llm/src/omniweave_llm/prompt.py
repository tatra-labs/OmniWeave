"""The prompt pack: four lanes, each a prompt generated from the corpus and a schema. D708.

06 section 4.2 is the specification. A prompt is five parts, and one of them is prose a human wrote:

| part | source | in `prompt_fp`? |
|---|---|---|
| 1. role and task | `prompts/<lane>.md`, authored | yes |
| 2. the entity-type table | the corpus's `etypes`, as the Segment frame carries them | yes |
| 3. the relation table, one `actor_rule` line each | the corpus's `relations` | yes |
| 4. the output contract in prose | rendered from `schemas/<lane>.json` | yes |
| 5. the wrapped body | `wrap.wrap_untrusted()` | **no** -- it is the cache key's input |

Parts 2-4 rendered from data are GR17: a new relation reaches the prompt and the schema together,
and no path lets the schema permit what the prompt never named.

## Rulings (the ledger's D708)

1. **`prompt_fp` is over parts 1-4 alone**, with CRLF folded to LF and trailing whitespace stripped
   from every line, then `sha256(...)[:12]` (06:1356). Without the normalisation every Windows
   checkout re-bills the corpus. Part 5 is the Segment, which the cache key already carries as
   `segment.content_digest`.
2. **The extraction lanes (`entity`, `claim`) render parts 2 and 3; the decision lanes (`merge`,
   `report`) do not.** A pair decision and a report name no entity type and no relation.
3. **The vocabulary enters the schema where it enters the prompt.** `$ETYPES` in a schema's `enum`
   becomes the corpus's types with `unknown` after them, once; `$RELATIONS` becomes the relation
   names. A nullable enum keeps its `null` (06 section 4.3: every leaf nullable before constrained
   decoding).
4. **The contract is rendered from the schema**, one line per top-level field and one per item
   field, so the prose cannot drift from what the decoder enforces.
5. **No geometry and no identifier in parts 1-4** (GR11): no `p<n>/<n>` address, no bare number
   that is not a bound, no path. A test renders every lane and greps.
6. **The server decodes against `decodable(schema)`; the answer is validated against `schema`**
   (D717). Ollama 0.20.7's schema-to-grammar crashes the server on a `pattern`: an access
   violation inside `SchemaToGrammar`, measured against the cite pattern and against a bare
   `^d[0-9]+#[0-9]+$`. On an empty `enum` it decodes invalid JSON. So the decoder's copy drops
   every `pattern`. An `enum` with no member is also dropped, and the nearest array around it
   gets `maxItems: 0`. A corpus with no relation then decodes `"relations": []`, the one
   answer the full schema admits. The full schema stays the contract the prompt renders and the
   validator applies, so a cite outside the pattern is still a malformed answer (D710).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

from omniweave_llm.wrap import wrap_untrusted

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "EXTRACTION_LANES",
    "LANES",
    "Prompt",
    "decodable",
    "prompt_fp",
    "render",
    "role",
    "schema",
]

LANES: Final = ("entity", "claim", "merge", "report")
EXTRACTION_LANES: Final = ("entity", "claim")
"""Ruling 2: the lanes that render the vocabulary tables."""

_ETYPES: Final = "$ETYPES"
_RELATIONS: Final = "$RELATIONS"
_UNKNOWN: Final = "unknown"


@dataclass(frozen=True, slots=True)
class Prompt:
    """One rendered prompt: its text, its fingerprint, and the schema its answer must match."""

    lane: str
    text: str
    fp: str
    """`prompt_fp`: 12 hex characters over parts 1-4 (ruling 1)."""
    schema: Mapping[str, Any]


def _lane(lane: str) -> str:
    if lane not in LANES:
        msg = f"{lane!r} is not a lane of the prompt pack: {', '.join(LANES)}"
        raise ValueError(msg)
    return lane


def role(lane: str) -> str:
    """Part 1: the authored role and task text for `lane`."""
    return (resources.files("omniweave_llm") / "prompts" / f"{_lane(lane)}.md").read_text("utf-8")


def schema(
    lane: str, *, etypes: Sequence[str] = (), relations: Sequence[str] = ()
) -> dict[str, Any]:
    """Ruling 3: `schemas/<lane>.json` with the corpus vocabulary in its enums."""
    text = (resources.files("omniweave_llm") / "schemas" / f"{_lane(lane)}.json").read_text("utf-8")
    types = [*dict.fromkeys([*etypes, _UNKNOWN])]
    return _fill(json.loads(text), {_ETYPES: types, _RELATIONS: list(dict.fromkeys(relations))})


def _fill(node: Any, markers: Mapping[str, list[str]]) -> Any:
    if isinstance(node, dict):
        return {key: _fill(value, markers) for key, value in node.items()}
    if isinstance(node, list):
        out: list[Any] = []
        for value in node:
            if isinstance(value, str) and value in markers:
                out.extend(markers[value])
            else:
                out.append(_fill(value, markers))
        return out
    return node


def decodable(full: Mapping[str, Any]) -> dict[str, Any]:
    """Ruling 6: `full` as a server's constrained decoder compiles it. `full` is not changed."""
    out, _empty = _decodable(full)
    return out


def _decodable(node: Any) -> tuple[Any, bool]:
    """`(node without patterns or empty enums, whether it can hold no value)`."""
    if isinstance(node, list):
        return [_decodable(value)[0] for value in node], False
    if not isinstance(node, dict):
        return node, False
    empty = node.get("enum") == []
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "pattern" or (key == "enum" and value == []):
            continue
        child, child_empty = _decodable(value)
        out[key] = child
        empty = empty or child_empty
    if out.get("type") == "array" and empty:
        out["maxItems"] = 0
        return out, False
    return out, empty


def prompt_fp(text: str) -> str:
    """Ruling 1: CRLF folded, each line right-stripped, trailing blank lines dropped, 12 hex."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return hashlib.sha256("\n".join(lines).rstrip("\n").encode("utf-8")).hexdigest()[:12]


def render(
    lane: str,
    *,
    body: str,
    source: str,
    etypes: Sequence[str] = (),
    relations: Sequence[tuple[str, str]] = (),
) -> Prompt:
    """The five parts for `lane`; `body` is wrapped as `source` (part 5).

    `relations` is `(relation, actor_rule)` pairs, each rule already `sanitize_label`-ed at write
    (06:2217-2218); `etypes` the corpus's promoted and builtin types (a proposed one never reaches
    a Segment frame, 06:1675).
    """
    the_schema = schema(lane, etypes=etypes, relations=[name for name, _ in relations])
    parts = [role(lane).strip()]
    if lane in EXTRACTION_LANES:
        types = [*dict.fromkeys([*etypes, _UNKNOWN])]
        parts.append("Entity types:\n" + "\n".join(f"- {etype}" for etype in types))
        parts.append(
            (
                "Relations, each with its actor rule (source and target):\n"
                + "\n".join(f"- {name}: {rule}" for name, rule in relations)
            )
            if relations
            else "Relations: none in this corpus; emit no relationships."
        )
    parts.append(_contract(the_schema))
    head = "\n\n".join(parts)
    return Prompt(
        lane=lane,
        text=f"{head}\n\n{wrap_untrusted(source, body)}",
        fp=prompt_fp(head),
        schema=the_schema,
    )


def _contract(the_schema: Mapping[str, Any]) -> str:
    """Ruling 4: the answer's shape, read off the schema it is decoded against."""
    lines = ["Answer with one JSON object and nothing else. Its fields:"]
    for name, field in the_schema["properties"].items():
        lines.append(f"- {name}: {_describe(field)}")
        items = field.get("items", {})
        for sub, spec in items.get("properties", {}).items():
            lines.append(f"    - {sub}: {_describe(spec)}")
    return "\n".join(lines)


def _describe(field: Mapping[str, Any]) -> str:
    kinds = field.get("type", "")
    kind = " or ".join(kinds) if isinstance(kinds, list) else str(kinds)
    words = [kind.replace("integer", "whole number")]
    if "enum" in field:
        words.append("one of " + ", ".join("null" if v is None else str(v) for v in field["enum"]))
    if "maxItems" in field:
        words.append(f"at most {field['maxItems']} items")
    if field.get("minItems"):
        words.append(f"at least {field['minItems']}")
    if "maxLength" in field:
        words.append(f"at most {field['maxLength']} characters")
    if "minLength" in field:
        words.append(f"at least {field['minLength']} characters")
    if "minimum" in field and "maximum" in field:
        words.append(f"from {field['minimum']} to {field['maximum']}")
    if "pattern" in field:
        words.append(
            "a cite exactly as a block line gives it"
            if "#" in field["pattern"]
            else "a date as YYYY, YYYY-MM or YYYY-MM-DD"
        )
    return ", ".join(words)
