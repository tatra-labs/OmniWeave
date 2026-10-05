"""`gen_office200.py` -- `fixtures/office-200`, the 200 office documents F2 measures over.

12-performance.md section 7.2 names the fixture -- *"`fixtures/office-200` | 200 office documents |
F2's marshal question; B02/B03"* -- and section 7.1 gives it one consumer, `ow bench inproc`: wall,
peak RSS and GIL-held fraction at `max_inproc` in {1,2,4,8} against the pure-Rust path. ADR-13 D13.2
then hangs anydoc's fork tripwire on it, `rss.office200_peak_bytes`, the peak RSS of
`parse.office.anydoc`'s worker over this corpus. Nothing generated it (D196), so the tripwire was
run by hand or not at all. **D656** writes it.

## Generated, not collected

The question the corpus answers is what anydoc's eager marshal costs: `to_document()` releases the
GIL around the decode (`py.detach`, `vendor/anydoc/python/src/lib.rs:194`) and then turns the whole
`Document` into Python objects with the GIL held. That cost scales with how many Blocks, Cells and
Inlines a document has, not with what its words say, so a synthetic corpus answers it as well as a
collected one and carries no licence (13-quality.md's Q-G1 regime governs collected fixtures; a
generated one has nothing to clear). What it must get right is the SHAPE: a few large documents
among many small ones, and every container anydoc marshals -- headings, paragraphs, tables, list
items, slides, sheets of cells -- in proportions an office folder has.

## The mix, fixed rather than drawn

| format | n | | size bucket | share | docx sections | xlsx rows x 8 | pptx slides |
|---|---|---|---|---|---|---|---|
| docx | 80 | | small | 110 | 1-3 | 20-120 | 3-8 |
| xlsx | 50 | | medium | 60 | 10-30 | 500-2,000 | 15-40 |
| pptx | 40 | | large | 24 | 80-150 | 8,000-12,000 | 80-120 |
| odt, ods, odp | 8, 7, 5 | | huge | 6 | 400 | 50,000 | 300 |
| rtf, epub, csv | 4, 3, 3 | | | | | | |

A docx section is a heading, eight paragraphs and, every third section, a six-by-four table. The
ODF, RTF, EPUB and CSV documents scale the same way at a third of the size. Which document gets
which format and bucket is a pure function of its index (`_draw`), so the corpus is the same on
every machine and the same in every run.

## The regime (13-quality.md:586-589)

No `random`, `secrets`, `uuid4`, `time.time` or `datetime.now`: every choice comes from `_Stream`,
a xorshift generator seeded from blake2b of a label, and every zip entry is dated 1980-01-01 with
`create_system = 0`, as on Windows, so the bytes are the same on any OS (D653). Output lands in
`fixtures/generated/office-200/`, which is gitignored, beside `office-200.manifest`
(`sha256  relpath` per file), and `fixtures/gen/EXPECTED.sha256` pins the manifest.

    uv run python fixtures/gen/gen_office200.py                 # write the corpus
    uv run python fixtures/gen/gen_office200.py --print-sha256  # and print the manifest's pin
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final
from xml.sax.saxutils import escape

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_OUT: Final = ROOT / "fixtures" / "generated" / "office-200"
COUNT: Final = 200
ZIP_DATE: Final = (1980, 1, 1, 0, 0, 0)

MIX: Final[tuple[tuple[str, int], ...]] = (
    ("docx", 80),
    ("xlsx", 50),
    ("pptx", 40),
    ("odt", 8),
    ("ods", 7),
    ("odp", 5),
    ("rtf", 4),
    ("epub", 3),
    ("csv", 3),
)
BUCKETS: Final[tuple[tuple[str, int], ...]] = (
    ("small", 110),
    ("medium", 60),
    ("large", 24),
    ("huge", 6),
)
SIZES: Final[dict[str, dict[str, tuple[int, int]]]] = {
    "small": {"sections": (1, 3), "rows": (20, 120), "slides": (3, 8)},
    "medium": {"sections": (10, 30), "rows": (500, 2_000), "slides": (15, 40)},
    "large": {"sections": (80, 150), "rows": (8_000, 12_000), "slides": (80, 120)},
    "huge": {"sections": (400, 400), "rows": (50_000, 50_000), "slides": (300, 300)},
}
COLUMNS: Final = 8
TABLE_EVERY: Final = 3
"""A docx section carries a table when its index is the last of each group of this many."""

_WORD_TEXT: Final = """
    agreement amendment annual approval asset audit balance board budget buyer capital cash
    clause client closing committee company compliance condition consent contract cost counsel
    credit customer data date debt deed default delivery deposit director dispute document due
    duty effective employee entity equity escrow estimate event exhibit expense facility fee
    filing finance forecast fund general grant guarantee holder income indemnity insurance
    interest invoice issue lease liability licence limit loan loss management margin market
    material meeting member milestone notice obligation officer option order owner party
    payment penalty period plan policy premium price principal product profit project property
    proposal purchase quarter rate record region renewal rent report reserve review revenue risk
    royalty salary schedule section security seller service share software statement subsidiary
    supplier tax term termination territory title total transfer trust unit value vendor warranty
year"""
WORDS: Final[tuple[str, ...]] = tuple(_WORD_TEXT.split())


class _Stream:
    """xorshift64*, seeded from blake2b of a label. The corpus's only source of choice."""

    __slots__ = ("_state",)

    def __init__(self, label: str) -> None:
        seed = int.from_bytes(hashlib.blake2b(label.encode(), digest_size=8).digest(), "big")
        self._state = seed or 1

    def next(self) -> int:
        x = self._state
        x ^= (x >> 12) & 0xFFFFFFFFFFFFFFFF
        x ^= (x << 25) & 0xFFFFFFFFFFFFFFFF
        x ^= (x >> 27) & 0xFFFFFFFFFFFFFFFF
        self._state = x
        return (x * 0x2545F4914F6CDD1D) & 0xFFFFFFFFFFFFFFFF

    def below(self, n: int) -> int:
        return self.next() % n

    def between(self, low: int, high: int) -> int:
        return low + self.below(high - low + 1)

    def words(self, n: int) -> str:
        return " ".join(WORDS[self.below(len(WORDS))] for _ in range(n))

    def sentence(self) -> str:
        text = self.words(self.between(8, 18))
        return text[0].upper() + text[1:] + "."

    def paragraph(self) -> str:
        return " ".join(self.sentence() for _ in range(self.between(2, 5)))


def _draw() -> list[tuple[str, str]]:
    """`(format, bucket)` for each of the 200 indices: both multisets fixed, the pairing shuffled.

    A Fisher-Yates shuffle of each fixed list under its own `_Stream`, so the counts in `MIX` and
    `BUCKETS` hold exactly and which document is which is still a pure function of its index.
    """
    formats = [name for name, n in MIX for _ in range(n)]
    buckets = [name for name, n in BUCKETS for _ in range(n)]
    assert len(formats) == len(buckets) == COUNT  # noqa: S101 -- the tables above are the spec
    for label, items in (("formats", formats), ("buckets", buckets)):
        stream = _Stream(f"office200:{label}")
        for i in range(len(items) - 1, 0, -1):
            j = stream.below(i + 1)
            items[i], items[j] = items[j], items[i]
    return list(zip(formats, buckets, strict=True))


# =============================================================================================
# Packages
# =============================================================================================


def _zip(entries: Sequence[tuple[str, bytes]], *, stored_first: bool = False) -> bytes:
    """A zip with fixed dates and `create_system = 0`. ODF and EPUB store `mimetype` first."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, (name, data) in enumerate(entries):
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.create_system = 0  # zipfile writes 3 on POSIX, 0 on Windows (D653)
            first = stored_first and index == 0
            info.compress_type = zipfile.ZIP_STORED if first else zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


_PKG: Final = "http://schemas.openxmlformats.org/package/2006"
_DOCREL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_W: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_P: Final = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
_XML: Final = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


def _types(*overrides: tuple[str, str]) -> bytes:
    parts = "".join(
        f'<Override PartName="{name}" ContentType="application/vnd.openxmlformats-officedocument.'
        f'{kind}"/>'
        for name, kind in overrides
    )
    return (
        f'{_XML}<Types xmlns="{_PKG}/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        f"{parts}</Types>"
    ).encode()


def _rels(*targets: tuple[str, str, str]) -> bytes:
    parts = "".join(
        f'<Relationship Id="{rid}" Type="{_DOCREL}/{kind}" Target="{target}"/>'
        for rid, kind, target in targets
    )
    return f'{_XML}<Relationships xmlns="{_PKG}/relationships">{parts}</Relationships>'.encode()


def docx(stream: _Stream, sections: int) -> bytes:
    """Heading, eight paragraphs, and a six-by-four table every third section."""
    body: list[str] = []
    for n in range(sections):
        body.append(
            '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
            f"<w:r><w:t>{n + 1}. {escape(stream.words(4).title())}</w:t></w:r></w:p>"
        )
        body.extend(
            f'<w:p><w:r><w:t xml:space="preserve">{escape(stream.paragraph())}</w:t></w:r></w:p>'
            for _ in range(8)
        )
        if n % TABLE_EVERY == TABLE_EVERY - 1:
            rows = "".join(
                "<w:tr>"
                + "".join(
                    f"<w:tc><w:p><w:r><w:t>{escape(stream.words(2))}</w:t></w:r></w:p></w:tc>"
                    for _ in range(4)
                )
                + "</w:tr>"
                for _ in range(6)
            )
            body.append(f"<w:tbl>{rows}</w:tbl>")
    document = f'{_XML}<w:document xmlns:w="{_W}"><w:body>{"".join(body)}</w:body></w:document>'
    return _zip(
        [
            (
                "[Content_Types].xml",
                _types(("/word/document.xml", "wordprocessingml.document.main+xml")),
            ),
            ("_rels/.rels", _rels(("rId1", "officeDocument", "word/document.xml"))),
            ("word/document.xml", document.encode()),
        ]
    )


def _cell(stream: _Stream, ref: str, column: int) -> str:
    """Even columns are numbers, odd columns inline strings: a ledger's shape, not a word list."""
    if column % 2 == 0:
        return f'<c r="{ref}"><v>{stream.below(1_000_000) / 100:.2f}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(stream.words(2))}</t></is></c>'


def xlsx(stream: _Stream, rows: int) -> bytes:
    letters = "ABCDEFGH"
    header = "".join(
        f'<c r="{letters[c]}1" t="inlineStr"><is><t>{escape(stream.words(1).title())}</t></is></c>'
        for c in range(COLUMNS)
    )
    data = "".join(
        f'<row r="{r}">'
        + "".join(_cell(stream, f"{letters[c]}{r}", c) for c in range(COLUMNS))
        + "</row>"
        for r in range(2, rows + 2)
    )
    sheet = f'{_XML}<worksheet xmlns="{_SS}"><sheetData><row r="1">{header}</row>{data}'
    sheet += "</sheetData></worksheet>"
    workbook = (
        f'{_XML}<workbook xmlns="{_SS}" xmlns:r="{_DOCREL}"><sheets>'
        '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    return _zip(
        [
            (
                "[Content_Types].xml",
                _types(
                    ("/xl/workbook.xml", "spreadsheetml.sheet.main+xml"),
                    ("/xl/worksheets/sheet1.xml", "spreadsheetml.worksheet+xml"),
                ),
            ),
            ("_rels/.rels", _rels(("rId1", "officeDocument", "xl/workbook.xml"))),
            ("xl/workbook.xml", workbook.encode()),
            ("xl/_rels/workbook.xml.rels", _rels(("rId1", "worksheet", "worksheets/sheet1.xml"))),
            ("xl/worksheets/sheet1.xml", sheet.encode()),
        ]
    )


def pptx(stream: _Stream, slides: int) -> bytes:
    """A title and four to seven bullet lines per slide."""

    def shape(number: int, text: str, placeholder: str = "") -> str:
        ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{number}" name="Shape {number}"/><p:cNvSpPr/>'
            f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr/>"
            f"<p:txBody><a:bodyPr/><a:lstStyle/>{text}</p:txBody></p:sp>"
        )

    entries: list[tuple[str, bytes]] = []
    ids: list[str] = []
    rels: list[tuple[str, str, str]] = []
    for n in range(1, slides + 1):
        title = f"<a:p><a:r><a:t>{escape(stream.words(3).title())}</a:t></a:r></a:p>"
        bullets = "".join(
            f"<a:p><a:r><a:t>{escape(stream.sentence())}</a:t></a:r></a:p>"
            for _ in range(stream.between(4, 7))
        )
        slide = (
            f'{_XML}<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree>'
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            f"<p:grpSpPr/>{shape(2, title, 'title')}{shape(3, bullets)}"
            "</p:spTree></p:cSld></p:sld>"
        )
        entries.append((f"ppt/slides/slide{n}.xml", slide.encode()))
        ids.append(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>')
        rels.append((f"rId{n}", "slide", f"slides/slide{n}.xml"))
    presentation = (
        f'{_XML}<p:presentation xmlns:p="{_P}" xmlns:r="{_DOCREL}">'
        f"<p:sldIdLst>{''.join(ids)}</p:sldIdLst></p:presentation>"
    )
    overrides = [("/ppt/presentation.xml", "presentationml.presentation.main+xml")]
    overrides += [
        (f"/ppt/slides/slide{n}.xml", "presentationml.slide+xml") for n in range(1, slides + 1)
    ]
    return _zip(
        [
            ("[Content_Types].xml", _types(*overrides)),
            ("_rels/.rels", _rels(("rId1", "officeDocument", "ppt/presentation.xml"))),
            ("ppt/presentation.xml", presentation.encode()),
            ("ppt/_rels/presentation.xml.rels", _rels(*rels)),
            *entries,
        ]
    )


_ODF_OFFICE: Final = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_ODF_TEXT: Final = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_ODF_TABLE: Final = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
_ODF_DRAW: Final = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
_ODF_MANIFEST: Final = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"


def _odf(mimetype: str, body: str) -> bytes:
    manifest = (
        f'{_XML}<manifest:manifest xmlns:manifest="{_ODF_MANIFEST}" manifest:version="1.2">'
        f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mimetype}"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
        "</manifest:manifest>"
    )
    content = (
        f'{_XML}<office:document-content xmlns:office="{_ODF_OFFICE}" xmlns:text="{_ODF_TEXT}" '
        f'xmlns:table="{_ODF_TABLE}" xmlns:draw="{_ODF_DRAW}" office:version="1.2">'
        f"<office:body>{body}</office:body></office:document-content>"
    )
    return _zip(
        [
            ("mimetype", mimetype.encode()),
            ("META-INF/manifest.xml", manifest.encode()),
            ("content.xml", content.encode()),
        ],
        stored_first=True,
    )


def odt(stream: _Stream, sections: int) -> bytes:
    parts: list[str] = []
    for n in range(sections):
        parts.append(
            f'<text:h text:outline-level="1">{n + 1}. {escape(stream.words(4).title())}</text:h>'
        )
        parts.extend(f"<text:p>{escape(stream.paragraph())}</text:p>" for _ in range(6))
        items = "".join(
            f"<text:list-item><text:p>{escape(stream.sentence())}</text:p></text:list-item>"
            for _ in range(3)
        )
        parts.append(f"<text:list>{items}</text:list>")
    return _odf(
        "application/vnd.oasis.opendocument.text", f"<office:text>{''.join(parts)}</office:text>"
    )


def ods(stream: _Stream, rows: int) -> bytes:
    def cell(column: int) -> str:
        if column % 2 == 0:
            value = f"{stream.below(1_000_000) / 100:.2f}"
            return (
                f'<table:table-cell office:value-type="float" office:value="{value}">'
                f"<text:p>{value}</text:p></table:table-cell>"
            )
        return (
            '<table:table-cell office:value-type="string">'
            f"<text:p>{escape(stream.words(2))}</text:p></table:table-cell>"
        )

    data = "".join(
        f"<table:table-row>{''.join(cell(c) for c in range(COLUMNS))}</table:table-row>"
        for _ in range(rows)
    )
    body = (
        '<office:spreadsheet><table:table table:name="Sheet1">'
        f'<table:table-column table:number-columns-repeated="{COLUMNS}"/>{data}'
        "</table:table></office:spreadsheet>"
    )
    return _odf("application/vnd.oasis.opendocument.spreadsheet", body)


def odp(stream: _Stream, slides: int) -> bytes:
    pages = "".join(
        f'<draw:page draw:name="page{n}">'
        f"<draw:frame><draw:text-box><text:p>{escape(stream.words(3).title())}</text:p>"
        "</draw:text-box></draw:frame><draw:frame><draw:text-box>"
        + "".join(f"<text:p>{escape(stream.sentence())}</text:p>" for _ in range(5))
        + "</draw:text-box></draw:frame></draw:page>"
        for n in range(1, slides + 1)
    )
    return _odf(
        "application/vnd.oasis.opendocument.presentation",
        f"<office:presentation>{pages}</office:presentation>",
    )


def rtf(stream: _Stream, sections: int) -> bytes:
    parts = [r"{\rtf1\ansi\deff0{\fonttbl{\f0 Calibri;}}"]
    for n in range(sections):
        parts.append(rf"\pard\b {n + 1}. {stream.words(4).title()}\b0\par ")
        parts.extend(rf"\pard {stream.paragraph()}\par " for _ in range(6))
    parts.append("}")
    return "".join(parts).encode("ascii")


def epub(stream: _Stream, sections: int) -> bytes:
    chapters = max(1, sections // 4)
    entries: list[tuple[str, bytes]] = [
        ("mimetype", b"application/epub+zip"),
        (
            "META-INF/container.xml",
            (
                f'{_XML}<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
                'version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>'
            ).encode(),
        ),
    ]
    items, spine = [], []
    for c in range(1, chapters + 1):
        body = f"<h1>Chapter {c}</h1>" + "".join(
            f"<p>{escape(stream.paragraph())}</p>" for _ in range(12)
        )
        xhtml = (
            "<?xml version='1.0' encoding='utf-8'?>"
            f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter {c}</title></head>'
            f"<body>{body}</body></html>"
        )
        entries.append((f"OEBPS/c{c}.xhtml", xhtml.encode()))
        items.append(f'<item id="c{c}" href="c{c}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{c}"/>')
    opf = (
        f'{_XML}<package xmlns="http://www.idpf.org/2007/opf" version="3.0" '
        'unique-identifier="bookid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="bookid">urn:office200</dc:identifier>'
        "<dc:title>A generated book</dc:title><dc:language>en</dc:language></metadata>"
        f"<manifest>{''.join(items)}</manifest><spine>{''.join(spine)}</spine></package>"
    )
    entries.insert(2, ("OEBPS/content.opf", opf.encode()))
    return _zip(entries, stored_first=True)


def csv(stream: _Stream, rows: int) -> bytes:
    lines = [",".join(stream.words(1) for _ in range(COLUMNS))]
    lines.extend(
        ",".join(
            f"{stream.below(1_000_000) / 100:.2f}" if c % 2 == 0 else stream.words(2)
            for c in range(COLUMNS)
        )
        for _ in range(rows)
    )
    return ("\r\n".join(lines) + "\r\n").encode("ascii")


# =============================================================================================
# The corpus
# =============================================================================================

_UNIT: Final[dict[str, str]] = {
    "docx": "sections",
    "odt": "sections",
    "rtf": "sections",
    "epub": "sections",
    "xlsx": "rows",
    "ods": "rows",
    "csv": "rows",
    "pptx": "slides",
    "odp": "slides",
}
_WRITERS: Final[dict[str, Callable[[_Stream, int], bytes]]] = {
    "docx": docx,
    "xlsx": xlsx,
    "pptx": pptx,
    "odt": odt,
    "ods": ods,
    "odp": odp,
    "rtf": rtf,
    "epub": epub,
    "csv": csv,
}
_SCALED_DOWN: Final = frozenset({"odt", "ods", "odp", "rtf", "epub", "csv"})
"""The formats written at a third of their bucket's size: they are 30 of the 200 and their
decoders are not what the marshal question is about."""


@dataclass(frozen=True, slots=True)
class Document:
    """One file of the corpus: where it goes, and the inputs that make its bytes."""

    index: int
    fmt: str
    bucket: str
    size: int

    @property
    def path(self) -> str:
        return f"{self.fmt}/{self.index:03d}-{self.bucket}.{self.fmt}"

    def to_bytes(self) -> bytes:
        return _WRITERS[self.fmt](_Stream(f"office200:{self.index}"), self.size)


def documents() -> tuple[Document, ...]:
    """The 200, in index order. Each one's size is drawn from its own stream, after its kind."""
    out: list[Document] = []
    for index, (fmt, bucket) in enumerate(_draw()):
        low, high = SIZES[bucket][_UNIT[fmt]]
        size = _Stream(f"office200:size:{index}").between(low, high)
        if fmt in _SCALED_DOWN:
            size = max(1, size // 3)
        out.append(Document(index=index, fmt=fmt, bucket=bucket, size=size))
    return tuple(out)


def manifest_bytes(docs: Sequence[Document]) -> bytes:
    """`sha256  relpath` per file, in index order: what `EXPECTED.sha256` pins."""
    lines = [f"{hashlib.sha256(doc.to_bytes()).hexdigest()}  {doc.path}" for doc in docs]
    return ("\n".join(lines) + "\n").encode("ascii")


def write_corpus(dest: Path) -> tuple[Path, str]:
    """Write every file under `dest` and the manifest beside it. Returns the manifest and digest."""
    lines: list[str] = []
    for doc in documents():
        data = doc.to_bytes()
        path = dest / doc.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  {doc.path}")
    raw = ("\n".join(lines) + "\n").encode("ascii")
    manifest = dest.parent / f"{dest.name}.manifest"
    manifest.write_bytes(raw)
    return manifest, hashlib.sha256(raw).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fixtures/office-200: F2's 200 office documents")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--print-sha256", action="store_true", help="print the manifest's pin")
    args = parser.parse_args(argv)
    manifest, digest = write_corpus(args.out)
    rel = (
        manifest.resolve().relative_to(ROOT).as_posix()
        if manifest.resolve().is_relative_to(ROOT)
        else manifest.as_posix()
    )
    sys.stdout.write(f"{digest}  {rel}\n" if args.print_sha256 else f"wrote {rel}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
