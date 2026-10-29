"""`fixtures/gen/gen_4m_cell_sheet.py`, the merge-free 4M-cell sheet (12-performance.md section
4.3), held to its pins and its shape. D929.

The pins are manifests over the members' uncompressed bytes, so they are portable across zlib
builds (the generator's docstring says why). The small pin is checked in a moment and the large
one in a few seconds; the content of a row does not depend on the cell count, which is what makes
the small pin a signal about the large one, and that property is a test of its own.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Final


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT: Final = _repo_root(Path(__file__).resolve())
GEN_PATH: Final = REPO_ROOT / "fixtures" / "gen" / "gen_4m_cell_sheet.py"
EXPECTED_PATH: Final = REPO_ROOT / "fixtures" / "gen" / "EXPECTED.sha256"


def _load(path: Path, name: str) -> ModuleType:
    """Load a `tools/` or `fixtures/gen/` script by path: a script, not a distribution.

    As `test_fixture_gen.py` loads `gen_5000p_pdf.py` and `test_gate_fixtures.py` loads the gate.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover -- both files are in this repo.
        message = f"cannot load {path}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen = _load(GEN_PATH, "omniweave_gen_4m_cell_sheet")
GATE = _load(REPO_ROOT / "tools" / "gate_fixtures.py", "_owsheet_gate_fixtures")
"""Q-G2's own `MAX_BINARY_BYTES`, so the cap this file measures against cannot drift from it."""


def _pin(cells: int) -> str:
    wanted = f"fixtures/generated/sheet/sheet_{cells}c.manifest"
    for line in EXPECTED_PATH.read_text(encoding="utf-8").splitlines():
        digest, _, path = line.partition("  ")
        if path == wanted and re.fullmatch(r"[0-9a-f]{64}", digest):
            return digest
    message = f"EXPECTED.sha256 pins no {wanted}"
    raise AssertionError(message)


def test_the_small_pin_is_the_manifest_of_a_freshly_generated_sheet(tmp_path: Path) -> None:
    text = gen.generate(tmp_path / "sheet.xlsx", cells=gen.SMALL_CELLS)
    assert hashlib.sha256(text.encode()).hexdigest() == _pin(gen.SMALL_CELLS)


def test_the_default_pin_is_the_manifest_of_the_four_million_cell_sheet(tmp_path: Path) -> None:
    """~6 s. A pin nothing checks is the silent corpus change arriving by the front door."""
    text = gen.generate(tmp_path / "sheet.xlsx", cells=gen.DEFAULT_CELLS)
    assert hashlib.sha256(text.encode()).hexdigest() == _pin(gen.DEFAULT_CELLS)
    assert (tmp_path / "sheet.xlsx").stat().st_size < 64 * 1024 * 1024, (
        "the office card's max_input_bytes would refuse it before any reader ran"
    )


def test_the_four_million_cell_archive_is_over_q_g2s_per_binary_cap(tmp_path: Path) -> None:
    """~6 s. Why this fixture is generated and never committed, as a measurement. D1010.

    13-quality.md:591 rules that the 4M-cell workbook is *"never in git"* and
    12-performance.md:1516 writes its size as *"generated"*. This is the arithmetic behind the
    ruling, and it is asserted rather than recorded so that a future compressor or a narrower
    `COLUMNS` cannot quietly turn a forced choice into an unexamined one.
    """
    gen.generate(tmp_path / "sheet.xlsx", cells=gen.DEFAULT_CELLS)
    size = (tmp_path / "sheet.xlsx").stat().st_size
    assert size > GATE.MAX_BINARY_BYTES, (
        f"{size} bytes now fits {GATE.MAX_BINARY_BYTES}; if this sheet can be committed, "
        "13-quality.md:591 and 12-performance.md:1516 are the rulings to revisit"
    )


def test_the_small_sheet_is_under_the_cap_so_the_refusal_is_about_size_alone(
    tmp_path: Path,
) -> None:
    """The other direction of D1010: the shape is committable, the cell count is not."""
    gen.generate(tmp_path / "sheet.xlsx", cells=gen.SMALL_CELLS)
    assert (tmp_path / "sheet.xlsx").stat().st_size < GATE.MAX_BINARY_BYTES


def test_the_manifest_is_over_uncompressed_bytes_so_the_archive_reads_back_to_it(
    tmp_path: Path,
) -> None:
    out = tmp_path / "sheet.xlsx"
    text = gen.generate(out, cells=gen.SMALL_CELLS)
    with zipfile.ZipFile(out) as archive:
        lines = [
            f"{hashlib.sha256(archive.read(name)).hexdigest()}  {name}\n"
            for name in archive.namelist()
        ]
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())
    assert "".join(lines) == text
    assert (tmp_path / "sheet.manifest").read_text(encoding="utf-8") == text


def test_a_rows_content_does_not_depend_on_the_cell_count() -> None:
    small = gen.sheet_xml(gen.SMALL_CELLS).decode()
    large = gen.sheet_xml(gen.SMALL_CELLS * 10).decode()
    rows = small.split("<sheetData>", 1)[1].split("</sheetData>", 1)[0]
    assert large.split("<sheetData>", 1)[1].startswith(rows)


def test_the_sheet_is_merge_free_and_every_row_holds_every_column() -> None:
    xml = gen.sheet_xml(gen.SMALL_CELLS).decode()
    assert "mergeCell" not in xml
    assert xml.count("<row ") == gen.SMALL_CELLS // gen.COLUMNS
    assert xml.count("<c ") == gen.SMALL_CELLS
    assert gen.row_xml(1).startswith('<row r="1"><c r="A1" t="inlineStr"><is><t>row 1</t>')
    assert f'<c r="{gen.column(gen.COLUMNS - 1)}1">' in gen.row_xml(1)


def test_column_names_carry_past_z() -> None:
    assert [gen.column(i) for i in (0, 25, 26, 27, 51, 52, 701, 702)] == [
        "A", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA",
    ]  # fmt: skip


def test_a_sheet_smaller_than_one_row_is_refused(tmp_path: Path) -> None:
    import pytest  # noqa: PLC0415

    with pytest.raises(ValueError, match="at least one row"):
        gen.generate(tmp_path / "sheet.xlsx", cells=gen.COLUMNS - 1)
