"""`tools/gate_frozen_stability.py`: Q-G4, the goldens' shapes held across cells. D849.

The ingest is a real `ow add` child under `--emit`, so it is replaced here, and the comparison
reads cells written under `tmp_path` against a small golden tree.
`test_frozen_stability_process.py`, in the conform tier, emits this machine's cell from a real
ingest and compares it.

Loaded by file path under a private name and at module scope, as `test_ow_golden.py` loads its
tool.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_frozen_stability.py"
    spec = importlib.util.spec_from_file_location("_owgate_frozen_stability", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
Cell = GATE.Cell
PDF = "core@2026.10/parse.pdf.pdfium@1/gen01p.pdf"
TXT = "core@2026.10/parse.text@1/notes.txt"
GOLDEN = {
    f"{PDF}.shape": "pages 2\nspans 14\n",
    f"{PDF}.pages": "1 7\n2 7\n",
    f"{TXT}.shape": "pages 1\nspans 3\n",
    f"{TXT}.outline": "h1 Notes\n",
}
SHAPES = {path: text for path, text in GOLDEN.items() if path.endswith(".shape")}
WIN = Cell("win32", "3.12", "153.0.7999.0")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    goldens = tmp_path / "root" / "fixtures" / "goldens"
    for path, text in GOLDEN.items():
        (goldens / path).parent.mkdir(parents=True, exist_ok=True)
        (goldens / path).write_bytes(text.encode())
    return tmp_path / "root"


@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    return tmp_path / "artifacts"


def _cells(artifacts: Path, *cells: Cell, tree: dict[str, str] = SHAPES) -> None:
    for cell in cells:
        GATE.emit(artifacts, cell, tree)


def _main(capsys: pytest.CaptureFixture[str], *argv: str, **kwargs: object) -> tuple[int, str]:
    code = GATE.main(list(argv), **kwargs)
    return code, capsys.readouterr().out


def _compare(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str], *argv: str
) -> tuple[int, str]:
    return _main(capsys, "--root", str(root), "--artifacts", str(artifacts), *argv)


def test_a_cell_is_named_by_its_os_python_and_pdfium() -> None:
    assert WIN.name == "win32-py3.12-pdfium153.0.7999.0"


def test_here_is_this_process() -> None:
    from pypdfium2.version import PDFIUM_INFO  # noqa: PLC0415

    cell = GATE.here()
    assert cell.os == sys.platform
    assert cell.python == f"{sys.version_info.major}.{sys.version_info.minor}"
    assert cell.pdfium == str(PDFIUM_INFO)
    assert cell.pdfium


def test_shapes_keeps_the_frozen_kind_only() -> None:
    assert GATE.shapes(GOLDEN) == SHAPES
    assert list(SHAPES) == [f"{PDF}.shape", f"{TXT}.shape"]


def test_emit_writes_the_cell_toml_and_the_shapes_and_nothing_else(tmp_path: Path) -> None:
    folder = GATE.emit(tmp_path, WIN, GOLDEN)
    assert folder == tmp_path / WIN.name
    written = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert written == sorted([GATE.CELL_FILE, *SHAPES])
    meta = tomllib.loads((folder / GATE.CELL_FILE).read_text(encoding="utf-8"))
    assert meta == {"os": "win32", "python": "3.12", "pdfium": "153.0.7999.0"}
    for path, text in SHAPES.items():
        assert (folder / path).read_bytes() == text.encode()


def test_an_emitted_cell_reads_back_as_itself(tmp_path: Path) -> None:
    folder = GATE.emit(tmp_path, WIN, GOLDEN)
    assert GATE._read_cell(folder) == (WIN, SHAPES)


@pytest.mark.parametrize(
    ("meta", "says"),
    [
        (None, "no readable cell.toml"),
        ("os = \n", "no readable cell.toml"),
        ('os = "win32"\npython = "3.12"\n', "cell.toml needs a non-empty os, python and pdfium"),
        (
            'os = "win32"\npython = ""\npdfium = "153"\n',
            "cell.toml needs a non-empty os, python and pdfium",
        ),
        (
            'os = "win32"\npython = 3.12\npdfium = "153"\n',
            "cell.toml needs a non-empty os, python and pdfium",
        ),
    ],
    ids=["missing", "malformed", "no-pdfium", "empty-python", "python-not-a-string"],
)
def test_a_cell_whose_metadata_does_not_read_is_refused(
    tmp_path: Path, meta: str | None, says: str
) -> None:
    folder = tmp_path / "anonymous"
    folder.mkdir()
    if meta is not None:
        (folder / GATE.CELL_FILE).write_bytes(meta.encode())
    with pytest.raises(ValueError, match=f"^anonymous: {says}"):
        GATE._read_cell(folder)


def test_compare_names_a_missing_an_extra_and_a_differing_shape() -> None:
    linux = Cell("linux", "3.13", "153.0.7999.0")
    found = {
        f"{PDF}.shape": "pages 2\nspans 15\n",
        "core@2026.10/parse.text@1/extra.txt.shape": "pages 1\n",
    }
    assert GATE.compare(SHAPES, {linux: found, WIN: dict(SHAPES)}) == [
        "linux-py3.13-pdfium153.0.7999.0: core@2026.10/parse.pdf.pdfium@1/gen01p.pdf.shape differs"
        " at line 2: 'spans 14' -> 'spans 15'",
        "linux-py3.13-pdfium153.0.7999.0: core@2026.10/parse.text@1/extra.txt.shape"
        " is not a golden",
        "linux-py3.13-pdfium153.0.7999.0: core@2026.10/parse.text@1/notes.txt.shape is missing",
    ]


def test_a_difference_past_the_shorter_text_is_at_its_length() -> None:
    longer = {**SHAPES, f"{TXT}.shape": SHAPES[f"{TXT}.shape"] + "tables 1\n"}
    assert GATE.compare(SHAPES, {WIN: longer}) == [f"{WIN.name}: {TXT}.shape differs at its length"]


def test_cells_are_compared_in_name_order() -> None:
    a, b = Cell("a", "3.12", "1"), Cell("b", "3.12", "1")
    lines = GATE.compare(SHAPES, {b: {}, a: {}})
    assert [line.split(":")[0] for line in lines] == [a.name, a.name, b.name, b.name]


def test_no_cells_means_the_gate_did_not_run(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _compare(root, artifacts, capsys)
    assert code == GATE.EXIT_NOT_RUN == 2
    assert out.splitlines() == [
        "Q-G4  2 golden shape(s); 0 cell(s): 0 pdfium build(s) of 2, 0 OS/Python cell(s) of 9",
        "Q-G4 DID NOT RUN  stability is not measured below 2 pdfium build(s) x 9 cell(s); "
        f"no cell under {artifacts}; run --emit in each",
    ]


def test_matching_cells_below_the_coverage_still_did_not_run(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cells(artifacts, WIN, Cell("linux", "3.12", "153.0.7999.0"))
    code, out = _compare(root, artifacts, capsys)
    assert code == 2
    assert out.splitlines() == [
        "Q-G4  2 golden shape(s); 2 cell(s): 1 pdfium build(s) of 2, 2 OS/Python cell(s) of 9",
        "Q-G4 DID NOT RUN  stability is not measured below 2 pdfium build(s) x 9 cell(s); "
        "every cell read matches",
    ]


def test_enough_matching_cells_pass(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cells(artifacts, WIN, Cell("win32", "3.12", "152.0.7900.0"), Cell("linux", "3.13", "1"))
    code, out = _compare(root, artifacts, capsys, "--pdfium-minors", "3", "--cells", "2")
    assert code == GATE.EXIT_CLEAN == 0
    assert out.splitlines() == [
        "Q-G4  2 golden shape(s); 3 cell(s): 3 pdfium build(s) of 3, 2 OS/Python cell(s) of 2",
        "Q-G4 ok  every cell matches the goldens",
    ]


@pytest.mark.parametrize(
    ("minors", "cells"), [("3", "3"), ("4", "2")], ids=["too-few-pairs", "too-few-builds"]
)
def test_each_coverage_count_is_held_on_its_own(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str], minors: str, cells: str
) -> None:
    """Three cells, two of them one `(os, python)` pair: three builds, but two pairs."""
    _cells(artifacts, WIN, Cell("win32", "3.12", "152.0.7900.0"), Cell("linux", "3.13", "1"))
    code, out = _compare(root, artifacts, capsys, "--pdfium-minors", minors, "--cells", cells)
    assert code == 2, out
    assert "Q-G4 DID NOT RUN" in out.splitlines()[-1]


def test_the_plans_fallback_is_nine_cells_at_one_pdfium(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """13-quality.md:676: *"nine cells at one pinned pdfium"* is `--pdfium-minors 1`."""
    _cells(artifacts, *(Cell(f"os{n}", "3.12", "153.0.7999.0") for n in range(9)))
    code, out = _compare(root, artifacts, capsys, "--pdfium-minors", "1")
    assert code == 0, out
    assert out.splitlines()[0].endswith("1 pdfium build(s) of 1, 9 OS/Python cell(s) of 9")


def test_a_cell_that_differs_fails_whatever_the_coverage(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cells(artifacts, WIN)
    _cells(artifacts, Cell("linux", "3.12", "1"), tree={f"{PDF}.shape": "pages 3\n"})
    code, out = _compare(root, artifacts, capsys)
    assert code == GATE.EXIT_FAIL == 1
    assert out.splitlines()[1:] == [
        f"  FAIL  linux-py3.12-pdfium1: {PDF}.shape differs at line 1: 'pages 2' -> 'pages 3'",
        f"  FAIL  linux-py3.12-pdfium1: {TXT}.shape is missing",
        "Q-G4 FAIL  2 difference(s)",
    ]


def test_the_goldens_are_the_frozen_value_not_the_cells_agreement(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling 2: two cells that agree with each other and not with the golden have drifted."""
    drifted = {**SHAPES, f"{TXT}.shape": "pages 1\nspans 4\n"}
    _cells(artifacts, WIN, Cell("linux", "3.13", "1"), tree=drifted)
    code, out = _compare(root, artifacts, capsys, "--pdfium-minors", "1", "--cells", "1")
    assert code == 1
    assert out.splitlines()[-1] == "Q-G4 FAIL  2 difference(s)"


def test_an_unreadable_cell_means_the_gate_did_not_run(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cells(artifacts, WIN)
    (artifacts / "stray").mkdir()
    code, out = _compare(root, artifacts, capsys, "--pdfium-minors", "1", "--cells", "1")
    assert code == 2
    [line] = out.splitlines()
    assert line.startswith("Q-G4 DID NOT RUN  stray: no readable cell.toml (")


def test_a_file_beside_the_cells_is_not_a_cell(
    root: Path, artifacts: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cells(artifacts, WIN)
    (artifacts / "README.txt").write_bytes(b"downloaded by the golden job\n")
    code, out = _compare(root, artifacts, capsys, "--pdfium-minors", "1", "--cells", "1")
    assert code == 0, out


def test_the_artifacts_default_under_the_root(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cells(root / GATE.ARTIFACTS, WIN)
    code, out = _main(capsys, "--root", str(root), "--pdfium-minors", "1", "--cells", "1")
    assert code == 0, out
    assert Path("artifacts/frozen-stability") == GATE.ARTIFACTS


def test_the_default_artifacts_are_ignored_by_git() -> None:
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/artifacts/" in lines


def test_emit_writes_this_cells_shapes_from_the_ingest(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[Path] = []

    def ingest(where: Path) -> dict[str, str]:
        seen.append(where)
        return dict(GOLDEN)

    target = tmp_path / "out"
    code, out = _main(
        capsys, "--root", str(root), "--emit", str(target), ingest=ingest, cell=lambda: WIN
    )
    assert code == 0, out
    assert seen == [root]
    assert out.splitlines() == [f"Q-G4  emitted 2 shape(s) to {target / WIN.name}"]
    assert GATE._read_cell(target / WIN.name) == (WIN, SHAPES)
    code, out = _compare(root, target, capsys, "--pdfium-minors", "1", "--cells", "1")
    assert code == 0, out


@pytest.mark.parametrize("error", [OSError("no ow on PATH"), ValueError("ow add exited 1")])
def test_an_ingest_that_fails_under_emit_did_not_run(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], error: Exception
) -> None:
    def ingest(_where: Path) -> dict[str, str]:
        raise error

    target = tmp_path / "out"
    code, out = _main(
        capsys, "--root", str(root), "--emit", str(target), ingest=ingest, cell=lambda: WIN
    )
    assert code == 2
    assert out.splitlines() == [f"Q-G4 DID NOT RUN  the ingest: {error}"]
    assert not target.exists()


@pytest.mark.parametrize("argv", [["--cells", "nine"], ["--nonsense"]], ids=["value", "flag"])
def test_a_bad_command_line_did_not_run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert GATE.main(argv) == 2
    assert "usage: gate_frozen_stability.py" in capsys.readouterr().err


def test_every_test_cell_emits_its_shapes_and_the_golden_job_compares_all_nine() -> None:
    """D931: V10-14 read "no job emits each cell's shapes for the gate to read". Each `test`
    cell emits and uploads its shapes, and `golden` waits on `test`, gathers them and runs the
    comparison over nine cells at one pinned pdfium, so a missing cell is "did not run"."""
    workflow = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    test_job = workflow.split("\n  test:\n", 1)[1].split("\n  golden:\n", 1)[0]
    golden_job = workflow.split("\n  golden:\n", 1)[1].split("\n  conform:\n", 1)[0]
    assert "run: uv run tools/gate_frozen_stability.py --emit shapes" in test_job
    assert 'name: "shapes-${{ matrix.os }}-py${{ matrix.py }}"' in test_job
    assert "needs: [versions, test]" in golden_job
    assert 'pattern: "shapes-*"' in golden_job and "merge-multiple: true" in golden_job
    assert (
        "run: uv run tools/gate_frozen_stability.py --artifacts shapes --pdfium-minors 1 --cells 9"
        in golden_job
    )
