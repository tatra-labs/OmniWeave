"""`derive.xref.native` as a `derive/1` driver: Segments in, linked references out. **D671.**

It reads what every Segment-grained free Pass reads -- a document's live Segments in one unit
(D668), with each member's marks (D670) -- and writes D666's `xref` frame per in-document link, with
`cover` or `cover_empty` on the `xref` lane:

    {"t":"seg","seg":"seg:9f2c1d4a77b03e51"}
    {"t":"xref","name":"_Toc42","akind":"section","cite":"d7#12","span":[8,22],
     "surface":"Indemnification"}
    {"t":"cover","lane":"xref","cites":["d7#12"]}

The unit is read whole before any Segment is answered, because a link's `akind` is the one the
document declares for its target anywhere in the document (`rules` reading 3).
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

from omniweave_graph.links.rules import Link, Notice, declared_kinds, find
from omniweave_graph.view import read_segment_views

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DRIVER_ID", "EMPTY_REASON", "LANE", "DocumentLinks"]

DRIVER_ID: Final = "derive.xref.native"
LANE: Final = "xref"
EMPTY_REASON: Final = "no in-document link in this Segment"
_HEAD_WINDOW: Final = 4096


class DocumentLinks:
    """In-document links, typed by the document's own anchors. Standard library only."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """Nothing to find: it reads marks the host hands it."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="standard library only")

    def __init__(self, **config: Scalar) -> None:
        """No parameters."""
        if config:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(sorted(config))}")

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """One document's Segments per unit in; their linked references and cover out.

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
            views = read_segment_views(raw)
            kinds = declared_kinds(m for v in views for m in v.members)
            for view in views:
                found = find(view.members, kinds)
                frames.append({"t": "seg", "seg": view.seg})
                frames += (_xref_frame(link) for link in found.links)
                frames += _cover_frames(found.links)
                frames += (_diag_frame(n) for n in found.notices)
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


def _xref_frame(link: Link) -> dict[str, Any]:
    return {
        "t": "xref",
        "name": link.name,
        "akind": link.akind,
        "cite": link.cite,
        "span": list(link.span),
        "surface": link.surface,
    }


def _cover_frames(links: Sequence[Link]) -> Iterator[dict[str, Any]]:
    cites = list(dict.fromkeys(link.cite for link in links))
    if cites:
        yield {"t": "cover", "lane": LANE, "cites": cites}
    else:
        yield {"t": "cover_empty", "lane": LANE, "reason": EMPTY_REASON}


def _diag_frame(n: Notice) -> dict[str, Any]:
    return {
        "t": "diag",
        "code": n.code,
        "severity": "warning",
        "component": DRIVER_ID,
        "message": n.message,
        "cite": n.cite,
        "detail": dict(n.detail),
        "fatal": False,
    }
