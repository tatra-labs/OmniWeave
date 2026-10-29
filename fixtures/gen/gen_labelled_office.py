#!/usr/bin/env python3
"""Generate the labelled office corpus: ordinary documents, and their structure references.

`gen_office_fixtures.py` holds a different principle, stated in its own third reason: *"A fixture
must be a CASE, not a document."* Its sixteen files each exist to make one thing the driver does
observable, and a seventeenth ordinary document would dilute that on purpose. This script holds
the documents, for the one reason that generator's principle cannot serve.

**`structure_f1` counts documents.** 13-quality.md:1097 macro-averages it *"over documents then
over slices"* and :1088 admits a slice only at `min_slice_n = 30`, so the floor over `office/*`
computes nothing until one slice holds thirty labelled documents. A user ruling of 2026-10-28
settled that the slice is `office/labelled`, one per family; it held ten, and these are the rest.
Nothing here is a case. Each file is a plain document with a plain structure, and the population
is the point.

## One declaration, two files

Every document below is an `Outline`: a tuple of rows, each naming the `kind`, the `parent_kind`
and the `text` that `omniweave.structure/1` asks for (`structure` ruling 2). The bytes and the
`.structure.jsonl` reference are both WRITTEN FROM THAT ONE DECLARATION, by a writer per format,
so the reference is ground truth by construction rather than a reading of the bytes somebody took
afterwards. A reference drafted from bytes can be wrong about them; a reference and the bytes
generated from the same outline can only disagree if a writer is wrong, and `tools/label_review.py`
reads the committed bytes back with its own readers to say so.

The rows are the text-bearing Blocks and nothing else, which is `structure` ruling 6: a `table`, a
`list` and a `footnote` carry no text of their own, and the row for the text inside one carries it
as `parent_kind`. So a cell is `("paragraph", "table_cell", ...)` and a list entry is
`("paragraph", "list_item", ...)`, exactly as the ten committed references spell them.

`checked` is absent from every row. D913's ruling stands -- Claude drafts, the user verifies -- and
a reference signs whole (`structure` ruling 3), through `tools/label_review.py --page`.

Usage:

    uv run python fixtures/gen/gen_labelled_office.py
    uv run python fixtures/gen/gen_labelled_office.py --out <dir>   # default: the office package

This script writes no digest manifest. `EXPECTED.sha256` belongs to `gen_office_fixtures.py`,
which owns that directory's pins, and `omniweave_conform.harness.NOT_INPUTS` names exactly that
one file, so a second manifest beside it would arrive at the conformance harness as a document.
The pin for every file here is the `sha256` in its own sidecar, which Q-G1 checks against the
bytes on every run, and a test holds each sidecar and each reference to this script's output.

Specified in 13-quality.md sections 4.4, 8.1 and 8.3; the slice ruling is D1002.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "packages" / "omniweave-office" / "fixtures"
GENERATOR = "fixtures/gen/gen_labelled_office.py"
ZIP_DATE = (2026, 1, 1, 0, 0, 0)
XML: Final = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
SCHEMA: Final = "omniweave.structure/1"

W: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ODF_OFFICE: Final = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
ODF_TEXT: Final = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
ODF_TABLE: Final = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
ODF_MANIFEST: Final = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
ODF_DRAW: Final = "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
SS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
A: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
P: Final = "http://schemas.openxmlformats.org/presentationml/2006/main"
XHTML: Final = "http://www.w3.org/1999/xhtml"
OPF: Final = "http://www.idpf.org/2007/opf"
DC: Final = "http://purl.org/dc/elements/1.1/"


@dataclass(frozen=True, slots=True)
class Row:
    """One text-bearing Block, as `omniweave.structure/1` asks for it (`structure` ruling 2)."""

    kind: str
    parent_kind: str
    text: str
    layer: str = "body"


@dataclass(frozen=True, slots=True)
class Outline:
    """One document: its format, what it is for a reader, its rows, and a table's width.

    `cols` chunks a run of `table_cell` rows into table rows. A document with no table leaves it
    at zero, and a writer that is handed cells without one is a bug this says out loud.
    """

    fmt: str
    purpose: str
    rows: tuple[Row, ...]
    cols: int = 0


def esc(text: str) -> str:
    """The three characters that may not sit in XML character data, and nothing else."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def zip_bytes(entries: list[tuple[str, bytes]], *, mimetype: str | None = None) -> bytes:
    """A ZIP whose bytes depend only on `entries`. Stored, fixed dates, no extra fields.

    `mimetype` is written first and uncompressed when given, which is what ODF 1.2 and EPUB 3
    both require of their package's first member.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        ordered = list(entries)
        if mimetype is not None:
            ordered.insert(0, ("mimetype", mimetype.encode()))
        for name, data in ordered:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.create_system = 0  # as on Windows, on any OS (D653)
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, data)
    return buffer.getvalue()


def _runs(rows: tuple[Row, ...]) -> list[tuple[str, list[Row]]]:
    """The rows grouped into runs by `parent_kind`, in order.

    A writer needs the run rather than the row: consecutive `list_item` rows are one list and
    consecutive `table_cell` rows are one table, and a per-row writer would emit a list per item.
    """
    out: list[tuple[str, list[Row]]] = []
    for row in rows:
        if out and out[-1][0] == row.parent_kind and row.parent_kind in {"list_item", "table_cell"}:
            out[-1][1].append(row)
        else:
            out.append((row.parent_kind, [row]))
    return out


def _chunks(cells: list[Row], cols: int) -> list[list[Row]]:
    if cols < 1:
        message = "a run of table_cell rows needs an Outline.cols to chunk it into table rows"
        raise ValueError(message)
    return [cells[at : at + cols] for at in range(0, len(cells), cols)]


# ---------------------------------------------------------------------------
# the writers -- one per format, each honouring the kinds that format spells
# ---------------------------------------------------------------------------


def as_odt(outline: Outline) -> bytes:
    """An ODF text document. Headings are `text:h`, lists `text:list`, tables `table:table`."""
    body = []
    for parent, run in _runs(outline.rows):
        if parent == "list_item":
            items = "".join(
                f"<text:list-item><text:p>{esc(r.text)}</text:p></text:list-item>" for r in run
            )
            body.append(f"<text:list>{items}</text:list>")
        elif parent == "table_cell":
            body.append(_odf_table(run, outline.cols))
        else:
            for row in run:
                if row.kind == "heading":
                    body.append(f'<text:h text:outline-level="1">{esc(row.text)}</text:h>')
                else:
                    body.append(f"<text:p>{esc(row.text)}</text:p>")
    return _odf("odt", "<office:text>" + "".join(body) + "</office:text>")


def _odf(fmt: str, body: str) -> bytes:
    """An ODF package: `mimetype` first and stored, a manifest, and one `content.xml`.

    One package shape serves the three ODF bodies, exactly as `gen_office_fixtures.py`'s own
    `odf()` does: what differs between a text document, a spreadsheet and a presentation is the
    body element and the media type, and nothing else.
    """
    mimetype = MEDIA_TYPES[fmt]
    content = (
        XML + f'<office:document-content xmlns:office="{ODF_OFFICE}" xmlns:text="{ODF_TEXT}" '
        f'xmlns:table="{ODF_TABLE}" xmlns:draw="{ODF_DRAW}" office:version="1.2">'
        f"<office:body>{body}</office:body></office:document-content>"
    )
    manifest = (
        XML + f'<manifest:manifest xmlns:manifest="{ODF_MANIFEST}" manifest:version="1.2">'
        f'<manifest:file-entry manifest:full-path="/" manifest:media-type="{mimetype}"/>'
        '<manifest:file-entry manifest:full-path="content.xml" '
        'manifest:media-type="text/xml"/></manifest:manifest>'
    )
    return zip_bytes(
        [("META-INF/manifest.xml", manifest.encode()), ("content.xml", content.encode())],
        mimetype=mimetype,
    )


def _odf_table(run: list[Row], cols: int) -> str:
    """One `table:table` from a run of cells, chunked into rows by `cols`."""
    rows = "".join(
        "<table:table-row>"
        + "".join(
            '<table:table-cell office:value-type="string">'
            f"<text:p>{esc(cell.text)}</text:p></table:table-cell>"
            for cell in chunk
        )
        + "</table:table-row>"
        for chunk in _chunks(run, cols)
    )
    return (
        '<table:table table:name="Table1">'
        f'<table:table-column table:number-columns-repeated="{cols}"/>{rows}</table:table>'
    )


def as_ods(outline: Outline) -> bytes:
    """An ODF spreadsheet. Every row is a cell, which is what a sheet carries."""
    tables = "".join(_odf_table(run, outline.cols) for _parent, run in _runs(outline.rows))
    return _odf("ods", f"<office:spreadsheet>{tables}</office:spreadsheet>")


def as_odp(outline: Outline) -> bytes:
    """An ODF presentation: one `draw:page`, one `draw:frame` per row.

    Slide text arrives through a text box, so an ODF presentation has no title placeholder and
    every row is a `paragraph` under the document, which is how `deck.odp`'s own reference spells
    its two rows.
    """
    frames = "".join(
        f"<draw:frame><draw:text-box><text:p>{esc(row.text)}</text:p></draw:text-box></draw:frame>"
        for row in outline.rows
    )
    page = f'<draw:page draw:name="page1">{frames}</draw:page>'
    return _odf("odp", f"<office:presentation>{page}</office:presentation>")


def _a1(column: int, row: int) -> str:
    """A spreadsheet cell's A1 reference."""
    name = ""
    while True:
        column, rest = divmod(column, 26)
        name = chr(ord("A") + rest) + name
        if column == 0:
            break
        column -= 1
    return f"{name}{row}"


def _rels(*entries: str) -> bytes:
    return (
        XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006'
        '/relationships">' + "".join(entries) + "</Relationships>"
    ).encode()


def _rel(rid: str, kind: str, target: str) -> str:
    return f'<Relationship Id="{rid}" Type="{R}/{kind}" Target="{target}"/>'


def _types(overrides: str) -> bytes:
    return (
        XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package'
        '.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        f"{overrides}</Types>"
    ).encode()


def as_xlsx(outline: Outline) -> bytes:
    """A SpreadsheetML workbook of one sheet.

    Every cell is an `inlineStr`, so the workbook needs no shared-string part and the bytes spell
    what the reference row spells, which is what makes `tools/label_review.py` able to confirm it.
    """
    cells = [row for _parent, run in _runs(outline.rows) for row in run]
    sheet_rows = "".join(
        f'<row r="{at}">'
        + "".join(
            f'<c r="{_a1(column, at)}" t="inlineStr"><is><t>{esc(cell.text)}</t></is></c>'
            for column, cell in enumerate(chunk)
        )
        + "</row>"
        for at, chunk in enumerate(_chunks(cells, outline.cols), start=1)
    )
    sheet = XML + f'<worksheet xmlns="{SS}"><sheetData>{sheet_rows}</sheetData></worksheet>'
    workbook = (
        XML + f'<workbook xmlns="{SS}" xmlns:r="{R}"><sheets>'
        '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    overrides = (
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats'
        '-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName='
        '"/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats'
        '-officedocument.spreadsheetml.worksheet+xml"/>'
    )
    return zip_bytes(
        [
            ("[Content_Types].xml", _types(overrides)),
            ("_rels/.rels", _rels(_rel("rId1", "officeDocument", "xl/workbook.xml"))),
            ("xl/workbook.xml", workbook.encode()),
            (
                "xl/_rels/workbook.xml.rels",
                _rels(_rel("rId1", "worksheet", "worksheets/sheet1.xml")),
            ),
            ("xl/worksheets/sheet1.xml", sheet.encode()),
        ]
    )


def _shape(name: str, texts: list[str], placeholder: str = "") -> str:
    runs = "".join(f"<a:p><a:r><a:t>{esc(text)}</a:t></a:r></a:p>" for text in texts)
    body = f"<p:txBody><a:bodyPr/><a:lstStyle/>{runs}</p:txBody>"
    ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="{name}"/><p:cNvSpPr/>'
        f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr/>{body}</p:sp>"
    )


_TREE: Final = (
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
)


def as_pptx(outline: Outline) -> bytes:
    """A PresentationML deck of one slide.

    A `title` row is the title placeholder and a `note`-layer row the notes slide, which is the
    part `layer = "note"` names. `deck.pptx`'s own reference is the same four shapes.
    """
    titles = [row.text for row in outline.rows if row.kind == "title"]
    notes = [row.text for row in outline.rows if row.layer == "note"]
    bullets = [row.text for row in outline.rows if row.kind != "title" and row.layer != "note"]
    shapes = _TREE
    if titles:
        shapes += _shape("Title 1", titles, "title")
    if bullets:
        shapes += _shape("Content 2", bullets)
    slide = (
        XML + f'<p:sld xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>'
        f"{shapes}</p:spTree></p:cSld></p:sld>"
    )
    presentation = (
        XML + f'<p:presentation xmlns:p="{P}" xmlns:r="{R}">'
        '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst></p:presentation>'
    )
    overrides = (
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd'
        '.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slides/slide1.xml" ContentType="application/vnd'
        '.openxmlformats-officedocument.presentationml.slide+xml"/>'
    )
    entries = [
        ("_rels/.rels", _rels(_rel("rId1", "officeDocument", "ppt/presentation.xml"))),
        ("ppt/presentation.xml", presentation.encode()),
        ("ppt/_rels/presentation.xml.rels", _rels(_rel("rId2", "slide", "slides/slide1.xml"))),
        ("ppt/slides/slide1.xml", slide.encode()),
    ]
    if notes:
        overrides += (
            '<Override PartName="/ppt/notesSlides/notesSlide1.xml" ContentType="application/vnd'
            '.openxmlformats-officedocument.presentationml.notesSlide+xml"/>'
        )
        note_part = (
            XML
            + f'<p:notes xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree>{_TREE}'
            + _shape("Notes 1", notes, "body")
            + "</p:spTree></p:cSld></p:notes>"
        )
        entries += [
            (
                "ppt/slides/_rels/slide1.xml.rels",
                _rels(_rel("rId1", "notesSlide", "../notesSlides/notesSlide1.xml")),
            ),
            ("ppt/notesSlides/notesSlide1.xml", note_part.encode()),
        ]
    entries.insert(0, ("[Content_Types].xml", _types(overrides)))
    return zip_bytes(entries)


def as_docx(outline: Outline) -> bytes:
    """A WordprocessingML document. Headings carry `w:outlineLvl`, list entries `w:numPr`."""
    body: list[str] = []
    notes: list[str] = []
    for parent, run in _runs(outline.rows):
        if parent == "list_item":
            body += [
                '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>'
                f"<w:r><w:t>{esc(row.text)}</w:t></w:r></w:p>"
                for row in run
            ]
        elif parent == "table_cell":
            grid = "<w:tblGrid>" + "<w:gridCol/>" * outline.cols + "</w:tblGrid>"
            trs = "".join(
                "<w:tr>"
                + "".join(
                    f"<w:tc><w:p><w:r><w:t>{esc(cell.text)}</w:t></w:r></w:p></w:tc>"
                    for cell in chunk
                )
                + "</w:tr>"
                for chunk in _chunks(run, outline.cols)
            )
            body.append(f"<w:tbl><w:tblPr/>{grid}{trs}</w:tbl>")
        elif parent == "footnote":
            for at, row in enumerate(run, start=2):
                notes.append(
                    f'<w:footnote w:id="{at}"><w:p><w:r><w:t>{esc(row.text)}</w:t>'
                    "</w:r></w:p></w:footnote>"
                )
                body.append(f'<w:p><w:r><w:footnoteReference w:id="{at}"/></w:r></w:p>')
        else:
            for row in run:
                level = '<w:pPr><w:outlineLvl w:val="0"/></w:pPr>' if row.kind == "heading" else ""
                body.append(f"<w:p>{level}<w:r><w:t>{esc(row.text)}</w:t></w:r></w:p>")
    document = (
        XML
        + f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>'
        + "".join(body)
        + "</w:body></w:document>"
    )
    numbering = (
        XML + f'<w:numbering xmlns:w="{W}">'
        '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0">'
        '<w:numFmt w:val="bullet"/><w:lvlText w:val="-"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
    )
    links = [
        f'<Relationship Id="rId5" Type="{R}/numbering" Target="numbering.xml"/>',
    ]
    entries = [
        (
            "[Content_Types].xml",
            (
                XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package'
                '.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/vnd'
                '.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ).encode(),
        ),
        (
            "_rels/.rels",
            (
                XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006'
                f'/relationships"><Relationship Id="rId1" Type="{R}/officeDocument" '
                'Target="word/document.xml"/></Relationships>'
            ).encode(),
        ),
        ("word/document.xml", document.encode()),
        ("word/numbering.xml", numbering.encode()),
    ]
    if notes:
        links.append(f'<Relationship Id="rId4" Type="{R}/footnotes" Target="footnotes.xml"/>')
        entries.append(
            (
                "word/footnotes.xml",
                (XML + f'<w:footnotes xmlns:w="{W}">' + "".join(notes) + "</w:footnotes>").encode(),
            )
        )
    entries.insert(
        3,
        (
            "word/_rels/document.xml.rels",
            (
                XML + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006'
                '/relationships">' + "".join(sorted(links)) + "</Relationships>"
            ).encode(),
        ),
    )
    return zip_bytes(entries)


def as_epub(outline: Outline) -> bytes:
    """An EPUB 3 package of one XHTML chapter. The `title` row is the package's `dc:title`."""
    title = next((row.text for row in outline.rows if row.kind == "title"), "Untitled")
    body = []
    for parent, run in _runs(outline.rows):
        if parent == "list_item":
            body.append("<ul>" + "".join(f"<li>{esc(r.text)}</li>" for r in run) + "</ul>")
        elif parent == "blockquote":
            body.append(
                "<blockquote>" + "".join(f"<p>{esc(r.text)}</p>" for r in run) + "</blockquote>"
            )
        else:
            for row in run:
                if row.kind == "title":
                    continue
                if row.kind == "heading":
                    body.append(f"<h1>{esc(row.text)}</h1>")
                elif row.kind == "code":
                    body.append(f"<pre><code>{esc(row.text)}</code></pre>")
                elif row.kind == "rule":
                    body.append("<hr/>")
                else:
                    body.append(f"<p>{esc(row.text)}</p>")
    chapter = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<html xmlns="{XHTML}"><head>'
        f"<title>{esc(title)}</title></head><body>" + "".join(body) + "</body></html>"
    )
    opf = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<package xmlns="{OPF}" version="3.0" '
        f'unique-identifier="id"><metadata xmlns:dc="{DC}">'
        f'<dc:identifier id="id">urn:uuid:{hashlib.sha256(title.encode()).hexdigest()[:32]}'
        f"</dc:identifier><dc:title>{esc(title)}</dc:title><dc:language>en</dc:language>"
        "</metadata><manifest>"
        '<item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/>'
        '</manifest><spine><itemref idref="c1"/></spine></package>'
    )
    container = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
        '<rootfiles><rootfile full-path="content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    return zip_bytes(
        [
            ("META-INF/container.xml", container.encode()),
            ("content.opf", opf.encode()),
            ("chapter.xhtml", chapter.encode()),
        ],
        mimetype="application/epub+zip",
    )


def _rtf(text: str) -> str:
    """RTF's three control characters, escaped. No row here needs a non-ASCII escape."""
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def as_rtf(outline: Outline) -> bytes:
    """An RTF document. The one non-container text format, so every row is a `\\par` paragraph."""
    text = "".join("\\pard " + _rtf(row.text) + "\\par\n" for row in outline.rows)
    return ("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Helvetica;}}\n" + text + "}\n").encode("ascii")


def as_csv(outline: Outline) -> bytes:
    """A CSV. Every row is a cell, chunked into records by `cols`, quoted by the csv module."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for chunk in _chunks(list(outline.rows), outline.cols):
        writer.writerow([cell.text for cell in chunk])
    return buffer.getvalue().encode("utf-8")


WRITERS: Final = {
    "odt": as_odt,
    "ods": as_ods,
    "odp": as_odp,
    "docx": as_docx,
    "xlsx": as_xlsx,
    "pptx": as_pptx,
    "epub": as_epub,
    "rtf": as_rtf,
    "csv": as_csv,
}

MEDIA_TYPES: Final = {
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "epub": "application/epub+zip",
    "rtf": "application/rtf",
    "csv": "text/csv",
}


# ---------------------------------------------------------------------------
# the corpus
# ---------------------------------------------------------------------------

OUTLINES: Final[dict[str, Outline]] = {
    "minutes.odt": Outline(
        "odt",
        "ordinary minutes: a heading, two paragraphs and a three-item list",
        (
            Row("heading", "document", "Minutes of the weekly review"),
            Row("paragraph", "document", "Present: three of four members."),
            Row("paragraph", "document", "The previous minutes were accepted without change."),
            Row("paragraph", "list_item", "the index rebuild finished on Tuesday"),
            Row("paragraph", "list_item", "the backlog is down to eleven items"),
            Row("paragraph", "list_item", "the next review is in a fortnight"),
        ),
    ),
    "recipe.odt": Outline(
        "odt",
        "a heading, a two-column ingredient table and three numbered steps",
        (
            Row("heading", "document", "Flatbread, four pieces"),
            Row("paragraph", "table_cell", "Ingredient"),
            Row("paragraph", "table_cell", "Amount"),
            Row("paragraph", "table_cell", "Flour"),
            Row("paragraph", "table_cell", "300 g"),
            Row("paragraph", "table_cell", "Water"),
            Row("paragraph", "table_cell", "180 ml"),
            Row("paragraph", "list_item", "Mix until no dry flour remains."),
            Row("paragraph", "list_item", "Rest the dough for twenty minutes."),
            Row("paragraph", "list_item", "Cook each piece for two minutes a side."),
        ),
        cols=2,
    ),
    "invoice.docx": Outline(
        "docx",
        "an invoice: a heading, two paragraphs and a three-column line-item table",
        (
            Row("heading", "document", "Invoice 2026-114"),
            Row("paragraph", "document", "Issued to the Northern Archive on 14 October 2026."),
            Row("paragraph", "table_cell", "Item"),
            Row("paragraph", "table_cell", "Hours"),
            Row("paragraph", "table_cell", "Amount"),
            Row("paragraph", "table_cell", "Index rebuild"),
            Row("paragraph", "table_cell", "12"),
            Row("paragraph", "table_cell", "960.00"),
            Row("paragraph", "table_cell", "Reader training"),
            Row("paragraph", "table_cell", "4"),
            Row("paragraph", "table_cell", "320.00"),
            Row("paragraph", "document", "Payable within thirty days of issue."),
        ),
        cols=3,
    ),
    "policy.docx": Outline(
        "docx",
        "two headings, four paragraphs and a footnote, which is the note layer on this path",
        (
            Row("heading", "document", "Retention policy"),
            Row("paragraph", "document", "This policy covers every document the archive holds."),
            Row("heading", "document", "How long a record is kept"),
            Row("paragraph", "document", "A reader request is kept for two years."),
            Row("paragraph", "document", "A catalogue record is kept indefinitely."),
            Row("paragraph", "document", "Questions go to the records office."),
            Row("paragraph", "footnote", "Reviewed each January.", "note"),
        ),
    ),
    "agenda.docx": Outline(
        "docx",
        "a heading and a five-item list, the shortest ordinary document in the family",
        (
            Row("heading", "document", "Agenda, 3 November"),
            Row("paragraph", "list_item", "Apologies"),
            Row("paragraph", "list_item", "Minutes of the last meeting"),
            Row("paragraph", "list_item", "Index rebuild: where it stands"),
            Row("paragraph", "list_item", "Budget for the next quarter"),
            Row("paragraph", "list_item", "Any other business"),
        ),
    ),
    "primer.epub": Outline(
        "epub",
        "a package title, a chapter heading, prose, a quotation and a code listing",
        (
            Row("title", "document", "A primer on indexes"),
            Row("heading", "document", "What an index is for"),
            Row("paragraph", "document", "An index answers a question without reading the book."),
            Row("paragraph", "blockquote", "Order is the first courtesy a reader is owed."),
            Row("code", "document", "index.lookup('order')\n"),
            Row("paragraph", "document", "The next chapter builds one."),
        ),
    ),
    "anthology.epub": Outline(
        "epub",
        "a package title, two headings and a four-item list of contents",
        (
            Row("title", "document", "Four short pieces"),
            Row("heading", "document", "Contents"),
            Row("paragraph", "list_item", "1. The weather in March"),
            Row("paragraph", "list_item", "2. A letter never sent"),
            Row("paragraph", "list_item", "3. Two walks"),
            Row("paragraph", "list_item", "4. The last page"),
            Row("heading", "document", "The weather in March"),
            Row("paragraph", "document", "It rained for nine days and then it did not."),
        ),
    ),
    "letter.rtf": Outline(
        "rtf",
        "five paragraphs, which is every Block an RTF carries on this path",
        (
            Row("paragraph", "document", "14 October 2026"),
            Row("paragraph", "document", "Dear Archivist,"),
            Row("paragraph", "document", "The index rebuild finished on Tuesday afternoon."),
            Row("paragraph", "document", "I will send the reader counts when they settle."),
            Row("paragraph", "document", "Yours sincerely,"),
        ),
    ),
    "receipt.rtf": Outline(
        "rtf",
        "four paragraphs with braces and a backslash in the text, which RTF escapes",
        (
            Row("paragraph", "document", "Receipt {2026-114}"),
            Row("paragraph", "document", "Paid in full on 20 October 2026."),
            Row("paragraph", "document", "Reference: NA\\2026\\114"),
            Row("paragraph", "document", "Thank you."),
        ),
    ),
    "ledger.csv": Outline(
        "csv",
        "a four-column ledger: a header row and three records, one with an embedded comma",
        (
            Row("paragraph", "table_cell", "date"),
            Row("paragraph", "table_cell", "account"),
            Row("paragraph", "table_cell", "amount"),
            Row("paragraph", "table_cell", "note"),
            Row("paragraph", "table_cell", "2026-10-01"),
            Row("paragraph", "table_cell", "reading room"),
            Row("paragraph", "table_cell", "120.00"),
            Row("paragraph", "table_cell", "chairs"),
            Row("paragraph", "table_cell", "2026-10-08"),
            Row("paragraph", "table_cell", "catalogue"),
            Row("paragraph", "table_cell", "64.50"),
            Row("paragraph", "table_cell", "labels, two boxes"),
            Row("paragraph", "table_cell", "2026-10-15"),
            Row("paragraph", "table_cell", "bindery"),
            Row("paragraph", "table_cell", "0.00"),
            Row("paragraph", "table_cell", "no spend"),
        ),
        cols=4,
    ),
    "roster.csv": Outline(
        "csv",
        "a three-column roster: a header row and four records, every cell distinct",
        (
            Row("paragraph", "table_cell", "name"),
            Row("paragraph", "table_cell", "shift"),
            Row("paragraph", "table_cell", "desk"),
            Row("paragraph", "table_cell", "Okonkwo"),
            Row("paragraph", "table_cell", "Monday morning"),
            Row("paragraph", "table_cell", "desk 1"),
            Row("paragraph", "table_cell", "Haraldsen"),
            Row("paragraph", "table_cell", "Tuesday morning"),
            Row("paragraph", "table_cell", "desk 2"),
            Row("paragraph", "table_cell", "Devereux"),
            Row("paragraph", "table_cell", "Wednesday afternoon"),
            Row("paragraph", "table_cell", "desk 3"),
            Row("paragraph", "table_cell", "Nakamura"),
            Row("paragraph", "table_cell", "Thursday afternoon"),
            Row("paragraph", "table_cell", "desk 4"),
        ),
        cols=3,
    ),
    "roadmap.pptx": Outline(
        "pptx",
        "a deck: a title, three bullets and a speaker note, which is the note layer here",
        (
            Row("title", "document", "Roadmap to the spring release"),
            Row("paragraph", "document", "the reader index ships first"),
            Row("paragraph", "document", "the catalogue migration follows it"),
            Row("paragraph", "document", "the public search page is last"),
            Row("paragraph", "speaker_note", "Do not promise a date for the search page.", "note"),
        ),
    ),
    "review.pptx": Outline(
        "pptx",
        "a deck with a title and four bullets and no note at all",
        (
            Row("title", "document", "Quarter in review"),
            Row("paragraph", "document", "reader visits up by a fifth"),
            Row("paragraph", "document", "two collections catalogued"),
            Row("paragraph", "document", "one reading room closed for repair"),
            Row("paragraph", "document", "spend inside the quarter's budget"),
        ),
    ),
    "kickoff.odp": Outline(
        "odp",
        "an ODF presentation: four text boxes, every one a paragraph under the document",
        (
            Row("paragraph", "document", "Catalogue migration, kickoff"),
            Row("paragraph", "document", "who is on the team"),
            Row("paragraph", "document", "what the first fortnight covers"),
            Row("paragraph", "document", "how we will know it worked"),
        ),
    ),
    "retro.odp": Outline(
        "odp",
        "an ODF presentation of three text boxes, the shortest deck in the family",
        (
            Row("paragraph", "document", "Retrospective, October"),
            Row("paragraph", "document", "the index rebuild took half the time we budgeted"),
            Row("paragraph", "document", "the reader survey went out a week late"),
        ),
    ),
    "budget.xlsx": Outline(
        "xlsx",
        "a three-column budget sheet: a header row and four records, every cell an inline string",
        (
            Row("paragraph", "table_cell", "Line"),
            Row("paragraph", "table_cell", "Budgeted"),
            Row("paragraph", "table_cell", "Spent"),
            Row("paragraph", "table_cell", "Binding"),
            Row("paragraph", "table_cell", "1200"),
            Row("paragraph", "table_cell", "1140"),
            Row("paragraph", "table_cell", "Shelving"),
            Row("paragraph", "table_cell", "800"),
            Row("paragraph", "table_cell", "815"),
            Row("paragraph", "table_cell", "Training"),
            Row("paragraph", "table_cell", "400"),
            Row("paragraph", "table_cell", "260"),
        ),
        cols=3,
    ),
    "inventory.xlsx": Outline(
        "xlsx",
        "a four-column inventory sheet: a header row and three records",
        (
            Row("paragraph", "table_cell", "Shelf"),
            Row("paragraph", "table_cell", "Items"),
            Row("paragraph", "table_cell", "Condition"),
            Row("paragraph", "table_cell", "Checked"),
            Row("paragraph", "table_cell", "A1"),
            Row("paragraph", "table_cell", "214"),
            Row("paragraph", "table_cell", "good"),
            Row("paragraph", "table_cell", "2026-09-30"),
            Row("paragraph", "table_cell", "A2"),
            Row("paragraph", "table_cell", "198"),
            Row("paragraph", "table_cell", "fair"),
            Row("paragraph", "table_cell", "2026-10-07"),
        ),
        cols=4,
    ),
    "timesheet.ods": Outline(
        "ods",
        "a three-column ODF timesheet: a header row and four records",
        (
            Row("paragraph", "table_cell", "Day"),
            Row("paragraph", "table_cell", "Desk hours"),
            Row("paragraph", "table_cell", "Catalogue hours"),
            Row("paragraph", "table_cell", "Monday"),
            Row("paragraph", "table_cell", "4"),
            Row("paragraph", "table_cell", "3"),
            Row("paragraph", "table_cell", "Tuesday"),
            Row("paragraph", "table_cell", "5"),
            Row("paragraph", "table_cell", "2"),
            Row("paragraph", "table_cell", "Wednesday"),
            Row("paragraph", "table_cell", "6"),
            Row("paragraph", "table_cell", "1"),
        ),
        cols=3,
    ),
    "catalogue.ods": Outline(
        "ods",
        "a four-column ODF catalogue extract: a header row and three records",
        (
            Row("paragraph", "table_cell", "Reference"),
            Row("paragraph", "table_cell", "Title"),
            Row("paragraph", "table_cell", "Year"),
            Row("paragraph", "table_cell", "Boxes"),
            Row("paragraph", "table_cell", "NA/1/1"),
            Row("paragraph", "table_cell", "Harbour board minutes"),
            Row("paragraph", "table_cell", "1894"),
            Row("paragraph", "table_cell", "7"),
            Row("paragraph", "table_cell", "NA/1/2"),
            Row("paragraph", "table_cell", "Harbour board accounts"),
            Row("paragraph", "table_cell", "1897"),
            Row("paragraph", "table_cell", "3"),
        ),
        cols=4,
    ),
    "handbook.docx": Outline(
        "docx",
        "three headings and five paragraphs, the longest prose document in the family",
        (
            Row("heading", "document", "Reading room handbook"),
            Row("paragraph", "document", "The reading room is open on weekday afternoons."),
            Row("heading", "document", "Before you arrive"),
            Row("paragraph", "document", "Order material at least one working day ahead."),
            Row("paragraph", "document", "Bring photographic identification."),
            Row("heading", "document", "In the room"),
            Row("paragraph", "document", "Pencils only, and one box on the desk at a time."),
            Row("paragraph", "document", "Photography without flash is permitted."),
        ),
    ),
}


def reference(outline: Outline) -> str:
    """The `.structure.jsonl` the outline declares: the header, then one row per text-bearing
    Block in document order, ids `s01` upward as the committed ten spell them."""
    lines = [json.dumps({"schema": SCHEMA})]
    for at, row in enumerate(outline.rows, start=1):
        lines.append(
            json.dumps(
                {
                    "id": f"s{at:02d}",
                    "page": 1,
                    "kind": row.kind,
                    "layer": row.layer,
                    "parent_kind": row.parent_kind,
                    "text": row.text,
                }
            )
        )
    return "\n".join(lines) + "\n"


SIDECAR: Final = """\
# {name}.meta.toml -- 13-quality.md section 4.4's fixture manifest.
#
# {purpose}
[fixture]
sha256 = "{digest}"
bytes = {size}
media_type = "{media_type}"
provenance = "generated"
spdx = "Apache-2.0"
generator = "{generator}"
# `generated` is 13-quality.md section 4.2's PREFERRED provenance: the generator path under
# fixtures/gen/ and the expected output sha256, both above. It carries no `review_by` -- the
# review window is "none for `generated` and `authored`, which have no external dependency to
# rot" -- and this file depends on nothing outside this repository.

[fixture.tests]
# 13-quality.md section 4.4's block, and :1150's vocabulary: the corpus declares the slice and a
# `[[gate]]` row's `slice` glob is matched against it, never the router's Slice.
# `{coarse}` is the coarse slice (D1002, a user ruling of 2026-10-28). The per-extension
# key beside it will never hold `min_slice_n = 30` documents, so its row reports `unknown` for
# ever; one slice per family is the set that can reach thirty, and the per-extension rows stay
# visible saying what they are. Q-G1 holds the pair together.
slices = [{slices}]
"""

COARSE: Final = "office/labelled"


def sidecar(name: str, outline: Outline, data: bytes) -> str:
    """One `.meta.toml`. The per-extension key comes from the format, so a new document in an
    existing format joins that slice without a table to update."""
    names = (f"office/{outline.fmt}", COARSE)
    return SIDECAR.format(
        name=name,
        purpose=outline.purpose,
        digest=hashlib.sha256(data).hexdigest(),
        size=len(data),
        media_type=MEDIA_TYPES[outline.fmt],
        generator=GENERATOR,
        coarse=COARSE,
        slices=", ".join(f'"{one}"' for one in names),
    )


def unique(outline: Outline) -> None:
    """Every row's text is distinct within its document, or this raises. **D1004.**

    A reference row reads *"this text, at this kind, under this one"* (`structure` ruling 6), and
    a text that appears twice in the document names neither place. The metric itself copes -- its
    matching is one-to-one with reading order breaking a tie (ruling 4) -- but the two readers who
    have to CHECK the row cannot: `tools/label_review.py` finds the first occurrence and reports
    the second row out of order, and a reviewer looking at a render has the same problem with no
    tool to tell them. A corpus grown for population is the easiest place for this to creep in:
    four of these eleven documents had a repeated cell or a contents entry quoting a heading, and
    every one of them read as a disagreement until the text was made distinct.

    A `note`-layer row is the one position this does not fix: a footnote lives in its own part and
    a byte reader finds it after the body whatever the outline says, so a footnote row goes LAST,
    which is where `rich.docx`'s own `s13` sits.
    """
    seen: dict[str, int] = {}
    for at, row in enumerate(outline.rows, start=1):
        if row.text in seen:
            message = (
                f"row s{at:02d} repeats the text of s{seen[row.text]:02d} ({row.text!r});"
                " a reference row no reviewer can pin to one place is not checkable"
            )
            raise ValueError(message)
        seen[row.text] = at


def build(name: str) -> bytes:
    """One document's bytes, from its outline alone."""
    outline = OUTLINES[name]
    unique(outline)
    return WRITERS[outline.fmt](outline)


def report(line: str) -> None:
    """`print` is banned by ruff's T20 across this repository, so the report goes to stdout
    directly -- the same route `gen_office_fixtures.py` takes for the same reason."""
    sys.stdout.write(f"{line}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the labelled office corpus and its references")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    stale = 0
    for name, outline in sorted(OUTLINES.items()):
        data = build(name)
        wanted = {
            name: data,
            f"{name}.meta.toml": sidecar(name, outline, data).encode("utf-8"),
            f"{name}.structure.jsonl": reference(outline).encode("utf-8"),
        }
        for relative, body in wanted.items():
            target = args.out / relative
            if args.check:
                same = target.is_file() and target.read_bytes() == body
                stale += not same
                report(f"{'ok  ' if same else 'STALE'}  {relative}")
            else:
                target.write_bytes(body)
        if not args.check:
            report(f"{name:22s} {len(data):7d} bytes, {len(outline.rows)} reference row(s)")
    if args.check:
        report(f"\n{stale} stale file(s)")
        return 1 if stale else 0
    report(f"\n{len(OUTLINES)} document(s) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
