"""`derive.entity.llm`'s answer, as the `owgraph-items/1` frames the host writes. D710.

The model answers 06:1399-1421's schema: entities, each a name, a type, a cite and a quote, and
relations between them by name. The host's sink takes Draft-shaped frames (D666), grounds every
quote against the stored block text, and refuses scope, dangling cites, covered ground and
unknown types by itself (06 section 1.7). So this module translates and does not judge: anything the
sink can refuse, it is handed and refuses with the item kept.

## Rulings (the ledger's D710)

1. **An answer that does not parse, or does not match the schema, is one malformed frame**: the raw
   text in an `entity` frame with no `key`, which the host's decoder rejects into a quarantine row
   under `OW_GRAPH_UNPARSED_ITEM`, the body kept verbatim (06:1502-1505), and a `cover_empty`
   saying why. It is never an empty answer, which would read as a Segment with no entities.
2. **One entity frame per distinct `(name, etype)`, one mention per item.** The sink binds a second
   proposal of the same entity to the first (06:628-634), so grouping here is only economy; the
   grouping key is the name casefolded, and the sink's `normalize_key` decides identity.
3. **A null name takes its quote; a null type is `unknown`.** Every leaf is nullable for
   constrained decoding (06:1495), and a null is not a refusal.
4. **Scope is the type's**: `document` for a type the view lists in `document_scoped`, else
   `corpus` (06:291). The sink takes a draft's scope as given.
5. **Trust is claimed `extracted`** and the runner clamps it to `inferred` (`MAX_TRUST_BY_METHOD`):
   06:897-901 reads the clamp rate as a liveness check that a billed Pass over-claims every time.
6. **A relation names its ends by name; an end no emitted entity carries is a malformed `edge`**
   with no `src`, quarantined `OW_GRAPH_UNPARSED_ITEM` with the relation kept. A dangling `tmp`
   would quarantine the whole Segment (`OW_GRAPH_DANGLING_TMP`), which one bad relation does not
   earn.
7. **Cover is the uncovered members the answer's items cite**, or `cover_empty` with a reason when
   there are none (GR3). A covered member is not claimed: the sink refuses items on it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from omniweave_llm.validate import violations

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_llm.view import SegmentView

__all__ = ["LANE", "TRUST_CLAIM", "answer_frames", "parse_answer", "unparsed_frames"]

LANE: Final = "entity"
TRUST_CLAIM: Final = "extracted"
"""Ruling 5."""

_NO_ITEMS: Final = "the model returned no item on uncovered ground"
_UNPARSED: Final = "the model's answer did not parse against the lane's schema"


def parse_answer(
    text: str, schema: Mapping[str, Any]
) -> tuple[Mapping[str, Any] | None, list[str]]:
    """Ruling 1's test: the answer, or `None` and every reason it is not one."""
    try:
        value = json.loads(text)
    except json.JSONDecodeError as error:
        return None, [f"$: not JSON ({error.msg})"]
    found = violations(schema, value)
    return (value, found) if not found else (None, found)


def unparsed_frames(view: SegmentView, raw: str, problems: list[str]) -> list[dict[str, Any]]:
    """Ruling 1: the raw answer kept in one malformed frame, and a cover_empty saying why."""
    return [
        {"t": "seg", "seg": view.seg},
        {"t": "entity", "unparsed": raw, "problems": problems[:20]},
        {"t": "cover_empty", "lane": LANE, "reason": _UNPARSED},
    ]


def answer_frames(view: SegmentView, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rulings 2-7: one Segment's answer as `owgraph-items/1` frames, `seg` first."""
    frames: list[dict[str, Any]] = [{"t": "seg", "seg": view.seg}]
    tmps: dict[tuple[str, str], str] = {}
    by_name: dict[str, str] = {}
    cited: set[str] = set()
    for item in answer.get("entities", ()):
        name = item["name"] if item.get("name") is not None else item["quote"]
        etype = item["etype"] if item.get("etype") is not None else "unknown"
        group = (name.casefold(), etype)
        if group not in tmps:
            tmp = f"t{len(tmps) + 1}"
            tmps[group] = tmp
            by_name.setdefault(name.casefold(), tmp)
            entity: dict[str, Any] = {
                "t": "entity",
                "tmp": tmp,
                "key": name,
                "etype": etype,
                "title": name,
                "scope": "document" if etype in view.document_scoped else "corpus",
                "trust": TRUST_CLAIM,
            }
            if item.get("description") is not None:
                entity["description"] = item["description"]
            frames.append(entity)
        frames.append(
            {
                "t": "mention",
                "entity": tmps[group],
                "cite": item["cite"],
                "quote": item["quote"],
                "surface": name,
                "trust": TRUST_CLAIM,
            }
        )
        cited.add(item["cite"])
    for item in answer.get("relations", ()):
        ends = (by_name.get(item["source"].casefold()), by_name.get(item["target"].casefold()))
        observed = {"cite": item["cite"], "quote": item["quote"]}
        edge: dict[str, Any] = {"t": "edge", "relation": item["relation"], "observed": observed}
        if None in ends:
            edge |= {"source": item["source"], "target": item["target"], "unresolved": True}
        else:
            edge |= {"src": ends[0], "dst": ends[1], "trust": TRUST_CLAIM}
            cited.add(item["cite"])
        frames.append(edge)
    claimed = sorted(b.cite for b in view.blocks if b.cite in cited and not b.covered)
    frames.append(
        {"t": "cover", "lane": LANE, "cites": claimed}
        if claimed
        else {"t": "cover_empty", "lane": LANE, "reason": _NO_ITEMS}
    )
    return frames
