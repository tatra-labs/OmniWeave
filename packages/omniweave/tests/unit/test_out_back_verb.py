"""`ow out back <slug> [--gen N]`: a sealed owtext artefact restored into its next JobDir.

Each test scaffolds an owtext JobDir through the verbs, checks it at `final` and compiles it in a
real worker, then restores the generation it sealed. `out.retain.restore()`'s own rulings are
`test_out_retain.py`'s; this file asks what the verb resolves, prints and refuses, and whether the
restored JobDir closes the loop through `check` and `compile`.
"""

from __future__ import annotations

import io
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_conform.suites.target.owtext.driver import HERE
from omniweave_conform.suites.target.owtext.normalizers import lower_ascii
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.job import Job
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="the named-pipe arm")
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n## forbidden\n"
    "- no glow (user)\n"
)
U01 = (
    '<section data-ow-el="u01/e1">\n'
    '  <p data-ow-el="u01/e2" class="lead" id="intro">Revenue rose 12% in Q3.</p>\n'
    "</section>\n"
)


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


def _ok(argv: Sequence[str], cwd: Path) -> str:
    code, out, err = _run(argv, cwd)
    assert (code, err) == (0, ""), err
    return out


def _sealed(project: Path) -> Path:
    """`q3@1` scaffolded, authored, checked and compiled; returns its JobDir."""
    out = _ok(
        ["scaffold", "owtext", "--brief", "brief.md", "--slug", "q3", "--render", "json"], project
    )
    job = Path(json.loads(out)["job_dir"])
    (job / "il" / "u01.html").write_text(U01, encoding="utf-8", newline="")
    il = job / "il" / "il.toml"
    il.write_text(
        il.read_text(encoding="utf-8") + '\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n',
        encoding="utf-8",
    )
    _ok(["check", "--stage", "final", "--job", str(job)], project)
    _ok(["compile", "--job", str(job)], project)
    return job


def _back(project: Path, *argv: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_ok(["back", "q3", "--render", "json", *argv], project))
    return document


# ---------------------------------------------------------------------------------------------
# Ruling 22: the restore, its report, and the loop it closes
# ---------------------------------------------------------------------------------------------


@WINDOWS_ONLY
def test_back_restores_the_newest_generation_into_the_next_ones_jobdir(project: Path) -> None:
    first = _sealed(project)
    out = _ok(["back", "q3"], project)
    lines = out.splitlines()
    assert lines[0].startswith("contract: unchanged since q3@1 (sha256:")
    restored = Path(lines[1].split(" into ", 1)[1].split(" as ", 1)[0])
    assert lines[1] == f"restored q3@1 into {restored} as q3@2 (1 unit(s))"
    assert lines[2] == f"edit il/, then: ow out check --stage final --job {restored}"
    assert restored.name == "q3@2"
    assert restored.parent.parent == first.parent.parent, "a new run under the same jobs root"
    for name in ("il.toml", "u01.html"):
        assert (restored / "il" / name).read_bytes() == (first / "il" / name).read_bytes()
    job = Job.load(restored)
    assert (job.plan.artifact_gen, job.plan.corpus, job.plan.gate_status) == (
        2,
        "handbook",
        "not-provided",
    )
    [unit] = job.plan.units
    assert (unit.id, unit.anchor, unit.source_part, unit.source_ord) == (
        "u01",
        "cover",
        "il/u01.html",
        1,
    )
    assert unit.source_nsig is not None
    brief = parse_brief((restored / "brief.md").read_text(encoding="utf-8"), baseline=())
    assert brief.digest() == Job.load(first).plan.brief_digest


@WINDOWS_ONLY
def test_the_json_report_names_both_generations_and_the_contract(project: Path) -> None:
    _sealed(project)
    document = _back(project)
    assert (document["slug"], document["from_gen"], document["artifact_gen"]) == ("q3", 1, 2)
    assert document["contract_unchanged"] is True
    assert document["recorded_digest"] == document["installed_digest"]
    assert document["units"] == ["u01"]
    assert document["run_id"] in document["job_dir"]


@WINDOWS_ONLY
def test_an_unedited_restore_compiles_to_the_lookup_and_an_edit_seals_the_next(
    project: Path,
) -> None:
    """The loop 09 section 3.6 draws: back, check, compile. Unedited, the six purity inputs are
    the sealed ones, so the compile is OUT12's lookup; edited, it is the next generation."""
    _sealed(project)
    restored = Path(_back(project)["job_dir"])
    _ok(["check", "--stage", "final", "--job", str(restored)], project)
    assert _ok(["compile", "--job", str(restored)], project).splitlines() == [
        "lookup hit: q3@1 is an earlier compile's bytes, placed again"
    ]
    (restored / "il" / "u01.html").write_text(U01.replace("12%", "15%"), encoding="utf-8")
    _ok(["check", "--stage", "final", "--job", str(restored)], project)
    sealed = _ok(["compile", "--job", str(restored)], project).splitlines()[-1]
    assert sealed.startswith("sealed q3@2 (release) at ")
    placed = Path(sealed.rsplit(" at ", 1)[1])
    assert placed.read_text(encoding="utf-8") == "== u01 ==\nRevenue rose 15% in Q3.\n"


@WINDOWS_ONLY
def test_gen_names_an_older_generation_and_the_next_is_still_one_past_the_newest(
    project: Path,
) -> None:
    _sealed(project)
    restored = Path(_back(project)["job_dir"])
    (restored / "il" / "u01.html").write_text(U01.replace("12%", "15%"), encoding="utf-8")
    _ok(["check", "--stage", "final", "--job", str(restored)], project)
    _ok(["compile", "--job", str(restored)], project)
    document = _back(project, "--gen", "1")
    assert (document["from_gen"], document["artifact_gen"]) == (1, 3)


@WINDOWS_ONLY
def test_a_moved_contract_is_said_first(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from omniweave_core.out import agentdoc  # noqa: PLC0415

    _sealed(project)
    text = (HERE / "constructs.toml").read_text(encoding="utf-8")
    moved = text.replace('since = "0.1.0"', 'since = "0.1.1"', 1)
    assert moved != text
    path = project / "moved.toml"
    path.write_text(moved, encoding="utf-8")
    table = ConstructTable.load(path, {"lower_ascii": lower_ascii})
    monkeypatch.setattr(agentdoc, "load_table", lambda *_args: table)
    lines = _ok(["back", "q3"], project).splitlines()
    assert lines[0].startswith("contract: CHANGED: q3@1 was compiled against sha256:")
    assert f"the installed table digests to {table.digest()}" in lines[0]
    assert lines[0].endswith("ow out check reports what the installed table finds")


# ---------------------------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------------------------


@WINDOWS_ONLY
def test_a_brief_missing_from_cas_is_a_dangling_row(project: Path) -> None:
    from omniweave.run.out_compile import store_cas  # noqa: PLC0415

    first = _sealed(project)
    blobs = store_cas(project / ".omniweave" / "index.owstore")
    path = blobs.path(Job.load(first).plan.brief_digest.removeprefix("sha256:"))
    path.chmod(0o644)
    path.unlink()
    code, out, err = _run(["back", "q3"], project)
    assert (code, out) != (0, "")
    assert "no CAS blob" in err


@WINDOWS_ONLY
def test_a_row_naming_no_brief_has_no_contract_to_restore(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniweave_core.store.artifact import SqliteArtifactStore  # noqa: PLC0415

    _sealed(project)
    real = SqliteArtifactStore.get
    monkeypatch.setattr(
        SqliteArtifactStore,
        "get",
        lambda self, slug, gen: replace(real(self, slug, gen), brief_digest=None),
    )
    code, out, err = _run(["back", "q3"], project)
    assert (code, out) == (2, "")
    assert "q3@1 names no Brief" in err


def test_a_slug_never_sealed_is_not_found(project: Path) -> None:
    code, out, err = _run(["back", "q3"], project)
    assert (code, out) == (2, "")
    assert "no artefact 'q3' is sealed in corpus 'handbook'" in err
    assert "ow out list --corpus handbook" in err


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--quiet"], "--quiet is parsed and not served by ow out back"),
        (["--render", "rows"], "--render rows is parsed and not served by ow out back"),
    ],
)
def test_usage_is_refused_by_name(argv: list[str], named: str, project: Path) -> None:
    code, out, err = _run(["back", "q3", *argv], project)
    assert (code, out) == (1, "")
    assert named in err
