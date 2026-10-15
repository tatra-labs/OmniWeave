"""Q-G24 tested as a program: `tools/gate_inventory.py`, the test-inventory ratchet. D845.

The gate is held to its docstring rule by rule:
- the area of a node id, the counts, the inventory's bytes and its parse;
- a decrease against the base end;
- `main()` with its collector and its history injected;
- `collect()` over a small project under `tmp_path`;
- the decrease clause over a real repository with a real `BLESS.log`;
- once over this repository, whose inventory must match its own collection.

Loaded by file path under a private name and at module scope, as `test_gate_flake.py` loads its
gate.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess  # noqa: TID251 -- the decrease clause reads a real repository.
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_inventory.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_inventory", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
Count = GATE.Count
ROWS = [
    ("packages/omniweave-core/tests/unit/test_a.py::test_one", False),
    ("packages/omniweave-core/tests/unit/test_a.py::test_two[x]", True),
    ("packages/omniweave-core/tests/test_g17.py::test_top", False),
    ("packages/omniweave/tests/conform/test_p.py::test_proc", False),
]
COUNTED = {
    "omniweave-core/tests": Count(1, 0),
    "omniweave-core/unit": Count(2, 1),
    "omniweave/conform": Count(1, 0),
}
ROW = (
    "2026-10-15\tq@example.org\teval/inventory.toml\tincidental=0,structural=1,unexplained=0\t{}\n"
)
REASON = "retire the P2 stub driver tests with the stub itself"


# --- rulings 1, 2 and 4 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("nodeid", "area"),
    [
        ("packages/omniweave-core/tests/unit/test_a.py::test_one", "omniweave-core/unit"),
        ("packages/omniweave-core/tests/unit/deep/test_b.py::T::test_m", "omniweave-core/unit"),
        ("packages/omniweave-core/tests/test_g17.py::test_top", "omniweave-core/tests"),
        ("packages/omniweave/tests/conform/test_p.py::test_proc", "omniweave/conform"),
        ("bench/serve/test_run.py::test_x", "bench"),
        ("test_loose.py::test_y", "(root)"),
    ],
)
def test_an_area_is_a_distribution_and_its_test_directory(nodeid: str, area: str) -> None:
    assert GATE.area_of(nodeid) == area


def test_items_are_counted_per_area_with_their_properties() -> None:
    assert GATE.areas(ROWS) == COUNTED
    assert list(GATE.areas(ROWS)) == sorted(COUNTED)


def test_the_inventory_is_sorted_rows_with_no_total_and_reads_back() -> None:
    text = GATE.render({"b/unit": Count(3, 1), "a/unit": Count(2, 0)})
    assert text == (
        GATE.HEADER
        + '\n[[area]]\narea = "a/unit"\ntests = 2\nproperties = 0\n'
        + '\n[[area]]\narea = "b/unit"\ntests = 3\nproperties = 1\n'
    )
    assert "total" not in text
    assert GATE.parse(text) == {"a/unit": Count(2, 0), "b/unit": Count(3, 1)}


@pytest.mark.parametrize(
    "text",
    [
        "[[area]\n",
        '[[area]]\narea = "a"\ntests = 1\n',
        '[[area]]\narea = "a"\ntests = 1\nproperties = 0\ntotal = 1\n',
        'area = ["not a table"]\n',
    ],
)
def test_an_inventory_of_another_shape_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match=r"eval/inventory.toml"):
        GATE.parse(text)


# --- ruling 5: decreases ---------------------------------------------------------------------


def test_a_decrease_is_a_lost_test_a_lost_property_or_a_lost_area() -> None:
    before = {"a/unit": Count(5, 2), "b/unit": Count(3, 0), "c/unit": Count(1, 1)}
    after = {
        "a/unit": Count(4, 2),
        "b/unit": Count(3, 0),
        "c/unit": Count(2, 0),
        "d/unit": Count(1, 0),
    }
    assert GATE.decreases(before, {**after, "a/unit": Count(4, 2)}) == [
        "a/unit: tests 5 -> 4",
        "c/unit: properties 1 -> 0",
    ]
    del after["b/unit"]
    assert "b/unit: gone, with its 3 test(s)" in GATE.decreases(before, after)
    assert (
        GATE.decreases(before, {k: Count(v.tests + 1, v.properties) for k, v in before.items()})
        == []
    )


# --- main(), injected ------------------------------------------------------------------------


def _collector(code: int = 0, rows: list[tuple[str, bool]] | None = None) -> Any:
    return lambda _root: (
        code,
        list(ROWS if rows is None else rows),
        ["E   ImportError: x", "1 error"],
    )


def _history(before: str = "", old_log: str = "", new_log: str = "") -> Any:
    return lambda _root, _base, _head: (before, old_log, new_log)


def _main(root: Path, capsys: pytest.CaptureFixture[str], *argv: str, **over: Any) -> Any:
    code = GATE.main(
        ["--root", str(root), *argv],
        collector=over.get("collector", _collector()),
        history=over.get("history", _history()),
    )
    return code, capsys.readouterr().out


def _inventory(root: Path, counted: dict[str, Any] = COUNTED) -> None:
    (root / "eval").mkdir(exist_ok=True)
    (root / "eval" / "inventory.toml").write_bytes(GATE.render(counted).encode())


def test_write_then_check_is_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "eval").mkdir()
    assert _main(tmp_path, capsys, "--write") == (
        0,
        "Q-G24  4 test(s), 1 propert(ies), 3 area(s)\n  wrote eval/inventory.toml\n"
        "Q-G24 ok  0 finding(s)\n",
    )
    assert _main(tmp_path, capsys) == (
        0,
        "Q-G24  4 test(s), 1 propert(ies), 3 area(s)\nQ-G24 ok  0 finding(s)\n",
    )


@pytest.mark.parametrize(
    ("present", "state"), [(True, "differs from the collection"), (False, "is missing")]
)
def test_an_inventory_that_is_not_the_collection_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], present: bool, state: str
) -> None:
    if present:
        _inventory(tmp_path, {"omniweave-core/unit": Count(2, 1)})
    code, out = _main(tmp_path, capsys)
    assert code == 1
    assert (
        f"  FAIL  eval/inventory.toml {state}; run `uv run tools/gate_inventory.py --write`" in out
    )


def test_a_collection_that_fails_is_a_finding_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "eval").mkdir()
    code, out = _main(tmp_path, capsys, "--write", collector=_collector(2))
    assert code == 1
    assert "  FAIL  collection exited 2; a module that fails to import loses its tests" in out
    assert "  | E   ImportError: x\n  | 1 error\n" in out
    assert "wrote" not in out
    assert not (tmp_path / "eval" / "inventory.toml").exists()


def test_a_decrease_without_a_bless_row_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _inventory(tmp_path)
    before = GATE.render({**COUNTED, "omniweave-core/unit": Count(9, 1)})
    code, out = _main(tmp_path, capsys, history=_history(before))
    assert code == 1
    assert "  fell  omniweave-core/unit: tests 9 -> 2" in out
    assert (
        "  FAIL  OW-Q-013 decrease omniweave-core/unit: tests 9 -> 2; "
        "OMNIWEAVE_BLESS=1 ow eval bless --inventory --reason '<why the tests went>'" in out
    )


def test_a_decrease_the_landed_change_blesses_passes_and_is_still_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _inventory(tmp_path)
    before = GATE.render({**COUNTED, "omniweave-core/unit": Count(9, 1)})
    code, out = _main(tmp_path, capsys, history=_history(before, "", ROW.format(REASON)))
    assert code == 0
    assert "  fell  omniweave-core/unit: tests 9 -> 2" in out


def test_a_bless_row_for_another_glob_does_not_bless_the_inventory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _inventory(tmp_path)
    before = GATE.render({**COUNTED, "omniweave-core/unit": Count(9, 1)})
    other = ROW.format(REASON).replace("eval/inventory.toml", "fixtures/goldens/*")
    assert _main(tmp_path, capsys, history=_history(before, "", other))[0] == 1


def test_a_rewritten_bless_log_is_a_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _inventory(tmp_path)
    before = GATE.render({**COUNTED, "omniweave-core/unit": Count(9, 1)})
    code, out = _main(tmp_path, capsys, history=_history(before, ROW.format(REASON), ""))
    assert code == 1
    assert "  FAIL  BLESS.log: BLESS.log was rewritten, not appended to" in out


def test_no_decrease_needs_no_bless(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _inventory(tmp_path)
    before = GATE.render({"omniweave-core/unit": Count(1, 0)})
    assert _main(tmp_path, capsys, history=_history(before, ROW.format(REASON), ""))[0] == 0


@pytest.mark.parametrize(
    "failure",
    [OSError("git merge-base: bad revision"), ValueError("eval/inventory.toml does not parse")],
)
def test_a_history_the_gate_cannot_read_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: Exception
) -> None:
    _inventory(tmp_path)

    def broken(_root: Path, _base: str, _head: str) -> tuple[str, str, str]:
        raise failure

    code, out = _main(tmp_path, capsys, history=broken)
    assert code == 2
    assert out == f"Q-G24 DID NOT RUN  the decrease clause: {failure}\n"


def test_a_base_inventory_that_does_not_parse_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _inventory(tmp_path)
    code, out = _main(tmp_path, capsys, history=_history("[[area]\n"))
    assert code == 2
    assert out.startswith(
        "Q-G24 DID NOT RUN  the decrease clause: eval/inventory.toml does not parse"
    )


def test_a_bad_flag_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--strict"]) == 2
    capsys.readouterr()


# --- collect(), over a project under tmp_path -----------------------------------------------


def _project(root: Path, body: str) -> None:
    tests = root / "packages" / "omniweave-x" / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_x.py").write_text(body, encoding="utf-8")


def test_collect_records_each_item_and_whether_hypothesis_drives_it(tmp_path: Path) -> None:
    _project(
        tmp_path,
        "from hypothesis import given, strategies as st\n\n\n"
        "def test_plain():\n    pass\n\n\n"
        "@given(st.integers())\ndef test_property(n):\n    pass\n",
    )
    code, rows, _tail = GATE.collect(tmp_path)
    assert code == 0
    assert sorted(rows) == [
        ("packages/omniweave-x/tests/unit/test_x.py::test_plain", False),
        ("packages/omniweave-x/tests/unit/test_x.py::test_property", True),
    ]
    assert GATE.areas(rows) == {"omniweave-x/unit": Count(2, 1)}


def test_collect_reports_a_module_that_fails_to_import(tmp_path: Path) -> None:
    _project(tmp_path, "import no_such_module_anywhere\n\n\ndef test_lost():\n    pass\n")
    code, rows, tail = GATE.collect(tmp_path)
    assert code != 0
    assert rows == []
    assert any("no_such_module_anywhere" in line or "error" in line.lower() for line in tail)


# --- ruling 5, over a real repository ---------------------------------------------------------

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")


def _git(repo: Path, *args: str) -> None:
    assert GIT is not None
    subprocess.run(  # noqa: S603 - fixed argv, argv[0] from shutil.which.
        [GIT, "-c", "user.name=q", "-c", "user.email=q@example.org", *args],
        cwd=repo,
        capture_output=True,
        check=True,
    )


def _commit(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(text.encode())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "step")


@needs_git
def test_the_decrease_clause_reads_the_merge_base_and_the_landed_bless(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(tmp_path, "init", "-q", "-b", "master")
    _commit(
        tmp_path,
        {"eval/inventory.toml": GATE.render({**COUNTED, "omniweave/conform": Count(5, 0)})},
    )
    _git(tmp_path, "checkout", "-q", "-b", "feat")
    _commit(tmp_path, {"eval/inventory.toml": GATE.render(COUNTED)})
    argv = ["--root", str(tmp_path), "--base", "master"]
    assert GATE.main(argv, collector=_collector()) == 1
    assert "  fell  omniweave/conform: tests 5 -> 1" in capsys.readouterr().out
    _commit(tmp_path, {"eval/BLESS.log": ROW.format(REASON)})
    assert GATE.main(argv, collector=_collector()) == 0
    capsys.readouterr()


@needs_git
def test_an_unknown_base_did_not_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git(tmp_path, "init", "-q", "-b", "master")
    _commit(tmp_path, {"eval/inventory.toml": GATE.render(COUNTED)})
    assert GATE.main(["--root", str(tmp_path), "--base", "nowhere"], collector=_collector()) == 2
    assert capsys.readouterr().out.startswith(
        "Q-G24 DID NOT RUN  the decrease clause: git rev-parse"
    )


# --- the repository ---------------------------------------------------------------------------


def test_this_repositorys_inventory_is_its_collection(capsys: pytest.CaptureFixture[str]) -> None:
    """The ratchet, in the suite while CI is off: a test added or lost without `--write` fails."""
    code = GATE.main(["--base", "HEAD"])
    out = capsys.readouterr().out
    assert code == 0, out
