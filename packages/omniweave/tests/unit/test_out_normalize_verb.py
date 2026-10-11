"""`ow out normalize`: owtext's `attr.class.upper` folded on a scaffolded JobDir, then re-checked.

`out.normalize`'s own rulings are `test_out_normalize.py`'s. This file asks what the verb loads (the
target's carrier and its own `normalizers.py`), prints and refuses.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_core.errors import NotFoundError, TargetError, UsageError
from omniweave_core.out.brief import BRIEF_SCHEMA
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n"
    "- u02: { anchor: content }\n## forbidden\n"
)
U01 = '<section>\n  <p class="Lead Story">One.</p>\n  <p class="X">Two.</p>\n</section>\n'
U02 = '<section>\n  <p class="lead">Three.</p>\n</section>\n'


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
    code, out, err = _run(
        ["scaffold", "owtext", "--brief", "brief.md", "--slug", "q3", "--render", "json"], project
    )
    assert (code, err) == (0, "")
    job = Path(json.loads(out)["job_dir"])
    (job / "il" / "u01.html").write_text(U01, encoding="utf-8")
    (job / "il" / "u02.html").write_text(U02, encoding="utf-8")
    il = job / "il" / "il.toml"
    il.write_text(
        il.read_text(encoding="utf-8")
        + '\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n'
        + '\n[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n',
        encoding="utf-8",
    )
    return job


def _json(argv: Sequence[str], project: Path, job: Path) -> dict[str, Any]:
    code, out, err = _run(["normalize", *argv, "--job", str(job), "--render", "json"], project)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    return document


def test_the_targets_own_normalizer_folds_the_class_names(project: Path) -> None:
    job = _job(project)
    assert _json([], project, job) == {
        "written": ["u01.html"],
        "changed": [{"unit": "u01", "construct": "attr.class.upper", "count": 2}],
    }
    assert (job / "il" / "u01.html").read_text(encoding="utf-8") == U01.replace(
        "Lead Story", "lead story"
    ).replace('"X"', '"x"')
    assert (job / "il" / "u02.html").read_text(encoding="utf-8") == U02


def test_the_check_warns_before_and_is_clean_after(project: Path) -> None:
    job = _job(project)
    code, out, _ = _run(["check", "--stage", "early", "--job", str(job)], project)
    assert code == 0
    assert "OW-T-211" in out
    assert "fix: ow out normalize --unit u01 --construct attr.class.upper" in out
    assert _json(["--stage", "early"], project, job)["written"] == ["u01.html"]
    code, out, _ = _run(["check", "--stage", "early", "--job", str(job)], project)
    assert "OW-T-211" not in out


def test_the_text_form_counts_and_ends_with_the_recheck(project: Path) -> None:
    job = _job(project)
    code, out, err = _run(["normalize", "--job", str(job)], project)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "normalized 2 value(s) in 1 file(s)",
        "  u01  attr.class.upper  x2",
        "re-check: ow out check --stage early",
    ]
    code, out, _ = _run(["normalize", "--job", str(job)], project)
    assert (code, out) == (0, "no value needed normalizing; nothing was written\n")


def test_unit_and_construct_narrow_the_run(project: Path) -> None:
    job = _job(project)
    assert _json(["--unit", "u02", "--construct", "attr.class.upper"], project, job) == {
        "written": [],
        "changed": [],
    }
    assert "Lead Story" in (job / "il" / "u01.html").read_text(encoding="utf-8")


def test_a_stale_report_is_refused(project: Path) -> None:
    job = _job(project)
    _run(["check", "--stage", "early", "--job", str(job)], project)
    (job / "il" / "u02.html").write_text(U02.replace("Three", "3"), encoding="utf-8")
    code, _, err = _run(["normalize", "--stage", "early", "--job", str(job)], project)
    assert code == TargetError.EXIT
    assert "OW-T-523" in err


def test_a_construct_that_is_no_normalize_row_is_not_found(project: Path) -> None:
    job = _job(project)
    code, _, err = _run(["normalize", "--construct", "elem.p", "--job", str(job)], project)
    assert code == NotFoundError.EXIT
    assert "OW-T-516" in err


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--stage", "late"], "--stage is one of early, first-unit, unit, final"),
        (["--corpus", "handbook"], "--corpus is not served by ow out normalize"),
        (["--quiet"], "--quiet is parsed and not served by ow out normalize"),
    ],
)
def test_usage_is_refused_by_name_and_nothing_is_written(
    argv: list[str], named: str, project: Path
) -> None:
    job = _job(project)
    code, _, err = _run(["normalize", "--job", str(job), *argv], project)
    assert code == UsageError.EXIT
    assert named in err
    assert (job / "il" / "u01.html").read_text(encoding="utf-8") == U01


def test_the_console_script_routes_normalize(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(project)
    monkeypatch.chdir(job)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    code = launcher.main(["out", "normalize", "--render", "json"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (0, "")
    assert json.loads(captured.out)["written"] == ["u01.html"]
