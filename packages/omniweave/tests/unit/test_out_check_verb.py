"""`ow out check --stage S`: the target's rules over a scaffolded JobDir at each of four stages.

Each test scaffolds an owtext JobDir through `ow out scaffold`, authors the golden fixture's two
units into it, and runs the gate. The corpus store is migrated and empty, so a final check's cite
resolves to nothing unless the test hands it the fixture's own `cites.json`.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_conform.suites.target.suite import _FixtureCites
from omniweave_core.errors import TargetError, UsageError
from omniweave_core.out.brief import BRIEF_SCHEMA
from omniweave_core.store import cites as store_cites
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "out" / "golden" / "owtext"
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n"
    "- u02: { anchor: content }\n## forbidden\n"
)
ROWS = '\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n'
ROWS_BOTH = ROWS + '\n[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n'


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


def _job(project: Path, *, rows: str = ROWS_BOTH, units: Sequence[str] = ("u01", "u02")) -> Path:
    """A scaffolded JobDir with the golden units authored and their rows added."""
    code, out, err = _run(
        ["scaffold", "owtext", "--brief", "brief.md", "--slug", "q3", "--render", "json"], project
    )
    assert (code, err) == (0, "")
    job = Path(json.loads(out)["job_dir"])
    for unit in units:
        shutil.copyfile(GOLDEN / "il" / f"{unit}.html", job / "il" / f"{unit}.html")
    il = job / "il" / "il.toml"
    il.write_text(il.read_text(encoding="utf-8") + rows, encoding="utf-8")
    return job


def _check(argv: Sequence[str], project: Path, job: Path) -> tuple[int, str, str]:
    return _run(["check", *argv, "--job", str(job)], project)


def _document(argv: Sequence[str], project: Path, job: Path) -> tuple[int, dict[str, Any]]:
    code, out, err = _check([*argv, "--render", "json"], project, job)
    assert err == ""
    document: dict[str, Any] = json.loads(out)
    return code, document


# ---------------------------------------------------------------------------------------------
# The stages
# ---------------------------------------------------------------------------------------------


def test_early_reads_the_il_and_the_table_and_exits_on_errors_alone(project: Path) -> None:
    """Ruling 12: no error, exit 0, and the report still says non-final."""
    job = _job(project)
    code, document = _document(["--stage", "early"], project, job)
    assert code == 0
    assert document["schema"] == "omniweave.out-report/1"
    assert document["stage"] == "early"
    assert document["gate"]["status"] == "non-final"
    assert document["counts"]["error"] == 0
    #  Ruling 11: no resolver before final, so the cite rule is a recorded skip.
    assert [s["needs"] for s in document["skipped_checks"]] == ["cites"]
    assert (job / "validation" / "early.json").is_file()


def test_the_text_form_is_the_console_block_and_says_early_is_not_a_gate(project: Path) -> None:
    job = _job(project)
    code, out, err = _check(["--stage", "early"], project, job)
    assert (code, err) == (0, "")
    assert out.startswith("gate: non-final   (0 blocking")
    assert "Clear with: ow out check --target owtext --stage final --render json" in out
    assert out.endswith("stage early: 0 error(s), exit 0; only --stage final is a release gate\n")


def test_an_error_at_an_early_stage_exits_8(project: Path) -> None:
    job = _job(project)
    unit = job / "il" / "u02.html"
    unit.write_text(
        unit.read_text(encoding="utf-8").replace("</section>", "<script>x()</script></section>"),
        encoding="utf-8",
    )
    code, out, _ = _check(["--stage", "early"], project, job)
    assert code == 8
    assert "OW-T-401" in out


def test_final_resolves_cites_in_the_jobs_corpus_and_fails_on_a_dead_one(project: Path) -> None:
    """The store is empty, so the golden unit's `d7#1` names no block."""
    job = _job(project)
    code, document = _document(["--stage", "final"], project, job)
    assert code == 8
    assert document["gate"]["status"] == "failed"
    assert [f["code"] for f in document["findings"]] == ["OW_TARGET_CITE_UNRESOLVED"]
    assert document["skipped_checks"] == []
    assert (job / "validation" / "final.json").is_file()


def _fixture_cites(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The corpus resolver replaced by the golden fixture's `cites.json`; returns the corpora."""
    corpora: list[str] = []

    def resolver(_thread: object, *, corpus: str) -> _FixtureCites:
        corpora.append(corpus)
        return _FixtureCites(GOLDEN / "cites.json")

    monkeypatch.setattr(store_cites, "SqliteCiteResolver", resolver)
    return corpora


def test_final_passes_when_every_cite_resolves_and_no_unit_needs_a_human(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (project / "brief.md").write_text(
        BRIEF.replace("- u02: { anchor: content }\n", ""), encoding="utf-8"
    )
    corpora = _fixture_cites(monkeypatch)
    job = _job(project, rows=ROWS, units=("u01",))
    code, document = _document(["--stage", "final"], project, job)
    assert corpora == ["handbook"]
    assert (code, document["gate"]["status"]) == (0, "passed")


def test_final_is_manual_required_while_a_unit_carries_a_manual_region(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The golden `u02` holds an `ow:manual` region: nothing is wrong, a human has work."""
    _fixture_cites(monkeypatch)
    job = _job(project)
    code, document = _document(["--stage", "final"], project, job)
    assert (code, document["gate"]["status"]) == (8, "manual-required")
    assert [row["unit"] for row in document["manual_units"]] == ["u02"]


@pytest.mark.parametrize("stage", ["early", "final"])
def test_only_final_hands_the_check_the_brief_and_the_roster(
    stage: str, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 11, read off the call: owtext's rules never read the Brief, so ask `check()`."""
    from omniweave_core.out import compile as out_compile  # noqa: PLC0415

    seen: dict[str, Any] = {}
    original = out_compile.check

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(out_compile, "check", spy)
    job = _job(project)
    _check(["--stage", stage], project, job)
    final = stage == "final"
    assert (seen["brief"] is not None) == final
    assert seen["plan_units"] == (["u01", "u02"] if final else None)
    assert (seen["cites"] is not None) == final


def test_final_holds_the_bundle_to_the_commissioned_roster(project: Path) -> None:
    """Ruling 11: one unit authored of two commissioned is OW-T-507 at final, and fine early."""
    job = _job(project, rows=ROWS, units=("u01",))
    assert _check(["--stage", "early"], project, job)[0] == 0
    code, _, err = _check(["--stage", "final"], project, job)
    assert code == TargetError.EXIT
    assert "OW-T-507" in err


@pytest.mark.parametrize(
    ("argv", "units"),
    [(["--stage", "first-unit"], ["u01"]), (["--stage", "unit", "--unit", "u02"], ["u02"])],
)
def test_first_unit_and_unit_check_their_one_unit(
    argv: list[str], units: list[str], project: Path
) -> None:
    job = _job(project)
    code, document = _document(argv, project, job)
    assert code == 0
    assert document["stage"] == argv[1]
    assert document["summary"]["units"] == len(units)
    assert (job / "validation" / f"{argv[1]}.json").is_file()


def test_the_job_dir_defaults_to_cwd(project: Path) -> None:
    job = _job(project)
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(
        ["out", "check", "--stage", "early"], cwd=job, env=_env(project), stdout=out, stderr=err
    )
    assert (code, err.getvalue()) == (0, "")


def test_a_matching_target_is_accepted_and_another_refused(project: Path) -> None:
    job = _job(project)
    assert _check(["--stage", "early", "--target", "owtext"], project, job)[0] == 0
    code, _, err = _check(["--stage", "early", "--target", "pptx"], project, job)
    assert code == UsageError.EXIT
    assert "--target pptx is not this JobDir's target, owtext" in err


# ---------------------------------------------------------------------------------------------
# Refused by name
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        ([], "ow out check needs --stage, one of early, first-unit, unit, final"),
        (["--stage", "late"], "needs --stage, one of"),
        (["--stage", "unit"], "--unit names the one unit --stage unit checks"),
        (["--stage", "early", "--unit", "u01"], "--unit names the one unit"),
        (["--stage", "early", "--corpus", "handbook"], "--corpus is not served by ow out check"),
        (["--stage", "early", "--quiet"], "--quiet is parsed and not served by ow out check"),
        (["--stage", "early", "--render", "jsonl"], "--render jsonl is parsed and not served"),
    ],
)
def test_usage_is_refused_by_name(argv: list[str], named: str, project: Path) -> None:
    job = _job(project)
    code, _, err = _check(argv, project, job)
    assert code == UsageError.EXIT
    assert named in err
    assert not (job / "validation" / "early.json").exists()


def test_a_directory_that_is_no_job_dir_is_named(project: Path) -> None:
    code, _, err = _run(["check", "--stage", "early", "--job", str(project)], project)
    assert code == TargetError.EXIT
    assert "OW-T-518" in err
    assert "job.json does not load" in err


def test_the_console_script_routes_check(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(project)
    monkeypatch.chdir(job)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    code = launcher.main(["out", "check", "--stage", "early", "--render", "json"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (0, "")
    assert json.loads(captured.out)["stage"] == "early"
