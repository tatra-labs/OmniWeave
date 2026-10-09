"""`derive.entity.gazetteer` as a `derive/1` driver: the corpus's names, found in a document.

**D683.** 06 section 3.7. The wire is `derive.entity.table`'s, with one frame in front: the host
opens each unit's view with the lexicon it was handed, by CAS digest, so the artefact is read once
per worker rather than copied into every document's view.

    {"t":"lexicon","blob":"<sha256 hex>"}
    {"t":"segment","seg":"seg:9f2c1d4a77b03e51",...}
    {"t":"block","cite":"d7#41","kind":"paragraph","text":"Acme Holdings Ltd. shall pay ..."}

Per hit (`rules.find`), once per entity per Segment and then a mention per occurrence:

    {"t":"entity","tmp":"e1","key":"acme_holdings_ltd","etype":"org","title":"Acme Holdings Ltd.",
     "scope":"corpus","trust":"extracted"}
    {"t":"mention","entity":"e1","cite":"d7#41","span":[0,18],"surface":"Acme Holdings Ltd.",
     "trust":"extracted"}
    {"t":"cover","lane":"entity","cites":["d7#41"]}

**No new entity, and no alias.** The `entity` frame proposes an entity the lexicon read from the
store, which is how a Pass binds to one (06:628): the sink finds it on `(scope, etype, key)`. It
writes no alias, so nothing this Pass writes can change the lexicon it reads (D683). A view with no
lexicon frame, or an empty lexicon, is one `cover_empty` per Segment: `empty lexicon`, 06:913's.
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

from omniweave_graph.gazetteer.rules import Automaton, Lexicon, decode_lexicon, find
from omniweave_graph.view import read_segment_views

if TYPE_CHECKING:
    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

    from omniweave_graph.view import SegmentView

__all__ = ["DRIVER_ID", "EMPTY_LEXICON", "LANES", "NO_HIT_REASON", "Gazetteer"]

DRIVER_ID: Final = "derive.entity.gazetteer"
LANES: Final = ("entity",)
"""06:965."""
EMPTY_LEXICON: Final = "empty lexicon"
"""06:913's `empty_reason`, verbatim: no lexicon was built yet, or it holds no name."""
NO_HIT_REASON: Final = "no lexicon name in this Segment"
AMBIGUOUS: Final = "OW_GRAPH_QUOTE_AMBIGUOUS"
_TRUST: Final = "extracted"
_HEAD_WINDOW: Final = 4096


class Gazetteer:
    """Lexicon names as mentions of the entities that carry them. Standard library only."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """Nothing to find: an automaton over the lexicon the host hands it."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="standard library only")

    def __init__(self, **config: Scalar) -> None:
        """No parameters: the lexicon is the corpus's, built by `op.lexicon`."""
        if config:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(sorted(config))}")
        self._built: tuple[str, Lexicon, Automaton] | None = None

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """One document's Segment views per unit, after its lexicon frame; each Segment's mentions.

        Raises:
            DriverError: `CORRUPT_INPUT` when a view is not the Segment form of `owgraph-segment/1`
                or its lexicon is not `owgraph-lexicon/1`; `TIMEOUT` when cancelled.
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
            built, raw = self._lexicon(raw, io)
            for view in read_segment_views(raw):
                frames.append({"t": "seg", "seg": view.seg})
                frames += _segment_frames(view, built, minted)
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

    def _lexicon(self, raw: bytes, io: DriverIO) -> tuple[tuple[Lexicon, Automaton] | None, bytes]:
        """The view's lexicon, built once per digest per worker, and the view after its frame."""
        first, _, rest = raw.partition(b"\n")
        try:
            head = json.loads(first) if first.strip() else None
        except ValueError:
            head = None
        if not isinstance(head, dict) or head.get("t") != "lexicon":
            return None, raw
        digest = head.get("blob")
        if not isinstance(digest, str) or not digest:
            _corrupt("the lexicon frame names no blob")
        if self._built is None or self._built[0] != digest:
            with io.blobs.open(digest) as handle:
                body = handle.read()
            try:
                lexicon = decode_lexicon(body)
            except ValueError as exc:
                _corrupt(f"lexicon {digest[:12]}: {exc}")
            self._built = (digest, lexicon, Automaton(sorted(lexicon.names)))
        _digest, lexicon, automaton = self._built
        return ((lexicon, automaton) if lexicon.names else None), rest


def _segment_frames(
    view: SegmentView, built: tuple[Lexicon, Automaton] | None, minted: list[int]
) -> list[dict[str, Any]]:
    if built is None:
        return [{"t": "cover_empty", "lane": "entity", "reason": EMPTY_LEXICON}]
    lexicon, automaton = built
    out: list[dict[str, Any]] = []
    tmps: dict[tuple[str, str], str] = {}
    covered: list[str] = []
    for member in view.members:
        if not member.text:
            continue
        for hit in find(member.text, automaton):
            targets = lexicon.names[hit.name]
            for target in targets:
                identity = (target.etype, target.key)
                tmp = tmps.get(identity)
                if tmp is None:
                    minted[0] += 1
                    tmp = f"e{minted[0]}"
                    tmps[identity] = tmp
                    out.append(
                        {
                            "t": "entity",
                            "tmp": tmp,
                            "key": target.key,
                            "etype": target.etype,
                            "title": target.title,
                            "scope": "corpus",
                            "trust": _TRUST,
                        }
                    )
                out.append(
                    {
                        "t": "mention",
                        "entity": tmp,
                        "cite": member.cite,
                        "span": [hit.a, hit.b],
                        "surface": hit.surface,
                        "trust": _TRUST,
                    }
                )
            if len(targets) > 1:
                out.append(_ambiguous(member.cite, hit.name, len(targets)))
            if member.cite not in covered:
                covered.append(member.cite)
    if covered:
        out.append({"t": "cover", "lane": "entity", "cites": covered})
    else:
        out.append({"t": "cover_empty", "lane": "entity", "reason": NO_HIT_REASON})
    return out


def _ambiguous(cite: str, name: str, count: int) -> dict[str, Any]:
    return {
        "t": "diag",
        "code": AMBIGUOUS,
        "severity": "warning",
        "component": DRIVER_ID,
        "message": f"{name!r} names {count} corpus entities; each got a mention",
        "cite": cite,
        "detail": {"name": name, "entities": count},
        "fatal": False,
    }


def _corrupt(message: str) -> NoReturn:
    raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=message)
