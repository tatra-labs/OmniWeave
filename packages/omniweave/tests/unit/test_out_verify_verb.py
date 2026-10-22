"""`ow out verify [--job DIR]` and `run.out_verify`: R1 and R7 over a sealed owtext artefact.

Each test scaffolds an owtext JobDir through the verbs, checks it at `final`, compiles it in a real
worker, and verifies the generation it sealed. A recompile that must differ, a row declaring a class
no comparison reaches, and the inputs R1 refuses are driven through `verify_artifact()` itself,
lowered in process.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.run.out_compile import in_process, store_cas
from omniweave.run.out_verify import verify_artifact
from omniweave.surface import out as verb
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_conform.suites.target.owtext.driver import HERE, OwTextCompiler
from omniweave_conform.suites.target.owtext.normalizers import lower_ascii
from omniweave_core.errors import TargetError
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.job import Job
from omniweave_core.out.ledger import LedgerRow, slot, write_index
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.artifact import SqliteArtifactStore
from omniweave_ports import ArtifactRef, DriverResult

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n## forbidden\n"
)
U01 = (
    '<section data-ow-el="u01/e1">\n'
    '  <p data-ow-el="u01/e2" class="lead" id="intro">Revenue rose 12% in Q3.</p>\n'
    "</section>\n"
)
TABLE = ConstructTable.load(HERE / "constructs.toml", {"lower_ascii": lower_ascii})


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
    (job / "il" / "u01.html").write_text(U01, encoding="utf-8", newline="")
    il = job / "il" / "il.toml"
    il.write_text(
        il.read_text(encoding="utf-8") + '\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n',
        encoding="utf-8",
    )
    return job


def _compiled(project: Path) -> Path:
    job = _job(project)
    for argv in (["check", "--stage", "final"], ["compile"]):
        code, _out, err = _run([*argv, "--job", str(job)], project)
        assert (code, err) == (0, ""), err
    return job


def _verify(project: Path, job: Path) -> tuple[int, dict[str, Any]]:
    code, out, err = _run(["verify", "--job", str(job), "--render", "json"], project)
    assert err == "", err
    document: dict[str, Any] = json.loads(out)
    return code, document


def _sealed(project: Path) -> tuple[Any, Any]:
    store = project / ".omniweave" / "index.owstore"
    with store_sqlite.StoreThread(lambda: store_sqlite.connect_readonly(store)) as thread:
        artifacts = SqliteArtifactStore(thread, clock=None)  # type: ignore[arg-type]
        row = artifacts.get("q3", 1)
        return row, artifacts.units(row.artifact_id)


def _direct(project: Path, job: Path, *, compiler: Any = None, **changes: Any) -> Any:
    """`verify_artifact()` over the sealed row, lowered in process."""
    row, units = _sealed(project)
    target = compiler or OwTextCompiler()
    blobs = store_cas(project / ".omniweave" / "index.owstore")
    arguments: dict[str, Any] = {
        "row": row,
        "units": units,
        "card_sha256": row.card_sha256,
        "constructs": TABLE,
        "carrier": target.carrier,
        "blobs": blobs,
        "lowering": in_process(
            target, make_io(MemoryBlobStore(project / "kit"), project / "io"), ".txt"
        ),
        "scratch": project / "scratch" / "q3@1",
    }
    arguments.update(changes)
    return verify_artifact(job, **arguments)


# ---------------------------------------------------------------------------------------------
# Rulings 1, 3, 4 and 5: the sealed artefact is what its retained IL compiles to
# ---------------------------------------------------------------------------------------------


def test_a_sealed_artefact_recompiles_to_itself_in_a_worker(project: Path) -> None:
    job = _compiled(project)
    code, document = _verify(project, job)
    assert code == 0
    assert document == {
        "slug": "q3",
        "artifact_gen": 1,
        "exit": 0,
        "r1": True,
        "classes": {"byte": "held", "part": "held"},
        "r7": True,
        "units_sealed": 1,
        "unit_count": 1,
    }
    code, out, err = _run(["verify", "--job", str(job)], project)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "R1 retained-IL identity   PASS   q3@1 recompiled from its retained IL: "
        + ", ".join(f"{name} held" for name in document["classes"]),
        "R7 total classification   PASS   1 unit row(s) sealed, 1 commissioned",
    ]
    assert not (project / ".omniweave" / "cache" / "tmp" / "verify" / "q3@1").exists()


def test_il_edited_since_the_seal_does_not_move_r1(project: Path) -> None:
    """Ruling 1: the retained IL is recompiled, never the JobDir's."""
    job = _compiled(project)
    (job / "il" / "u01.html").write_text(U01.replace("12%", "99%"), encoding="utf-8")
    code, document = _verify(project, job)
    assert (code, document["r1"]) == (0, True)


def test_a_recompile_that_differs_fails_r1_at_every_class(project: Path) -> None:
    class Other(OwTextCompiler):
        def lower(self, plan: Any, il: Any, ledger: Any, io: Any) -> DriverResult:
            del plan, il, ledger
            return DriverResult("ok", (ArtifactRef.of("artifact", b"== u01 ==\nOther\n", io),))

    job = _compiled(project)
    found = _direct(project, job, compiler=Other())
    assert dict(found.classes) == {"byte": "differs", "part": "differs"}
    assert (found.r1, found.r7, found.passed) == (False, True, False)


def test_a_class_no_comparison_reaches_is_unchecked_and_never_a_pass(project: Path) -> None:
    job = _compiled(project)
    row, _units = _sealed(project)
    found = _direct(project, job, row=replace(row, determinism=("part", "render")))
    assert dict(found.classes) == {"part": "held", "render": "unchecked"}
    assert found.r1 is True
    alone = _direct(project, job, row=replace(row, determinism=("render",)))
    assert (dict(alone.classes), alone.r1) == ({"render": "unchecked"}, False)


def test_r7_counts_the_sealed_unit_rows_against_the_roster(project: Path) -> None:
    job = _compiled(project)
    found = _direct(project, job, units=())
    assert (found.units_sealed, found.unit_count, found.r7, found.passed) == (0, 1, False, False)


def test_a_failing_law_exits_8_and_says_fail(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verb's exit and lines are the laws': a failing R1 is exit 8, never a raise."""
    from omniweave.run import out_verify  # noqa: PLC0415

    job = _compiled(project)
    real = out_verify.verify_artifact

    def failing(*args: Any, **kwargs: Any) -> Any:
        found = real(*args, **kwargs)
        return replace(found, classes={"byte": "differs", "part": "held"}, units_sealed=0)

    monkeypatch.setattr(out_verify, "verify_artifact", failing)
    code, out, err = _run(["verify", "--job", str(job)], project)
    assert (code, err) == (8, "")
    assert out.splitlines() == [
        "R1 retained-IL identity   FAIL   q3@1 recompiled from its retained IL: "
        "byte differs, part held",
        "R7 total classification   FAIL   0 unit row(s) sealed, 1 commissioned",
    ]
    code, document = _verify(project, job)
    assert (code, document["exit"], document["r1"], document["r7"]) == (8, 8, False, False)


# ---------------------------------------------------------------------------------------------
# Ruling 2: only over the inputs the artefact was sealed over
# ---------------------------------------------------------------------------------------------


def _refused(project: Path, job: Path, **changes: Any) -> str:
    with pytest.raises(TargetError) as caught:
        _direct(project, job, **changes)
    assert caught.value.code() == "OW_TARGET_VERIFY_INPUTS"
    return str(caught.value)


def test_another_brief_is_refused(project: Path) -> None:
    job = _compiled(project)
    loaded = Job.load(job)
    other = parse_brief(BRIEF.replace("per_unit: light", "per_unit: dense"), baseline=())
    plan = replace(loaded.plan, brief=other, brief_digest=other.digest())
    replace(loaded, plan=plan).write(job)
    assert "Brief digests to" in _refused(project, job)
    code, _out, err = _run(["verify", "--job", str(job)], project)
    assert code != 0
    assert "OW-T-527" in err


def test_a_ledger_changed_since_the_seal_is_refused(project: Path) -> None:
    job = _compiled(project)
    sha = "c" * 64
    write_index(job, [LedgerRow(asset_id=1, sha256=sha, slot=slot(sha), role="image", unit="u01")])
    assert "ledger digests to" in _refused(project, job)
    assert not (project / "scratch" / "q3@1").exists(), "the scratch goes on every exit path"


def test_another_card_or_table_is_refused(project: Path) -> None:
    job = _compiled(project)
    assert "installed card is" in _refused(project, job, card_sha256="sha256:" + "0" * 64)
    other = ConstructTable.load(HERE / "constructs.toml", {"lower_ascii": lower_ascii})
    assert other.digest() == TABLE.digest()
    row, _units = _sealed(project)
    moved = replace(row, constructs_digest="sha256:" + "1" * 64)
    assert "construct table digests to" in _refused(project, job, row=moved)
    renamed = replace(row, slug="q4")
    assert "the JobDir compiles owtext q3" in _refused(project, job, row=renamed)


# ---------------------------------------------------------------------------------------------
# The verb's refusals
# ---------------------------------------------------------------------------------------------


def test_a_job_whose_generation_was_never_sealed_is_not_found(project: Path) -> None:
    job = _job(project)
    code, out, err = _run(["verify", "--job", str(job)], project)
    assert (code, out) == (2, "")
    assert "no artefact q3@1 in this store" in err


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--corpus", "handbook"], "--corpus is not served by ow out verify"),
        (["--quiet"], "--quiet is parsed and not served by ow out verify"),
        (["--render", "rows"], "--render rows is parsed and not served by ow out verify"),
    ],
)
def test_usage_is_refused_by_name(argv: list[str], named: str, project: Path) -> None:
    job = _job(project)
    code, out, err = _run(["verify", "--job", str(job), *argv], project)
    assert (code, out) == (1, "")
    assert named in err
