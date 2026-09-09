"""`tools/ow_merge_index_lock.py`: the merge driver as git invokes it.

`test_store_indexlock.py` holds the truth table over the merge FUNCTION. This file holds the
contract with git, which is a different set of claims and each one can fail on its own: what the
argument order means, what lands in `%A`, and what the exit code says about it.

*"Git invokes it as `%O %A %B` (ancestor, ours, theirs) and it writes the result into `%A`, exiting
0 for a clean merge and non-zero when a conflict remains"*, per 07-store-and-retrieval.md:3146,
whose registered command passes five placeholders (`%O %A %B %L %P`).

The tool lives under `tools/`, which is not an installed package, so it is loaded by path. That is
the one place in this file that touches `importlib`: `importlib.import_module` is banned outside
`host/` for library code, and a test harness reaching a repo script is neither.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omniweave_core.store.indexlock import (
    GITATTRIBUTES_LINE,
    LOCK_PATH,
    LockHeader,
    LockRow,
    read_lock,
    write_lock,
)

REPO = Path(__file__).resolve().parents[4]
DRIVER_PATH = REPO / "tools" / "ow_merge_index_lock.py"

HEADER = LockHeader(
    scorer=1, segmenter="derive.segment.spine@3:9c1e", space="bge-m3@a1b2c3/768/cosine/i8"
)
DIGEST = bytes.fromhex("9c1e" * 8)
KEY = bytes.fromhex("11" * 16)
OTHER_KEY = bytes.fromhex("22" * 16)


def row(key: bytes = KEY, gen: int = 1) -> LockRow:
    return LockRow(
        doc_key=key,
        gen=gen,
        status="ok",
        n_blocks=42,
        n_segments=3,
        content_digest=DIGEST,
        uri="/c/one.pdf",
    )


def _load_driver() -> ModuleType:
    """Import `tools/ow_merge_index_lock.py` by path. Cached in `sys.modules` like any import."""
    name = "ow_merge_index_lock"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, DRIVER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - a missing tool is a repo defect
        pytest.fail(f"cannot load {DRIVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


driver = _load_driver()


@pytest.fixture
def sink() -> io.StringIO:
    """The injected `TextIO` the driver reports through. `print` is banned repo-wide (T20)."""
    return io.StringIO()


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _three(tmp_path: Path, base: str, ours: str, theirs: str) -> tuple[str, str, str]:
    """The three paths git would pass, as `(%O, %A, %B)`."""
    return (
        str(_write(tmp_path / "base.lock", base)),
        str(_write(tmp_path / LOCK_PATH, ours)),
        str(_write(tmp_path / "theirs.lock", theirs)),
    )


def _side(*rows: LockRow) -> str:
    return write_lock(HEADER, rows)


# ---------------------------------------------------------------------------
# The three exit codes.
# ---------------------------------------------------------------------------


def test_a_clean_merge_exits_zero_and_the_answer_is_in_the_ours_file(
    tmp_path: Path, sink: io.StringIO
) -> None:
    """Two disjoint additions on top of an empty base: nothing for a human to do."""
    argv = _three(tmp_path, _side(), _side(row(KEY)), _side(row(OTHER_KEY)))
    assert driver.main(list(argv), out=sink) == driver.EXIT_CLEAN
    merged = Path(argv[1]).read_text(encoding="utf-8")
    assert merged == _side(row(KEY), row(OTHER_KEY))
    assert sink.getvalue() == ""


def test_a_real_conflict_exits_non_zero_and_leaves_markers_in_the_ours_file(
    tmp_path: Path, sink: io.StringIO
) -> None:
    argv = _three(tmp_path, _side(row(gen=1)), _side(row(gen=2)), _side(row(gen=3)))
    assert driver.main(list(argv), out=sink) == driver.EXIT_CONFLICT
    merged = Path(argv[1]).read_text(encoding="utf-8")
    assert "<<<<<<<" in merged
    assert "=======" in merged
    assert ">>>>>>>" in merged
    assert KEY.hex() in sink.getvalue()
    assert "ow store verify --lock" in sink.getvalue()


def test_a_deleted_line_stays_deleted_through_the_driver(tmp_path: Path, sink: io.StringIO) -> None:
    """The graphify cell, end to end.

    *"a deleted line stays deleted"* -- 00-vision.md:583; the counter-example is
    `_nx.compose(G_cur, G_oth)` at `graphify/cli.py:2572`, a union that loads the base path and
    never reads it (07:3105-3107). Base and theirs both hold the row, ours deleted it, and the file
    git is handed back must not contain it.
    """
    argv = _three(tmp_path, _side(row()), _side(), _side(row()))
    assert driver.main(list(argv), out=sink) == driver.EXIT_CLEAN
    merged = Path(argv[1]).read_text(encoding="utf-8")
    assert KEY.hex() not in merged
    assert read_lock(merged).rows == ()


def test_a_refused_input_exits_two_and_leaves_the_ours_file_untouched(
    tmp_path: Path, sink: io.StringIO
) -> None:
    """An unsorted receipt is not a receipt, and the honest answer is not a rewritten file."""
    unsorted = write_lock(HEADER, ()) + row(OTHER_KEY).render() + "\n" + row(KEY).render() + "\n"
    argv = _three(tmp_path, unsorted, _side(row(KEY)), _side(row(OTHER_KEY)))
    ours_before = Path(argv[1]).read_text(encoding="utf-8")
    assert driver.main(list(argv), out=sink) == driver.EXIT_REFUSED
    assert Path(argv[1]).read_text(encoding="utf-8") == ours_before
    assert "UNCHANGED" in sink.getvalue()
    assert "ow store lock" in sink.getvalue()


def test_the_three_exit_codes_are_distinct_and_only_clean_is_zero() -> None:
    codes = (driver.EXIT_CLEAN, driver.EXIT_CONFLICT, driver.EXIT_REFUSED)
    assert codes == (0, 1, 2)
    assert len(set(codes)) == 3


def test_no_temporary_file_survives_a_completed_merge(tmp_path: Path, sink: io.StringIO) -> None:
    argv = _three(tmp_path, _side(), _side(row(KEY)), _side(row(OTHER_KEY)))
    driver.main(list(argv), out=sink)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "base.lock",
        LOCK_PATH,
        "theirs.lock",
    ]


# ---------------------------------------------------------------------------
# The argument contract.
# ---------------------------------------------------------------------------


def test_the_positional_order_is_ancestor_ours_theirs(tmp_path: Path, sink: io.StringIO) -> None:
    """Swapping the first two arguments changes the answer, which is what proves the order is read.

    With base holding gen=1, ours deleting it and theirs holding gen=1, the correct answer is a
    deletion. Passing (ours, base, theirs) instead makes the base an empty file and the answer an
    add/add of one identical line -- a different, clean, WRONG result. A driver that ignored `%O`
    (graphify's does) would return that second answer for the first invocation.
    """
    base, ours, theirs = _three(tmp_path, _side(row()), _side(), _side(row()))
    assert driver.main([base, ours, theirs], out=sink) == driver.EXIT_CLEAN
    assert KEY.hex() not in Path(ours).read_text(encoding="utf-8")

    _write(Path(ours), _side())
    empty = str(_write(tmp_path / "empty.lock", _side()))
    assert driver.main([empty, ours, theirs], out=sink) == driver.EXIT_CLEAN
    assert KEY.hex() in Path(ours).read_text(encoding="utf-8")


def test_the_optional_marker_length_and_pathname_are_accepted(
    tmp_path: Path, sink: io.StringIO
) -> None:
    """The plan registers five placeholders, `%O %A %B %L %P` (07:3146), so five must work."""
    argv = _three(tmp_path, _side(row(gen=1)), _side(row(gen=2)), _side(row(gen=3)))
    assert driver.main([*argv, "9", "some/other/name.lock"], out=sink) == driver.EXIT_CONFLICT
    merged = Path(argv[1]).read_text(encoding="utf-8")
    assert "<" * 9 in merged
    assert "some/other/name.lock" in sink.getvalue()


def test_three_arguments_alone_are_enough(tmp_path: Path, sink: io.StringIO) -> None:
    """The task's contract is `%O %A %B`; `%L` defaults to git's 7 and `%P` to the lock path."""
    argv = _three(tmp_path, _side(row(gen=1)), _side(row(gen=2)), _side(row(gen=3)))
    assert driver.main(list(argv), out=sink) == driver.EXIT_CONFLICT
    assert "<" * 7 in Path(argv[1]).read_text(encoding="utf-8")
    assert LOCK_PATH in sink.getvalue()


def test_a_missing_ancestor_path_reads_as_an_empty_base(tmp_path: Path, sink: io.StringIO) -> None:
    """Git passes an empty `%O` for a path added on both branches."""
    ours = str(_write(tmp_path / LOCK_PATH, _side(row(KEY))))
    theirs = str(_write(tmp_path / "theirs.lock", _side(row(OTHER_KEY))))
    absent = str(tmp_path / "no-such-base.lock")
    assert driver.main([absent, ours, theirs], out=sink) == driver.EXIT_CLEAN
    assert read_lock(Path(ours).read_text(encoding="utf-8")).rows == (row(KEY), row(OTHER_KEY))


@pytest.mark.parametrize("bad", [[], ["only-one"], ["one", "two"]])
def test_too_few_arguments_is_refused_and_says_the_usage(bad: list[str], sink: io.StringIO) -> None:
    assert driver.main(bad, out=sink) == driver.EXIT_REFUSED
    assert "%O %A %B" in sink.getvalue()


def test_a_non_numeric_marker_length_is_refused(tmp_path: Path, sink: io.StringIO) -> None:
    argv = _three(tmp_path, _side(), _side(row(KEY)), _side(row(OTHER_KEY)))
    assert driver.main([*argv, "seven"], out=sink) == driver.EXIT_REFUSED
    assert "%L" in sink.getvalue()


def test_a_missing_ours_file_is_refused_rather_than_invented(
    tmp_path: Path, sink: io.StringIO
) -> None:
    """`%A` is the output. If it does not exist this is not a merge, and inventing one is worse."""
    base = str(_write(tmp_path / "base.lock", _side()))
    theirs = str(_write(tmp_path / "theirs.lock", _side(row(KEY))))
    missing = str(tmp_path / "gone.lock")
    assert driver.main([base, missing, theirs], out=sink) == driver.EXIT_REFUSED
    assert not Path(missing).exists()


def test_a_crlf_working_tree_merges_to_the_same_bytes_as_an_lf_one(
    tmp_path: Path, sink: io.StringIO
) -> None:
    """11-repo-layout.md:490-493 rule 3, applied to the merge rather than to a `--check`."""
    lf = _three(tmp_path, _side(), _side(row(KEY)), _side(row(OTHER_KEY)))
    assert driver.main(list(lf), out=sink) == driver.EXIT_CLEAN
    lf_result = Path(lf[1]).read_text(encoding="utf-8")

    crlf_dir = tmp_path / "crlf"
    crlf_dir.mkdir()
    paths = []
    for name, text in (
        ("base.lock", _side()),
        (LOCK_PATH, _side(row(KEY))),
        ("theirs.lock", _side(row(OTHER_KEY))),
    ):
        target = crlf_dir / name
        target.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
        paths.append(str(target))
    assert driver.main(paths, out=sink) == driver.EXIT_CLEAN
    assert Path(paths[1]).read_text(encoding="utf-8") == lf_result


def test_a_non_utf8_input_is_refused_and_not_merged(tmp_path: Path, sink: io.StringIO) -> None:
    argv = _three(tmp_path, _side(), _side(row(KEY)), _side(row(OTHER_KEY)))
    (tmp_path / "theirs.lock").write_bytes(b"# schema=1 scorer=1 segmenter=s@1:a space=\xff\n")
    ours_before = Path(argv[1]).read_text(encoding="utf-8")
    assert driver.main(list(argv), out=sink) == driver.EXIT_REFUSED
    assert Path(argv[1]).read_text(encoding="utf-8") == ours_before


# ---------------------------------------------------------------------------
# Registration -- for that path only.
# ---------------------------------------------------------------------------


def test_print_registration_prints_both_halves_and_exits_zero(sink: io.StringIO) -> None:
    assert driver.main(["--print-registration"], out=sink) == driver.EXIT_CLEAN
    printed = sink.getvalue()
    assert GITATTRIBUTES_LINE in printed
    assert "git config merge.ow-index-lock.name" in printed
    assert "git config merge.ow-index-lock.driver" in printed


def test_the_registration_the_driver_prints_never_names_a_glob(sink: io.StringIO) -> None:
    """*"registered for that path only"* -- 07:3112-3113, 01-principles.md:689.

    The only `%` tokens are git's five placeholders, and the only path is one literal filename. A
    `*` or a `**` here would aim a line-deleting driver at every text file in the repository.
    """
    driver.main(["--print-registration"], out=sink)
    for line in sink.getvalue().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        stripped = line.replace("%O %A %B %L %P", "")
        assert "*" not in stripped, line
        assert "?" not in stripped, line
    assert LOCK_PATH in sink.getvalue()


def test_no_glob_appears_anywhere_in_the_driver_source() -> None:
    """A structural claim, not a stylistic one: this driver must never match more than one path."""
    source = DRIVER_PATH.read_text(encoding="utf-8")
    for banned in ('glob("', ".glob(", 'rglob("', "fnmatch", 'merge="*"', "* merge="):
        assert banned not in source, banned


def test_the_driver_module_docstring_states_the_scope_and_the_memory_behaviour() -> None:
    doc = driver.__doc__ or ""
    assert "for that path only" in doc
    assert "no cap" in doc.lower()
    assert "independent of corpus size" in doc
