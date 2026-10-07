"""`owgraph-segment/1`'s Segment form, decoded: what each Segment-grained free Pass reads. **D666.**

06-structure-extraction.md section 4.1 prints the protocol: a `segment` header naming the Segment
and its `heading_path`, carrying a `defaults` map, then one `block` frame per member in
`segment_block.ord` order, addressed by `cite` only.

    {"t":"segment","seg":"seg:9f2c1d4a77b03e51","heading_path":["Part II","1. Definitions"],
     "n_blocks":2,"defaults":{"layer":"body","covered":false}}
    {"t":"block","cite":"d7#412","kind":"list_item","ord":0,"text":"Affiliate: ..."}
    {"t":"block","cite":"d7#430","kind":"table_cell","ord":1,"text":"Affiliate",
     "table":{"table_cite":"d7#429","r":1,"c":0,"header_rows":1,"n_cols":2}}

A key absent from a block frame takes its value in `defaults` (06:1325-1334). Keys a free Pass has
no use for -- `doc`, `etypes`, `relations`, `marks`, `quote`, `trust` -- are accepted and ignored,
because the host assembles one view for every Pass on the Segment and a billed Pass needs them.

**One addition to the printed `table` object: `n_cols`.** A glossary is "one term per two-column
table row" (06:1124), and a cell frame otherwise says nothing about how wide its table is; the
container is not a member (D662 reading 1), so it cannot be looked up. The host has the grid.

Pure decoding, standard library only. A malformed view is `CORRUPT_INPUT`: the host built it, so a
bad one is a host defect a driver must refuse rather than guess past.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NoReturn

from omniweave_ports import DriverError, FailureClass

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = ["Cell", "Mark", "Member", "SegmentView", "read_segment_view", "read_segment_views"]


@dataclass(frozen=True, slots=True)
class Cell:
    """Where a `table_cell` member sits in its table."""

    table_cite: str
    r: int
    c: int
    header_rows: int = 0
    n_cols: int = 0
    """0 when the host did not say; a rule that needs the width then does not fire."""


@dataclass(frozen=True, slots=True)
class Mark:
    """One `mark` row over the member's text: 06:1316's `[a, b, kind, value]`. **D670.**

    `kind` is open (0001's `mark.kind` is TEXT): `bold`, `link`, `note_ref`, `anchor`, ... and
    `value` is the kind's own JSON -- an `anchor` mark's is `{"name": ..., "akind": ...}`."""

    a: int
    b: int
    kind: str
    value: object = None


@dataclass(frozen=True, slots=True)
class Member:
    """One member block of the Segment. `text` is `block.text` verbatim, so a span into it is a
    `TextSpan` the host can bounds-check without a second normalisation."""

    cite: str
    kind: str
    text: str | None = None
    layer: str = "body"
    covered: bool = False
    table: Cell | None = None
    label: str | None = None
    """`block.label`: a list item's printed marker, a picture's alt text (D670)."""
    marks: tuple[Mark, ...] = ()


@dataclass(frozen=True, slots=True)
class SegmentView:
    seg: str
    """`"seg:" + hex(content_digest)[:16]` -- echoed on the output so a reader can pair them."""
    heading_path: tuple[str, ...]
    members: tuple[Member, ...]


def read_segment_view(raw: bytes) -> SegmentView:
    """Decode one Segment-form view. Anything else is `CORRUPT_INPUT`."""
    views = read_segment_views(raw)
    if len(views) != 1:
        _corrupt(f"the view holds {len(views)} Segments where one was expected")
    return views[0]


def read_segment_views(raw: bytes) -> tuple[SegmentView, ...]:
    """Decode a document's Segments, each a `segment` header and its members, one after another.

    **D668.** A document-granularity Pass is INVOKEd once per document (06:810), and an `INVOKE`
    carries one unit per work row, so its unit is the document and its view is every live Segment
    of it in this form, in `segment.ord` order. A document with no Segment is no view at all.
    """
    frames = list(_lines(raw))
    if not frames or frames[0].get("t") != "segment":
        _corrupt("the view does not open with a segment frame naming its Segment")
    views: list[SegmentView] = []
    start = 0
    for end in range(1, len(frames) + 1):
        if end == len(frames) or frames[end].get("t") == "segment":
            views.append(_one(frames[start], frames[start + 1 : end]))
            start = end
    return tuple(views)


def _one(head: dict[str, Any], blocks: list[dict[str, Any]]) -> SegmentView:
    if not isinstance(head.get("seg"), str):
        _corrupt("the view does not open with a segment frame naming its Segment")
    path = head.get("heading_path", [])
    if not isinstance(path, list) or not all(isinstance(p, str) for p in path):
        _corrupt("heading_path must be a list of strings")
    defaults = head.get("defaults", {})
    if not isinstance(defaults, dict):
        _corrupt("defaults must be an object")
    members = tuple(_member(frame, defaults) for frame in blocks)
    return SegmentView(seg=head["seg"], heading_path=tuple(path), members=members)


def _lines(raw: bytes) -> Iterator[dict[str, Any]]:
    for number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except ValueError:
            _corrupt(f"line {number} is not JSON")
        if not isinstance(frame, dict):
            _corrupt(f"line {number} is not a frame")
        yield frame


def _member(frame: dict[str, Any], defaults: Mapping[str, Any]) -> Member:
    if frame.get("t") != "block":
        _corrupt(f"a {frame.get('t')!r} frame where a block frame belongs")
    cite, kind, text = frame.get("cite"), frame.get("kind"), frame.get("text")
    layer = frame.get("layer", defaults.get("layer", "body"))
    covered = frame.get("covered", defaults.get("covered", False))
    if not isinstance(cite, str) or not isinstance(kind, str) or not isinstance(layer, str):
        _corrupt(f"block frame {cite!r}: cite, kind and layer must be strings")
    if text is not None and not isinstance(text, str):
        _corrupt(f"block frame {cite!r}: text is not a string")
    if not isinstance(covered, bool):
        _corrupt(f"block frame {cite!r}: covered is not a boolean")
    label = frame.get("label")
    if label is not None and not isinstance(label, str):
        _corrupt(f"block frame {cite!r}: label is not a string")
    return Member(
        cite=cite,
        kind=kind,
        text=text,
        layer=layer,
        covered=covered,
        table=_cell(cite, frame),
        label=label,
        marks=_marks(cite, frame.get("marks", [])),
    )


def _marks(cite: str, raw: object) -> tuple[Mark, ...]:
    if not isinstance(raw, list):
        _corrupt(f"block frame {cite!r}: marks is not a list")
    out: list[Mark] = []
    for item in raw:
        if (
            not isinstance(item, list)
            or len(item) != 4  # noqa: PLR2004 -- [a, b, kind, value]
            or not all(type(v) is int and v >= 0 for v in item[:2])
            or item[1] < item[0]
            or not isinstance(item[2], str)
        ):
            _corrupt(f"block frame {cite!r}: a mark is not [a, b, kind, value] with a <= b")
        out.append(Mark(a=item[0], b=item[1], kind=item[2], value=item[3]))
    return tuple(out)


def _cell(cite: str, frame: dict[str, Any]) -> Cell | None:
    table = frame.get("table")
    if table is None:
        return None
    if not isinstance(table, dict):
        _corrupt(f"block frame {cite!r}: table is not an object")
    try:
        cell = Cell(
            table_cite=table["table_cite"],
            r=table["r"],
            c=table["c"],
            header_rows=table.get("header_rows", 0),
            n_cols=table.get("n_cols", 0),
        )
    except KeyError as exc:
        _corrupt(f"block frame {cite!r}: table is missing {exc}")
    if not isinstance(cell.table_cite, str) or not all(
        type(v) is int and v >= 0 for v in (cell.r, cell.c, cell.header_rows, cell.n_cols)
    ):
        _corrupt(f"block frame {cite!r}: table mistypes a field")
    return cell


def _corrupt(message: str) -> NoReturn:
    raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"owgraph-segment/1: {message}")
