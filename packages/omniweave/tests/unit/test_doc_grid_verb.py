"""`ow doc grid`: one table read back through `read_grid()`, its exits, and `ow doc diff`'s refusal.

The store is `conftest.py`'s `seeded_store` with one table added by its `seeded_table`, in the
shape `DocSink.add_grid` writes it: a `table` block, its `table_cell` children, one `table_meta`
row and one `cell` row per origin. Two rows by three columns, the first a header row, and the
second row's last two columns merged into one origin:

    [0,0] Name  [0,1] Q1     [0,2] Q2
    [1,0] Fees  [1,1] 4,000 (1x2)
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave.surface import doc as verb

if TYPE_CHECKING:
    from collections.abc import Sequence

PROJECT = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
TABLE = 10
CELLS = {
    11: (0, 0, 1, 1, "Name"),
    12: (0, 1, 1, 1, "Q1"),
    13: (0, 2, 1, 1, "Q2"),
    14: (1, 0, 1, 1, "Fees"),
    15: (1, 1, 1, 2, "4,000"),
}


@pytest.fixture
def project(tmp_path: Path, seeded_store: Any, seeded_table: Any) -> Path:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    seeded_table(seeded_store(tmp_path / ".omniweave" / "index.owstore"), CELLS, table=TABLE)
    return tmp_path


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["doc", *argv], env={}, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _json(argv: Sequence[str], cwd: Path) -> dict[str, Any]:
    code, out, err = _run([*argv, "--render", "json"], cwd)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    return document


# ---------------------------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------------------------


def test_render_json_is_the_grid_with_every_origin_cell_row_major(project: Path) -> None:
    document = _json(["grid", "d1#10"], project)
    assert next(iter(document)) == "schema"
    assert (document["table"], document["corpus"]) == ("d1#10", "handbook")
    assert (document["n_rows"], document["n_cols"], document["row_len"]) == (2, 3, [3, 3])
    assert (document["header_rows"], document["has_merges"], document["kind"]) == (1, True, "data")
    cells = [
        (c["cite"], c["r"], c["c"], c["row_span"], c["col_span"], c["text"])
        for c in document["cells"]
    ]
    assert cells == [
        ("d1#11", 0, 0, 1, 1, "Name"),
        ("d1#12", 0, 1, 1, 1, "Q1"),
        ("d1#13", 0, 2, 1, 1, "Q2"),
        ("d1#14", 1, 0, 1, 1, "Fees"),
        ("d1#15", 1, 1, 1, 2, "4,000"),
    ]
    assert [c["header"] for c in document["cells"]] == [True, True, True, False, False]


def test_a_cells_cite_opens_the_table_it_sits_in(project: Path) -> None:
    assert _json(["grid", "d1#15"], project)["table"] == "d1#10"


def test_the_text_render_is_a_head_line_and_one_line_per_origin(project: Path) -> None:
    code, out, err = _run(["grid", "d1#10"], project)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == (
        "table d1#10  2 rows x 3 cols  header_rows 1  header_cols 0  merges yes  kind data"
    )
    assert lines[1] == "  [0,0] header  d1#11  Name"
    assert lines[5] == "  [1,1] 1x2  d1#15  4,000"


def test_with_two_corpora_declared_every_cite_is_qualified(project: Path) -> None:
    (project / "omniweave.toml").write_text(
        PROJECT + '[corpora.legal]\npath = ".omniweave/legal.owstore"\n', encoding="utf-8"
    )
    document = _json(["grid", "handbook:d1#10"], project)
    assert document["table"] == "handbook:d1#10"
    assert document["cells"][0]["cite"] == "handbook:d1#11"


# ---------------------------------------------------------------------------------------------
# Refusals, and their exits
# ---------------------------------------------------------------------------------------------


def test_a_block_that_is_no_table_is_2_naming_its_kind(project: Path) -> None:
    code, out, err = _run(["grid", "d1#2"], project)
    assert (code, out) == (2, "")
    assert "names a paragraph block" in err


def test_a_ref_that_does_not_resolve_is_2(project: Path) -> None:
    code, _, err = _run(["grid", "d1#999"], project)
    assert code == 2
    assert "OW-M-032" in err


def test_a_ref_naming_several_blocks_is_usage() -> None:
    """A document or page ref resolves to many blocks, and a grid is one table's."""
    from omniweave_core.errors import UsageError  # noqa: PLC0415

    assert verb._one_block((7,), "d1#7") == 7
    with pytest.raises(UsageError, match="reads one table"):
        verb._one_block((7, 8), "d1")


def test_doc_diff_is_refused_by_name_with_internal_errors_exit(project: Path) -> None:
    """D621: `RebindReadSide` has no store behind it, so `ow doc diff` cannot run."""
    code, out, err = _run(["diff", "d1"], project)
    assert (code, out) == (70, "")
    assert "RebindReadSide" in err


@pytest.mark.parametrize(
    ("flags", "named"),
    [
        (["--quiet"], "--quiet"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
    ],
)
def test_a_parsed_flag_this_build_cannot_serve_is_refused_by_name(
    project: Path, flags: list[str], named: str
) -> None:
    code, out, err = _run(["grid", "d1#10", *flags], project)
    assert (code, out) == (1, "")
    assert named in err


def test_an_undeclared_corpus_or_a_missing_store_is_2(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    assert _run(["grid", "d1#10"], tmp_path)[0] == 2
    assert _run(["grid", "legal:d1#10"], tmp_path)[0] == 2


def test_an_error_under_render_json_is_the_error_object_on_stdout(project: Path) -> None:
    code, out, err = _run(["grid", "d1#2", "--render", "json"], project)
    assert (code, err) == (2, "")
    assert list(json.loads(out)) == ["schema", "error"]


def test_python_m_omniweave_dispatches_doc(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "doc" in launcher.DISPATCHED
    monkeypatch.chdir(project)
    monkeypatch.setattr("os.environ", {})
    assert launcher.main(["doc", "grid", "d1#10"]) == 0
    assert capsys.readouterr().out.startswith("table d1#10")
