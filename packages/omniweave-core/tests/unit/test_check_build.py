"""`tools/check_build.py`: the build job's 28-file and reproducibility assertions. D874.

`judge()` and `reproduced()` are held rule by rule over file names and digests. `main()` runs with
its two builds faked, each writing a chosen set of artefacts, so no test here spawns `uv build`:
V10-2's instrument runs the real one. Loaded by file path under a private name and at module scope,
as `test_gate_bless.py` loads its gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "check_build.py"
    spec = importlib.util.spec_from_file_location("_owgate_check_build", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
NAMES = ("omniweave", "omniweave-core")
GOOD = (
    "omniweave-0.1.0-py3-none-any.whl",
    "omniweave-0.1.0.tar.gz",
    "omniweave_core-0.1.0-py3-none-any.whl",
    "omniweave_core-0.1.0.tar.gz",
)


def _kinds(findings: list[Any]) -> list[tuple[str, str]]:
    return [(f.kind, f.names) for f in findings]


def test_the_members_are_the_workspace_s_fourteen() -> None:
    members = GATE.members(REPO)
    assert len(members) == 14
    assert "omniweave-core" in members
    assert all(name.startswith("omniweave") for name in members)


def test_one_sdist_and_one_pure_wheel_per_member_is_clean() -> None:
    assert GATE.judge(NAMES, GOOD) == []


def test_a_missing_or_doubled_artefact_is_named() -> None:
    assert _kinds(GATE.judge(NAMES, GOOD[1:])) == [("wheel", "omniweave: 0 wheels, not 1")]
    doubled = (*GOOD, "omniweave_core-0.1.1.tar.gz")
    assert _kinds(GATE.judge(NAMES, doubled)) == [("sdist", "omniweave-core: 2 sdists, not 1")]


def test_a_platform_wheel_and_a_stray_are_named() -> None:
    files = (
        "omniweave-0.1.0-cp312-cp312-win_amd64.whl",
        "omniweave-0.1.0.tar.gz",
        *GOOD[2:],
        "notes.txt",
    )
    assert _kinds(GATE.judge(NAMES, files)) == [
        ("platform", "omniweave-0.1.0-cp312-cp312-win_amd64.whl is not py3-none-any (section 7.1)"),
        ("stray", "notes.txt is no workspace member's artefact"),
    ]


def test_a_member_s_prefix_is_not_another_member_s() -> None:
    """`omniweave_core-*` is not `omniweave`'s: the stem ends at the dash."""
    assert _kinds(GATE.judge(("omniweave",), GOOD[2:])) == [
        ("sdist", "omniweave: 0 sdists, not 1"),
        ("wheel", "omniweave: 0 wheels, not 1"),
        ("stray", "omniweave_core-0.1.0-py3-none-any.whl is no workspace member's artefact"),
        ("stray", "omniweave_core-0.1.0.tar.gz is no workspace member's artefact"),
    ]


def test_reproducibility_compares_name_for_name_and_byte_for_byte() -> None:
    first = {"a.whl": "1", "b.tar.gz": "2"}
    assert GATE.reproduced(first, dict(first)) == []
    assert _kinds(GATE.reproduced(first, {"a.whl": "1", "b.tar.gz": "3"})) == [
        ("reproducible", "b.tar.gz: pass two's sha256 differs from pass one's")
    ]
    assert _kinds(GATE.reproduced(first, {"a.whl": "1"})) == [
        ("reproducible", "b.tar.gz: built by one pass only")
    ]


def test_digests_leave_dotfiles_out(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("*", encoding="utf-8")
    (tmp_path / "a.whl").write_bytes(b"x")
    assert list(GATE.digests(tmp_path)) == ["a.whl"]


def _fake_builds(monkeypatch: pytest.MonkeyPatch, *passes: dict[str, bytes]) -> list[str]:
    epochs: list[str] = []
    queue = list(passes)

    def build(_root: Path, out: Path, epoch: str) -> None:
        epochs.append(epoch)
        out.mkdir(parents=True, exist_ok=True)
        for name, data in queue.pop(0).items():
            (out / name).write_bytes(data)

    monkeypatch.setattr(GATE, "build", build)
    monkeypatch.setattr(GATE, "members", lambda _root: NAMES)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    return epochs


def _artefacts(**changed: bytes) -> dict[str, bytes]:
    return {name: changed.get(name.split("-")[0], name.encode()) for name in GOOD}


def test_two_identical_passes_exit_0_under_one_epoch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    epochs = _fake_builds(monkeypatch, _artefacts(), _artefacts())
    assert GATE.main([]) == 0
    assert epochs == ["1700000000", "1700000000"]
    assert capsys.readouterr().out == (
        "check_build ok: 2 members, 2 sdists, 2 wheels, SOURCE_DATE_EPOCH=1700000000; every wheel "
        "py3-none-any; two passes, 4 identical sha256s\n"
    )


def test_a_pass_that_differs_exits_1_naming_the_file(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_builds(monkeypatch, _artefacts(), _artefacts(omniweave=b"other"))
    assert GATE.main([]) == 1
    out = capsys.readouterr().out
    assert "omniweave-0.1.0.tar.gz: pass two's sha256 differs from pass one's" in out
    assert out.splitlines()[-1].startswith("check_build FAILED: 2 finding(s);")


def test_dist_is_pass_one_and_only_pass_two_is_built(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name, data in _artefacts().items():
        (tmp_path / name).write_bytes(data)
    epochs = _fake_builds(monkeypatch, _artefacts())
    assert GATE.main(["--dist", str(tmp_path)]) == 0
    assert len(epochs) == 1


def test_a_build_that_cannot_run_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*_args: object) -> None:
        raise GATE.BuildError("no uv on PATH")

    monkeypatch.setattr(GATE, "build", broken)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1")
    assert GATE.main([]) == 2
    assert "the build could not run: no uv on PATH" in capsys.readouterr().out


def test_the_epoch_is_the_environment_s_when_set() -> None:
    assert GATE._epoch(REPO, {"SOURCE_DATE_EPOCH": "42"}) == "42"
