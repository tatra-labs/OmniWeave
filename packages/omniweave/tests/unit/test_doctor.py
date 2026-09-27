"""`ow doctor`: D-02 over hand-built indexes, the report's three tuples, and the verb's exit.

The index bytes are `conftest.py`'s `git_index`. What is pinned here is the doctor's side:
- which paths count as a store;
- the order in which a tracked store and an unreadable index are reported;
- 18:748's rule, that `fix` is empty only at `ok`;
- 18:222's exit;
- the list of rows this build does not check;
- D-08 over a replaced catalog (W7.8e): the real rebuild over real hostile wheels is G11's clause
  6, run as a process, and this file pins the row's rules.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave_core.errors import explain

from omniweave import doctor

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from omniweave.sdk.reports import DoctorFinding, DoctorReport


@pytest.fixture(autouse=True)
def roster(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The catalog D-08 reads, replaced, so no test here depends on what this machine installed.

    A test sets `cards` (id -> attested) and `faults`. `calls` records what each pass was given.
    """
    from omniweave_core import discovery  # noqa: PLC0415

    state = SimpleNamespace(cards={}, faults=(), calls=[])

    def fake_catalog(**kwargs: object) -> SimpleNamespace:
        state.calls.append(("catalog", kwargs))
        cards = {k: SimpleNamespace(attested=v) for k, v in state.cards.items()}
        return SimpleNamespace(cards=cards)

    def fake_discover(**kwargs: object) -> SimpleNamespace:
        state.calls.append(("discover", kwargs))
        return SimpleNamespace(faults=state.faults)

    monkeypatch.setattr(discovery, "catalog", fake_catalog)
    monkeypatch.setattr(discovery, "discover", fake_discover)
    return state


@pytest.fixture
def repo(tmp_path: Path, git_index: Any) -> Any:
    """A work tree at `tmp_path` whose index tracks exactly the paths given."""

    def make(tracked: Sequence[str], **index: object) -> Path:
        (tmp_path / ".git").mkdir()
        data = git_index.build(tuple(p.encode() for p in tracked), **index)
        (tmp_path / ".git" / "index").write_bytes(data)
        return tmp_path

    return make


def _all(report: DoctorReport) -> tuple[DoctorFinding, ...]:
    return (*report.ok, *report.warned, *report.failed)


def test_the_two_spellings_are_the_registers() -> None:
    row = explain(doctor.STORE_TRACKED)
    assert row.symbol == doctor.STORE_TRACKED_SYMBOL
    assert explain(doctor.STORE_TRACKED_SYMBOL).numeric == "OW-S-060"
    assert row.fix.startswith("git rm --cached")  # 15:1515's fix cell


def test_built_and_unbuilt_are_exactly_d01_to_d27() -> None:
    assert not set(doctor.BUILT) & set(doctor.UNBUILT)
    assert sorted((*doctor.BUILT, *doctor.UNBUILT)) == [f"D-{n:02d}" for n in range(1, 28)]


@pytest.mark.parametrize(
    "path",
    [
        ".omniweave/index.owstore",
        "index.vec.owstore",
        "deep/er/events.owstore",
        ".omniweave/index.owstore-wal",
        ".omniweave/index.owstore-shm",
    ],
)
def test_a_tracked_store_or_sidecar_fails_with_ow_s_060(repo: Any, path: str) -> None:
    finding = doctor.check_tracked_store(repo(["README.md", path]))
    assert finding.severity == "error"
    assert finding.detail.startswith("OW-S-060 OW_STORE_TRACKED_IN_GIT: 1 store file(s)")
    assert finding.fix == f"git rm --cached -- {path}"


@pytest.mark.parametrize("path", ["owstore.md", "notes/owstore", "x.owstore.d/readme"])
def test_a_name_that_only_mentions_owstore_is_not_a_store(repo: Any, path: str) -> None:
    """The glob is matched against the final component, so a directory named like a store does
    not make every file inside it one."""
    assert doctor.check_tracked_store(repo([path])).severity == "ok"


def test_every_tracked_store_is_named_and_a_spaced_path_is_quoted(repo: Any) -> None:
    finding = doctor.check_tracked_store(repo(["a.owstore", "my corpus/b.owstore"]))
    assert "2 store file(s)" in finding.detail
    assert finding.fix == 'git rm --cached -- a.owstore "my corpus/b.owstore"'


def test_a_clean_index_is_ok(repo: Any) -> None:
    finding = doctor.check_tracked_store(repo([".gitignore", "src/a.py"]))
    assert (finding.severity, finding.fix) == ("ok", "")


def test_outside_a_work_tree_is_ok(tmp_path: Path) -> None:
    assert doctor.check_tracked_store(tmp_path).severity == "ok"


def test_an_unreadable_index_warns_and_never_reads_as_clean(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "index").write_bytes(b"garbage")
    finding = doctor.check_tracked_store(tmp_path)
    assert finding.severity == "warning"
    assert finding.fix == "git ls-files -- '*.owstore*'"


def test_a_store_seen_before_the_read_stopped_still_fails(repo: Any) -> None:
    """A split index is incomplete, but the entries it did hold are real: one of them being a
    store is a failure, not a warning."""
    link = b"link" + b"\0\0\0\x14" + b"\0" * 20
    finding = doctor.check_tracked_store(repo(["a.owstore"], extensions=link))
    assert finding.severity == "error"


def test_run_sorts_findings_three_ways_and_fix_is_empty_only_at_ok(repo: Any) -> None:
    report = doctor.run(cwd=repo(["a.owstore"]), env={})
    assert [one.check for one in report.failed] == ["D-02"]
    assert [one.check for one in report.ok] == ["catalog", "D-08"]
    for one in _all(report):
        assert (one.fix == "") is (one.severity == "ok"), one


def test_run_carries_the_resolved_configuration(repo: Any) -> None:
    report = doctor.run(cwd=repo([]), env={})
    assert report.failed == ()
    assert len(report.config_digest) == len(report.semantic_digest) == 64
    assert report.config_sources
    assert all(isinstance(source, str) and source for source in report.config_sources.values())


def _main(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = doctor.main(argv, cwd=cwd, env={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_the_verb_exits_1_on_a_tracked_store_and_prints_the_fix(repo: Any) -> None:
    code, out, _ = _main(["doctor"], repo([".omniweave/index.owstore"]))
    assert code == doctor.FAILED == 1
    assert "FAIL D-02: OW-S-060 OW_STORE_TRACKED_IN_GIT" in out
    assert "fix: git rm --cached -- .omniweave/index.owstore" in out
    assert out.rstrip().endswith("doctor: fails the 2 check(s) it ran")


def test_the_verb_exits_0_and_names_every_row_it_did_not_run(repo: Any) -> None:
    code, out, _ = _main(["doctor", "--runtime"], repo(["src/a.py"]))
    assert code == doctor.OK == 0
    assert "ok   D-02: no .owstore is tracked" in out
    assert f"25 of 27 checks are not built yet and were not run: {', '.join(doctor.UNBUILT)}" in out


def test_an_unknown_flag_is_argparses_usage_error(tmp_path: Path) -> None:
    code, _, err = _main(["doctor", "--no-such-flag"], tmp_path)
    assert code == 2
    assert "--no-such-flag" in err


def test_python_m_omniweave_dispatches_doctor(
    repo: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "doctor" in launcher.DISPATCHED
    monkeypatch.chdir(repo(["a.owstore"]))
    assert launcher.main(["doctor"]) == 1
    assert "OW-S-060" in capsys.readouterr().out


# ---------------------------------------------------------------------------------------------
# D-08 and the catalog rebuild (W7.8e)
# ---------------------------------------------------------------------------------------------

ENABLED = ("parse.office.anydoc", "parse.pdf.pdfium", "parse.page.olmocr")


def _d08(*, allow: bool = False) -> list[DoctorFinding]:
    found = doctor.check_driver_cards(
        env={}, project_root=None, enabled=ENABLED, allow_unattested=allow
    )
    return [one for one in found if one.check == "D-08"]


def test_an_enabled_unattested_card_fails_d08_once_per_driver(roster: SimpleNamespace) -> None:
    roster.cards = {"parse.office.anydoc": False, "parse.pdf.pdfium": False}
    failed = _d08()
    assert [one.severity for one in failed] == ["error", "error"]
    assert "parse.office.anydoc is in [drivers] enabled" in failed[0].detail
    assert all(one.fix.startswith("OMNIWEAVE_DRIVERS_ALLOW_UNATTESTED=true") for one in failed)


def test_allow_unattested_waives_d08_and_says_so(roster: SimpleNamespace) -> None:
    roster.cards = {"parse.office.anydoc": False, "parse.pdf.pdfium": True}
    (only,) = _d08(allow=True)
    assert only.severity == "ok"
    assert "2 enabled driver(s) have a valid card; attestation waived for parse.office.anydoc" in (
        only.detail
    )


def test_attested_cards_pass_d08_with_nothing_waived(roster: SimpleNamespace) -> None:
    roster.cards = {"parse.office.anydoc": True, "parse.pdf.pdfium": True}
    (only,) = _d08()
    assert (only.severity, "waived" in only.detail) == ("ok", False)


def test_an_enabled_id_with_no_card_is_named_and_fails_nothing(roster: SimpleNamespace) -> None:
    """00:116: olmOCR is enabled so the rule can fire where the distribution is absent."""
    roster.cards = {"parse.office.anydoc": True}
    (only,) = _d08()
    assert only.severity == "ok"
    assert "2 enabled id(s) have no installed card" in only.detail
    assert "parse.page.olmocr" in only.detail


def test_an_unattested_card_that_is_not_enabled_is_not_d08s(roster: SimpleNamespace) -> None:
    roster.cards = {"parse.office.anydoc": True, "parse.rogue.entrypoint": False}
    assert [one.severity for one in _d08()] == ["ok"]


def test_the_catalog_line_names_every_card_discovered(roster: SimpleNamespace) -> None:
    """The line G11's clause 6 reads, so a pass that found nothing cannot read as a pass."""
    roster.cards = {"parse.b": True, "parse.a": False}
    found = doctor.check_driver_cards(env={}, project_root=None, enabled=(), allow_unattested=False)
    (line,) = [one for one in found if one.check == "catalog"]
    assert line.detail == "rebuilt: 2 card(s): parse.a, parse.b"


def test_a_discovery_fault_is_a_warning_carrying_its_own_fix(roster: SimpleNamespace) -> None:
    roster.faults = (
        SimpleNamespace(symbol="OW_X", detail="bad", source="/x/driver.toml", fix="do this"),
        SimpleNamespace(symbol="OW_Y", detail="worse", source="/y", fix=""),
    )
    found = doctor.check_driver_cards(env={}, project_root=None, enabled=(), allow_unattested=False)
    warned = [one for one in found if one.severity == "warning"]
    assert [one.detail for one in warned] == ["OW_X: bad (/x/driver.toml)", "OW_Y: worse (/y)"]
    assert [one.fix for one in warned] == ["do this", "python tools/ow_drivers.py list"]


def test_run_reads_the_opt_in_and_the_project_from_the_resolved_config(
    roster: SimpleNamespace, tmp_path: Path
) -> None:
    """`allow_unattested` through its declared twin, and `project_root` from the directory of the
    `omniweave.toml` that was read, never from the working directory itself."""
    (tmp_path / "omniweave.toml").write_text("[drivers]\nrequire_lock = false\n", "utf-8")
    sub = tmp_path / "deeper"
    sub.mkdir()
    roster.cards = {"parse.office.anydoc": False}
    env = {"OMNIWEAVE_DRIVERS_ALLOW_UNATTESTED": "true"}
    report = doctor.run(cwd=sub, env=env)
    assert [one.check for one in report.failed] == []
    kinds = dict(roster.calls)
    assert kinds["catalog"] == {"env": env, "project_root": tmp_path.resolve()}
    assert kinds["discover"] == {"env": env, "project_root": tmp_path.resolve()}


def test_without_a_project_file_discovery_gets_no_project(
    roster: SimpleNamespace, tmp_path: Path
) -> None:
    doctor.run(cwd=tmp_path, env={})
    assert {kwargs["project_root"] for _name, kwargs in roster.calls} == {None}


def test_a_configuration_that_fails_says_d08_did_not_run(
    roster: SimpleNamespace, tmp_path: Path
) -> None:
    (tmp_path / "omniweave.toml").write_text("[drivers]\nallow_unattested = 7\n", "utf-8")
    report = doctor.run(cwd=tmp_path, env={})
    assert [one.check for one in report.failed] == ["config"]
    assert [(one.check, one.detail) for one in report.warned] == [
        ("D-08", "not run: the configuration did not resolve")
    ]
    assert roster.calls == []
