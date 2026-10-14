"""`out.job.scaffold()` and `job_path()`: one JobDir, written whole, from a card and a Brief (D764).

02 section 5 row 2 lists what a JobDir holds, 09 section 3.2 says which roster the scaffold writes,
and section 5.4 names the path. The target is owtext, found through the conformance suite's
directory, so the table and the card are the shipped ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import omniweave_conform.suites.target as target_suites
import pytest
from omniweave_conform.suites.target.owtext.driver import OwTextCompiler
from omniweave_core.discovery import discover
from omniweave_core.errors import TargetError
from omniweave_core.events import traceparent
from omniweave_core.out.agentdoc import load_table
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.card import CompileCard
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import (
    BRIEF_MD,
    JOB_JSON,
    ILBundle,
    Job,
    job_path,
    read_il_files,
    scaffold,
)
from omniweave_core.out.ledger import ASSET_INDEX, ledger_digest, read_index
from omniweave_core.out.report import il_digest

SUITES = Path(target_suites.__file__).parent
TRACE = traceparent("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7")
RUN = "r_01JA2B3C4D5E6F7G8H9JKMNPQR"


def _brief_text(rhythm: str) -> str:
    return (
        f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
        "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
        f"- level: static\n## typography\n## rhythm\n{rhythm}## forbidden\n"
    )


RHYTHM = "- u99: { anchor: content }\n- u01: { anchor: cover }\n- u100: { anchor: close }\n"
"""`u99` before `u100` is numeric order; text order would put `u100` first."""


def _owtext() -> tuple[CompileCard, str, Any]:
    for card in discover(env={"OMNIWEAVE_DRIVER_PATH": str(SUITES)}).cards:
        if str(card.identity.port) == "compile" and CompileCard.of(card).target == "owtext":
            compiled = CompileCard.of(card)
            return compiled, card.card_sha256, load_table(Path(card.source), compiled)
    raise AssertionError("owtext")


def _scaffold(job_dir: Path, *, rhythm: str = RHYTHM, slug: str = "q3-board") -> Job:
    card, sha, table = _owtext()
    text = _brief_text(rhythm)
    return scaffold(
        job_dir,
        card=card,
        card_sha256=sha,
        table=table,
        brief_text=text,
        brief=parse_brief(text, baseline=()),
        slug=slug,
        artifact_gen=3,
        corpus="handbook",
        traceparent=TRACE,
        clock_ns=1_700_000_000_000_000_000,
    )


def _where(tmp_path: Path) -> Path:
    return job_path(tmp_path / "cache", RUN, "q3-board", 3)


# ---------------------------------------------------------------------------------------------
# Ruling 23: the path
# ---------------------------------------------------------------------------------------------


def test_the_job_path_is_run_scoped_with_the_slug_and_generation(tmp_path: Path) -> None:
    assert job_path(tmp_path, RUN, "q3-board", 3) == tmp_path / "jobs" / RUN / "q3-board@3"


@pytest.mark.parametrize(
    ("run_id", "slug", "gen", "said"),
    [
        ("r_short", "q3-board", 1, "is not r_ and 26"),
        ("01JA2B3C4D5E6F7G8H9JKMNPQR", "q3-board", 1, "is not r_ and 26"),
        ("r_01JA2B3C4D5E6F7G8H9JKMNPQI", "q3-board", 1, "is not r_ and 26"),
        (RUN, "q3-board", 0, "artifact_gen 0 is below 1"),
    ],
)
def test_a_malformed_run_id_or_generation_is_refused(
    run_id: str, slug: str, gen: int, said: str, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match=said):
        job_path(tmp_path, run_id, slug, gen)


@pytest.mark.parametrize("slug", ["Q3-board", "q3_board", "-q3", "", "a" * 65, "../up", "q3 board"])
def test_a_slug_outside_its_grammar_is_refused(slug: str, tmp_path: Path) -> None:
    with pytest.raises(
        TargetError, match="is not lower-case letters, digits and hyphens"
    ) as caught:
        job_path(tmp_path, RUN, slug, 1)
    assert caught.value.code() == "OW_TARGET_SLUG_INVALID"
    with pytest.raises(TargetError, match="is not lower-case letters"):
        _scaffold(tmp_path / "job", slug=slug)
    assert not (tmp_path / "job").exists()


# ---------------------------------------------------------------------------------------------
# Ruling 22: the layout, written whole
# ---------------------------------------------------------------------------------------------


def test_the_job_dir_holds_what_02_lists_and_nothing_else(tmp_path: Path) -> None:
    where = _where(tmp_path)
    _scaffold(where)
    assert sorted(p.relative_to(where).as_posix() for p in where.rglob("*")) == [
        "assets", ASSET_INDEX, BRIEF_MD, "il", "il/il.toml", JOB_JSON, "out", "validation",
    ]  # fmt: skip
    assert (where / BRIEF_MD).read_text(encoding="utf-8") == _brief_text(RHYTHM)
    assert read_index(where) == ()
    assert sorted(p.name for p in where.parent.iterdir()) == ["q3-board@3"]


def test_job_json_is_the_job_returned_and_loads_back(tmp_path: Path) -> None:
    where = _where(tmp_path)
    job = _scaffold(where)
    assert Job.load(where) == job
    assert (where / JOB_JSON).read_bytes() == job.to_bytes()


def test_il_toml_names_the_table_and_no_unit_yet(tmp_path: Path) -> None:
    """Ruling 25: a row with no file is OW-T-507, so the authoring agent adds each row."""
    where = _where(tmp_path)
    _, _, table = _owtext()
    _scaffold(where)
    assert (where / "il" / "il.toml").read_text(encoding="utf-8") == (
        f'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "{table.digest()}"\n'
    )
    bundle = ILBundle.load(where / "il", carrier=OwTextCompiler().carrier, constructs=table)
    assert bundle.units == ()


# ---------------------------------------------------------------------------------------------
# Rulings 24 and 26: the Plan a scaffold can honestly write
# ---------------------------------------------------------------------------------------------


def test_the_roster_is_the_rhythm_in_numeric_order_with_anchors(tmp_path: Path) -> None:
    plan = _scaffold(_where(tmp_path)).plan
    assert [(u.id, u.ord, u.il_path, u.anchor) for u in plan.units] == [
        ("u01", 1, "il/u01.html", "cover"),
        ("u99", 2, "il/u99.html", "content"),
        ("u100", 3, "il/u100.html", "close"),
    ]
    assert plan.unit_count == 3
    assert all(u.nsig is None and u.manual_reason is None for u in plan.units)


def test_the_plan_carries_what_a_scaffold_knows(tmp_path: Path) -> None:
    where = _where(tmp_path)
    card, sha, table = _owtext()
    job = _scaffold(where)
    plan = job.plan
    assert (plan.target, plan.slug, plan.artifact_gen, plan.corpus) == (
        "owtext", "q3-board", 3, "handbook",
    )  # fmt: skip
    assert (plan.delivery, plan.gate_status, dict(plan.cites)) == (
        "release", GateStatus.NOT_PROVIDED, {},
    )  # fmt: skip
    assert plan.il_digest == il_digest(read_il_files(where / "il"))
    assert plan.constructs_digest == table.digest() == card.constructs_digest
    assert plan.ledger_digest == ledger_digest(())
    assert plan.brief_digest == plan.brief.digest()
    assert plan.card_sha256 == sha
    assert plan.toolchain_digest is None
    assert (job.traceparent, job.determinism.clock_ns) == (TRACE, 1_700_000_000_000_000_000)


def test_a_rhythm_with_no_row_commissions_nothing_and_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TargetError, match="## rhythm commissions no unit") as caught:
        _scaffold(tmp_path / "job", rhythm="")
    assert caught.value.code() == "OW_TARGET_BRIEF_INVALID"
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------------------------
# Ruling 22: never over a JobDir, and nothing left behind
# ---------------------------------------------------------------------------------------------


def test_an_existing_job_dir_is_refused_and_left_alone(tmp_path: Path) -> None:
    where = _where(tmp_path)
    where.mkdir(parents=True)
    (where / "keep.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(TargetError, match="a scaffold never writes over a JobDir") as caught:
        _scaffold(where)
    assert caught.value.code() == "OW_TARGET_JOB_EXISTS"
    assert sorted(p.name for p in where.iterdir()) == ["keep.txt"]


def test_a_staged_copy_left_by_a_crash_is_refused_too(tmp_path: Path) -> None:
    where = _where(tmp_path)
    staged = where.with_name(where.name + ".tmp")
    staged.mkdir(parents=True)
    with pytest.raises(TargetError, match=r"q3-board@3\.tmp exists"):
        _scaffold(where)
    assert not where.exists()


def test_a_failure_part_way_leaves_no_job_dir_and_no_staged_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    where = _where(tmp_path)

    def broken(_self: Job, _job_dir: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Job, "write", broken)
    with pytest.raises(OSError, match="disk full"):
        _scaffold(where)
    assert sorted(p.name for p in where.parent.iterdir()) == []


def test_the_written_job_validates_against_the_committed_schema(tmp_path: Path) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    where = _where(tmp_path)
    _scaffold(where)
    repo = Path(__file__).resolve().parents[4]
    schema = json.loads((repo / "schema" / "job-v1.json").read_text(encoding="utf-8"))
    jsonschema.validate(json.loads((where / JOB_JSON).read_bytes()), schema)
