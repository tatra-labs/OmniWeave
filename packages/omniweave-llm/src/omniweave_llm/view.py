"""The billed Segment form, as a billed Pass reads it. D710.

The host renders it (`omniweave_core.store.items.build_segment_view(..., billed=...)`, D709): a
`segment` header carrying the corpus vocabulary, `doc` and `defaults`, then the members in
`segment_block.ord` order, each addressed by `cite` and carrying `covered` when it differs from the
default. This module is the reading end, in the one package a billed driver may import alongside
`omniweave_ports`.

**A free view is refused.** A header without `etypes` and `relations` is the form a free Pass reads
(D667 ruling 6), and a billed prompt rendered from it would name no type and no relation: the
schema would admit `unknown` alone, silently. `read_views` raises instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Final

__all__ = ["Block", "SegmentView", "read_views"]

_FREE: Final = (
    "a free view: a billed Pass reads the billed form (D709), which carries the vocabulary"
)


@dataclass(frozen=True, slots=True)
class Block:
    """One member: its cite, its text (empty for a container), and whether it is covered ground."""

    cite: str
    text: str
    covered: bool


@dataclass(frozen=True, slots=True)
class SegmentView:
    """One Segment of the billed form."""

    seg: str
    etypes: tuple[str, ...]
    document_scoped: frozenset[str]
    """The types whose entities are scoped to their document (06:291): `defined_term`, `section`."""
    relations: tuple[tuple[str, str], ...]
    """`(relation, actor_rule)`, as the prompt's part 3 prints them."""
    blocks: tuple[Block, ...]
    body: str
    """The Segment's frames as received: the prompt's part 5, which the model reads."""


def read_views(body: bytes) -> tuple[SegmentView, ...]:
    """Every Segment in a unit's body, in order.

    Raises:
        ValueError: a line that is not a JSON object, a block before any header, or a free view.
    """
    views: list[SegmentView] = []
    header: dict[str, Any] | None = None
    blocks: list[Block] = []
    lines: list[str] = []
    for number, line in enumerate(body.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        frame = json.loads(line)
        if not isinstance(frame, dict):
            msg = f"line {number} is not a JSON object"
            raise ValueError(msg)  # noqa: TRY004 -- one error class for every malformed body
        if frame.get("t") == "segment":
            if header is not None:
                views.append(_view(header, blocks, lines))
            header, blocks, lines = frame, [], [line]
            continue
        if header is None:
            msg = f"line {number} comes before any segment header"
            raise ValueError(msg)
        lines.append(line)
        if frame.get("t") == "block":
            default = bool(header.get("defaults", {}).get("covered", False))
            blocks.append(
                Block(
                    cite=str(frame["cite"]),
                    text=str(frame.get("text") or ""),
                    covered=bool(frame.get("covered", default)),
                )
            )
    if header is not None:
        views.append(_view(header, blocks, lines))
    return tuple(views)


def _view(header: dict[str, Any], blocks: list[Block], lines: list[str]) -> SegmentView:
    if "etypes" not in header or "relations" not in header:
        raise ValueError(_FREE)
    return SegmentView(
        seg=str(header["seg"]),
        etypes=tuple(str(e) for e in header["etypes"]),
        document_scoped=frozenset(str(e) for e in header.get("document_scoped", ())),
        relations=tuple((str(r["relation"]), str(r["actor_rule"])) for r in header["relations"]),
        blocks=tuple(blocks),
        body="\n".join(lines),
    )
