"""`ow doctor`'s four local rows: D-01, D-05, D-11 and D-15. D953.

Each row is asked of a configuration `load()` resolved from a temp project, with the two machine
readings (the SQLite version and a volume's free bytes) handed in where a test cannot choose them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from omniweave.doctor import local
from omniweave_core.config import load

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.config import Config

CORPUS = '[corpora.docs]\npath = ".omniweave/docs.owstore"\n[serve]\ndefault_corpus = "docs"\n'


def _config(project: Path, text: str = CORPUS) -> Config:
    project.mkdir(parents=True, exist_ok=True)
    (project / "omniweave.toml").write_text(text, encoding="utf-8")
    return load(cwd=project, env={"OMNIWEAVE_HOME": str(project.parent / "home")})


# --- D-01 -----------------------------------------------------------------------------------


def test_d01_passes_at_the_floor_and_fails_below_it_with_the_stores_own_refusal() -> None:
    assert local.check_sqlite((3, 42, 0)).severity == "ok"
    old = local.check_sqlite((3, 41, 2))
    assert old.severity == "error"
    assert old.detail.startswith("OW_SQLITE_TOO_OLD: SQLite 3.41.2 is below the declared floor")
    assert old.fix == "pip install omniweave-core[sqlite]"


def test_d01_over_the_linked_library_is_ok_here() -> None:
    assert local.check_sqlite().severity == "ok"


# --- D-05 -----------------------------------------------------------------------------------


def test_d05_a_declared_corpus_not_written_yet_is_ok(tmp_path: Path) -> None:
    found = local.check_corpora(_config(tmp_path / "p"), cwd=tmp_path / "p")
    assert [one.severity for one in found] == ["ok", "ok"]
    assert "not written yet" in found[1].detail


def test_d05_a_default_corpus_naming_no_entry_fails_with_ow_a_002(tmp_path: Path) -> None:
    text = '[corpora.docs]\npath = "d.owstore"\n[serve]\ndefault_corpus = "doc"\n'
    (first, *_) = local.check_corpora(_config(tmp_path / "p", text), cwd=tmp_path / "p")
    assert first.severity == "error"
    assert "names no declared corpus" in first.detail
    assert "set [serve] default_corpus to one of: docs" in first.fix


def test_d05_a_store_path_that_is_a_directory_fails(tmp_path: Path) -> None:
    project = tmp_path / "p"
    (project / ".omniweave" / "docs.owstore").mkdir(parents=True)
    found = local.check_corpora(_config(project), cwd=project)
    assert found[-1].severity == "error"
    assert "is a directory, and a store is a file" in found[-1].detail
    assert found[-1].fix.startswith("set [corpora.docs] path to a file")


def test_d05_a_store_under_a_file_fails(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    (project / ".omniweave").write_text("not a directory", encoding="utf-8")
    found = local.check_corpora(_config(project), cwd=project)
    assert found[-1].severity == "error"
    assert "which is a file, so no store can be created there" in found[-1].detail


def test_d05_a_missing_source_root_fails(tmp_path: Path) -> None:
    text = (
        '[corpora.docs]\npath = "d.owstore"\nsource = "nowhere"\n[serve]\ndefault_corpus = "docs"\n'
    )
    found = local.check_corpora(_config(tmp_path / "p", text), cwd=tmp_path / "p")
    assert found[-1].severity == "error"
    assert "source root" in found[-1].detail
    assert "does not exist" in found[-1].detail


# --- D-11 -----------------------------------------------------------------------------------


def test_d11_passes_with_room_and_warns_with_the_shortfall(tmp_path: Path) -> None:
    config = _config(tmp_path / "p")
    roomy = local.check_free_space(config, cwd=tmp_path / "p", free=lambda _path: 10 << 30)
    assert [one.severity for one in roomy] == ["ok", "ok"]
    tight = local.check_free_space(config, cwd=tmp_path / "p", free=lambda _path: 2 << 30)
    cache, output = tight
    assert (cache.severity, output.severity) == ("warning", "ok")
    assert cache.fix.startswith(f"free {(5 << 30) - (2 << 30)} bytes on the volume holding ")


def test_d11_reads_the_volume_of_the_nearest_existing_ancestor(tmp_path: Path) -> None:
    config = _config(tmp_path / "p")
    asked: list[Path] = []

    def free(path: Path) -> int:
        asked.append(path)
        return 10 << 30

    local.check_free_space(config, cwd=tmp_path / "p", free=free)
    assert all(path.exists() for path in asked), "a root not created yet is read at its parent"


# --- D-15 -----------------------------------------------------------------------------------


def test_d15_no_project_writes_no_shard_and_is_ok(tmp_path: Path) -> None:
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "home")})
    found = local.check_events_dir(config, env={})
    assert (found.severity, found.detail) == (
        "ok",
        "no event shard is written here: no project, or no ndjson sink",
    )


def test_d15_a_writable_events_dir_is_ok_and_one_to_be_created_says_so(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    assert local.check_events_dir(config, env={}, posix=False).detail.endswith(
        "is created by the first run"
    )
    (project / ".omniweave" / "events").mkdir(parents=True)
    assert local.check_events_dir(config, env={}, posix=False).severity == "ok"


def test_d15_on_posix_a_directory_others_can_read_warns_with_chmod(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    events = project / ".omniweave" / "events"
    events.mkdir(parents=True)
    events.chmod(0o755)
    found = local.check_events_dir(config, env={}, posix=True)
    assert found.severity == "warning"
    assert found.fix == f"chmod 700 {events.as_posix()}"


def test_d15_an_unwritable_directory_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "p"
    config = _config(project)
    (project / ".omniweave" / "events").mkdir(parents=True)
    monkeypatch.setattr(local.os, "access", lambda _path, _mode: False)
    found = local.check_events_dir(config, env={}, posix=False)
    assert found.severity == "warning"
    assert "is not writable, so a run's events degrade to the console" in found.detail
