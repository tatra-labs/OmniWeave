"""`parse.pptx.native`: compile.pptx.native's `read_back`, an ordinary `parse/1` driver. **D804.**

09-generation.md section 11: *"`read_back` ... is **an ordinary `parse/1` Driver** — an ordinary
card, an ordinary probe, an ordinary licence block, an ordinary conformance run"*, and a generated
artefact re-enters the corpus through the pipe that already exists. It reads the package `lower/`
wrote (`_walk`) and emits `owdoc-fragment/1`, held by R2 to its IL (09 section 11.1).

## Rulings

1. **Every block is a read-back's**: `method = "roundtrip"` (OUT22), `trust = "inferred"`, and
   `quote = "normalized"`, because the text was read from the artefact but is not a byte range of
   it.
2. **A slide is a page, `page_kind = "slide"`**, in the presentation's own order, sized by the
   presentation's `p:sldSz` in milli-points: an EMU is 1/12,700 of a point. Each page's
   record comes before its blocks and after the last page's, since a fragment's block names
   the page that is open.
3. **Each address and its cites ride in `x`.** The provenance part's `at` names where each
   address landed: its slide, its shape's `p:cNvPr` id, and for a `<tspan>` its line and runs
   (D803). `x.ow.el` goes on that block, and `x.ow.cites` on the same block, the canonical cites
   the part lists for that address, in its order.
4. **A package with no provenance part is not this target's.** Its addresses and cites cannot be
   placed, so the parse refuses as `CORRUPT_INPUT` rather than read a foreign `.pptx` as if it
   were one.
5. **`sniff()` is "not mine" to every stream.** 09 Q4: the routing policy does not prefer a
   target's own `read_back`, which is reached by name. A guess here would contend with
   `parse.office.anydoc` for every `.pptx` a corpus ingests. So the card declares no
   `format_tokens` either: core's table maps the media type, and a pair is a claim the
   conformance kit holds `sniff()` to (D812).
6. **A cancelled read stops at the next slide** (D812). Each slide is a loop top: the
   read checks `io.cancelled()` before it and reports progress after it, as the kit's
   contract suite asks of every driver.
"""

from __future__ import annotations

import io
import json
import tomllib
import zipfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_ports import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    FormatGuess,
    ProbeStatus,
    ProbeVerdict,
)
from pptx.oxml.ns import qn

from omniweave_target_pptx.back._walk import Lookup, Node, Place, read_slide

if TYPE_CHECKING:
    from omniweave_ports.detect import StreamHint
    from omniweave_ports.types import DriverIO, PartSelector, ProbeEnv, Scalar, UnitRef

__all__ = ["KIND_MAP", "MEDIA_TYPE", "PROVENANCE", "PptxReader", "kinds"]

MEDIA_TYPE: Final = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_TARGET: Final = Path(__file__).resolve().parent.parent
KIND_MAP: Final = _TARGET / "kind_map.toml"
PROVENANCE: Final[str] = tomllib.loads((_TARGET / "driver.toml").read_text(encoding="utf-8"))[
    "compile"
]["provenance_part"]
"""The compile card's own name for the embedded part, read where the compile reads it."""
PART: Final = "pptx/package"
EMU_PER_MPT: Final = 12.7
"""Ruling 2: an EMU is 1/12,700 of a point, so 12.7 EMU a milli-point."""
_HEAD_WINDOW: Final = 65_536
_PARSER: Final = etree.XMLParser(resolve_entities=False, no_network=True)
_PRESENTATION: Final = "ppt/presentation.xml"
_PRESENTATION_RELS: Final = "ppt/_rels/presentation.xml.rels"
_SLIDE_ID, _SLIDE_SIZE, _R_ID = qn("p:sldId"), qn("p:sldSz"), qn("r:id")
_SP_TREE: Final = f"{qn('p:cSld')}/{qn('p:spTree')}"
ACHIEVED: Final[dict[str, object]] = {
    "spatial": "none",
    "origin_span": "none",
    "text_span": False,
    "marks": False,
    "reading_order": "source",
    "sections": "outline_from_source",
    "tables": "none",
    "math": [],
    "assets": "none",
    "asset_origin": False,
    "notes": "none",
    "confidence": "none",
    "furniture": "destroyed",
    "round_trip": "structure",
    "forfeits": [],
}


def kinds() -> dict[str, str]:
    """`kind_map.toml`: construct id -> Kind, ruling 3's map from an address to its block."""
    raw = tomllib.loads(KIND_MAP.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in raw["kind"].items()}


class PptxReader:
    """A `.pptx` compile.pptx.native built, read back by its own spelling."""

    PORT: ClassVar[str] = "parse/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="lxml over the package's own parts")

    def __init__(self, **config: Scalar) -> None:
        """No configuration: the card's `[config]` accepts none."""
        del config

    def sniff(self, head: bytes, hint: StreamHint) -> tuple[FormatGuess, ...]:
        """Ruling 5: reached by name, never by content."""
        del head, hint
        return ()

    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO) -> DriverResult:
        """Read the package, place each address and cite, then `owdoc-fragment/1`."""
        del parts
        with io.blobs.open(unit.content_sha256) as handle:
            raw = handle.read()
        members = _members(raw)
        provenance = members.get(PROVENANCE)
        if provenance is None:
            raise DriverError(
                cls=FailureClass.CORRUPT_INPUT,
                message=f"no {PROVENANCE}: this .pptx is not one compile.pptx.native built",
            )
        embedded = json.loads(provenance)
        lookup = Lookup(embedded.get("els", {}), kinds())
        at: Mapping[str, Mapping[str, Any]] = embedded.get("at", {})
        presentation = _xml(members, _PRESENTATION)
        slides = _slides(members, presentation)
        roots: list[Node] = []
        for page, name in enumerate(slides):
            _stop_if_cancelled(io)
            tree = _xml(members, name).find(_SP_TREE)
            section, *notes = read_slide(tree, page, _located(at, page + 1), lookup)
            section.el = next((el for el, p in at.items() if p == {"slide": page + 1}), None)
            roots += [section, *notes]
            io.progress(done=page + 1, total=len(slides))
        _stop_if_cancelled(io)
        _cite(roots, embedded.get("cites", []))
        body = _records(roots)
        width, height = _size(presentation)
        records = [
            {
                "t": "doc",
                "format": "pptx",
                "media_type": MEDIA_TYPE,
                "page_count": len(slides),
                "achieved": ACHIEVED,
            },
            {
                "t": "part",
                "path": PART,
                "sha256": unit.content_sha256,
                "byte_len": len(raw),
                "retain": False,
            },
            *_paged(body, len(slides), width, height),
            {
                "t": "end",
                "status": "ok",
                "page_stats": {
                    str(page): {"blocks": sum(1 for b in body if b["page"] == page)}
                    for page in range(len(slides))
                },
            },
        ]
        payload = "".join(
            json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
            for record in records
        ).encode("utf-8")
        return DriverResult(
            outcome="ok",
            produced=(ArtifactRef.of("doc_fragment", payload, io),),
            metrics=DriverMetrics(bytes_read=len(raw)),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        return b'"t":"block"' in ref.head(_HEAD_WINDOW)


def _stop_if_cancelled(io: DriverIO) -> None:
    """Ruling 6: a loop top."""
    if io.cancelled():
        raise DriverError(cls=FailureClass.TIMEOUT, message="cancelled", retry_after_ms=0)


def _members(raw: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            return {info.filename: zf.read(info) for info in zf.infolist()}
    except zipfile.BadZipFile as exc:
        raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"not a package: {exc}") from None


def _xml(members: Mapping[str, bytes], name: str) -> Any:
    data = members.get(name)
    if data is None:
        raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"no {name} in the package")
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"{name}: {exc}") from None


def _slides(members: Mapping[str, bytes], presentation: Any) -> list[str]:
    """Ruling 2: each slide's part, in the presentation's `p:sldIdLst` order."""
    rels = _xml(members, _PRESENTATION_RELS)
    targets = {r.get("Id"): r.get("Target") for r in rels}
    return [f"ppt/{targets[s.get(_R_ID)]}" for s in presentation.iter(_SLIDE_ID)]


def _size(presentation: Any) -> tuple[int, int]:
    """Ruling 2: the slide size in milli-points."""
    size = presentation.find(_SLIDE_SIZE)
    return (
        round(int(size.get("cx")) / EMU_PER_MPT),
        round(int(size.get("cy")) / EMU_PER_MPT),
    )


def _located(at: Mapping[str, Mapping[str, Any]], slide: int) -> dict[int, list[Place]]:
    """Ruling 3: each address that landed in `slide`, by its shape's id."""
    out: dict[int, list[Place]] = {}
    for el, place in at.items():
        if place.get("slide") != slide or "shape" not in place:
            continue
        runs = place.get("runs", [0, 0])
        out.setdefault(int(place["shape"]), []).append(
            Place(
                el=el,
                line=place.get("line"),
                runs=(int(runs[0]), int(runs[1])),
                preserve=bool(place.get("preserve", False)),
            )
        )
    return out


def _cite(roots: list[Node], rows: list[Mapping[str, Any]]) -> None:
    """Ruling 3: each address's cites, in the part's order."""
    cites: dict[str, list[str]] = {}
    for row in rows:
        cites.setdefault(str(row["el"]), []).append(str(row["cite"]))
    for root in roots:
        for node in root.walk():
            if node.el is not None:
                node.cites = cites.get(node.el, [])


def _records(roots: list[Node]) -> list[dict[str, Any]]:
    """Each slide's blocks in order, every `tmp` assigned first."""
    order = [n for root in roots for n in root.walk()]
    tmps = {id(node): f"b{n}" for n, node in enumerate(order, 1)}
    out = []
    for node in order:
        record: dict[str, Any] = {
            "t": "block",
            "tmp": tmps[id(node)],
            "parent": None if node.parent is None else tmps[id(node.parent)],
            "page": node.page,
            "kind": node.kind,
            "layer": node.layer,
            "text": node.text,
            "quote": "normalized",
            "trust": "inferred",
            "method": "roundtrip",
            "os": {"k": "none"},
            "quad": None,
            "marks": [],
            "payload": None,
        }
        x: dict[str, Any] = {}
        if node.el is not None:
            x["x.ow.el"] = node.el
            if node.cites:
                x["x.ow.cites"] = node.cites
        if x:
            record["x"] = x
        out.append(record)
    return out


def _paged(
    body: list[dict[str, Any]], count: int, width: int, height: int
) -> Iterator[dict[str, Any]]:
    """Ruling 2: each page's record, then its blocks, which name the page that is open."""
    for page in range(count):
        yield _page_record(page, width, height)
        yield from (b for b in body if b["page"] == page)


def _page_record(page: int, width: int, height: int) -> dict[str, Any]:
    """Ruling 2: one `slide` page, its size and no quad, since no geometry is reported."""
    return {
        "t": "page",
        "page": page,
        "page_kind": "slide",
        "w_mpt": width,
        "h_mpt": height,
        "quad_origin": None,
        "quad_unit": None,
        "quad_dpi": None,
        "rotation": 0,
        "method": "roundtrip",
    }
