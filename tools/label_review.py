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
GLOB: Final = "packages/*/fixtures/*.assertions.toml"
SCHEMA: Final = "omniweave.assertions/1"
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
    """
    body = _RTF_HEADER.sub(" ", text)
    out = []
    for chunk in re.split(r"\\par\b", body):
        line = _RTF_WORD.sub(" ", chunk)
        line = re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", line)).strip()
        if line:
            out.append(line)
    return out


def _epub_blocks(path: Path) -> list[str]:
    out: list[str] = []
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
    document = _members(fixture, re.compile(r"^word/document\.xml$"))[0]
    runs = tuple(_paragraphs(document))
    return Evidence(
        "word/document.xml: paragraphs in document order, and the first table's cells",
        runs=runs,
        pages=(runs,),
        grid=tuple(tuple(row) for row in _docx_grid(document)),
    )


def _read_pptx(fixture: Path) -> Evidence:
    runs = tuple(
        line
        for data in _members(fixture, re.compile(r"^ppt/slides/slide\d+\.xml$"))
        for line in _paragraphs(data)
    )
    return Evidence("ppt/slides/slideN.xml: paragraphs, slide by slide", runs=runs, pages=(runs,))


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
    return Evidence("the spine's XHTML, tags stripped", runs=runs, pages=(runs,))


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


CHECKS: Final[Mapping[str, Callable[[Claim, Evidence], Row]]] = {
    "present": _check_present,
    "absent": _check_absent,
    "order": _check_order,
    "table": _check_table,
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


def apply_verdicts(root: Path, verdicts: Mapping[str, Any]) -> list[str]:
    """Write the reviewer's `checked` values into the sidecars. Only theirs, only the two values.

    A verdict file is `{"<sidecar path>": {"<assertion id>": "verified" | "rejected"}}`. An id the
    sidecar does not carry, or a value outside section 8.1's two, stops the whole write: every
    sidecar is staged in memory and nothing reaches disk until all of them parse, because a
    half-applied review is worse than none.
    """
    by_sidecar: dict[Path, dict[str, str]] = {}
    for path, rows in verdicts.items():
        if path in {"schema", "note"}:
            continue
        sidecar = root / path
        if not sidecar.is_file():
            message = f"no such sidecar: {path}"
            raise SystemExit(message)
        for label, verdict in dict(rows).items():
            if verdict not in VERDICTS:
                message = f"{path}:{label}: {verdict!r} is not one of {VERDICTS}"
                raise SystemExit(message)
            by_sidecar.setdefault(sidecar, {})[label] = verdict
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
    written = []
    for sidecar, blob, count in staged:
        sidecar.write_bytes(blob)
        written.append(f"{sidecar.relative_to(root)}: {count} signed")
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


def page_html(data: Mapping[str, Any]) -> str:
    """The review page: one row per label, with the evidence beside the claim.

    Written as a file so it can be published and worked through away from a terminal. The verdict
    controls are the page's; this file never fills one in.
    """
    out: list[str] = []
    labels = sum(len(group["labels"]) for group in data["fixtures"])
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
            out.append(f"<article class={state} id={_esc(group['fixture'])}--{_esc(label['id'])}>")
            out.append(
                f"<div class=head><code>{_esc(label['id'])}</code>"
                f"<span class=type>{_esc(label['type'])}</span>"
                f"<span class=badge>{_esc(state)}</span></div>"
            )
            out.append(f"<p class=claim>{_esc(label['claim'])}</p>")
            out.append(f"<p class=why>{_esc(label['why'])}</p>")
            if label["excerpt"]:
                rendered = "\n".join(_esc(line) for line in label["excerpt"])
                out.append(f"<pre class=excerpt>{rendered}</pre>")
            out.append("</article>")
        out.append("</section>")
    out.append("</main>")
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
    if arguments.json:
        arguments.json.write_bytes(
            (json.dumps(bundle(rows, arguments.root), indent=2, sort_keys=False) + "\n").encode(
                "utf-8"
            )
        )
        _say(f"wrote {arguments.json}")
    if arguments.page:
        arguments.page.write_bytes(page_html(bundle(rows, arguments.root)).encode("utf-8"))
        _say(f"wrote {arguments.page}")
    report(rows, per_row=arguments.rows)
    _, disagree, unknown = _summary(rows)
    if unknown:
        return EXIT_NO_EVIDENCE
    if disagree:
        return EXIT_DISAGREES
    return EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
