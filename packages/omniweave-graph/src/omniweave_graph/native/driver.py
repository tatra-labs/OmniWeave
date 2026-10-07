"""`derive.anchor.native` as a `derive/1` driver: Segments in, declared anchors out. **D670.**

It reads what every Segment-grained free Pass reads (D668), now with each member's `marks` and
`label` (D670), and writes D666's `anchor` frame per declared anchor, with `cover` or `cover_empty`
on the `anchor` lane.

    {"t":"seg","seg":"seg:9f2c1d4a77b03e51"}
    {"t":"anchor","name":"4.2","akind":"section","cite":"d7#40","span":[0,3],
     "scope":"document","surface":"4.2 Indemnity"}
    {"t":"cover","lane":"anchor","cites":["d7#40"]}

A second definition of one `(name_norm, akind)` in a generation is the sink's to quarantine with
both surfaces (06:115-118); this Pass reports every declaration it finds.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_ports import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    ProbeStatus,
    ProbeVerdict,
)

from omniweave_graph.native.rules import Anchor, find
from omniweave_graph.view import read_segment_views

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DRIVER_ID", "EMPTY_REASON", "LANE", "DeclaredAnchors"]

DRIVER_ID: Final = "derive.anchor.native"
LANE: Final = "anchor"
EMPTY_REASON: Final = "no declared anchor in this Segment"
_HEAD_WINDOW: Final = 4096


class DeclaredAnchors:
    """Anchor marks, heading numbering and labels, as the store holds them. Stdlib only."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """Nothing to find: it reads structure the host hands it."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="standard library only")

    def __init__(self, **config: Scalar) -> None:
        """No parameters."""
        if config:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(sorted(config))}")

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """One document's Segments per unit in; their declared anchors and cover out.

        Raises:
            DriverError: `CORRUPT_INPUT` when a view is not the Segment form of
                `owgraph-segment/1`; `TIMEOUT` when cancelled.
        """
        frames: list[dict[str, Any]] = []
        read = 0
        for done, unit in enumerate(scope.units):
            if io.cancelled():
                raise DriverError(
                    cls=FailureClass.TIMEOUT,
                    message=f"cancelled after {done} of {len(scope.units)} units",
                    retry_after_ms=0,
                )
            with io.blobs.open(unit.content_sha256) as handle:
                raw = handle.read()
            read += len(raw)
            for view in read_segment_views(raw):
                anchors = find(view.members)
                frames.append({"t": "seg", "seg": view.seg})
                frames += (_anchor_frame(a) for a in anchors)
                frames += _cover_frames(anchors)
            io.progress(done + 1, len(scope.units))
        payload = "".join(
            json.dumps(f, separators=(",", ":"), ensure_ascii=False) + "\n" for f in frames
        ).encode("utf-8")
        return DriverResult(
            outcome="ok",
            produced=(ArtifactRef.of("graph_items", payload, io),),
            metrics=DriverMetrics(bytes_read=read),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """At least one Segment answered. Its answer may be one `cover_empty` frame."""
        return b'"t":"seg"' in ref.head(_HEAD_WINDOW)


def _anchor_frame(a: Anchor) -> dict[str, Any]:
    return {
        "t": "anchor",
        "name": a.name,
        "akind": a.akind,
        "cite": a.cite,
        "span": list(a.span),
        "scope": "document",
        "surface": a.surface,
    }


def _cover_frames(anchors: Sequence[Anchor]) -> Iterator[dict[str, Any]]:
    cites = list(dict.fromkeys(a.cite for a in anchors))
    if cites:
        yield {"t": "cover", "lane": LANE, "cites": cites}
    else:
        yield {"t": "cover_empty", "lane": LANE, "reason": EMPTY_REASON}
