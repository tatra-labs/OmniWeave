"""`omniweave_conform.portability`: the two halves' frozen values and their comparison. D903.

The suite's runs are `test_conform_eval_run.py`'s; this file holds the module's rulings: what a
difference is, the committed parts table's shape, and that the shape half reads `.shape` alone.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from omniweave_conform import golden, portability
from omniweave_conform.roundtrip import targets
from omniweave_core.errors import QualityError

REPO = Path(__file__).resolve().parents[4]


def test_a_difference_is_missing_extra_or_changed_over_the_union_of_names() -> None:
    held = portability.differences({"a": "1", "b": "2", "c": "3"}, {"a": "1", "b": "9", "d": "4"})
    assert held.compared == 4
    assert held.matched == 1
    assert held.differences == ("b: differs", "c: missing", "d: not frozen")


def test_identical_sides_have_no_difference_and_empty_sides_compare_nothing() -> None:
    assert portability.differences({"a": "1"}, {"a": "1"}) == portability.Held(1, ())
    assert portability.differences({}, {}) == portability.Held(0, ())


def test_the_shape_half_reads_shape_reductions_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ruling 1: `pages` and `outline` are tracked, and moved on Linux (D886)."""
    tree = {"c/d@1/x.pdf.shape": "s", "c/d@1/x.pdf.pages": "p", "c/d@1/x.pdf.outline": "o"}
    monkeypatch.setattr(golden, "read_tree", lambda _root: tree)
    monkeypatch.setattr(golden, "ingest", lambda _root: {**tree, "c/d@1/x.pdf.pages": "moved"})
    assert portability.shapes(REPO) == ({"c/d@1/x.pdf.shape": "s"}, {"c/d@1/x.pdf.shape": "s"})


def test_the_parts_table_renders_and_reads_back(tmp_path: Path) -> None:
    table = {"pptx": {"b.xml": "2" * 64}, "docx": {"[Content_Types].xml": "1" * 64}}
    (tmp_path / "eval").mkdir()
    text = portability.render_parts(table, cell="linux, Python 3.13")
    (tmp_path / portability.PARTS).write_bytes(text.encode("utf-8"))
    assert portability.read_parts(tmp_path) == table
    assert text.index('target = "docx"') < text.index('target = "pptx"')
    assert "# Written on linux, Python 3.13." in text


@pytest.mark.parametrize(
    "body",
    [
        None,
        b"[[target]\n",
        b'[[target]]\ntarget = "docx"\n',
        b'[[target]]\ntarget = "docx"\nparts = {}\n',
        b"[[target]]\nparts = {a = 'b'}\n",
    ],
)
def test_an_unreadable_or_partial_table_is_refused(tmp_path: Path, body: bytes | None) -> None:
    """Ruling 3: an empty or broken table agrees with nothing, so it is never read as one."""
    (tmp_path / "eval").mkdir()
    if body is not None:
        (tmp_path / portability.PARTS).write_bytes(body)
    with pytest.raises(QualityError, match="eval/portability") as raised:
        portability.read_parts(tmp_path)
    assert "tools/ow_portability.py --write" in raised.value.fix


def test_the_committed_table_names_every_register_target() -> None:
    register = tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
    committed = portability.read_parts(REPO)
    #  D914: the `pptx` row also freezes V10-10's 40-unit golden, `tools/ow_portability.py`'s
    #  GOLDEN40, which no register row names and every CI cell checks.
    assert set(committed) == {target.target for target in targets(register, REPO)} | {
        "pptx@golden40"
    }
    assert all(len(sha) == 64 for members in committed.values() for sha in members.values())
