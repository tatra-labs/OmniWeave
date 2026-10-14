"""The embedded citation channel, every OOXML target's: its rows, its addresses and its part.
**D802.**

09-generation.md section 10's embedded channel for OOXML is the card's `provenance_part`,
`customXml/omniweave-provenance.json`, which `read_back` recovers an artefact's cites from. docx
built it for itself (D782, D786). A deck needs the same channel, so it lives here, once
(INV-21), and each target writes the bytes `body()` returns into its own package.

## Rulings

1. **One row for each cited element and cite, in document order.** A row gives the element's
   `data-ow-el`, the canonical cite (the Plan's corpus prefix removed), the `doc_gen` the compile
   pinned it at (`Plan.cites`), and its kind and span where the IL states them. An element that
   cites and carries no address is `OW_TARGET_IL_MALFORMED`, since its row would have no
   address; a cite the Plan pinned no generation for is `OW_TARGET_CITE_UNRESOLVED`.
2. **A kind is one of 09 section 10's four, and a span is `a:b` with `a < b`.** A span names one
   cite's text, so it is read only beside a single cite, as the compile's `artifact_cite` rows
   read it. A value outside either grammar is `OW_TARGET_IL_MALFORMED`.
3. **`els` maps every address in the artefact to its construct**: the first native element row
   the element matches, as the walk dispatches it (D786). A reader recovers what each address
   was from it, through the target's `kind_map.toml`.
4. **The part is written whether or not anything is cited**, so a reader can tell an artefact
   with no cites from one that is not omniweave's. Its body is canonical JSON, and visible text
   is never a citation.
5. **`citations()` is the receipt's `citations_channel` row, read from the part itself**: passed
   with its row count, or failed when the package holds no part.
6. **A target whose markup cannot name every address lists where each landed** (`at`, D803). A
   document's bookmarks carry its addresses; a deck's runs have nothing to carry one, so a deck
   writes each address's unit, shape, line and runs, and its reader reads them. `at` is written
   only by a target that passes it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from omniweave_core.canonical import JsonValue, canonical
from omniweave_core.errors import TargetError
from omniweave_core.model.block import Cite
from omniweave_core.out.cites import CITE_KINDS
from omniweave_core.out.lowering import Row, walk
from omniweave_core.out.receipt import CheckValue

if TYPE_CHECKING:
    from omniweave_core.out.carrier import CarrierNode
    from omniweave_core.out.plan import Plan

__all__ = [
    "MEDIA_TYPE",
    "RELATIONSHIP",
    "SCHEMA",
    "addresses",
    "body",
    "citations",
    "cited",
    "kind",
    "span",
]

SCHEMA: Final = "omniweave.out-provenance/1"
MEDIA_TYPE: Final = "application/json"
RELATIONSHIP: Final = "urn:omniweave:relationship:provenance"
"""A package relationship's type is a URI; this one names no place, so nothing can fetch it."""


def kind(value: str) -> str:
    """Ruling 2: `data-ow-cite-kind`, one of the four kinds `artifact_cite` stores."""
    if value not in CITE_KINDS:
        msg = f"data-ow-cite-kind {value!r} is not one of {sorted(CITE_KINDS)}"
        raise ValueError(msg)
    return value


def span(value: str) -> tuple[int, int]:
    """Ruling 2: `data-ow-cite-span="a:b"`, a range of the cited block's text, `a < b`."""
    a, sep, b = value.partition(":")
    if not sep or not a.isdecimal() or not b.isdecimal() or int(a) >= int(b):
        msg = f"data-ow-cite-span {value!r} is not a:b with a < b"
        raise ValueError(msg)
    return int(a), int(b)


def cited(roots: Sequence[CarrierNode], plan: Plan) -> list[dict[str, JsonValue]]:
    """Ruling 1: the part's rows, every cited element with an address and every cite a pin."""
    rows: list[dict[str, JsonValue]] = []
    for root in roots:
        for node in walk(root):
            tokens = (node.attr("data-ow-cite") or "").split()
            if not tokens:
                continue
            if not node.el:
                raise TargetError(
                    f"{node.at}: an element cites {' '.join(tokens)} and carries no data-ow-el, "
                    "so its provenance row has no address",
                    symbol="OW_TARGET_IL_MALFORMED",
                    fix="ow out stamp",
                )
            facts = _facts(node, single=len(tokens) == 1)
            for token in tokens:
                cite = token.removeprefix(f"{plan.corpus}:")
                pinned = plan.cites.get(Cite(cite))
                if pinned is None:
                    raise TargetError(
                        f"{node.at}: cite {token!r} has no generation pinned in the Plan",
                        symbol="OW_TARGET_CITE_UNRESOLVED",
                        fix=f"ow open {token}",
                    )
                rows.append({"el": node.el, "cite": cite, "doc_gen": pinned, **facts})
    return rows


def addresses(roots: Sequence[CarrierNode], rows: Sequence[Row]) -> dict[str, str]:
    """Ruling 3: every `data-ow-el` and the construct its element is."""
    out: dict[str, str] = {}
    for root in roots:
        for node in walk(root):
            if not node.el:
                continue
            for row in rows:
                if row.selector.kind == "element" and row.selector.matches(node):
                    out[node.el] = row.construct.id
                    break
    return out


def body(
    rows: Sequence[Mapping[str, JsonValue]],
    els: Mapping[str, str],
    *,
    corpus: str,
    slug: str,
    artifact_gen: int,
    at: Mapping[str, Mapping[str, JsonValue]] | None = None,
) -> bytes:
    """Ruling 4: the part's canonical JSON; ruling 6: `at`, where a target passes it."""
    document: JsonValue = {
        "schema": SCHEMA,
        "corpus": corpus,
        "slug": slug,
        "artifact_gen": artifact_gen,
        "cites": [dict(row) for row in rows],
        "els": dict(els),  # canonical JSON sorts every object's keys
    }
    if at is not None:
        document["at"] = {el: dict(place) for el, place in at.items()}
    return canonical(document)


def citations(members: Mapping[str, bytes], name: str) -> CheckValue:
    """Ruling 5: the embedded channel's rows, counted from the part itself."""
    raw = members.get(name)
    if raw is None:
        return CheckValue("citations_channel", "failed", f"no {name} in the package")
    rows = json.loads(raw).get("cites", [])
    return CheckValue("citations_channel", "passed", f"embedded: {len(rows)} cite row(s)")


def _facts(node: CarrierNode, *, single: bool) -> dict[str, JsonValue]:
    """Ruling 2: a cite's kind and span as the IL states them."""
    raw_kind, raw_span = node.attr("data-ow-cite-kind"), node.attr("data-ow-cite-span")
    try:
        found_kind = None if raw_kind is None else kind(raw_kind)
        found_span = None if raw_span is None or not single else span(raw_span)
    except ValueError as exc:
        raise TargetError(
            f"{node.at}: {exc}", symbol="OW_TARGET_IL_MALFORMED", fix="ow out check --stage final"
        ) from None
    return {"kind": found_kind, "span": None if found_span is None else list(found_span)}
