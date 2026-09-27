"""`ow doctor`: D-02 over hand-built indexes, the report's three tuples, and the verb's exit.

The index bytes are `conftest.py`'s `git_index`. What is pinned here is the doctor's side:
- which paths count as a store;
- the order in which a tracked store and an unreadable index are reported;
- 18:748's rule, that `fix` is empty only at `ok`;
- 18:222's exit;
- the list of rows this build does not check.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave_core.errors import explain

from omniweave import doctor

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from omniweave.sdk.reports import DoctorFinding, DoctorReport


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
    assert [one.check for one in report.ok] == []
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
    assert out.rstrip().endswith("doctor: fails the 1 check(s) it ran")


def test_the_verb_exits_0_and_names_every_row_it_did_not_run(repo: Any) -> None:
    code, out, _ = _main(["doctor", "--runtime"], repo(["src/a.py"]))
    assert code == doctor.OK == 0
    assert "ok   D-02: no .owstore is tracked" in out
    assert f"26 of 27 checks are not built yet and were not run: {', '.join(doctor.UNBUILT)}" in out


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
