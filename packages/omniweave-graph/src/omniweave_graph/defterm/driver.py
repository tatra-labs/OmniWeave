"""`derive.anchor.defterm` as a `derive/1` driver: Segment views in, definition sites out. **D666.**

## What it reads

`owgraph-segment/1`'s Segment form, one view per `UnitRef` (`omniweave_graph.view`). 06:810 runs a
document-granularity free Pass *"once, INVOKEd with the document's Segments as units"*.

## What it emits -- `owgraph-items/1`

06 section 1.7 prints the Drafts a host reconstructs from these frames and 04:643 names the frame
kinds; neither prints the frames. They are the Drafts' fields, under the Drafts' names, with three
encodings that a JSON line forces (the ruling recorded as D666):

    {"t":"seg","seg":"seg:9f2c1d4a77b03e51"}
    {"t":"entity","tmp":"e1","key":"IBM","etype":"defined_term","title":"IBM",
     "scope":"document","trust":"extracted"}
    {"t":"alias","entity":"e1","surface":"International Business Machines Corporation",
     "alias_kind":"expansion","trust":"extracted"}
    {"t":"alias","entity":"e1","surface":"IBM","alias_kind":"abbrev","trust":"extracted"}
    {"t":"anchor","name":"IBM","akind":"defined_term","cite":"d7#4","span":[45,48],
     "scope":"document","surface":"IBM"}
    {"t":"cover","lane":"anchor","cites":["d7#4"]}
    {"t":"cover","lane":"entity","cites":["d7#4"]}
    {"t":"cover_empty","lane":"anchor","reason":"no definition site in this Segment"}
    {"t":"diag","code":"OW_RESOURCE_LIMIT",...}

1. **`seg` opens each unit's items**, echoing the view's `seg`, as `doc` opens the segmenter's: a
   host reads them in order and never pairs an item with a Segment by guessing.
2. **`Grounded` is `cite` plus exactly one of `span` (`[ts_a, ts_b]`) or `quote`.** The union is
   06:403's; two keys keep "span and quote together" a decode refusal rather than a case.
3. **`trust` is `Trust`'s lower-case member name**, as `owdoc-fragment/1` spells it, and is a claim
   the host clamps. Every frame here claims `extracted`: a definition site is read off the text,
   and `MAX_TRUST_BY_METHOD[heuristic]` allows it.
4. **`cover` names the blocks an item came from, per lane; `cover_empty` gives the reason when there
   are none** (GR3, 06:916-920). This Pass's lanes are `anchor` and `entity` (06:961), so every
   Segment gets two frames. Finding nothing is an answer -- `ok`, never `EMPTY_RESULT`.

`tmp` tokens are `e1`, `e2`, ... across the whole invocation, so no two units share one.
Every span is into `block.text` as the view carried it, half-open and in characters -- the
`TextSpan` the sink bounds-checks -- because a regex knows exactly where its term is and a quote
would make the host search for what the driver already found.
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

from omniweave_graph.defterm.rules import Definition, Notice, find
from omniweave_graph.view import read_segment_view

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DRIVER_ID", "LANES", "DefinedTerms"]

DRIVER_ID: Final = "derive.anchor.defterm"
LANES: Final = ("anchor", "entity")
"""06:961. The order the cover frames are written in."""
EMPTY_REASON: Final = "no definition site in this Segment"
_ETYPE: Final = "defined_term"
_TRUST: Final = "extracted"
_HEAD_WINDOW: Final = 4096


class DefinedTerms:
    """Copular, parenthetical, hereinafter and glossary definitions. Standard library only."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """Nothing to find: four regexes and a structural rule over text the host hands it."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="standard library only")

    def __init__(self, **config: Scalar) -> None:
        """No parameters: the bounds are 06's numbers, not an operator's."""
        if config:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(sorted(config))}")

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """One Segment view per unit in; its definition sites and cover out, unit by unit.

        Raises:
            DriverError: `CORRUPT_INPUT` when a view is not the Segment form of
                `owgraph-segment/1`; `TIMEOUT` when cancelled.
        """
        frames: list[dict[str, Any]] = []
        read = 0
        tmp = 0
        for done, unit in enumerate(scope.units):
            if io.cancelled():
                raise DriverError(
                    cls=FailureClass.TIMEOUT,
                    message=f"cancelled after {done} of {len(scope.units)} Segments",
                    retry_after_ms=0,
                )
            with io.blobs.open(unit.content_sha256) as handle:
                raw = handle.read()
            read += len(raw)
            view = read_segment_view(raw)
            found = find(view.members, view.heading_path)
            frames.append({"t": "seg", "seg": view.seg})
            for definition in found.definitions:
                tmp += 1
                frames += _definition_frames(definition, f"e{tmp}")
            frames += _cover_frames(found.definitions)
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
        """At least one Segment answered. Its answer may be two `cover_empty` frames."""
        return b'"t":"seg"' in ref.head(_HEAD_WINDOW)


def _definition_frames(d: Definition, tmp: str) -> Iterator[dict[str, Any]]:
    entity: dict[str, Any] = {
        "t": "entity",
        "tmp": tmp,
        "key": d.term,
        "etype": _ETYPE,
        "title": d.term,
        "scope": "document",
        "trust": _TRUST,
    }
    if d.description is not None:
        entity["description"] = d.description
    yield entity
    for alias in d.aliases:
        yield {
            "t": "alias",
            "entity": tmp,
            "surface": alias.surface,
            "alias_kind": alias.alias_kind,
            "trust": _TRUST,
        }
    yield {
        "t": "anchor",
        "name": d.term,
        "akind": "defined_term",
        "cite": d.cite,
        "span": list(d.span),
        "scope": "document",
        "surface": d.term,
    }


def _cover_frames(definitions: tuple[Definition, ...]) -> Iterator[dict[str, Any]]:
    cites = list(dict.fromkeys(d.cite for d in definitions))
    for lane in LANES:
        if cites:
            yield {"t": "cover", "lane": lane, "cites": cites}
        else:
            yield {"t": "cover_empty", "lane": lane, "reason": EMPTY_REASON}


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
