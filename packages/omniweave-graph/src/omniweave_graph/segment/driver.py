"""`derive.segment.spine` as a `derive/1` driver: a document view in, its Segments out. **D662.**

## What it reads -- `owgraph-segment/1`, document form

02-architecture.md:181 has the segmenter read *"`owgraph-segment/1` -- a host-assembled view over
committed blocks"*, and 06:1303-1317 prints that protocol's Segment form: a `segment` header, then
`block` frames addressed by `cite` only. The segmenter runs before any Segment exists, so it reads
the same block frames under a `doc` header instead. One `UnitRef` per document; its
`content_sha256` names the view's blob.

    {"t":"doc","doc":"d7","sections":{"/0001":"Part II","/0001/0004":"7. Risk Factors"},
     "defaults":{"layer":"body","page":1,"sec":"/"}}
    {"t":"block","cite":"d7#3","kind":"heading","sec":"/0001","text":"Part II"}
    {"t":"block","cite":"d7#400","kind":"table","page":13,"sec":"/0001/0004",
     "grid":{"n_rows":40,"n_cols":4,"header_rows":1}}
    {"t":"block","cite":"d7#401","kind":"table_cell","page":13,"sec":"/0001/0004","text":"FY2024",
     "table":{"table_cite":"d7#400","r":0,"c":0}}

`sections` maps a `block_sec.sec_path` to its section's heading text, so `heading_path` is a
lookup and never a second walk. `defaults` elides the modal `layer`, `page` and `sec` exactly as
06:1325-1334 elides a Segment frame's (a key absent from a block takes the default). `text` absent
is a container. The blocks arrive in reading order; the segmenter never reorders.

## What it emits -- the `segment` frame of `owgraph-items/1`

04-driver-system.md:643 says `segment` is an item D7's ladder produces *"and the graph wire does not
print"*; this driver is the reason it now does (the ruling recorded as D662):

    {"t":"doc","doc":"d7"}
    {"t":"segment","layer":"body","atom":null,"heading_path":["Part II"],
     "blocks":["d7#3","d7#4"],"n_tokens":31,"tokenizer":"ow.bytes4/1","synopsis_of":null}
    {"t":"diag","code":"OW_RESOURCE_LIMIT","severity":"warning","component":"derive.segment.spine",
     "message":"...","cite":"d7#9","page":2,"detail":{"limit":"MAX_SEGMENT_TOKENS"},"fatal":false}

A frame's position is its `segment.ord`. Everything else on the `segment` row -- the digest, trust
and quote minima, the kind mask, pages, `n_chars`, restriction bits -- is the host's to derive from
the members, because every one of them is a stored field and a driver that reported them would be
trusted with numbers the host can check.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, Final, NoReturn

from omniweave_ports import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    ProbeStatus,
    ProbeVerdict,
)

from omniweave_graph.segment.spine import Block, Grid, Notice, Params, Segment, segment
from omniweave_graph.tokens import TOKENIZER_ID

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DRIVER_ID", "SpineSegmenter", "read_view"]

DRIVER_ID: Final = "derive.segment.spine"
_HEAD_WINDOW: Final = 4096
_DEFAULTABLE: Final = ("layer", "page", "sec")


class SpineSegmenter:
    """Heading-scoped, table-atomic, zero-overlap, block-aligned Segments. Standard library only."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """Nothing to find: the segmenter is arithmetic over text the host hands it."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="standard library only")

    def __init__(self, **config: Scalar) -> None:
        """The six `Params`, each optional and each refused above its framework ceiling."""
        unknown = sorted(set(config) - set(Params.__slots__))
        if unknown:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(unknown)}")
        self._params = Params(**config)  # type: ignore[arg-type]

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """One document view per unit in; its Segments and Diags out, in `segment.ord` order.

        Raises:
            DriverError: `CORRUPT_INPUT` when a view is not `owgraph-segment/1`; `EMPTY_RESULT`
                when no unit has a block with text; `TIMEOUT` when cancelled.
        """
        frames: list[dict[str, Any]] = []
        read = 0
        segments = 0
        for done, unit in enumerate(scope.units):
            if io.cancelled():
                raise DriverError(
                    cls=FailureClass.TIMEOUT,
                    message=f"cancelled after {done} of {len(scope.units)} documents",
                    retry_after_ms=0,
                )
            with io.blobs.open(unit.content_sha256) as handle:
                raw = handle.read()
            read += len(raw)
            doc, sections, blocks = read_view(raw)
            spine = segment(blocks, sections, self._params)
            segments += len(spine.segments)
            frames.append({"t": "doc", "doc": doc})
            frames += (_segment_frame(s) for s in spine.segments)
            frames += (_diag_frame(n) for n in spine.notices)
            io.progress(done + 1, len(scope.units))
        if not segments:
            raise DriverError(
                cls=FailureClass.EMPTY_RESULT, message="no block in the view carries text"
            )
        payload = "".join(
            json.dumps(f, separators=(",", ":"), ensure_ascii=False) + "\n" for f in frames
        ).encode("utf-8")
        return DriverResult(
            outcome="ok",
            produced=(ArtifactRef.of("graph_items", payload, io),),
            metrics=DriverMetrics(bytes_read=read),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """At least one Segment: a document with no text is `EMPTY_RESULT`, never an empty `ok`."""
        return b'"t":"segment"' in ref.head(_HEAD_WINDOW)


def read_view(raw: bytes) -> tuple[str, Mapping[str, str], list[Block]]:
    """Decode one `owgraph-segment/1` document view. Anything else is `CORRUPT_INPUT`."""
    lines = _lines(raw)
    head = next(lines, None)
    if head is None or head.get("t") != "doc" or not isinstance(head.get("doc"), str):
        _corrupt("the view does not open with a doc frame naming its document")
    sections = head.get("sections", {})
    defaults = {"layer": "body", "page": 1, "sec": "/", **head.get("defaults", {})}
    if not isinstance(sections, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in sections.items()
    ):
        _corrupt("sections must map a sec_path to its heading text")
    blocks = [_block(frame, defaults) for frame in lines]
    return head["doc"], sections, blocks


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


def _block(frame: dict[str, Any], defaults: Mapping[str, Any]) -> Block:
    if frame.get("t") != "block":
        _corrupt(f"a {frame.get('t')!r} frame where a block frame belongs")
    try:
        values = {key: frame.get(key, defaults[key]) for key in _DEFAULTABLE}
        grid = frame.get("grid")
        table = frame.get("table")
        block = Block(
            cite=frame["cite"],
            kind=frame["kind"],
            text=frame.get("text"),
            grid=None
            if grid is None
            else Grid(grid["n_rows"], grid["n_cols"], grid.get("header_rows", 0)),
            table=None if table is None else table["table_cite"],
            r=0 if table is None else table["r"],
            c=0 if table is None else table["c"],
            **values,
        )
    except (KeyError, TypeError) as exc:
        _corrupt(f"block frame {frame.get('cite')!r} is missing or mistypes {exc}")
    for name, kind in (("cite", str), ("kind", str), ("layer", str), ("sec", str), ("page", int)):
        if not isinstance(getattr(block, name), kind):
            _corrupt(f"block frame {frame.get('cite')!r}: {name} is not a {kind.__name__}")
    if block.text is not None and not isinstance(block.text, str):
        _corrupt(f"block frame {block.cite!r}: text is not a string")
    return block


def _corrupt(message: str) -> NoReturn:
    raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"owgraph-segment/1: {message}")


def _segment_frame(s: Segment) -> dict[str, Any]:
    return {
        "t": "segment",
        "layer": s.layer,
        "atom": s.atom,
        "heading_path": list(s.heading_path),
        "blocks": list(s.blocks),
        "n_tokens": s.n_tokens,
        "tokenizer": TOKENIZER_ID,
        "synopsis_of": s.synopsis_of,
    }


def _diag_frame(n: Notice) -> dict[str, Any]:
    return {
        "t": "diag",
        "code": n.code,
        "severity": "warning",
        "component": DRIVER_ID,
        "message": n.message,
        "cite": n.cite,
        "page": n.page,
        "detail": dict(n.detail),
        "fatal": False,
    }
