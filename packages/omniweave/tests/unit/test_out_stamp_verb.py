"""`ow out stamp [--job DIR]`: addresses minted on a scaffolded JobDir, then checked.

Each test scaffolds an owtext JobDir, authors two units with no `data-ow-el` (the golden fixture's
text with its addresses taken out), and stamps them. `out.stamp`'s own rulings are
`test_out_stamp.py`'s; this file asks what the verb resolves, prints and refuses.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import omniweave.__main__ as launcher
import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_core.errors import TargetError, UsageError
from omniweave_core.out.brief import BRIEF_SCHEMA
from omniweave_core.out.stamp import LOCK_NAME
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "out" / "golden" / "owtext" / "il"
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n"
    "- u02: { anchor: content }\n## forbidden\n"
)
_ADDRESS = re.compile(r' data-ow-el="[^"]*"')


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    (tmp_path / "brief.md").write_text(BRIEF, encoding="utf-8")
    return tmp_path


def _env(home: Path) -> dict[str, str]:
    return {
        "OMNIWEAVE_HOME": str(home / "owhome"),
        "HOME": str(home / "home"),
        "USERPROFILE": str(home / "home"),
        "OMNIWEAVE_DRIVER_PATH": str(SUITES),
    }


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", *argv], cwd=cwd, env=_env(cwd), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _job(project: Path) -> Path:
    """A scaffolded JobDir with the golden units authored, their addresses taken out."""
    code, out, err = _run(
        ["scaffold", "owtext", "--brief", "brief.md", "--slug", "q3", "--render", "json"], project
    )
    assert (code, err) == (0, "")
    job = Path(json.loads(out)["job_dir"])
    for unit in ("u01", "u02"):
        text = (GOLDEN / f"{unit}.html").read_text(encoding="utf-8")
        (job / "il" / f"{unit}.html").write_text(_ADDRESS.sub("", text), encoding="utf-8")
    il = job / "il" / "il.toml"
    il.write_text(
        il.read_text(encoding="utf-8")
        + '\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n'
        + '\n[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n',
        encoding="utf-8",
    )
    return job


def test_a_stamp_mints_the_golden_addresses_and_check_then_runs(project: Path) -> None:
    """The golden units' own addresses come back, because the golden IL was stamped in order."""
    job = _job(project)
    code, out, err = _run(["stamp", "--job", str(job), "--render", "json"], project)
    assert (code, err) == (0, "")
    assert json.loads(out) == {
        "written": ["u01.html", "u02.html"],
        "units": [
            {"unit": "u01", "addresses": ["u01/e1", "u01/e2"]},
            {"unit": "u02", "addresses": ["u02/e1", "u02/e2", "u02/e3"]},
        ],
        "stale_lock": False,
    }
    for unit in ("u01", "u02"):
        stamped = (job / "il" / f"{unit}.html").read_text(encoding="utf-8")
        golden = (GOLDEN / f"{unit}.html").read_text(encoding="utf-8")
        #  The golden spells the attribute first; a stamp appends it. Same addresses, same order.
        assert _ADDRESS.findall(stamped) == _ADDRESS.findall(golden)
        assert _ADDRESS.sub("", stamped) == _ADDRESS.sub("", golden)
    assert _run(["check", "--stage", "early", "--job", str(job)], project)[0] == 0


def test_the_text_form_names_each_unit_and_ends_with_the_recheck(project: Path) -> None:
    job = _job(project)
    code, out, err = _run(["stamp", "--job", str(job)], project)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "stamped 5 address(es) in 2 file(s)",
        "  u01  u01/e1 u01/e2",
        "  u02  u02/e1 u02/e2 u02/e3",
        "re-check: ow out check --stage early",
    ]


def test_a_second_stamp_writes_nothing_and_says_so(project: Path) -> None:
    job = _job(project)
    _run(["stamp", "--job", str(job)], project)
    code, out, _ = _run(["stamp", "--job", str(job)], project)
    assert code == 0
    assert (
        out == "every citable, text-bearing element already has an address; nothing was written\n"
    )


def test_a_stale_lock_is_replaced_and_said(project: Path) -> None:
    job = _job(project)
    (job / "il" / LOCK_NAME).write_text("4242 1\n", encoding="ascii")
    code, out, _ = _run(["stamp", "--job", str(job)], project)
    assert code == 0
    assert out.splitlines()[0] == "replaced a stale il/.stamp.lock"
    assert not (job / "il" / LOCK_NAME).exists()


def test_the_job_dir_defaults_to_cwd(project: Path) -> None:
    job = _job(project)
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", "stamp"], cwd=job, env=_env(project), stdout=out, stderr=err)
    assert (code, err.getvalue()) == (0, "")
    assert 'data-ow-el="u01/e1"' in (job / "il" / "u01.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--corpus", "handbook"], "--corpus is not served by ow out stamp"),
        (["--quiet"], "--quiet is parsed and not served by ow out stamp"),
        (["--render", "rows"], "--render rows is parsed and not served by ow out stamp"),
    ],
)
def test_usage_is_refused_by_name_and_nothing_is_written(
    argv: list[str], named: str, project: Path
) -> None:
    job = _job(project)
    code, _, err = _run(["stamp", "--job", str(job), *argv], project)
    assert code == UsageError.EXIT
    assert named in err
    assert "data-ow-el" not in (job / "il" / "u01.html").read_text(encoding="utf-8")


def test_a_directory_that_is_no_job_dir_is_named(project: Path) -> None:
    code, _, err = _run(["stamp", "--job", str(project)], project)
    assert code == TargetError.EXIT
    assert "OW-T-518" in err


def test_the_console_script_routes_stamp(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(project)
    monkeypatch.chdir(job)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    code = launcher.main(["out", "stamp", "--render", "json"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (0, "")
    assert json.loads(captured.out)["written"] == ["u01.html", "u02.html"]
