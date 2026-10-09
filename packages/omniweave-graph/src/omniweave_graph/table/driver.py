"""`derive.entity.table` as a `derive/1` driver: Segment views in, row entities and claims out.

**D681.** 06 section 3.6. The wire is `derive.anchor.defterm`'s (D666): a document's Segments in
`owgraph-segment/1`'s Segment form, one `seg` frame per Segment opening its items on
`owgraph-items/1`. Per data row of a table with a header row (`rules.find`):

    {"t":"entity","tmp":"e1","key":"Acme Holdings Ltd.","etype":"org","title":"Acme Holdings Ltd.",
     "scope":"corpus","trust":"extracted"}
    {"t":"alias","entity":"e1","surface":"Acme Holdings Ltd.","alias_kind":"canonical",
     "trust":"extracted"}
    {"t":"mention","entity":"e1","cite":"d7#41","span":[0,18],"surface":"Acme Holdings Ltd.",
     "trust":"extracted"}
    {"t":"claim","subject":"e1","object_literal":"2026-06-30","object_datatype":"xsd:date",
     "claim_type":"attribute","predicate":"Signed","description":"Signed of Acme ...: 2026-06-30",
     "status":"asserted","observed":{"cite":"d7#42","span":[0,10]},"trust":"extracted"}
    {"t":"cover","lane":"entity","cites":["d7#41"]}
    {"t":"cover","lane":"claim","cites":["d7#42"]}

A subject seen again in one Segment -- the same party on two rows -- keeps its first `tmp`: the
second row's claims and mention bind to it rather than minting a second token for a row the sink
would upsert onto the same entity anyway. Only in one Segment: `drive_items` opens a sink per
Segment, so a token is bound for one run, and a token reused in the next would dangle. Tokens are
numbered across the whole invocation, so no two Segments share one. Every claim is `extracted`:
the method is `native_xml` (06:962) and `MAX_TRUST_BY_METHOD` allows it. Finding nothing is an
answer: two `cover_empty`.
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

from omniweave_graph.table.rules import Row, find
from omniweave_graph.view import read_segment_views

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DRIVER_ID", "EMPTY_REASON", "LANES", "NO_FACT_REASON", "TableEntities"]

DRIVER_ID: Final = "derive.entity.table"
LANES: Final = ("entity", "claim")
"""06:962. The order the cover frames are written in."""
EMPTY_REASON: Final = "no table with a header row in this Segment"
NO_FACT_REASON: Final = "no cell beside a row's subject under a non-empty header"
_TRUST: Final = "extracted"
_HEAD_WINDOW: Final = 4096


class TableEntities:
    """Header-keyed rows as entities and `attribute` claims. Standard library only."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """Nothing to find: arithmetic over the cells the host hands it."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="standard library only")

    def __init__(self, **config: Scalar) -> None:
        """No parameters: the rules are 06 section 3.6's, not an operator's."""
        if config:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(sorted(config))}")

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """One document's Segment views per unit in; each Segment's rows and cover out.

        Raises:
            DriverError: `CORRUPT_INPUT` when a view is not the Segment form of
                `owgraph-segment/1`; `TIMEOUT` when cancelled.
        """
        frames: list[dict[str, Any]] = []
        read = 0
        minted = [0]
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
            for view in read_segment_views(raw):
                rows = find(view.members)
                frames.append({"t": "seg", "seg": view.seg})
                tmps: dict[tuple[str, str, str], str] = {}
                for row in rows:
                    frames += _row_frames(row, tmps, minted)
                frames += _cover_frames(rows)
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
        """At least one Segment answered. Its answer may be two `cover_empty` frames."""
        return b'"t":"seg"' in ref.head(_HEAD_WINDOW)


def _row_frames(
    row: Row, tmps: dict[tuple[str, str, str], str], minted: list[int]
) -> Iterator[dict[str, Any]]:
    subject = row.subject
    identity = (row.scope, row.etype, subject.text.casefold())
    tmp = tmps.get(identity)
    if tmp is None:
        minted[0] += 1
        tmp = f"e{minted[0]}"
        tmps[identity] = tmp
        yield {
            "t": "entity",
            "tmp": tmp,
            "key": subject.text,
            "etype": row.etype,
            "title": subject.text,
            "scope": row.scope,
            "trust": _TRUST,
        }
        yield {
            "t": "alias",
            "entity": tmp,
            "surface": subject.text,
            "alias_kind": "canonical",
            "trust": _TRUST,
        }
    yield {
        "t": "mention",
        "entity": tmp,
        "cite": subject.cite,
        "span": list(subject.span),
        "surface": subject.text,
        "trust": _TRUST,
    }
    for fact in row.facts:
        yield {
            "t": "claim",
            "subject": tmp,
            "object_literal": fact.cell.text,
            "object_datatype": fact.datatype,
            "claim_type": "attribute",
            "predicate": fact.header,
            "description": f"{fact.header} of {subject.text}: {fact.cell.text}",
            "status": "asserted",
            "observed": {"cite": fact.cell.cite, "span": list(fact.cell.span)},
            "trust": _TRUST,
        }


def _cover_frames(rows: tuple[Row, ...]) -> Iterator[dict[str, Any]]:
    by_lane = {
        "entity": list(dict.fromkeys(row.subject.cite for row in rows)),
        "claim": list(dict.fromkeys(f.cell.cite for row in rows for f in row.facts)),
    }
    for lane in LANES:
        if by_lane[lane]:
            yield {"t": "cover", "lane": lane, "cites": by_lane[lane]}
        else:
            reason = NO_FACT_REASON if lane == "claim" and rows else EMPTY_REASON
            yield {"t": "cover_empty", "lane": lane, "reason": reason}
