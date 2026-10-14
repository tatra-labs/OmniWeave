"""`ow out scaffold <target> --brief PATH --slug S`: a JobDir from a card, a Brief and a corpus.

The project is a temporary directory with one corpus whose store is migrated and empty, and the
target is owtext, found through the conformance suite's directory on `OMNIWEAVE_DRIVER_PATH`. What
`scaffold()` writes is `test_out_scaffold.py`'s; this file asks what the verb resolves and refuses.
"""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_core.errors import NotFoundError, TargetError, UsageError
from omniweave_core.out.brief import BRIEF_SCHEMA
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import JOB_JSON, Job
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n"
    "- u02: { anchor: content }\n## forbidden\n- no clip art (user)\n"
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """One corpus, `handbook`, whose store exists, is migrated, and has sealed nothing."""
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    store = tmp_path / ".omniweave" / "index.owstore"
    store.parent.mkdir()
    connection = store_sqlite.connect(store)
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
    code = verb.main(["out", "scaffold", *argv], cwd=cwd, env=_env(cwd), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _json(argv: Sequence[str], cwd: Path) -> dict[str, Any]:
    code, out, err = _run([*argv, "--render", "json"], cwd)
    assert (code, err) == (0, ""), err
    document: dict[str, Any] = json.loads(out)
    return document


ARGS = ["owtext", "--brief", "brief.md", "--slug", "q3-board"]


# ---------------------------------------------------------------------------------------------
# What the verb resolves
# ---------------------------------------------------------------------------------------------


def test_the_job_dir_is_under_roots_cache_run_scoped_at_the_next_generation(
    project: Path,
) -> None:
    document = _json(ARGS, project)
    job_dir = Path(document["job_dir"])
    assert job_dir.parent.parent == (project / ".omniweave" / "cache" / "jobs").resolve()
    assert job_dir.parent.name == document["run_id"]
    assert document["run_id"].startswith("r_") and len(document["run_id"]) == 28
    assert job_dir.name == "q3-board@1"
    assert (document["target"], document["slug"], document["artifact_gen"]) == (
        "owtext", "q3-board", 1,
    )  # fmt: skip
    assert document["corpus"] == "handbook"
    assert [u["id"] for u in document["units"]] == ["u01", "u02"]
    assert document["units"][0] == {
        "id": "u01", "ord": 1, "il_path": "il/u01.html", "anchor": "cover",
    }  # fmt: skip


def test_the_written_job_is_the_one_the_report_names(project: Path) -> None:
    document = _json(ARGS, project)
    job = Job.load(Path(document["job_dir"]))
    assert job.traceparent == document["traceparent"]
    assert job.plan.corpus == "handbook"
    assert job.plan.gate_status is GateStatus.NOT_PROVIDED
    assert (Path(document["job_dir"]) / "brief.md").read_text(encoding="utf-8") == BRIEF


def test_two_scaffolds_are_two_runs(project: Path) -> None:
    first, second = _json(ARGS, project), _json(ARGS, project)
    assert first["run_id"] != second["run_id"]
    assert first["traceparent"] != second["traceparent"]
    assert first["artifact_gen"] == second["artifact_gen"] == 1


def test_the_generation_is_one_past_the_corpus_latest(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniweave_core.store import artifact  # noqa: PLC0415

    seen: list[str] = []

    def latest(_connection: object, slug: str) -> int:
        seen.append(slug)
        return 4

    monkeypatch.setattr(artifact, "latest_generation", latest)
    document = _json(ARGS, project)
    assert seen == ["q3-board"]
    assert document["artifact_gen"] == 5
    assert Path(document["job_dir"]).name == "q3-board@5"


def test_roots_cache_from_the_project_file_is_relative_to_it(project: Path) -> None:
    (project / "omniweave.toml").write_text(
        #  A cache inside the source root is refused (the three roots), so the source is `src`.
        '[roots]\nsource = "src"\ncache = "build/ow-cache"\n'
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n',
        encoding="utf-8",
    )
    sub = project / "deeper"
    sub.mkdir()
    code, out, err = _run(
        ["owtext", "--brief", "../brief.md", "--slug", "q3-board", "--render", "json"], sub
    )
    assert (code, err) == (0, "")
    job_dir = Path(json.loads(out)["job_dir"])
    assert job_dir.is_relative_to((project / "build" / "ow-cache" / "jobs").resolve())


def test_corpus_names_the_store_and_the_plans_corpus(project: Path) -> None:
    """`--corpus` is read by `scaffold` (D765), so it is not refused, and it must exist."""
    document = _json([*ARGS, "--corpus", "handbook"], project)
    assert document["corpus"] == "handbook"
    code, out, _ = _run([*ARGS, "--corpus", "atlas", "--render", "json"], project)
    assert code == NotFoundError.EXIT
    assert "atlas" in json.loads(out)["error"]["message"]


def test_of_two_corpora_the_named_one_is_the_plans(project: Path) -> None:
    (project / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
        '[corpora.atlas]\npath = ".omniweave/atlas.owstore"\n',
        encoding="utf-8",
    )
    connection = store_sqlite.connect(project / ".omniweave" / "atlas.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    document = _json([*ARGS, "--corpus", "atlas"], project)
    assert document["corpus"] == "atlas"
    assert Job.load(Path(document["job_dir"])).plan.corpus == "atlas"


def test_the_brief_is_parsed_against_the_targets_baseline(project: Path) -> None:
    """An untagged prohibition is accepted only when it is a baseline row of the table."""
    baseline = "- elem.script: executable content in an authored artefact; no text mapping exists\n"
    (project / "brief.md").write_text(
        BRIEF.replace("## forbidden\n", "## forbidden\n" + baseline), encoding="utf-8"
    )
    job = Job.load(Path(_json(ARGS, project)["job_dir"]))
    assert [p.tier for p in job.plan.brief.forbidden] == ["baseline", "user"]


def test_the_text_form_names_the_job_dir_and_the_roster(project: Path) -> None:
    code, out, err = _run(ARGS, project)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == "scaffolded owtext q3-board@1 in corpus handbook"
    assert lines[1].startswith("  job dir  ")
    assert Path(lines[1].split("job dir  ", 1)[1], JOB_JSON).is_file()
    assert lines[3:5] == ["  u01  il/u01.html  cover", "  u02  il/u02.html  content"]
    assert lines[-1].startswith("next: write each unit's file under il/")


# ---------------------------------------------------------------------------------------------
# What the verb refuses
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["owtext", "--slug", "q3-board"], "needs --brief"),
        (["owtext", "--brief", "brief.md"], "needs --slug"),
        (["owtext"], "needs --brief and --slug"),
        ([*ARGS, "--quiet"], "--quiet is parsed and not served by ow out scaffold"),
        ([*ARGS, "--render", "rows"], "--render rows is parsed and not served"),
    ],
)
def test_usage_is_refused_by_name_before_anything_is_written(
    argv: list[str], named: str, project: Path
) -> None:
    code, _, err = _run(argv, project)
    assert code == UsageError.EXIT
    assert named in err
    assert not (project / ".omniweave" / "cache").exists()


def test_a_missing_brief_is_not_found(project: Path) -> None:
    code, _, err = _run(["owtext", "--brief", "nope.md", "--slug", "q3-board"], project)
    assert code == NotFoundError.EXIT
    assert "no Brief at" in err
    assert "nope.md" in err


def test_a_brief_the_parser_refuses_is_its_code(project: Path) -> None:
    (project / "brief.md").write_text(BRIEF.replace("- unit: section\n", ""), encoding="utf-8")
    code, _, err = _run(ARGS, project)
    assert code == TargetError.EXIT
    assert "OW-T-008" in err
    assert not (project / ".omniweave" / "cache").exists()


def test_a_brief_that_is_not_utf8_is_the_briefs_code(project: Path) -> None:
    (project / "brief.md").write_bytes(BRIEF.encode("utf-8") + b"\xff\xfe")
    code, _, err = _run(ARGS, project)
    assert code == TargetError.EXIT
    assert "OW-T-008" in err
    assert "brief.md does not read as UTF-8 text: UnicodeDecodeError" in err


def test_a_bad_slug_is_refused_before_anything_is_written(project: Path) -> None:
    code, _, err = _run(["owtext", "--brief", "brief.md", "--slug", "Q3 Board"], project)
    assert code == TargetError.EXIT
    assert "OW-T-519" in err
    assert not (project / ".omniweave" / "cache").exists()


def test_a_corpus_with_no_store_is_not_found(project: Path) -> None:
    (project / ".omniweave" / "index.owstore").unlink()
    code, _, err = _run(ARGS, project)
    assert code == NotFoundError.EXIT
    assert "has no store" in err


def test_an_unknown_target_is_its_code(project: Path) -> None:
    code, _, err = _run(["deck", "--brief", "brief.md", "--slug", "q3-board"], project)
    assert code == NotFoundError.EXIT
    assert "OW-T-515" in err


def test_the_console_script_routes_scaffold(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(project)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    code = launcher.main(["out", "scaffold", *ARGS, "--render", "json"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (0, "")
    assert Path(json.loads(captured.out)["job_dir"], JOB_JSON).is_file()
    assert os.environ["OMNIWEAVE_DRIVER_PATH"] == str(SUITES)
