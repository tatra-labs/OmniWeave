"""`parse.docx.native`: compile.docx.native's `read_back`, an ordinary `parse/1` driver. **D786.**

09-generation.md section 11: *"`read_back` ... is **an ordinary `parse/1` Driver** — an ordinary
card, an ordinary probe, an ordinary licence block, an ordinary conformance run"*, and a generated
artefact re-enters the corpus through the pipe that already exists. It reads the package `lower/`
wrote (`_walk`) and emits `owdoc-fragment/1`.

## Rulings

1. **Every block is a read-back's**: `method = "roundtrip"` (OUT22), `trust = "inferred"`, the
   ceiling `MAX_TRUST_BY_METHOD` gives the method, and `quote = "normalized"`, because the text
   was read from the artefact but is not a byte range of it.
2. **Each address and its cites ride in `x`** (D785). `x.ow.el` goes on the block `_walk` ruling 4
   places it on, and `x.ow.cites` on the same block, the canonical cites the provenance part
   lists for that address, in its order.
3. **A note is a `Layer.NOTE` block and its reference a `note_ref` mark.** The mark is zero-width
   where the reference stands in the paragraph's text (03:381), and the fragment decoder makes
   it the `NOTE_REF` relationship to the body.
4. **A package with no provenance part is not this target's.** Its addresses and cites cannot be
   placed, so the parse refuses as `CORRUPT_INPUT` rather than read a foreign `.docx` as if it
   were one.
5. **`sniff()` is "not mine" to every stream.** 09 Q4: the routing policy does not prefer a
   target's own `read_back`, which is reached by name. A guess here would contend with
   `parse.office.anydoc` for every `.docx` a corpus ingests.
"""

from __future__ import annotations

import io
import json
import tomllib
import zipfile
from collections.abc import Mapping
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

from omniweave_target_docx.read._walk import Node, Notes, read_body, read_notes

if TYPE_CHECKING:
    from omniweave_ports.detect import StreamHint
    from omniweave_ports.types import DriverIO, PartSelector, ProbeEnv, Scalar, UnitRef

__all__ = ["KIND_MAP", "MEDIA_TYPE", "PROVENANCE", "DocxReader", "kinds"]

MEDIA_TYPE: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TARGET: Final = Path(__file__).resolve().parent.parent
KIND_MAP: Final = _TARGET / "kind_map.toml"
PROVENANCE: Final[str] = tomllib.loads((_TARGET / "driver.toml").read_text(encoding="utf-8"))[
    "compile"
]["provenance_part"]
"""The compile card's own name for the embedded part, read where the compile reads it."""
PART: Final = "docx/package"
_PAGE: Final = 0
_HEAD_WINDOW: Final = 65_536
_PARSER: Final = etree.XMLParser(resolve_entities=False, no_network=True)
_NOTES: Final = (("footnote", "word/footnotes.xml"), ("endnote", "word/endnotes.xml"))
ACHIEVED: Final[dict[str, object]] = {
    "spatial": "none",
    "origin_span": "none",
    "text_span": False,
    "marks": False,
    "reading_order": "source",
    "math": [],
    "assets": "none",
    "asset_origin": False,
    "confidence": "none",
    "furniture": "destroyed",
    "round_trip": "structure",
    "forfeits": [],
}


def kinds() -> dict[str, str]:
    """`kind_map.toml`: construct id -> Kind, ruling 4's map from an address to its block."""
    raw = tomllib.loads(KIND_MAP.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in raw["kind"].items()}


class DocxReader:
    """A `.docx` compile.docx.native built, read back by its own spelling."""

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
                message=f"no {PROVENANCE}: this .docx is not one compile.docx.native built",
            )
        embedded = json.loads(provenance)
        sections = read_body(
            _xml(members, "word/document.xml"), _xml(members, "word/numbering.xml")
        )
        notes = Notes()
        for kind, name in _NOTES:
            read_notes(_xml(members, name), kind, notes)
        _place(sections, notes, embedded, kinds())
        if io.cancelled():
            raise DriverError(cls=FailureClass.TIMEOUT, message="cancelled", retry_after_ms=0)
        body = _records(sections, notes)
        io.progress(done=len(sections), total=len(sections))
        records = [
            {
                "t": "doc",
                "format": "docx",
                "media_type": MEDIA_TYPE,
                "page_count": 1,
                "achieved": _achieved(sections, notes),
            },
            {
                "t": "part",
                "path": PART,
                "sha256": unit.content_sha256,
                "byte_len": len(raw),
                "retain": False,
            },
            _page_record(),
            *body,
            {"t": "end", "status": "ok", "page_stats": {str(_PAGE): {"blocks": len(body)}}},
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


def _members(raw: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            return {info.filename: zf.read(info) for info in zf.infolist()}
    except zipfile.BadZipFile as exc:
        raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"not a package: {exc}") from None


def _xml(members: Mapping[str, bytes], name: str) -> Any | None:
    data = members.get(name)
    if data is None:
        return None
    try:
        return etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError as exc:
        raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=f"{name}: {exc}") from None


def _place(
    sections: list[Node], notes: Notes, embedded: Mapping[str, Any], kind_map: Mapping[str, str]
) -> None:
    """Rulings 2 of this module and 4 of `_walk`: each address on its block, with its cites."""
    constructs: Mapping[str, str] = embedded.get("els", {})
    cites: dict[str, list[str]] = {}
    for row in embedded.get("cites", []):
        cites.setdefault(str(row["el"]), []).append(str(row["cite"]))
    roots = [*sections, *notes.by_id.values()]
    for root in roots:
        for node in root.walk():
            for el in node.starts:
                want = kind_map.get(constructs.get(el, ""))
                target: Node | None = node
                while target is not None and target.kind != want:
                    target = target.parent
                if want is not None and target is not None and target.el is None:
                    target.el = el
                    target.cites = cites.get(el, [])


def _records(sections: list[Node], notes: Notes) -> list[dict[str, Any]]:
    """The body's blocks in order, then the notes; every `tmp` assigned first, so a reference
    can name a note body defined after it (ruling 3)."""
    order = [n for root in sections for n in root.walk()]
    note_roots = list(notes.by_id.values())
    order += [n for root in note_roots for n in root.walk()]
    tmps = {id(node): f"b{n}" for n, node in enumerate(order, 1)}
    by_note = {key: tmps[id(node)] for key, node in notes.by_id.items()}
    labels = {key: str(n) for n, key in enumerate(notes.by_id, 1)}
    out = []
    for node in order:
        record: dict[str, Any] = {
            "t": "block",
            "tmp": tmps[id(node)],
            "parent": None if node.parent is None else tmps[id(node.parent)],
            "page": _PAGE,
            "kind": node.kind,
            "layer": node.layer,
            "text": node.joined(),
            "quote": "normalized",
            "trust": "inferred",
            "method": "roundtrip",
            "os": {"k": "none"},
            "quad": None,
            "marks": [
                {
                    "kind": "note_ref",
                    "a": at,
                    "b": at,
                    "label": labels.get((kind, number), number),
                    "target_tmp": by_note[kind, number],
                }
                for at, kind, number in node.refs
                if (kind, number) in by_note
            ],
            "payload": node.payload,
        }
        if node.cell is not None:
            record["cell"] = node.cell
        x: dict[str, Any] = {}
        if node.el is not None:
            x["x.ow.el"] = node.el
            if node.cites:
                x["x.ow.cites"] = node.cites
        if x:
            record["x"] = x
        out.append(record)
    return out


def _achieved(sections: list[Node], notes: Notes) -> dict[str, object]:
    nodes = [n for root in sections for n in root.walk()]
    tables = [n for n in nodes if n.kind == "table_cell"]
    spans = any(
        n.cell is not None and (n.cell["row_span"] > 1 or n.cell["col_span"] > 1) for n in tables
    )
    return {
        **ACHIEVED,
        "sections": "outline_from_source" if any(n.kind == "heading" for n in nodes) else "none",
        "tables": ("cells_with_spans" if spans else "cells") if tables else "none",
        "notes": "linked" if notes.by_id else "none",
    }


def _page_record() -> dict[str, Any]:
    """One `stream` page: a flow document has no page box."""
    return {
        "t": "page",
        "page": _PAGE,
        "page_kind": "stream",
        "w_mpt": None,
        "h_mpt": None,
        "quad_origin": None,
        "quad_unit": None,
        "quad_dpi": None,
        "rotation": 0,
        "method": "roundtrip",
    }
