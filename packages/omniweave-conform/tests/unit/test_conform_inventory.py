"""`omniweave_conform.inventory`'s bless, and `entry.bless`: OW-Q-013's fix. D846.

The counting itself is D845's and is held by `test_gate_inventory.py`, which reaches it through
`tools/gate_inventory.py`. This file holds what D846 added: `bless_inventory()` over a small
project under `tmp_path`, collected for real, and the entry point's three preconditions, which are
the flag, the author and git.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from omniweave_conform import entry
from omniweave_conform.bless import parse_log
from omniweave_conform.inventory import (
    INVENTORY,
    LOG,
    Blessed,
    Count,
    bless_inventory,
    parse,
    render,
)
from omniweave_core.errors import QualityError

REASON = "retire the stub driver's tests with the stub itself"
DATE = "2026-10-15"
AUTHOR = "q@example.org"


def _project(root: Path, tests: int = 2) -> None:
    folder = root / "packages" / "omniweave-x" / "tests" / "unit"
    folder.mkdir(parents=True, exist_ok=True)
    body = "".join(f"def test_{n}():\n    pass\n\n\n" for n in range(tests))
    (folder / "test_x.py").write_text(body, encoding="utf-8")


def _inventory(root: Path, counted: dict[str, Count]) -> None:
    (root / "eval").mkdir(exist_ok=True)
    (root / INVENTORY).write_bytes(render(counted).encode())


def _bless(root: Path, reason: str = REASON) -> Blessed:
    return bless_inventory(root, reason=reason, date=DATE, author=AUTHOR, env=dict(os.environ))


# --- bless_inventory() -----------------------------------------------------------------------


def test_a_fall_rewrites_the_inventory_and_appends_one_row(tmp_path: Path) -> None:
    _project(tmp_path, tests=2)
    _inventory(tmp_path, {"omniweave-x/unit": Count(5, 0), "omniweave-y/unit": Count(1, 0)})
    done = _bless(tmp_path)
    assert parse((tmp_path / INVENTORY).read_text(encoding="utf-8")) == {
        "omniweave-x/unit": Count(2, 0)
    }
    [row] = parse_log((tmp_path / LOG).read_text(encoding="utf-8"))
    assert (row.date, row.author, row.glob, row.reason) == (DATE, AUTHOR, INVENTORY, REASON)
    assert dict(row.counts) == {"incidental": 0, "structural": 2, "unexplained": 0}
    assert done.fell == (
        "omniweave-x/unit: tests 5 -> 2",
        "omniweave-y/unit: gone, with its 1 test(s)",
    )
    assert done.changed == ("omniweave-x/unit", "omniweave-y/unit")
    assert done.tests == 2
    assert done.row == row.line().rstrip("\n")


def test_an_area_that_grew_beside_one_that_fell_is_incidental(tmp_path: Path) -> None:
    _project(tmp_path, tests=3)
    _inventory(tmp_path, {"omniweave-x/unit": Count(1, 0), "omniweave-z/unit": Count(4, 0)})
    _bless(tmp_path)
    [row] = parse_log((tmp_path / LOG).read_text(encoding="utf-8"))
    assert dict(row.counts) == {"incidental": 1, "structural": 1, "unexplained": 0}


def test_a_row_is_appended_after_the_rows_already_there(tmp_path: Path) -> None:
    _project(tmp_path, tests=1)
    _inventory(tmp_path, {"omniweave-x/unit": Count(3, 0)})
    counts = "incidental=1,structural=0,unexplained=0"
    first = f"2026-10-01\t{AUTHOR}\tfixtures/goldens/*\t{counts}\t{REASON}\n"
    (tmp_path / LOG).write_bytes(first.encode())
    _bless(tmp_path)
    text = (tmp_path / LOG).read_text(encoding="utf-8")
    assert text.startswith(first)
    assert [row.glob for row in parse_log(text)] == ["fixtures/goldens/*", INVENTORY]


def test_nothing_fallen_is_refused_and_nothing_written(tmp_path: Path) -> None:
    _project(tmp_path, tests=2)
    _inventory(tmp_path, {"omniweave-x/unit": Count(1, 0)})
    before = (tmp_path / INVENTORY).read_bytes()
    with pytest.raises(QualityError, match="nothing to bless") as raised:
        _bless(tmp_path)
    assert "gate_inventory.py --write" in raised.value.fix
    assert (tmp_path / INVENTORY).read_bytes() == before
    assert not (tmp_path / LOG).exists()


def test_a_failed_collection_blesses_nothing(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / "packages" / "omniweave-x" / "tests" / "unit" / "test_broken.py").write_text(
        "import no_such_module_anywhere\n", encoding="utf-8"
    )
    _inventory(tmp_path, {"omniweave-x/unit": Count(9, 0)})
    with pytest.raises(QualityError, match="the collection exited"):
        _bless(tmp_path)
    assert not (tmp_path / LOG).exists()


@pytest.mark.parametrize(("reason", "log"), [("too short", ""), (REASON, "not a row\n")])
def test_a_row_the_grammar_refuses_writes_nothing(tmp_path: Path, reason: str, log: str) -> None:
    _project(tmp_path, tests=1)
    _inventory(tmp_path, {"omniweave-x/unit": Count(3, 0)})
    before = (tmp_path / INVENTORY).read_bytes()
    if log:
        (tmp_path / LOG).write_bytes(log.encode())
    with pytest.raises(QualityError):
        _bless(tmp_path, reason)
    assert (tmp_path / INVENTORY).read_bytes() == before
    assert (tmp_path / LOG).read_bytes() == log.encode() if log else not (tmp_path / LOG).exists()


# --- entry.bless() --------------------------------------------------------------------------


def _isolated(tmp_path: Path, **over: str) -> dict[str, str]:
    """The environment with git's global and system config pointed at nothing."""
    empty = tmp_path / "empty.gitconfig"
    empty.write_bytes(b"")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": str(empty), "GIT_CONFIG_NOSYSTEM": "1"}
    env.update(over)
    return env


def test_the_entry_point_refuses_without_the_bless_flag(tmp_path: Path) -> None:
    env = {k: v for k, v in _isolated(tmp_path).items() if k != "OMNIWEAVE_BLESS"}
    with pytest.raises(QualityError, match="OMNIWEAVE_BLESS=1 is not in the environment"):
        entry.bless(root=str(tmp_path), reason=REASON, date=DATE, env=env)


def test_the_entry_point_refuses_when_git_names_no_author(tmp_path: Path) -> None:
    with pytest.raises(QualityError, match=r"`git config user\.email` names none") as raised:
        entry.bless(
            root=str(tmp_path),
            reason=REASON,
            date=DATE,
            env=_isolated(tmp_path, OMNIWEAVE_BLESS="1"),
        )
    assert raised.value.fix == "git config user.email <your address>"


def test_the_entry_point_refuses_when_git_is_not_on_path(tmp_path: Path) -> None:
    """The env's `PATH` is the one searched: a git found anywhere else would find this email."""
    env = _isolated(
        tmp_path,
        OMNIWEAVE_BLESS="1",
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="user.email",
        GIT_CONFIG_VALUE_0="bless@example.org",
    )
    key = next(k for k in env if k.upper() == "PATH")
    env[key] = str(tmp_path / "nowhere")
    with pytest.raises(QualityError, match="names none"):
        entry.bless(root=str(tmp_path), reason=REASON, date=DATE, env=env)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")
def test_the_entry_point_blesses_as_the_repositorys_author(tmp_path: Path) -> None:
    git = shutil.which("git")
    assert git is not None
    env = _isolated(
        tmp_path,
        OMNIWEAVE_BLESS="1",
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="user.email",
        GIT_CONFIG_VALUE_0="bless@example.org",
    )
    _project(tmp_path, tests=1)
    _inventory(tmp_path, {"omniweave-x/unit": Count(2, 0)})
    done = entry.bless(root=str(tmp_path), reason=REASON, date=DATE, env=env)
    assert done == {
        "inventory": INVENTORY,
        "log": LOG,
        "row": f"{DATE}\tbless@example.org\t{INVENTORY}\tincidental=0,structural=1,unexplained=0"
        f"\t{REASON}",
        "fell": ["omniweave-x/unit: tests 2 -> 1"],
        "changed": ["omniweave-x/unit"],
        "tests": 1,
    }
