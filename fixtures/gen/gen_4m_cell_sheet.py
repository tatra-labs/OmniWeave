"""`gen_4m_cell_sheet.py` -- the merge-free 4M-cell spreadsheet, synthesised byte by byte. D929.

12-performance.md section 4.3 calls it *"the document that broke every proposal"*: one sheet, one
page, four million cells and no merged region, so every cell is a Block of its own and the
document is the worst case for one transaction, one worker's memory and one page's Block count.
Its consumers, all named by the plan and none built until now:

* **`rss.merged4mcell_peak_bytes`** (12:592, budget 4 GiB in a worker), the `rss` bench subject's
  second fixture (12:1480, 12:1516);
* **F29's spike** (12:668-679), a cell-count sweep at 0.5M / 1M / 2M / 4M / 8M cells on one page,
  which this generator's `--cells` serves;
* **`TABLE_SYNOPSIS_CELLS = 20_000`**, which any size here exceeds, so the table's embedding
  collapses to one synopsis segment (12:651-655).

## The shape

`COLUMNS` columns per row: column A is the text label `row <r>` and the rest are integers that are
a pure function of `(row, column)`, so **the content of row r does not depend on the cell count**
and a small sheet is byte for byte the first rows of a large one. That is the property that makes
the small pin a real signal about the large one, as `gen_5000p_pdf.py`'s pages are.

Inline strings and no `sharedStrings.xml`: a shared-string table would be a second part the
reader has to hold whole, which is a different worst case than the one the plan prices.

## Why the pin is a manifest and the archive is deflated

The office driver's card caps `max_input_bytes` at 64 MiB, and the sheet XML for 4M cells is
about 120 MB, so a stored archive would be refused before any reader ran. The members are
deflated. Deflate's bytes are not stable across zlib builds (CPython 3.14's Windows builds bundle
zlib-ng), so the pin is a MANIFEST, as `office-200`'s and the reference corpora's are: one
`sha256  member` line per archive member over its UNCOMPRESSED bytes, and `EXPECTED.sha256` pins
the manifest. A content change moves the pin; a compressor change does not.

## The regime, 13-quality.md:586-589

Deterministic with no clock, no `random`, no ids: every ZIP entry carries `ZIP_DATE`, and the
content is arithmetic. Output lands in `fixtures/generated/`, which is `.gitignore`d.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import zipfile
from pathlib import Path
from typing import Final

DEFAULT_CELLS: Final = 4_000_000
"""12-performance.md:651's *"merge-free 4M-cell spreadsheet"*."""

SMALL_CELLS: Final = 2_000
"""The cells `EXPECTED.sha256`'s cheap pin covers: 100 rows."""

COLUMNS: Final = 20
"""Cells per row. 4M cells is then 200,000 rows, inside every reader's row limit."""

ZIP_DATE: Final = (1980, 1, 1, 0, 0, 0)

SS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
XML: Final = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
SHEET: Final = "xl/worksheets/sheet1.xml"


def column(index: int) -> str:
    """The spreadsheet column name of zero-based `index`: 0 is A, 25 is Z, 26 is AA."""
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def row_xml(row: int) -> str:
    """One row's XML. A pure function of `row`, which is what makes the small pin a prefix."""
    cells = [f'<c r="A{row}" t="inlineStr"><is><t>row {row}</t></is></c>']
    cells.extend(
        f'<c r="{column(c)}{row}"><v>{(row * 31 + c * 7) % 100_000}</v></c>'
        for c in range(1, COLUMNS)
    )
    return f'<row r="{row}">{"".join(cells)}</row>'


def sheet_xml(cells: int) -> bytes:
    """The worksheet: `cells // COLUMNS` rows and no `mergeCells`."""
    rows = cells // COLUMNS
    out = io.StringIO()
    out.write(XML + f'<worksheet xmlns="{SS}"><sheetData>')
    for row in range(1, rows + 1):
        out.write(row_xml(row))
    out.write("</sheetData></worksheet>")
    return out.getvalue().encode("utf-8")


def _rels(*items: str) -> bytes:
    return (XML + f'<Relationships xmlns="{PR}">' + "".join(items) + "</Relationships>").encode()


def _rel(rid: str, kind: str, target: str) -> str:
    return (
        f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/{kind}" Target="{target}"/>'
    )


def members(cells: int) -> list[tuple[str, bytes]]:
    """The workbook's parts, in archive order, uncompressed. What the manifest is over."""
    types = (
        XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd'
        '.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd'
        '.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    ).encode()
    workbook = (
        XML + f'<workbook xmlns="{SS}" xmlns:r="{R}"><sheets>'
        '<sheet name="Data" sheetId="1" r:id="rId1"/></sheets></workbook>'
    ).encode()
    return [
        ("[Content_Types].xml", types),
        ("_rels/.rels", _rels(_rel("rId1", "officeDocument", "xl/workbook.xml"))),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", _rels(_rel("rId1", "worksheet", "worksheets/sheet1.xml"))),
        (SHEET, sheet_xml(cells)),
    ]


def manifest(parts: list[tuple[str, bytes]]) -> str:
    """`sha256  member` per part, over its uncompressed bytes. `EXPECTED.sha256` pins this."""
    return "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in parts)


def repo_root() -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {here}"
    raise RuntimeError(message)


def default_out(cells: int) -> Path:
    """`<repo>/fixtures/generated/sheet/sheet_{cells}c.xlsx`, `.gitignore`d."""
    return repo_root() / "fixtures" / "generated" / "sheet" / f"sheet_{cells}c.xlsx"


def generate(out: Path, *, cells: int = DEFAULT_CELLS) -> str:
    """Write the workbook to `out` and its manifest beside it; return the manifest text."""
    if cells < COLUMNS:
        message = f"cells must be at least one row of {COLUMNS}, got {cells}"
        raise ValueError(message)
    parts = members(cells)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0  # as on Windows, on any OS (D653)
            info.external_attr = 0o600 << 16
            archive.writestr(info, data)
    text = manifest(parts)
    out.with_suffix(".manifest").write_text(text, encoding="utf-8", newline="\n")
    return text


def main(argv: list[str] | None = None) -> int:
    """`python fixtures/gen/gen_4m_cell_sheet.py [--cells N] [--out PATH] [--print-sha256]`."""
    parser = argparse.ArgumentParser(
        prog="gen_4m_cell_sheet.py",
        description="Generate the merge-free N-cell sheet fixture (12-performance.md section 4.3).",
    )
    parser.add_argument("--cells", type=int, default=DEFAULT_CELLS, help="cell count")
    parser.add_argument("--out", type=Path, default=None, help="output path")
    parser.add_argument(
        "--print-sha256",
        action="store_true",
        help="also print one EXPECTED.sha256 line for this output's manifest",
    )
    args = parser.parse_args(argv)
    if args.cells < COLUMNS:
        sys.stderr.write(f"gen_4m_cell_sheet.py: --cells must be >= {COLUMNS}, got {args.cells}\n")
        return 2
    out: Path = args.out if args.out is not None else default_out(args.cells)
    text = generate(out, cells=args.cells)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    sys.stdout.write(f"path      {out}\n")
    sys.stdout.write(f"bytes     {out.stat().st_size}\n")
    sys.stdout.write(
        f"cells     {args.cells // COLUMNS * COLUMNS} ({args.cells // COLUMNS} rows)\n"
    )
    sys.stdout.write(f"manifest  {digest}\n")
    if args.print_sha256:
        relative = out.with_suffix(".manifest").relative_to(repo_root()).as_posix()
        sys.stdout.write(f"{digest}  {relative}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
