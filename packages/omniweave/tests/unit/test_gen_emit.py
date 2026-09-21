"""The artefact register and the byte-diff spine. 10 section 2.3; 11 section 1.9; gate G25.

The red cases all run against a temporary repository root, because the property under test is what
`check()` says about a tree and the only tree this process may not write to is the real one. The
green case is the real one, and it is the assertion that matters: `ow surface emit --check` is green
on the repository as it ships, with all seven renderers written.
"""

from __future__ import annotations

import ast
from pathlib import Path

import omniweave.gen.emit as emit_module
import pytest
from omniweave.gen.artefacts import (
    ARTEFACTS,
    Artefact,
    Shape,
    State,
    by_number,
    path_carrying,
)
from omniweave.gen.emit import (
    RENDERERS,
    REPO_ROOT,
    TREE_RENDERERS,
    check,
    emit,
    normalise,
    render,
    write,
)

TABLE_ORDER = (
    "schema/mcp-tools-v1.json",
    "the MCP instructions string, two variants",
    "the CLI argparse tree",
    "omniweave/sdk/_generated.pyi",
    "llms.txt",
    "docs/AGENTS.md",
    "skills/omniweave/references/actions.md",
)
"""10:206's `artefact` column, transcribed here a second time so the register is compared against
the table rather than against itself."""


# ---------------------------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------------------------


def test_the_register_is_10_206s_seven_rows_in_that_tables_order() -> None:
    assert tuple(a.name for a in ARTEFACTS) == TABLE_ORDER
    assert tuple(a.number for a in ARTEFACTS) == (1, 2, 3, 4, 5, 6, 7)


def test_six_of_the_seven_are_files_and_the_seventh_is_the_instructions_string() -> None:
    """D314. 10:202 says `--check` byte-diffs all seven; artefact 2 has no path in any document."""
    assert len(path_carrying()) == 6
    pathless = [a for a in ARTEFACTS if a.path is None]
    assert [a.number for a in pathless] == [2]


def test_all_seven_artefacts_have_a_renderer_now() -> None:
    """W7.2g closes the set. `check()`'s PENDING clause has no shipped row left to fire on, and
    the tests that exercise it build their own -- see `_one()`."""
    assert [a.number for a in ARTEFACTS if a.state is State.LIVE] == [1, 2, 3, 4, 5, 6, 7]
    assert not [a for a in ARTEFACTS if a.state is State.PENDING]


def test_each_live_row_is_in_the_table_its_shape_names() -> None:
    """One renderer table per shape, and a row in the wrong one is a row nothing renders.

    Artefacts 1, 4, 5, 6 and 7 are `FILE`s and have bytes; artefact 3 is a `TREE` and has a
    membership as well; artefact 2 is a `STRING` and is in neither, because it has no path to
    diff against."""
    assert set(RENDERERS) == {1, 4, 5, 6, 7}
    assert set(TREE_RENDERERS) == {3}
    assert by_number(1).shape is Shape.FILE
    assert by_number(2).shape is Shape.STRING
    assert by_number(3).shape is Shape.TREE
    assert by_number(4).shape is Shape.FILE
    assert by_number(5).shape is Shape.FILE
    assert by_number(6).shape is Shape.FILE
    assert by_number(7).shape is Shape.FILE


def test_string_is_exactly_the_shape_of_the_rows_with_no_path() -> None:
    """`artefacts._shape_failures()` raises on a disagreement; this is the property it asserts."""
    for artefact in ARTEFACTS:
        assert (artefact.shape is Shape.STRING) == (artefact.path is None), artefact.number


def test_neither_renderer_table_can_be_appended_to_at_runtime() -> None:
    """A register a caller could grow would make the states in `artefacts.py` a suggestion."""
    with pytest.raises(TypeError):
        RENDERERS[99] = lambda: b""  # type: ignore[index]
    with pytest.raises(TypeError):
        TREE_RENDERERS[99] = dict  # type: ignore[index]


def test_by_number_refuses_an_eighth() -> None:
    assert by_number(5).name == "llms.txt"
    with pytest.raises(KeyError, match="seven artefacts"):
        by_number(8)


def test_the_repo_root_this_module_computed_is_the_repo_root() -> None:
    assert (REPO_ROOT / "codes.toml").is_file()
    assert (REPO_ROOT / "packages" / "omniweave").is_dir()


# ---------------------------------------------------------------------------------------------
# `check()` against the tree that ships
# ---------------------------------------------------------------------------------------------


def test_ow_surface_emit_check_is_green_on_this_repository() -> None:
    """Gate G25's byte-diff half, on the tree as it stands. `()` is the gate passing."""
    assert check() == ()


def test_nothing_is_committed_for_an_artefact_nothing_can_produce() -> None:
    """The property `test_no_generated_artefact_has_been_written_yet` used to assert over two paths
    by name, now derived over all six. 00:851 makes LEANN's hand-written `llms.txt` G25's named
    defect, and a committed file for a PENDING row is exactly that shape.

    **Vacuous since W7.2g**, and kept rather than deleted: every row is `LIVE`, so the loop body
    never runs against the shipped register. It is the assertion an eighth artefact meets on the
    day its row is added and before its renderer exists, which is the day it is worth having.
    `_one()` carries the non-vacuous half against a temporary root."""
    for artefact in path_carrying():
        assert artefact.path is not None
        if artefact.state is State.PENDING:
            assert not (REPO_ROOT / artefact.path).exists(), artefact.path


def test_emit_writes_nothing_because_every_live_file_is_already_committed() -> None:
    """`ow surface emit` on a clean tree is a no-op, which is `write()`'s equal-bytes branch and
    the reason `--bless` leaves a reviewable diff instead of touching seven files."""
    assert emit() == ()


def test_render_returns_bytes_for_the_five_file_rows_that_are_live() -> None:
    produced = {a.number: render(a) for a in ARTEFACTS}
    assert produced[1] is not None
    assert produced[1].endswith(b"]\n")
    assert produced[4] is not None
    assert produced[4].startswith(b'"""The SDK')
    assert produced[5] is not None
    assert produced[5].startswith(b"# llms.txt ")
    assert produced[6] is not None
    assert produced[6].startswith(b"# AGENTS.md ")
    assert produced[7] is not None
    assert produced[7].startswith(b"<!-- skills/omniweave/references/actions.md ")
    assert [n for n, payload in produced.items() if payload is None] == [2, 3]


# ---------------------------------------------------------------------------------------------
# `check()`'s four clauses, against a temporary root
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository root this test module may write to. The real one it may not."""
    monkeypatch.setattr(emit_module, "REPO_ROOT", tmp_path)
    return tmp_path


def _synthetic(root: Path) -> Path:
    """`_one()`'s path under a temporary root. One spelling, used by every red case."""
    return root / "docs" / "reference" / "nothing.md"


def _one(**over: object) -> Artefact:
    """A synthetic EIGHTH row, and it is synthetic now for a reason worth stating.

    It borrowed a real `PENDING` row until W7.2g: artefact 5 until `llms.txt` landed, artefact 6
    until `docs/AGENTS.md` did, artefact 7 until this cell. **The register has no `PENDING` row
    left** -- all seven are `LIVE` -- so there is nothing real left to borrow, and a fixture that
    kept naming artefact 7 would assert a state the shipped register contradicts, which is the
    fossil these three moves have been avoiding.

    The clause under test is still worth its tests. `check()`'s third clause is the one that made
    the register a gate before any renderer existed, it is the LEANN shape (00:851), and it is
    what an eighth artefact would meet on its first day.
    """
    base: dict[str, object] = {
        "number": 8,
        "name": "docs/reference/nothing.md",
        "path": "docs/reference/nothing.md",
        "shape": Shape.FILE,
        "source": "nothing; this row exists only in this test module",
        "consumer": "no one",
        "state": State.PENDING,
        "lands_with": "W0.0",
    }
    base.update(over)
    return Artefact(**base)  # type: ignore[arg-type]


def test_clause_3_a_committed_file_for_a_pending_row_fails(
    fake_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(),))
    (fake_root / "docs" / "reference").mkdir(parents=True)
    _synthetic(fake_root).write_text("hand written\n", encoding="utf-8", newline="\n")
    findings = check()
    assert len(findings) == 1
    assert "no renderer produces it" in findings[0]
    assert "W0.0" in findings[0]


@pytest.mark.usefixtures("fake_root")
def test_clause_1_a_pending_row_with_a_renderer_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register claiming less than the code can do is as wrong as the reverse."""
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(),))
    monkeypatch.setattr(emit_module, "RENDERERS", {8: lambda: b"x\n"})
    assert any("promote the row to LIVE" in line for line in check())


@pytest.mark.usefixtures("fake_root")
def test_clause_1b_a_live_row_with_no_renderer_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(state=State.LIVE),))
    assert any("no renderer is registered" in line for line in check())


@pytest.mark.usefixtures("fake_root")
def test_clause_4_a_live_row_with_nothing_committed_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(state=State.LIVE),))
    monkeypatch.setattr(emit_module, "RENDERERS", {8: lambda: b"x\n"})
    assert any("nothing is committed there" in line for line in check())


def test_clause_2_a_live_row_whose_bytes_differ_fails(
    fake_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(state=State.LIVE),))
    monkeypatch.setattr(emit_module, "RENDERERS", {8: lambda: b"generated\n"})
    (fake_root / "docs" / "reference").mkdir(parents=True)
    _synthetic(fake_root).write_text("stale\n", encoding="utf-8", newline="\n")
    assert any("differs from what the generator produces" in line for line in check())


def test_a_live_row_that_matches_passes(fake_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(state=State.LIVE),))
    monkeypatch.setattr(emit_module, "RENDERERS", {8: lambda: b"generated\n"})
    (fake_root / "docs" / "reference").mkdir(parents=True)
    _synthetic(fake_root).write_text("generated\n", encoding="utf-8", newline="\n")
    assert check() == ()


# ---------------------------------------------------------------------------------------------
# CRLF, and the writer
# ---------------------------------------------------------------------------------------------


def test_a_crlf_checkout_does_not_fail_a_gate_it_has_nothing_to_do_with(
    fake_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """11:484's whole subject: *"a generator that emits `\\n` and a working tree that holds
    `\\r\\n` disagree byte-for-byte for reasons that have nothing to do with the code."*"""
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(state=State.LIVE),))
    monkeypatch.setattr(emit_module, "RENDERERS", {8: lambda: b"one\ntwo\n"})
    (fake_root / "docs" / "reference").mkdir(parents=True)
    _synthetic(fake_root).write_bytes(b"one\r\ntwo\r\n")
    assert check() == ()


def test_normalise_folds_only_a_carriage_return_that_precedes_a_newline() -> None:
    assert normalise(b"a\r\nb\r\n") == b"a\nb\n"
    assert normalise(b"a\rb") == b"a\rb"
    assert normalise(b"a\nb") == b"a\nb"


def test_the_writer_emits_lf_on_every_platform(fake_root: Path) -> None:
    """11:487's rule, and this is the only `open(..., "w")` in the package for that reason."""
    artefact = _one(state=State.LIVE)
    assert write(artefact, b"one\ntwo\n") is True
    assert _synthetic(fake_root).read_bytes() == b"one\ntwo\n"


@pytest.mark.usefixtures("fake_root")
def test_writing_the_same_bytes_twice_is_a_no_op() -> None:
    """`--bless` is a reviewable act; a no-op write would put every artefact in every diff."""
    artefact = _one(state=State.LIVE)
    assert write(artefact, b"same\n") is True
    assert write(artefact, b"same\n") is False


def test_writing_over_a_crlf_file_with_equal_content_is_a_no_op(fake_root: Path) -> None:
    artefact = _one(state=State.LIVE)
    (fake_root / "docs" / "reference").mkdir(parents=True)
    _synthetic(fake_root).write_bytes(b"same\r\n")
    assert write(artefact, b"same\n") is False


def test_writing_creates_the_parent_directory(fake_root: Path) -> None:
    artefact = _one(path="skills/omniweave/references/actions.md", state=State.LIVE)
    assert write(artefact, b"# actions\n") is True
    assert (fake_root / "skills" / "omniweave" / "references" / "actions.md").is_file()


def test_writing_an_artefact_that_is_not_a_file_refuses() -> None:
    with pytest.raises(ValueError, match="has no path"):
        write(by_number(2), b"anything")


@pytest.mark.usefixtures("fake_root")
def test_emit_writes_a_live_row_and_reports_the_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(emit_module, "ARTEFACTS", (_one(state=State.LIVE),))
    monkeypatch.setattr(emit_module, "RENDERERS", {8: lambda: b"generated\n"})
    assert emit() == ("docs/reference/nothing.md",)
    assert emit() == (), "a second run changes nothing"
    assert check() == ()


# ---------------------------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------------------------


def test_only_the_writer_opens_a_file_for_writing() -> None:
    """11:487 scopes a semgrep ban to `omniweave/gen/`; this is the ban's subject, counted.

    One call site, and it passes `newline="\\n"`. A ban is only as good as the number of places it
    has to watch, which is the argument for having a `write()` at all.
    """
    source = Path(emit_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    opens = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "open"
    ]
    assert len(opens) == 1
    keywords = {kw.arg for kw in opens[0].keywords}
    assert {"encoding", "newline"} <= keywords


def test_the_spine_reads_no_clock_no_environment_and_no_randomness() -> None:
    """10:229's ban. `pathlib` is exempt here and only here: this module is the one that writes."""
    source = Path(emit_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"time", "random", "secrets", "os", "datetime"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module
