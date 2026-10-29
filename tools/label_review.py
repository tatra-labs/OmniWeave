"""Ruling 1's label review page: every drafted assertion beside evidence from the bytes. **D980.**

A user ruling of 2026-10-23, ruling 1: *"Claude builds a review page (one row per label: excerpt,
assertion, approve/reject/edit); only the user's verdicts are written back as `checked`."* D913
drafted 110 assertions over 14 fixtures and left every one unchecked, which is why V10-3's four
accuracy floors read UNMEASURED and `ow eval release-check` refuses on the drafted labels'
unverified rates: 13-quality.md section 8.1 scores a row only once a reviewer has signed it.

**The evidence is read off the committed fixture bytes by this file's own readers** -- uncompressed
PDF content streams, and `zipfile` + `ElementTree` for the office formats -- and never through an
omniweave driver. The claims were drafted from the generators' text functions, so confirming them
with the system the labels exist to judge would be a circular label; confirming them against the
file is not.

`agrees` is this file's arithmetic over that evidence, **not a verdict**. It is printed so a
reviewer can see which rows the bytes already support and spend attention on the rest. Nothing here
writes `checked` on its own: `--apply` reads a verdict file the reviewer produced and refuses any
value but `verified` or `rejected`.

Exit 0 when every row has evidence and no claim contradicts it, 1 when a claim contradicts the
bytes (a drafted label to mend before a reviewer ever sees it), 2 when a row's evidence cannot be
read at all -- which is never a pass, because an unreadable row is one a reviewer would have to
take on trust.

**The structure references are the second population, and the signature unit is the DOCUMENT.**
D1001, a user ruling of 2026-10-28. `omniweave_conform.structure` ruling 3: *"A document scores
only when EVERY row of its reference is `verified`. An assertion signs one claim and scores alone
(13:1022); a precision denominator does not."* So a `*.structure.jsonl` takes one verdict for the
whole file, where a `*.assertions.toml` takes one per row, and `--apply` tells the two apart by the
shape of the value rather than by a flag: a string is a document's verdict, a mapping is a row's.

What this file can and cannot judge about a structure row is the part worth reading. The `text` it
can: the row's string is looked for in the same reading order the evidence readers already build,
under the evaluator's own `normalize_eval`, so "present" here means what `structure.match()` will
mean. The ORDER it can: a reference whose rows do not follow the document's reading order is a
defect in the reference, and this is where a reviewer would never notice it. The
`(kind, layer, parent_kind)` triple it CANNOT, and says so on every row: 13:1104 makes that triple
*"authored by a human reading a `soffice`/pdfium render"*, and a `<w:t>` run carries no answer to
"is this a heading". That is the judgement the signature is for.

    uv run tools/label_review.py                       # the summary, one line per fixture
    uv run tools/label_review.py --rows                # one line per label
    uv run tools/label_review.py --json out.json       # the evidence bundle
    uv run tools/label_review.py --page review.html    # the review page
    uv run tools/label_review.py --apply verdicts.json # the reviewer's verdicts, written back
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import struct
import sys
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

ROOT: Final = Path(__file__).resolve().parents[1]

for _dist in sorted((ROOT / "packages").iterdir()) if (ROOT / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.normalize import normalize_eval  # noqa: E402

#  The ONE import of a package here, and it is the evaluator's fold rather than a driver. 13:1050
#  makes `normalize_eval` "a composition rather than a second implementation" and
#  `omniweave_conform.normalize` rule 2 gives the dash/Cf/whitespace table one home, so folding by
#  hand in this file would be the drift that rule exists against -- "two normalisers that quietly
#  converge are one normaliser with two names". Reading a CLAIM through the system the labels judge
#  would be circular; folding a string the way the metric will fold it is what makes "present" here
#  mean "matchable" there.

GLOB: Final = "packages/*/fixtures/*.assertions.toml"
SCHEMA: Final = "omniweave.assertions/1"
STRUCTURE_GLOB: Final = "packages/*/fixtures/*.structure.jsonl"
STRUCTURE_SCHEMA: Final = "omniweave.structure/1"
VERDICTS: Final = ("verified", "rejected")
"""13-quality.md section 8.1: the only two values a reviewer's signature can take."""
DIRECTIONS: Final[Mapping[str, tuple[int, int]]] = {
    "right": (0, 1),
    "left": (0, -1),
    "up": (-1, 0),
    "down": (1, 0),
}


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


EXIT_CLEAN: Final = 0
EXIT_DISAGREES: Final = 1
EXIT_NO_EVIDENCE: Final = 2

_LITERAL: Final = re.compile(rb"\((?:\\.|[^()\\])*\)", re.DOTALL)
_KIDS: Final = re.compile(rb"/Type\s*/Pages[^>]*?/Kids\s*\[([^\]]*)\]", re.DOTALL)
_REF: Final = re.compile(rb"(\d+)\s+0\s+R")
_OBJ: Final = re.compile(rb"(\d+)\s+0\s+obj(.*?)endobj", re.DOTALL)
_RTF_WORD: Final = re.compile(r"\\[a-z]+-?\d* ?|\\\n|[{}]", re.IGNORECASE)
_RTF_ESCAPE: Final = re.compile(r"\\([\\{}])")
"""RTF's three control symbols: an escaped backslash, open brace or close brace (D1004)."""
_RTF_HELD: Final[Mapping[str, str]] = {"\\": "\x00", "{": "\x01", "}": "\x02"}
"""What each stands in as while the control-word pass runs. Three characters no RTF body carries:
a control symbol is the only way to spell any of them, so a held one cannot be a real one."""
_RTF_HEADER: Final = re.compile(
    r"\{\\(?:fonttbl|colortbl|stylesheet|info|\*)[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
    re.IGNORECASE,
)
"""The header groups a reader skips: a font name is not the document's text."""
_A1: Final = re.compile(r"([A-Z]+)(\d+)")
_BACKSLASH: Final = 0x5C
_BIFF_LABELSST: Final = 0x00FD
_BIFF_NUMBER: Final = 0x0203
_BIFF_SST: Final = 0x00FC
_BIFF_BOF: Final = 0x0809
_SST_HEADER: Final = 8
"""The two counts a BIFF `SST` opens with, before its first string."""
_LABELSST_LEN: Final = 10
"""`LABELSST`: row, column, XF, SST index."""
_NUMBER_LEN: Final = 14
"""`NUMBER`: row, column, XF, and an IEEE double."""
CONTEXT: Final = 6
"""How many runs a disagreeing row shows, so a reviewer sees where it looked."""


@dataclass(frozen=True, slots=True)
class Claim:
    """One `[[assertion]]` row, as written."""

    sidecar: Path
    fixture: Path
    index: int
    body: Mapping[str, Any]

    @property
    def id(self) -> str:
        return str(self.body.get("id", f"#{self.index}"))

    @property
    def type(self) -> str:
        return str(self.body.get("type", "?"))

    @property
    def page(self) -> int | None:
        value = self.body.get("page")
        return int(value) if isinstance(value, int) else None

    @property
    def checked(self) -> str | None:
        value = self.body.get("checked")
        return str(value) if value is not None else None

    @property
    def sentence(self) -> str:
        """The claim in one line, in the reviewer's language rather than TOML's."""
        where = f"page {self.page}" if self.page else "the document"
        body = self.body
        if self.type == "present":
            return f'{where} contains "{body.get("text", "")}"'
        if self.type == "absent":
            return f'no page contains "{body.get("text", "")}"'
        if self.type == "order":
            return f'on {where}, "{body.get("before", "")}" comes before "{body.get("after", "")}"'
        if self.type == "table":
            parts = [
                f'its {name} neighbour is "{body[name]}"' for name in DIRECTIONS if name in body
            ]
            return f'on {where}, the cell "{body.get("cell", "")}" has ' + ", and ".join(parts)
        return json.dumps(dict(body), sort_keys=True)


@dataclass(frozen=True, slots=True)
class Evidence:
    """What the committed bytes say, and how this file read them."""

    origin: str
    runs: tuple[str, ...] = ()
    pages: tuple[tuple[str, ...], ...] = ()
    grid: tuple[tuple[str, ...], ...] = ()
    unreadable: str | None = None
    derived: tuple[int, ...] = ()
    """Indices into `runs` whose text leaves do not spell what the markup means. **D1001.**

    A `<m:oMath>` paragraph's leaves are `x`, `2` and `+1`; what the paragraph MEANS is a
    superscript, and the string a parser emits for it is a transcription in some notation. This
    names those positions so a reference row that disagrees with the leaves can be reported as
    unconfirmable THERE and as wrong everywhere else -- which is the difference between a reader
    that is narrower than the format and a reference that is mistaken."""


@dataclass(frozen=True, slots=True)
class Row:
    """One label, its evidence, and this file's arithmetic over the two."""

    claim: Claim
    evidence: Evidence
    agrees: bool | None
    why: str
    excerpt: tuple[str, ...] = field(default=())


def unescape(literal: bytes) -> str:
    """A PDF string literal's bytes, with the escapes the writer had to add removed."""
    body, out, index = literal[1:-1], bytearray(), 0
    while index < len(body):
        char = body[index]
        if char == _BACKSLASH and index + 1 < len(body):
            out.append(body[index + 1])
            index += 2
            continue
        out.append(char)
        index += 1
    return out.decode("latin-1")


def pdf_pages(path: Path) -> list[list[str]]:
    """Each page's drawn strings, in drawing order, off the uncompressed content streams.

    Drawing order is what an `order` assertion is about, and it is a property of the file rather
    than of any reader: the strings reach the page in the sequence the stream feeds them to `Tj`.
    """
    data = path.read_bytes()
    body = {int(m.group(1)): m.group(2) for m in _OBJ.finditer(data)}
    kids = _KIDS.search(data)
    order = [int(n) for n in _REF.findall(kids.group(1))] if kids else sorted(body)
    pages: list[list[str]] = []
    for number in order:
        page = body.get(number, b"")
        marker = page.find(b"/Contents")
        if marker < 0:
            continue
        ref = _REF.search(page[marker:])
        if ref is None:
            continue
        stream = body.get(int(ref.group(1)), b"")
        start = stream.find(b"stream")
        if start < 0:
            continue
        start = stream.find(b"\n", start) + 1
        end = stream.find(b"endstream")
        pages.append([unescape(m.group(0)) for m in _LITERAL.finditer(stream[start:end])])
    return pages


def _members(path: Path, pattern: re.Pattern[str]) -> list[bytes]:
    with zipfile.ZipFile(path) as archive:
        return [archive.read(name) for name in sorted(archive.namelist()) if pattern.search(name)]


def _local(element: ET.Element) -> str:
    return element.tag.rpartition("}")[2]


def _paragraphs(xml_bytes: bytes, leaf: str = "t") -> list[str]:
    """Each paragraph's whole text, in document order: its runs joined, blanks dropped.

    A reviewer compares a claim against a paragraph, never against the formatting runs the writer
    happened to split it into.
    """
    root = ET.fromstring(xml_bytes)  # noqa: S314 -- a committed fixture, read offline
    out = []
    for element in root.iter():
        if _local(element) != "p":
            continue
        text = "".join("".join(node.itertext()) for node in element.iter() if _local(node) == leaf)
        if text.strip():
            out.append(text)
    return out


def _math_paragraphs(xml_bytes: bytes) -> set[int]:
    """The indices, among `_paragraphs`' output, of paragraphs carrying OMML.

    Walked the same way `_paragraphs` walks, and counted the same way -- a paragraph whose text is
    blank is dropped there and must be dropped here, or every index after it is off by one.
    """
    root = ET.fromstring(xml_bytes)  # noqa: S314 -- a committed fixture, read offline
    found: set[int] = set()
    index = 0
    for element in root.iter():
        if _local(element) != "p":
            continue
        text = "".join("".join(node.itertext()) for node in element.iter() if _local(node) == "t")
        if not text.strip():
            continue
        if any(_local(node) == "oMath" for node in element.iter()):
            found.add(index)
        index += 1
    return found


def _odf_paragraphs(xml_bytes: bytes) -> list[str]:
    """ODF's block text in document order: `text:h` as well as `text:p`.

    A heading is a `text:h`, so reading only `text:p` would lose every title -- and then a claim
    about a title would look false when the file is right.
    """
    root = ET.fromstring(xml_bytes)  # noqa: S314 -- a committed fixture, read offline
    return [
        "".join(element.itertext())
        for element in root.iter()
        if _local(element) in {"p", "h"} and "".join(element.itertext()).strip()
    ]


def _docx_grid(xml_bytes: bytes) -> list[list[str]]:
    """The first table's cells, row by row. A vertically merged cell repeats downwards."""
    root = ET.fromstring(xml_bytes)  # noqa: S314 -- a committed fixture, read offline
    for element in root.iter():
        if _local(element) != "tbl":
            continue
        grid = []
        for row in (node for node in element.iter() if _local(node) == "tr"):
            cells = [
                "".join(
                    "".join(leaf.itertext()) for leaf in cell.iter() if _local(leaf) == "t"
                ).strip()
                for cell in row
                if _local(cell) == "tc"
            ]
            grid.append(cells)
        return grid
    return []


def _odf_grid(xml_bytes: bytes) -> list[list[str]]:
    """An ODF sheet's cells. `number-columns-spanned` widens a cell; a covered cell repeats it."""
    root = ET.fromstring(xml_bytes)  # noqa: S314 -- a committed fixture, read offline
    grid = []
    for row in (node for node in root.iter() if _local(node) == "table-row"):
        cells: list[str] = []
        for cell in row:
            name = _local(cell)
            if name not in {"table-cell", "covered-table-cell"}:
                continue
            text = "".join(cell.itertext()).strip()
            repeat = 1
            for key, value in cell.attrib.items():
                if key.rpartition("}")[2] in {"number-columns-spanned", "number-columns-repeated"}:
                    repeat = max(repeat, int(value))
            cells.extend([text] * repeat)
        if any(cells):
            grid.append(cells)
    return grid


def _xlsx_grid(path: Path) -> list[list[str]]:
    shared = _members(path, re.compile(r"^xl/sharedStrings\.xml$"))
    pool: list[str] = []
    if shared:
        root = ET.fromstring(shared[0])  # noqa: S314 -- a committed fixture, read offline
        pool = ["".join(node.itertext()) for node in root.iter() if _local(node) == "si"]
    cells: dict[tuple[int, int], str] = {}
    for data in _members(path, re.compile(r"^xl/worksheets/sheet\d+\.xml$")):
        root = ET.fromstring(data)  # noqa: S314 -- a committed fixture, read offline
        for element in root.iter():
            if _local(element) != "c":
                continue
            match = _A1.fullmatch(element.get("r", ""))
            if match is None:
                continue
            column = 0
            for letter in match.group(1):
                column = column * 26 + (ord(letter) - 64)
            value = "".join(
                "".join(child.itertext()) for child in element if _local(child) in {"v", "is"}
            )
            if element.get("t") == "s" and value.isdigit() and int(value) < len(pool):
                value = pool[int(value)]
            cells[(int(match.group(2)) - 1, column - 1)] = value.strip()
        break
    return _dense(cells)


def _xls_grid(path: Path) -> list[list[str]]:
    """BIFF8's cell records, walked from the first `BOF`: `LABELSST`, `NUMBER` and the `SST`.

    The compound file this sits in is not parsed. The walk starts at the first `BOF` record and
    stops the moment a record header does not fit, so a desynchronised stream yields what it read
    and never a guess.
    """
    blob = path.read_bytes()
    start = blob.find(struct.pack("<H", _BIFF_BOF))
    if start < 0:
        return []
    pool: list[str] = []
    cells: dict[tuple[int, int], str] = {}
    offset = start
    while offset + 4 <= len(blob):
        record, length = struct.unpack_from("<HH", blob, offset)
        payload = blob[offset + 4 : offset + 4 + length]
        if len(payload) < length:
            break
        if record == _BIFF_SST and length >= _SST_HEADER:
            index = _SST_HEADER
            while index + 3 <= len(payload):
                count, flags = struct.unpack_from("<HB", payload, index)
                index += 3
                if flags & 1:
                    pool.append(payload[index : index + count * 2].decode("utf-16-le", "replace"))
                    index += count * 2
                else:
                    pool.append(payload[index : index + count].decode("latin-1"))
                    index += count
        elif record == _BIFF_LABELSST and length >= _LABELSST_LEN:
            row, column, _, which = struct.unpack_from("<HHHI", payload)
            cells[(row, column)] = pool[which] if which < len(pool) else ""
        elif record == _BIFF_NUMBER and length >= _NUMBER_LEN:
            row, column, _, number = struct.unpack_from("<HHHd", payload)
            cells[(row, column)] = f"{number:g}"
        offset += 4 + length
    return _dense(cells)


def _dense(cells: Mapping[tuple[int, int], str]) -> list[list[str]]:
    if not cells:
        return []
    rows = max(row for row, _ in cells) + 1
    columns = max(column for _, column in cells) + 1
    return [[cells.get((row, column), "") for column in range(columns)] for row in range(rows)]


def _csv_grid(path: Path) -> list[list[str]]:
    return [
        [value.strip() for value in row]
        for row in csv.reader(io.StringIO(path.read_text("utf-8")))
        if any(value.strip() for value in row)
    ]


def _rtf_paragraphs(text: str) -> list[str]:
    """RTF's paragraphs: split at `par`, then strip the control words inside each one.

    Stripping every control word first would cut a paragraph at each `\\i` and `\\b`, and a claim
    about a whole sentence would then read as false against a file that carries it.

    **RTF's three control SYMBOLS are unescaped** (D1004). `\\{`, `\\}` and `\\\\` are how an RTF
    file spells a brace or a backslash in running text. Left as they are, a row claiming
    `Receipt {2026-114}` reads as false against a file that spells exactly that -- the tool
    calling a reference wrong about a file that carries it, which is the same mistake the DOCX
    footnote part was.

    They are held aside BEFORE `_RTF_WORD` runs and restored after, rather than unescaped in
    place, because that pattern's third alternative strips a bare `{` or `}` as a group delimiter:
    unescaping first would hand it a real brace to eat, and unescaping afterwards finds the brace
    already gone and only the backslash left. A placeholder is the one order in which neither pass
    can see the other's work.
    """
    body = _RTF_ESCAPE.sub(lambda hit: _RTF_HELD[hit.group(1)], _RTF_HEADER.sub(" ", text))
    out = []
    for chunk in re.split(r"\\par\b", body):
        line = _RTF_WORD.sub(" ", chunk)
        line = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", line)).strip()
        for literal, held in _RTF_HELD.items():
            line = line.replace(held, literal)
        if line:
            out.append(line)
    return out


_OPF_TITLE: Final = re.compile(rb"<dc:title[^>]*>(.*?)</dc:title>", re.DOTALL)


def _epub_blocks(path: Path) -> list[str]:
    """The package title, then every XHTML document's block text.

    **The title comes from `content.opf` and not from the XHTML.** An EPUB's title is package
    metadata (`<dc:title>`); `book.epub`'s chapter carries `<h1>Chapter one</h1>` and nothing
    saying what the book is called. A reader that read the XHTML alone reported the title row of
    its structure reference as disagreeing with a file that carries the string (D1001), which is
    the reader being narrower than the format rather than the reference being wrong.
    """
    out: list[str] = []
    for data in _members(path, re.compile(r"\.opf$")):
        found = _OPF_TITLE.search(data)
        if found is not None:
            title = re.sub(rb"<[^>]+>", b"", found.group(1)).decode("utf-8", "replace").strip()
            if title:
                out.append(title)
    for data in _members(path, re.compile(r"\.(?:x?html|htm|xhtml)$")):
        text = re.sub(rb"</(?:p|div|h\d|li|section|body)>", b"\n", data)
        text = re.sub(rb"<[^>]+>", b"", text)
        out += [
            line.strip() for line in text.decode("utf-8", "replace").splitlines() if line.strip()
        ]
    return out


def _read_pdf(fixture: Path) -> Evidence:
    pages = tuple(tuple(page) for page in pdf_pages(fixture))
    if not pages:
        return Evidence("PDF content streams", unreadable="no page content stream parsed")
    return Evidence(
        "the uncompressed PDF content streams, in drawing order",
        runs=tuple(run for page in pages for run in page),
        pages=pages,
    )


def _read_docx(fixture: Path) -> Evidence:
    """The body, then the notes. **The notes are here because a reference row describes one.**

    `word/footnotes.xml` and `word/endnotes.xml` are separate parts, and a reader that stopped at
    `word/document.xml` reported `rich.docx`'s footnote row as disagreeing with a file that
    carries it (D1001). They come last because that is where the reference puts them and because
    a note is not in the body's reading order -- the `note` layer is how a row says so.
    """
    document = _members(fixture, re.compile(r"^word/document\.xml$"))[0]
    notes = [
        line
        for data in _members(fixture, re.compile(r"^word/(?:foot|end)notes\.xml$"))
        for line in _paragraphs(data)
    ]
    runs = (*_paragraphs(document), *notes)
    return Evidence(
        "word/document.xml: paragraphs in document order, then word/footnotes.xml and "
        "word/endnotes.xml, and the first table's cells",
        runs=runs,
        pages=(runs,),
        grid=tuple(tuple(row) for row in _docx_grid(document)),
        derived=tuple(sorted(_math_paragraphs(document))),
    )


def _read_pptx(fixture: Path) -> Evidence:
    """The slides, then the speaker notes, for `_read_docx`'s reason: a row describes one.

    `ppt/notesSlides/notesSlideN.xml` is where a speaker note lives, and a reference row carrying
    `layer = "note"` with `parent_kind = "speaker_note"` is a claim about that part and not about
    the slide (D1001).
    """
    slides = [
        line
        for data in _members(fixture, re.compile(r"^ppt/slides/slide\d+\.xml$"))
        for line in _paragraphs(data)
    ]
    notes = [
        line
        for data in _members(fixture, re.compile(r"^ppt/notesSlides/notesSlide\d+\.xml$"))
        for line in _paragraphs(data)
    ]
    runs = (*slides, *notes)
    return Evidence(
        "ppt/slides/slideN.xml: paragraphs, slide by slide, then ppt/notesSlides/notesSlideN.xml",
        runs=runs,
        pages=(runs,),
    )


def _read_odf_text(fixture: Path) -> Evidence:
    runs = tuple(_odf_paragraphs(_members(fixture, re.compile(r"^content\.xml$"))[0]))
    return Evidence("content.xml: paragraphs in document order", runs=runs, pages=(runs,))


def _read_ods(fixture: Path) -> Evidence:
    content = _members(fixture, re.compile(r"^content\.xml$"))[0]
    runs = tuple(_odf_paragraphs(content))
    return Evidence(
        "content.xml: the sheet's rows and cells",
        runs=runs,
        pages=(runs,),
        grid=tuple(tuple(row) for row in _odf_grid(content)),
    )


def _read_xlsx(fixture: Path) -> Evidence:
    grid = tuple(tuple(row) for row in _xlsx_grid(fixture))
    return Evidence(
        "xl/worksheets/sheet1.xml with xl/sharedStrings.xml",
        runs=_flat(grid),
        pages=(_flat(grid),),
        grid=grid,
    )


def _read_xls(fixture: Path) -> Evidence:
    grid = tuple(tuple(row) for row in _xls_grid(fixture))
    if not grid:
        return Evidence("BIFF8 cell records", unreadable="no BOF record found")
    return Evidence(
        "the BIFF8 record stream: LABELSST, NUMBER and the SST",
        runs=_flat(grid),
        pages=(_flat(grid),),
        grid=grid,
    )


def _read_csv(fixture: Path) -> Evidence:
    grid = tuple(tuple(row) for row in _csv_grid(fixture))
    return Evidence(
        "the file itself, through csv.reader",
        runs=_flat(grid),
        pages=(_flat(grid),),
        grid=grid,
    )


def _read_epub(fixture: Path) -> Evidence:
    runs = tuple(_epub_blocks(fixture))
    return Evidence(
        "content.opf's dc:title, then the spine's XHTML, tags stripped", runs=runs, pages=(runs,)
    )


def _read_rtf(fixture: Path) -> Evidence:
    runs = tuple(_rtf_paragraphs(fixture.read_text("latin-1")))
    return Evidence(
        "the RTF body: paragraphs at the par breaks, inline control words stripped",
        runs=runs,
        pages=(runs,),
    )


def _flat(grid: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """A grid's non-empty cells, row by row: what a `present` or `order` claim reads."""
    return tuple(value for row in grid for value in row if value)


READERS: Final[Mapping[str, Callable[[Path], Evidence]]] = {
    ".pdf": _read_pdf,
    ".docx": _read_docx,
    ".pptx": _read_pptx,
    ".odt": _read_odf_text,
    ".odp": _read_odf_text,
    ".ods": _read_ods,
    ".xlsx": _read_xlsx,
    ".xls": _read_xls,
    ".csv": _read_csv,
    ".epub": _read_epub,
    ".rtf": _read_rtf,
}
"""One reader per format a label is drafted over. A fixture whose suffix is absent here has no
evidence, and `judge` refuses to call its claims either way."""


def read_evidence(fixture: Path) -> Evidence:
    """The fixture's text as its own bytes carry it, with the reader named."""
    suffix = fixture.suffix.lower()
    reader = READERS.get(suffix)
    if reader is None:
        return Evidence("none", unreadable=f"no independent reader for {suffix}")
    try:
        return reader(fixture)
    except (OSError, zipfile.BadZipFile, ET.ParseError, IndexError, ValueError) as error:
        return Evidence(f"{suffix} reader", unreadable=f"{type(error).__name__}: {error}")


def _where(claim: Claim, evidence: Evidence) -> tuple[str, ...]:
    """The runs a claim is about: its page's, when the evidence is paginated."""
    if claim.page and len(evidence.pages) >= claim.page:
        return evidence.pages[claim.page - 1]
    return evidence.runs


def _first(runs: Sequence[str], needle: str) -> int:
    for index, run in enumerate(runs):
        if needle in run:
            return index
    return -1


def _find_cell(grid: Sequence[Sequence[str]], text: str) -> tuple[int, int] | None:
    for row_index, row in enumerate(grid):
        for column_index, value in enumerate(row):
            if value == text:
                return row_index, column_index
    for row_index, row in enumerate(grid):
        for column_index, value in enumerate(row):
            if text in value:
                return row_index, column_index
    return None


def _check_present(claim: Claim, evidence: Evidence) -> Row:
    runs = _where(claim, evidence)
    text = str(claim.body.get("text", ""))
    index = _first(runs, text)
    if index < 0:
        return Row(
            claim, evidence, False, "no run on that page contains the text", tuple(runs[:CONTEXT])
        )
    return Row(claim, evidence, True, f"run {index + 1} of {len(runs)} contains it", (runs[index],))


def _check_absent(claim: Claim, evidence: Evidence) -> Row:
    """`absent` is about the whole document: a claim that no page carries the text."""
    text = str(claim.body.get("text", ""))
    hit = [run for run in evidence.runs if text in run]
    if hit:
        return Row(claim, evidence, False, f"the text appears: {hit[0][:60]!r}", tuple(hit[:3]))
    return Row(claim, evidence, True, f"absent from all {len(evidence.runs)} runs", ())


def _check_order(claim: Claim, evidence: Evidence) -> Row:
    runs = _where(claim, evidence)
    before = str(claim.body.get("before", ""))
    after = str(claim.body.get("after", ""))
    first, second = _first(runs, before), _first(runs, after)
    if first < 0 or second < 0:
        missing = before if first < 0 else after
        return Row(claim, evidence, False, f"not on that page: {missing!r}", tuple(runs[:CONTEXT]))
    held = first < second
    said = "precedes" if held else "does NOT precede"
    return Row(
        claim,
        evidence,
        held,
        f"run {first + 1} {said} run {second + 1}",
        (runs[first], runs[second]),
    )


def _check_table(claim: Claim, evidence: Evidence) -> Row:
    if not evidence.grid:
        return Row(claim, evidence, None, "no evidence: this reader found no table", ())
    cell = str(claim.body.get("cell", ""))
    at = _find_cell(evidence.grid, cell)
    if at is None:
        return Row(claim, evidence, False, f"no cell holds {cell!r}", _grid_lines(evidence.grid))
    row_index, column_index = at
    for name, want, got in _neighbours(claim, evidence.grid, row_index, column_index):
        if want not in got:
            return Row(
                claim,
                evidence,
                False,
                f"the {name} of {cell!r} is {got!r}, not {want!r}",
                _grid_lines(evidence.grid),
            )
    return Row(
        claim,
        evidence,
        True,
        f"{cell!r} sits at row {row_index + 1}, column {column_index + 1}, with those neighbours",
        _grid_lines(evidence.grid),
    )


def _neighbours(
    claim: Claim, grid: Sequence[Sequence[str]], row_index: int, column_index: int
) -> list[tuple[str, str, str]]:
    """Each direction the claim names, with what it wants there and what the grid holds.

    A direction that walks off the edge yields `""`, which no claim can match -- the row then
    disagrees rather than raising.
    """
    out = []
    for name, (down, across) in DIRECTIONS.items():
        if name not in claim.body:
            continue
        target_row, target_column = row_index + down, column_index + across
        got = ""
        if 0 <= target_row < len(grid):
            row = grid[target_row]
            if 0 <= target_column < len(row):
                got = row[target_column]
        out.append((name, str(claim.body[name]), got))
    return out


def _check_cell_rel(claim: Claim, evidence: Evidence) -> Row:
    """A `cell_rel` is NO EVIDENCE here, and the reason is the point. **D1005.**

    `cell_rel` is `table`'s relation asked of `Grid.up/down/left_heading` -- a derived cover map
    with column spans and header CHAINS (`cells` rulings 2 and 3). This file reads a flat cell
    grid off the bytes, where a span is a blank neighbour rather than a wide origin: `right` of a
    span-2 cell is `''` here and its last column's neighbour there, and `top_heading` has no
    meaning in a grid with no declared header rows. Judging one on this grid would call a CORRECT
    row wrong, which is worse than declining -- the same reasoning that made `rich.docx`'s two
    OMML rows no evidence rather than disagreements (D1001).

    So the row is reported unjudged, with the grid this reader DID find attached, which is what a
    reviewer needs to check the relation against the table by eye. The machine check lives where
    the grid does: `test_conform_table_assertions.py` parses every fixture through
    `parse.office.anydoc` and judges every committed `table` and `cell_rel` on its real `Grid`.
    """
    lines = _grid_lines(evidence.grid) if evidence.grid else ()
    return Row(
        claim,
        evidence,
        None,
        "no evidence: a cell_rel is a claim about the parsed Grid's spans and header chains, and"
        " this reader has a flat cell grid; test_conform_table_assertions.py judges it on the"
        " real Grid",
        lines,
    )


DECLARED_UNJUDGED: Final = frozenset({"cell_rel"})
"""Types whose no-evidence is DECLARED rather than a gap, so `main()` can still exit 0. **D1005.**

Without this the exit code could never be zero once a `cell_rel` was committed, and an exit code
that can never be zero says nothing at all -- the lesson `TRANSCRIBED` records for the structure
half. The declaration is checked in both directions: `_check_cell_rel` explains the reason on
every row, and `test_label_review.py` fails if the tier stops firing, which is what a stale
declaration looks like. An unknown of any OTHER type still exits `EXIT_NO_EVIDENCE`."""

CHECKS: Final[Mapping[str, Callable[[Claim, Evidence], Row]]] = {
    "present": _check_present,
    "absent": _check_absent,
    "order": _check_order,
    "table": _check_table,
    "cell_rel": _check_cell_rel,
}
"""One check per assertion type 13-quality.md section 8.1 defines. A type absent here is reported
unknown rather than guessed at, so a new assertion type cannot pass by default."""


def judge(claim: Claim, evidence: Evidence) -> Row:
    """This file's arithmetic over the bytes. Never a verdict -- `agrees` is not `checked`."""
    if evidence.unreadable:
        return Row(claim, evidence, None, f"no evidence: {evidence.unreadable}")
    check = CHECKS.get(claim.type)
    if check is None:
        return Row(claim, evidence, None, f"no check for type {claim.type!r}", ())
    return check(claim, evidence)


def _grid_lines(grid: Sequence[Sequence[str]]) -> tuple[str, ...]:
    return tuple(" | ".join(value or "-" for value in row) for row in grid)


def claims(root: Path) -> list[Claim]:
    """Every drafted assertion in the tree, sidecar by sidecar, in file order."""
    out: list[Claim] = []
    for sidecar in sorted(root.glob(GLOB)):
        data = tomllib.loads(sidecar.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            message = f"{sidecar}: schema is {data.get('schema')!r}, not {SCHEMA!r}"
            raise SystemExit(message)
        fixture = sidecar.with_name(sidecar.name.removesuffix(".assertions.toml"))
        for index, body in enumerate(data.get("assertion", []), start=1):
            out.append(Claim(sidecar, fixture, index, body))
    return out


def review(root: Path) -> list[Row]:
    cache: dict[Path, Evidence] = {}
    rows = []
    for claim in claims(root):
        if claim.fixture not in cache:
            cache[claim.fixture] = read_evidence(claim.fixture)
        rows.append(judge(claim, cache[claim.fixture]))
    return rows


def _posix(path: Path, root: Path) -> str:
    """The path a reviewer and a verdict file both name it by: relative to the root, with /."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def bundle(rows: Sequence[Row], root: Path = ROOT) -> dict[str, Any]:
    """The review page's input: one JSON object per label, grouped by fixture."""
    fixtures: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _posix(row.claim.fixture, root)
        group = fixtures.setdefault(
            key,
            {
                "fixture": key,
                "sidecar": _posix(row.claim.sidecar, root),
                "origin": row.evidence.origin,
                "labels": [],
            },
        )
        group["labels"].append(
            {
                "id": row.claim.id,
                "type": row.claim.type,
                "page": row.claim.page,
                "claim": row.claim.sentence,
                "toml": {k: v for k, v in row.claim.body.items() if k != "slices"},
                "slices": list(row.claim.body.get("slices", [])),
                "checked": row.claim.checked,
                "agrees": row.agrees,
                "why": row.why,
                "excerpt": list(row.excerpt),
            }
        )
    return {
        "schema": "omniweave.label-review/1",
        "note": "agrees is this tool's arithmetic over the fixture bytes, not a reviewer's verdict",
        "fixtures": list(fixtures.values()),
    }


STRUCTURE_SUFFIX: Final = ".structure.jsonl"


def _document_verdict(path: str, sidecar: Path, verdict: str) -> str:
    """One verdict for a whole file: the structure references' shape, and only theirs."""
    if not sidecar.name.endswith(STRUCTURE_SUFFIX):
        message = (
            f"{path}: one verdict for the whole file is the structure references' shape; "
            "an assertions sidecar takes one verdict per row"
        )
        raise SystemExit(message)
    if verdict not in VERDICTS:
        message = f"{path}: {verdict!r} is not one of {VERDICTS}"
        raise SystemExit(message)
    return verdict


def _row_verdicts(path: str, sidecar: Path, rows: Mapping[str, Any]) -> dict[str, str]:
    """One verdict per row: the assertions sidecars' shape, and only theirs."""
    if sidecar.name.endswith(STRUCTURE_SUFFIX):
        message = (
            f"{path}: a structure reference takes ONE verdict for the document, not one per "
            "row (structure ruling 3: a precision denominator does not sign one claim)"
        )
        raise SystemExit(message)
    out: dict[str, str] = {}
    for label, verdict in dict(rows).items():
        if verdict not in VERDICTS:
            message = f"{path}:{label}: {verdict!r} is not one of {VERDICTS}"
            raise SystemExit(message)
        out[label] = verdict
    return out


def apply_verdicts(root: Path, verdicts: Mapping[str, Any]) -> list[str]:
    """Write the reviewer's `checked` values into the sidecars. Only theirs, only the two values.

    A verdict file is `{"<sidecar path>": {"<assertion id>": "verified" | "rejected"}}` for an
    assertions sidecar, and `{"<reference path>": "verified" | "rejected"}` for a structure
    reference -- a STRING rather than a mapping, because `structure` ruling 3's signature unit is
    the document and a per-row verdict there would be a shape this file accepted and the metric
    ignored. The value's shape chooses, so neither spelling needs a flag and the wrong one for a
    file is refused by name.

    An id the sidecar does not carry, or a value outside section 8.1's two, stops the whole write:
    every file is staged in memory and nothing reaches disk until all of them parse, because a
    half-applied review is worse than none.
    """
    by_sidecar: dict[Path, dict[str, str]] = {}
    by_document: dict[Path, str] = {}
    for path, rows in verdicts.items():
        if path in {"schema", "note"}:
            continue
        sidecar = root / path
        if not sidecar.is_file():
            message = f"no such sidecar: {path}"
            raise SystemExit(message)
        if isinstance(rows, str):
            by_document[sidecar] = _document_verdict(path, sidecar, rows)
        else:
            by_sidecar[sidecar] = _row_verdicts(path, sidecar, rows)
    staged: list[tuple[Path, bytes, int]] = []
    for sidecar, rows in sorted(by_sidecar.items()):
        text = sidecar.read_text(encoding="utf-8")
        data = tomllib.loads(text)
        known = {str(row.get("id")) for row in data.get("assertion", [])}
        unknown = sorted(set(rows) - known)
        if unknown:
            message = f"{sidecar.name}: no such assertion id: {', '.join(unknown)}"
            raise SystemExit(message)
        for label, verdict in rows.items():
            text = _stamp(text, label, verdict)
        staged.append((sidecar, text.encode("utf-8"), len(rows)))
    said: list[tuple[Path, bytes, str]] = []
    for sidecar, verdict in sorted(by_document.items()):
        blob, count = signed_document(sidecar, verdict)
        said.append((sidecar, blob, f"{count} row(s) {verdict} (the whole document)"))
    written = []
    for sidecar, blob, count in staged:
        sidecar.write_bytes(blob)
        written.append(f"{sidecar.relative_to(root)}: {count} signed")
    for sidecar, blob, line in said:
        sidecar.write_bytes(blob)
        written.append(f"{sidecar.relative_to(root)}: {line}")
    return written


def _stamp(text: str, label: str, verdict: str) -> str:
    """Append or replace one row's `checked`, leaving every other byte of the file alone.

    The sidecars are hand-written and commented, and a reviewer's signature is not a reason to
    reformat them -- so this edits the row's own lines rather than re-emitting the document.
    """
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == f'id = "{label}"'),
        None,
    )
    if start is None:
        message = f'{label}: no `id = "{label}"` line to sign'
        raise SystemExit(message)
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[[")),
        len(lines),
    )
    newline = "\r\n" if lines[start].endswith("\r\n") else "\n"
    for index in range(start, end):
        if lines[index].lstrip().startswith("checked"):
            lines[index] = f'checked = "{verdict}"{newline}'
            return "".join(lines)
    tail = end
    while tail > start and not lines[tail - 1].strip():
        tail -= 1
    lines.insert(tail, f'checked = "{verdict}"{newline}')
    return "".join(lines)


@dataclass(frozen=True, slots=True)
class Reference:
    """One row of a `*.structure.jsonl`: 13:1104's tuple, and the document it describes."""

    sidecar: Path
    fixture: Path
    id: str
    page: int
    kind: str
    layer: str
    parent_kind: str | None
    text: str
    checked: str | None

    @property
    def sentence(self) -> str:
        """The row in one line, in a reviewer's language: what to look for, and where."""
        under = "with no parent" if self.parent_kind is None else f"under a {self.parent_kind}"
        return (
            f'on page {self.page}, in the {self.layer} layer, "{self.text}" '
            f"is a {self.kind} {under}"
        )


@dataclass(frozen=True, slots=True)
class Reading:
    """One reference row against the fixture's own bytes. `agrees` is about the TEXT alone."""

    reference: Reference
    evidence: Evidence
    at: int | None
    agrees: bool | None
    why: str
    excerpt: tuple[str, ...] = field(default=())

    @property
    def judged(self) -> str:
        """What a reviewer still has to decide, stated on the row rather than in a preamble."""
        return (
            f"kind={self.reference.kind} layer={self.reference.layer} "
            f"parent_kind={self.reference.parent_kind} -- not judged here (13:1104)"
        )


def references(root: Path = ROOT) -> list[Reference]:
    """Every structure reference row in the tree, in document then row order.

    The first line is the schema header and is not a row. A file whose header is missing or
    unknown raises: a reference with no version is one whose shape cannot be changed later, which
    is `structure` ruling 1's reason for the header, and skipping it silently would hand a
    reviewer rows out of a file nothing else will read.
    """
    out: list[Reference] = []
    for sidecar in sorted(root.glob(STRUCTURE_GLOB)):
        lines = [line for line in sidecar.read_text(encoding="utf-8").splitlines() if line.strip()]
        header = json.loads(lines[0]) if lines else {}
        if header.get("schema") != STRUCTURE_SCHEMA:
            message = f"{sidecar.name}: first line is not {STRUCTURE_SCHEMA!r}"
            raise SystemExit(message)
        fixture = sidecar.with_name(sidecar.name.removesuffix(".structure.jsonl"))
        for line in lines[1:]:
            row = json.loads(line)
            parent = row.get("parent_kind")
            out.append(
                Reference(
                    sidecar=sidecar,
                    fixture=fixture,
                    id=str(row.get("id", "?")),
                    page=int(row.get("page", 0)),
                    kind=str(row.get("kind", "?")),
                    layer=str(row.get("layer", "?")),
                    parent_kind=None if parent is None else str(parent),
                    text=str(row.get("text", "")),
                    checked=None if row.get("checked") is None else str(row["checked"]),
                )
            )
    return out


def reading_order(evidence: Evidence, page: int) -> tuple[str, ...]:
    """The strings the page carries, in the order the bytes carry them.

    A spreadsheet's grid and a document's runs are one sequence here on purpose: a reference row
    says "this text, at this kind", and whether the text arrived as a paragraph or as a cell is
    the `parent_kind` column's business and not this sequence's.
    """
    if evidence.pages and len(evidence.pages) >= page:
        return evidence.pages[page - 1]
    return (*evidence.runs, *_flat(evidence.grid))


def _folded(values: Sequence[str]) -> list[str]:
    return [normalize_eval(value) for value in values]


def read_structure(root: Path = ROOT) -> list[Reading]:
    """Every reference row judged on its text and its position, document by document.

    One `read_evidence` per fixture, not per row: the readers unzip and parse, and 59 rows over ten
    documents would otherwise be 59 reads of the same ten files.
    """
    out: list[Reading] = []
    cache: dict[Path, Evidence] = {}
    seen: dict[Path, int] = {}
    for reference in references(root):
        evidence = cache.setdefault(reference.fixture, read_evidence(reference.fixture))
        if evidence.unreadable is not None:
            out.append(Reading(reference, evidence, None, None, evidence.unreadable))
            continue
        order = reading_order(evidence, reference.page)
        folded = _folded(order)
        wanted = normalize_eval(reference.text)
        at = next((index for index, value in enumerate(folded) if value == wanted), None)
        if at is None:
            at = next((index for index, value in enumerate(folded) if wanted in value), None)
            exact = False
        else:
            exact = True
        if at is None:
            out.append(_unmatched(reference, evidence, order, folded))
            continue
        previous = seen.get(reference.sidecar)
        backwards = previous is not None and at < previous
        seen[reference.sidecar] = at
        how = "exactly" if exact else "inside a longer string"
        why = f"found {how} at position {at} of {len(order)} in the document's own order"
        if backwards:
            why += f", BEFORE the previous row's {previous}: the reference is out of order"
        out.append(Reading(reference, evidence, at, not backwards, why, excerpt=(order[at],)))
    return out


TRANSCRIBED: Final[tuple[tuple[str, str, str, str], ...]] = (
    (
        "packages/omniweave-office/fixtures/rich.docx.structure.jsonl",
        "s04",
        "x2+1",
        "x^{2}+1",
    ),
    (
        "packages/omniweave-office/fixtures/rich.docx.structure.jsonl",
        "s05",
        "The ratio ab",
        "The ratio \\frac{a}{b}",
    ),
)
"""The reference rows no byte reader can confirm, each with what the bytes say. **D1001.**

Both are `rich.docx` OMML. `<m:sSup>` over the text leaves `x`, `2` and `+1` is a superscript,
and the string a parser emits for it is a transcription in some notation; the bytes carry `x2+1`
and the row carries `x^{2}+1`. A reader with no renderer cannot decide whether that notation is
the right one, and that is the judgement the reviewer's signature is for.

**Declared rather than tolerated, and checked in BOTH directions.** A transcription this tuple
does not name is a finding, so a new one cannot arrive unnoticed; a row named here that becomes
literally matchable is also a finding, because a declaration that stopped being true is a comment.
Without the declaration the tool would exit 2 over this tree for ever, and an exit code that can
never be zero says nothing at all."""

_LETTERS: Final = re.compile(r"[^0-9A-Za-z]+")


def letters(text: str) -> str:
    """A string with every non-alphanumeric character dropped. The transcription comparison."""
    return _LETTERS.sub("", text)


def _transcribes(said: str, wanted: str) -> bool:
    """Whether `wanted` could be a transcription of `said`: every letter of `said`, in order.

    A notation adds characters and never drops them -- `x2+1` becomes `x^{2}+1`, and
    `The ratio ab` becomes `The ratio \\frac{a}{b}` where `frac` is the command's name and not
    content. So the test is a SUBSEQUENCE and not equality, which is permissive enough to be wrong
    on its own: it is only ever asked about an index in `Evidence.derived`, a paragraph the reader
    has seen carry markup its text leaves do not spell. Everywhere else, a row that is not in the
    bytes is a row that disagrees with them.
    """
    walk = iter(wanted)
    return all(character in walk for character in letters(said))


def _unmatched(
    reference: Reference,
    evidence: Evidence,
    order: Sequence[str],
    folded: Sequence[str],
) -> Reading:
    """A row whose text is in no string of the page: wrong, or a transcription. **D1001.**

    Two of `rich.docx`'s rows are neither wrong nor readable. The file writes `x^{2}+1` as OMML --
    `<m:sSup>` over the text leaves `x`, `2` and `+1` -- so the bytes carry `x2+1` and the
    reference carries the notation a parser is expected to emit for it. No byte-level reader can
    confirm that transcription, and calling it a DISAGREEMENT would send a reviewer to check a row
    that is very likely right while saying nothing about the one thing that is actually in doubt.

    So a row whose letters and digits match a string on the page, with only notation between them,
    is reported as **no evidence** rather than as a disagreement: this file prints what the bytes
    say beside what the row says and leaves the judgement where 13:1104 puts it. `agrees is None`
    is already this file's third state and already exits 2, *"because an unreadable row is one a
    reviewer would have to take on trust"* -- which is exactly what a transcription is.
    """
    wanted = letters(normalize_eval(reference.text))
    near = next(
        (
            index
            for index in evidence.derived
            if wanted and index < len(folded) and _transcribes(folded[index], wanted)
        ),
        None,
    )
    if near is not None:
        return Reading(
            reference,
            evidence,
            near,
            None,
            f"the bytes at position {near} say {order[near]!r} and the row says "
            f"{reference.text!r}: the same letters and digits with different notation, so this "
            "is a transcription no byte reader can confirm -- check it against a render",
            excerpt=(order[near],),
        )
    return Reading(
        reference,
        evidence,
        None,
        False,
        f"page {reference.page} carries no text folding to {reference.text!r} "
        f"({len(order)} string(s) read)",
        excerpt=tuple(order[:12]),
    )


def transcription_findings(readings: Sequence[Reading], root: Path = ROOT) -> list[str]:
    """`TRANSCRIBED` against what was read, both ways. An empty list is the declaration holding."""
    declared = {(path, label): (said, says) for path, label, said, says in TRANSCRIBED}
    found: dict[tuple[str, str], Reading] = {
        (_posix(one.reference.sidecar, root), one.reference.id): one
        for one in readings
        if one.agrees is None
    }
    out: list[str] = []
    for key in sorted(set(found) - set(declared)):
        out.append(f"{key[0]} {key[1]}: unconfirmable and not in TRANSCRIBED -- {found[key].why}")
    for key in sorted(set(declared) - set(found)):
        #  A declaration names a file of THIS repository, so a root that does not hold it is a
        #  different tree -- a fixture root in `tmp_path`, which the tests build -- and has
        #  nothing to say about it. A root that DOES hold it and reads it cleanly is the stale
        #  direction, and that is the one worth failing.
        if not (root / key[0]).is_file():
            continue
        reading = next(
            (
                one
                for one in readings
                if (_posix(one.reference.sidecar, root), one.reference.id) == key
            ),
            None,
        )
        became = "is gone from its reference" if reading is None else f"now reads {reading.agrees}"
        out.append(
            f"{key[0]} {key[1]}: declared a transcription and {became} -- delete the row from "
            "TRANSCRIBED, or mend the reference"
        )
    for key, (said, says) in sorted(declared.items()):
        one = found.get(key)
        if one is None:
            continue
        actual = one.excerpt[0] if one.excerpt else ""
        if actual != said or one.reference.text != says:
            out.append(
                f"{key[0]} {key[1]}: TRANSCRIBED records {said!r} against {says!r}; the tree has "
                f"{actual!r} against {one.reference.text!r}"
            )
    return out


def documents(readings: Sequence[Reading]) -> dict[Path, list[Reading]]:
    """The readings grouped by the file that takes the verdict, in tree order."""
    grouped: dict[Path, list[Reading]] = {}
    for reading in readings:
        grouped.setdefault(reading.reference.sidecar, []).append(reading)
    return grouped


def structure_bundle(readings: Sequence[Reading], root: Path = ROOT) -> dict[str, Any]:
    """The review page's second input: one object per DOCUMENT, because that is the unit signed."""
    out: list[dict[str, Any]] = []
    for sidecar, group in documents(readings).items():
        first = group[0].reference
        signed = {reading.reference.checked for reading in group}
        out.append(
            {
                "fixture": _posix(first.fixture, root),
                "reference": _posix(sidecar, root),
                "origin": group[0].evidence.origin,
                "checked": sorted(one for one in signed if one) or None,
                "rows": [
                    {
                        "id": reading.reference.id,
                        "page": reading.reference.page,
                        "kind": reading.reference.kind,
                        "layer": reading.reference.layer,
                        "parent_kind": reading.reference.parent_kind,
                        "text": reading.reference.text,
                        "claim": reading.reference.sentence,
                        "checked": reading.reference.checked,
                        "agrees": reading.agrees,
                        "at": reading.at,
                        "why": reading.why,
                        "excerpt": list(reading.excerpt),
                    }
                    for reading in group
                ],
            }
        )
    return {
        "schema": "omniweave.structure-review/1",
        "note": (
            "agrees is this tool's arithmetic over the fixture bytes and covers the TEXT and its "
            "position only; (kind, layer, parent_kind) is the reviewer's judgement against a "
            "render (13:1104). The verdict is per DOCUMENT (structure ruling 3)."
        ),
        "documents": out,
    }


def signed_document(sidecar: Path, verdict: str) -> tuple[bytes, int]:
    """A `*.structure.jsonl` with one verdict on every row, as bytes. Writes nothing.

    Ruling 3's unit is the document, so one value reaches every row, and a row already carrying
    the other verdict is overwritten: a reviewer signing a document again has changed their mind,
    which they are allowed to do, and a mixed file is what ruling 3 forbids. Staged rather than
    written for the reason `apply_verdicts` stages the sidecars -- a half-applied review is worse
    than none -- and `json.dumps`' default separators are the ones these files already use, so a
    row the verdict does not change round-trips byte for byte.
    """
    lines = sidecar.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    signed = 0
    for index, line in enumerate(lines):
        if index == 0 or not line.strip():
            out.append(line)
            continue
        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        row = json.loads(line)
        row["checked"] = verdict
        out.append(json.dumps(row, ensure_ascii=False) + newline)
        signed += 1
    return "".join(out).encode("utf-8"), signed


def structure_report(readings: Sequence[Reading], *, per_row: bool) -> None:
    for sidecar, group in documents(readings).items():
        agree = sum(1 for one in group if one.agrees is True)
        disagree = sum(1 for one in group if one.agrees is False)
        unknown = sum(1 for one in group if one.agrees is None)
        signed = sorted({one.reference.checked for one in group if one.reference.checked})
        _say(
            f"{sidecar.name:34s} {len(group):3d} rows  "
            f"text agrees {agree:3d}  disagrees {disagree}  no-evidence {unknown}  "
            f"signed {','.join(signed) or 'no'}"
        )
        if not per_row:
            continue
        for one in group:
            mark = {True: "agrees  ", False: "DISAGREE", None: "no-evid."}[one.agrees]
            _say(f"    {mark}  {one.reference.id:5s} {one.why}")
    total = len(readings)
    files = len(documents(readings))
    fully = sum(
        1
        for group in documents(readings).values()
        if group and all(one.reference.checked == "verified" for one in group)
    )
    _say(
        f"\n{total} structure reference row(s) over {files} document(s): "
        f"{sum(1 for one in readings if one.agrees is True)} agree with the bytes on text and "
        f"order, {sum(1 for one in readings if one.agrees is False)} do not, "
        f"{len(TRANSCRIBED)} are declared transcriptions. "
        f"{fully} document(s) are fully verified and therefore score (structure ruling 3)."
    )


def _summary(rows: Sequence[Row]) -> tuple[int, int, int]:
    agree = sum(1 for row in rows if row.agrees is True)
    disagree = sum(1 for row in rows if row.agrees is False)
    unknown = sum(1 for row in rows if row.agrees is None)
    return agree, disagree, unknown


def _mark(row: Row) -> str:
    return {True: "agrees  ", False: "DISAGREE", None: "no-evid."}[row.agrees]


def report(rows: Sequence[Row], *, per_row: bool) -> None:
    by_fixture: dict[Path, list[Row]] = {}
    for row in rows:
        by_fixture.setdefault(row.claim.fixture, []).append(row)
    for fixture, group in by_fixture.items():
        agree, disagree, unknown = _summary(group)
        signed = sum(1 for row in group if row.claim.checked)
        _say(
            f"{fixture.name:22s} {len(group):3d} labels  "
            f"agrees {agree:3d}  disagrees {disagree}  no-evidence {unknown}  "
            f"signed {signed}"
        )
        if not per_row:
            continue
        for row in group:
            _say(f"    {_mark(row)}  {row.claim.id:22s} {row.why}")
    agree, disagree, unknown = _summary(rows)
    _say(
        f"\n{len(rows)} labels over {len(by_fixture)} fixtures: "
        f"{agree} agree with the bytes, {disagree} disagree, {unknown} have no evidence. "
        f"{sum(1 for row in rows if row.claim.checked)} carry a reviewer's signature."
    )


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _verdict_controls(key: str, label: str = "") -> str:
    """Two radios and a clear, keyed by what `--apply` will be told. The page's only inputs.

    `key` is `"<path>::<row id>"` for an assertion and `"<path>"` for a structure reference, which
    is the same distinction `apply_verdicts` makes by the value's shape -- so the exported file is
    the shape that file already accepts, and nothing here invents a second grammar.
    """
    name = _esc(key)
    said = f"<span class=signlabel>{_esc(label)}</span>" if label else ""
    return (
        f'<span class=verdict data-key="{name}">{said}'
        f'<label><input type=radio name="v::{name}" value=verified> verified</label>'
        f'<label><input type=radio name="v::{name}" value=rejected> rejected</label>'
        f'<button type=button class=clear title="unset">&times;</button></span>'
    )


_EXPORT: Final = """
<section id=export><h2>Your verdicts</h2>
<p class=lede>Paste this into a file and run
<code>uv run tools/label_review.py --apply &lt;that file&gt;</code>. A structure reference takes one
verdict for the whole document and an assertions sidecar one per row, which is why the two read
differently below. Nothing is written until you run that command.</p>
<p class=counts id=counts></p>
<pre id=out>{}</pre>
<button type=button id=copy>copy</button>
</section>
"""

_SCRIPT: Final = """
const KEY = 'omniweave.label-review.verdicts';
let state = {};
try { state = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch (e) { state = {}; }

function render() {
  const out = {};
  let rows = 0, docs = 0;
  for (const [key, verdict] of Object.entries(state)) {
    if (!verdict) continue;
    const [path, row] = key.split('::');
    if (row === undefined) { out[path] = verdict; docs += 1; }
    else { (out[path] = out[path] || {})[row] = verdict; rows += 1; }
  }
  document.getElementById('out').textContent = JSON.stringify(out, null, 2);
  document.getElementById('counts').textContent =
    docs + ' document(s) and ' + rows + ' assertion(s) signed on this page.';
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* private window */ }
}

for (const span of document.querySelectorAll('.verdict')) {
  const key = span.dataset.key;
  for (const input of span.querySelectorAll('input')) {
    if (state[key] === input.value) input.checked = true;
    input.addEventListener('change', () => { state[key] = input.value; render(); });
  }
  span.querySelector('.clear').addEventListener('click', () => {
    for (const input of span.querySelectorAll('input')) input.checked = false;
    delete state[key];
    render();
  });
}
document.getElementById('copy').addEventListener('click', async () => {
  const button = document.getElementById('copy');
  try {
    await navigator.clipboard.writeText(document.getElementById('out').textContent);
    button.textContent = 'copied';
  } catch (e) { button.textContent = 'select the text above'; }
  setTimeout(() => { button.textContent = 'copy'; }, 1800);
});
render();
"""


def _structure_sections(data: Mapping[str, Any]) -> list[str]:
    """The structure half of the review page: one section per DOCUMENT, one verdict per section."""
    out: list[str] = []
    rows = sum(len(group["rows"]) for group in data["documents"])
    out.append("<header class=second><h1>Structure references</h1>")
    out.append(
        f"<p class=lede>{rows} reference rows over {len(data['documents'])} documents, each a "
        "<code>(page, kind, layer, parent_kind, text)</code> tuple that "
        "<code>structure_f1</code> scores a parse against. <strong>The verdict is per "
        "document, not per row</strong>: one unsigned row makes every unmatched prediction "
        "unjudgeable, so a part-signed reference is reported unscored rather than scored over "
        "its signed part. <strong>What is checked below is the text and its position</strong> "
        "&mdash; found in the bytes, in the reference's own order. <strong>What is not is the "
        "triple</strong>: whether that string is a heading rather than a paragraph, and what it "
        "sits under, is a reading of a render, and it is the whole of what your signature "
        "says.</p></header>"
    )
    for group in data["documents"]:
        out.append(f"<section><h2>{_esc(group['fixture'])}</h2>")
        signed = ", ".join(group["checked"] or []) or "unsigned"
        out.append(
            f"<p class=origin>evidence: {_esc(group['origin'])} &middot; reference: "
            f"<code>{_esc(group['reference'])}</code> &middot; {_esc(signed)}</p>"
        )
        out.append(
            "<div class=sign>"
            + _verdict_controls(group["reference"], label="this document, every row:")
            + "</div>"
        )
        for row in group["rows"]:
            agrees = row["agrees"]
            state = "agrees" if agrees else ("disagrees" if agrees is False else "unknown")
            out.append(f"<article class={state}>")
            out.append(
                f"<div class=head><code>{_esc(row['id'])}</code>"
                f"<span class=type>{_esc(row['kind'])} / {_esc(row['layer'])}</span>"
                f"<span class=type>under {_esc(row['parent_kind'])}</span>"
                f"<span class=badge>{_esc(state)}</span></div>"
            )
            out.append(f"<p class=claim>{_esc(row['claim'])}</p>")
            out.append(f"<p class=why>{_esc(row['why'])}</p>")
            if row["excerpt"]:
                rendered = "\n".join(_esc(line) for line in row["excerpt"])
                out.append(f"<pre class=excerpt>{rendered}</pre>")
            out.append("</article>")
        out.append("</section>")
    return out


def page_html(data: Mapping[str, Any], structure: Mapping[str, Any] | None = None) -> str:
    """The review page: one row per label, with the evidence beside the claim.

    Written as a file so it can be published and worked through away from a terminal. The verdict
    controls are the page's; this file never fills one in. `structure` adds the second population,
    whose unit is the document rather than the row.
    """
    out: list[str] = []
    labels = sum(len(group["labels"]) for group in data["fixtures"])
    #  A whole document, not a fragment: the page is written to a file and opened in a browser,
    #  and without the doctype it renders in quirks mode, where the width query that lays the
    #  verdict controls out on a phone never fires.
    out.append("<!doctype html>")
    out.append('<meta charset="utf-8">')
    out.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    out.append("<title>Label Review</title>")
    out.append(f"<style>{_CSS}</style>")
    out.append("<main><header><h1>Label review</h1>")
    out.append(
        f"<p class=lede>{labels} drafted assertions over {len(data['fixtures'])} fixtures. "
        "Every claim was drafted from a generator's text functions and none is signed. "
        "The evidence beside each one is read off the committed fixture bytes by "
        "<code>tools/label_review.py</code>'s own readers, never through an omniweave driver. "
        "<strong>agrees</strong> is that tool's arithmetic, not a verdict: a row counts toward an "
        "accuracy floor only once you sign it.</p></header>"
    )
    for group in data["fixtures"]:
        out.append(f"<section><h2>{_esc(group['fixture'])}</h2>")
        out.append(f"<p class=origin>evidence: {_esc(group['origin'])}</p>")
        for label in group["labels"]:
            agrees = label["agrees"]
            state = "agrees" if agrees else ("disagrees" if agrees is False else "unknown")
            out.append(
                f'<article class={state} data-file="{_esc(group["sidecar"])}" '
                f'data-row="{_esc(label["id"])}">'
            )
            out.append(
                f"<div class=head><code>{_esc(label['id'])}</code>"
                f"<span class=type>{_esc(label['type'])}</span>"
                f"<span class=badge>{_esc(state)}</span>"
                + _verdict_controls(f"{group['sidecar']}::{label['id']}")
                + "</div>"
            )
            out.append(f"<p class=claim>{_esc(label['claim'])}</p>")
            out.append(f"<p class=why>{_esc(label['why'])}</p>")
            if label["excerpt"]:
                rendered = "\n".join(_esc(line) for line in label["excerpt"])
                out.append(f"<pre class=excerpt>{rendered}</pre>")
            out.append("</article>")
        out.append("</section>")
    if structure is not None:
        out.extend(_structure_sections(structure))
    out.append(_EXPORT)
    out.append("</main>")
    out.append(f"<script>{_SCRIPT}</script>")
    return "\n".join(out)


_CSS: Final = """
:root { --ink:#17181c; --dim:#5b6070; --line:#dfe1e8; --bg:#fbfbfd; --card:#fff;
        --ok:#1f7a4d; --bad:#b4232b; --unk:#8a6d00; }
:root:not([data-theme=light]) { }
@media (prefers-color-scheme: dark) { :root:not([data-theme=light]) {
  --ink:#e8e9ee; --dim:#a0a5b5; --line:#2c2f3a; --bg:#13141a; --card:#1a1c23;
  --ok:#5fd398; --bad:#ff8a8a; --unk:#e0c14a; } }
:root[data-theme=dark] { --ink:#e8e9ee; --dim:#a0a5b5; --line:#2c2f3a; --bg:#13141a;
  --card:#1a1c23; --ok:#5fd398; --bad:#ff8a8a; --unk:#e0c14a; }
body { background:var(--bg); color:var(--ink); font:15px/1.55 ui-sans-serif,system-ui,sans-serif; }
main { max-width:62rem; margin:0 auto; padding:2.5rem 1.25rem 6rem; }
h1 { font-size:1.6rem; margin:0 0 .5rem; letter-spacing:-.01em; }
h2 { font-size:1rem; font-family:ui-monospace,monospace; margin:2.5rem 0 .25rem; }
header.second { border-top:1px solid var(--line); margin-top:4rem; padding-top:2rem; }
.verdict { display:inline-flex; gap:.55rem; align-items:center; margin-left:auto;
  font-size:.8rem; color:var(--dim); }
.verdict label { display:inline-flex; gap:.2rem; align-items:center; cursor:pointer; }
.verdict input { accent-color:var(--ok); margin:0; }
.verdict .clear { background:none; border:1px solid var(--line); border-radius:999px;
  color:var(--dim); cursor:pointer; font-size:.78rem; line-height:1; padding:.15rem .4rem; }
.sign { background:var(--card); border:1px solid var(--line); border-radius:8px;
  margin:.5rem 0 .75rem; padding:.5rem .9rem; }
.signlabel { color:var(--ink); font-weight:600; }
#export { border-top:1px solid var(--line); margin-top:4rem; padding-top:2rem; }
#export pre { background:var(--card); border:1px solid var(--line); border-radius:8px;
  font-size:.8rem; max-height:22rem; overflow:auto; padding:.7rem .9rem; }
#copy { background:var(--card); border:1px solid var(--line); border-radius:6px; color:var(--ink);
  cursor:pointer; font:inherit; font-size:.85rem; margin-top:.5rem; padding:.35rem .8rem; }
@media (max-width:40rem) { .verdict { margin-left:0; width:100%; } }
.lede { color:var(--dim); max-width:46rem; }
.origin { color:var(--dim); font-size:.84rem; margin:0 0 .75rem; }
article { background:var(--card); border:1px solid var(--line); border-left-width:3px;
  border-radius:8px; padding:.7rem .9rem; margin:.5rem 0; }
article.agrees { border-left-color:var(--ok); }
article.disagrees { border-left-color:var(--bad); }
article.unknown { border-left-color:var(--unk); }
.head { display:flex; gap:.6rem; align-items:center; flex-wrap:wrap; }
.head code { font-weight:600; }
.type, .badge { font-size:.72rem; text-transform:uppercase; letter-spacing:.06em;
  color:var(--dim); border:1px solid var(--line); border-radius:999px; padding:.05rem .45rem; }
.claim { margin:.4rem 0 .2rem; }
.why { color:var(--dim); font-size:.86rem; margin:0; }
pre.excerpt { background:transparent; border:1px dashed var(--line); border-radius:6px;
  color:var(--dim); font-size:.8rem; margin:.5rem 0 0; overflow-x:auto; padding:.5rem .6rem; }
"""


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--rows", action="store_true", help="one line per label, not per fixture")
    parser.add_argument("--json", type=Path, help="write the evidence bundle here")
    parser.add_argument("--page", type=Path, help="write the review page here")
    parser.add_argument("--apply", type=Path, help="a reviewer's verdict file, written back")
    arguments = parser.parse_args(argv)

    if arguments.apply:
        verdicts = json.loads(arguments.apply.read_text(encoding="utf-8"))
        for line in apply_verdicts(arguments.root, verdicts):
            _say(line)
        return EXIT_CLEAN

    rows = review(arguments.root)
    readings = read_structure(arguments.root)
    if arguments.json:
        payload = {
            **bundle(rows, arguments.root),
            "structure": structure_bundle(readings, arguments.root),
        }
        arguments.json.write_bytes(
            (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")
        )
        _say(f"wrote {arguments.json}")
    if arguments.page:
        page = page_html(bundle(rows, arguments.root), structure_bundle(readings, arguments.root))
        arguments.page.write_bytes(page.encode("utf-8"))
        _say(f"wrote {arguments.page}")
    report(rows, per_row=arguments.rows)
    _say("")
    structure_report(readings, per_row=arguments.rows)
    undeclared = transcription_findings(readings, arguments.root)
    for line in undeclared:
        _say(f"  TRANSCRIBED: {line}")
    _, disagree, unknown = _summary(rows)
    disagree += sum(1 for one in readings if one.agrees is False)
    unknown -= sum(1 for row in rows if row.agrees is None and row.claim.type in DECLARED_UNJUDGED)
    if unknown or undeclared:
        return EXIT_NO_EVIDENCE
    if disagree:
        return EXIT_DISAGREES
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
