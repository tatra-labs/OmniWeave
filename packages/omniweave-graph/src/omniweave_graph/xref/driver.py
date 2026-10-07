"""`derive.xref.pattern` as a `derive/1` driver: Segments in, references out. **D669.**

It reads what `derive.anchor.defterm` reads -- the Segment form of `owgraph-segment/1`, a document's
live Segments in one unit (D668) -- and writes D666's item frames: one `seg` frame per Segment, an
`xref` frame per occurrence, and `cover` or `cover_empty` on the `xref` lane.

    {"t":"seg","seg":"seg:9f2c1d4a77b03e51"}
    {"t":"xref","name":"4.2(b)","akind":"section","cite":"d7#12","span":[31,45],
     "surface":"Section 4.2(b)"}
    {"t":"cover","lane":"xref","cites":["d7#12"]}

**The Pass does not decide whether a reference resolves** (06:1097-1102): the sink writes the
`ref_site` occurrence and `ref_unresolved`, an anti-join view, says whether a head-generation anchor
names it under the scope rule. So an `xref` frame carries no scope and no target.
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

from omniweave_graph.view import read_segment_views
from omniweave_graph.xref.rules import Notice, Ref, find, patterns

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DRIVER_ID", "EMPTY_REASON", "LANE", "ReferencePatterns"]

DRIVER_ID: Final = "derive.xref.pattern"
LANE: Final = "xref"
EMPTY_REASON: Final = "no reference-shaped token in this Segment"
_HEAD_WINDOW: Final = 4096


class ReferencePatterns:
    """`patterns.toml`'s regex set over body prose. Standard library only."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """The pattern set compiles, or the driver is unavailable and says why."""
        del env
        try:
            count = len(patterns())
        except (ValueError, KeyError, OSError) as exc:
            return ProbeVerdict(status=ProbeStatus.UNAVAILABLE, detail=f"patterns.toml: {exc}")
        return ProbeVerdict(status=ProbeStatus.OK, detail=f"{count} patterns")

    def __init__(self, **config: Scalar) -> None:
        """No parameters: a corpus tunes the pattern file, not a knob."""
        if config:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(sorted(config))}")

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """One document's Segments per unit in; their occurrences and cover out.

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
                found = find(view.members)
                frames.append({"t": "seg", "seg": view.seg})
                frames += (_xref_frame(r) for r in found.refs)
                frames += _cover_frames(found.refs)
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


def _xref_frame(r: Ref) -> dict[str, Any]:
    return {
        "t": "xref",
        "name": r.name,
        "akind": r.akind,
        "cite": r.cite,
        "span": list(r.span),
        "surface": r.surface,
    }


def _cover_frames(refs: Sequence[Ref]) -> Iterator[dict[str, Any]]:
    cites = list(dict.fromkeys(r.cite for r in refs))
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
