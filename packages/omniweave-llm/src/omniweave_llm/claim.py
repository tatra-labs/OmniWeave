"""`derive.claim.llm`'s answer, as the `owgraph-items/1` frames the host writes. D721.

The model answers 06:1430-1460's schema: claims, each a subject, a type, a predicate, an object, a
status, an optional time and a cite with its quote. A claim's subject is an entity, and so is its
object when the model says so. The sink binds an entity frame to the entity its key already names
(06:628-634), so a claim lands on the subject `derive.entity.*` extracted. The host grounds every
quote, and refuses dangling cites and covered ground by itself (06 section 1.7). As in D710, this
module translates and does not judge.

## Rulings (the ledger's D721)

1. **An answer that does not parse, or does not match the schema, is one malformed `claim` frame**
   with the raw text, and a `cover_empty` saying why (D710 ruling 1, on this lane).
2. **A claim's subject is an entity frame, one per distinct `(subject, subject_etype)`.** A null
   type is `unknown`. Scope is the type's (D710 ruling 4). The frame carries no mention: the
   claim's own `observed` is its grounding, and a subject named in passing is not a mention of it.
3. **An object is an entity only when `object_is_entity` says so and the object is named**; it is
   then an entity frame of type `unknown`. Every other object is a literal of datatype `string`
   (06:1165: *"A guess is `string`"*). A null object is neither: a claim may name no object.
4. **The time's precision is its shape**: `YYYY` is `year`, `YYYY-MM` is `month`, `YYYY-MM-DD` is
   `day`. The schema's pattern admits nothing else, and the validator holds it (D710).
5. **A null description is the empty string.** `ClaimDraft.description` is not optional.
6. **Trust is claimed `extracted`**, for the runner's clamp to lower (D710 ruling 5).
7. **Cover is the uncovered members the claims cite**, or `cover_empty` with a reason (GR3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from omniweave_llm.entity import TRUST_CLAIM, parse_answer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_llm.view import SegmentView

__all__ = ["LANE", "answer_frames", "parse_answer", "precision", "unparsed_frames"]

LANE: Final = "claim"
_NO_ITEMS: Final = "the model returned no claim on uncovered ground"
_UNPARSED: Final = "the model's answer did not parse against the lane's schema"
_PRECISION: Final = {4: "year", 7: "month", 10: "day"}
"""Ruling 4: a date's length is its precision, for the three shapes the schema admits."""


def precision(start: str | None, end: str | None) -> str | None:
    """Ruling 4: the finer of the two dates' precisions, or `None` when neither is given."""
    found = [_PRECISION[len(v)] for v in (start, end) if v is not None and len(v) in _PRECISION]
    order = list(_PRECISION.values())
    return max(found, key=order.index) if found else None


def unparsed_frames(view: SegmentView, raw: str, problems: list[str]) -> list[dict[str, Any]]:
    """Ruling 1: the raw answer kept in one malformed frame, and a cover_empty saying why."""
    return [
        {"t": "seg", "seg": view.seg},
        {"t": "claim", "unparsed": raw, "problems": problems[:20]},
        {"t": "cover_empty", "lane": LANE, "reason": _UNPARSED},
    ]


def answer_frames(view: SegmentView, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rulings 2-7: one Segment's answer as `owgraph-items/1` frames, `seg` first."""
    frames: list[dict[str, Any]] = [{"t": "seg", "seg": view.seg}]
    tmps: dict[tuple[str, str], str] = {}
    cited: set[str] = set()

    def entity(name: str, etype: str) -> str:
        group = (name.casefold(), etype)
        if group not in tmps:
            tmps[group] = f"t{len(tmps) + 1}"
            frames.append(
                {
                    "t": "entity",
                    "tmp": tmps[group],
                    "key": name,
                    "etype": etype,
                    "title": name,
                    "scope": "document" if etype in view.document_scoped else "corpus",
                    "trust": TRUST_CLAIM,
                }
            )
        return tmps[group]

    for item in answer.get("claims", ()):
        subject = entity(item["subject"], item.get("subject_etype") or "unknown")
        claim: dict[str, Any] = {
            "t": "claim",
            "subject": subject,
            "claim_type": item["claim_type"],
            "predicate": item["predicate"],
            "description": item.get("description") or "",
            "status": item["status"],
            "observed": {"cite": item["cite"], "quote": item["quote"]},
            "trust": TRUST_CLAIM,
        }
        obj = item.get("object")
        if obj is not None and item.get("object_is_entity"):
            claim["object_entity"] = entity(obj, "unknown")
        elif obj is not None:
            claim |= {"object_literal": obj, "object_datatype": "string"}
        start, end = item.get("t_start"), item.get("t_end")
        when = precision(start, end)
        if when is not None:
            claim |= {"t_start": start, "t_end": end, "t_precision": when}
        frames.append(claim)
        cited.add(item["cite"])
    claimed = sorted(b.cite for b in view.blocks if b.cite in cited and not b.covered)
    frames.append(
        {"t": "cover", "lane": LANE, "cites": claimed}
        if claimed
        else {"t": "cover_empty", "lane": LANE, "reason": _NO_ITEMS}
    )
    return frames
