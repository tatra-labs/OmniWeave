"""`ow doctor`'s local rows: D-01, D-05, D-11 and D-15 (D953), D-10 (D958), D-25 (D961) and
D-26 (D963).

Each row is asked of a configuration `load()` resolved from a temp project, with the two machine
readings (the SQLite version and a volume's free bytes) handed in where a test cannot choose them.
"""

from __future__ import annotations

import gzip
import json
import os
from typing import TYPE_CHECKING

import pytest
from omniweave.doctor import local
from omniweave.run.supervisor import HostFacts
from omniweave_core.config import load
from omniweave_core.redact import CANARY

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


# --- D-10 (D958) ----------------------------------------------------------------------------

GB = 1 << 30
ROSTER = {"free": 450, "local_compute": 1_800, "billed_api": 260}
"""08:717-723's roster: each cost class's heaviest enabled card's `[isolation] memory_mb`."""


def test_d10_the_laptop_fits_with_its_workers_clamped_to_its_cpus(tmp_path: Path) -> None:
    """08:729: 3 x 450 + 2 x 1800 + 8 x 260 = 7,030 MB against 0.8 x 16 GB."""
    laptop = HostFacts(cpus=4, ram_bytes=16 * GB, free_disk_bytes=GB)
    found = local.check_ram(_config(tmp_path / "p"), memory_mb=ROSTER, cwd=tmp_path, host=laptop)
    assert (found.check, found.severity, found.fix) == ("D-10", "ok", "")
    assert found.detail == (
        "the enabled drivers' worker processes fit: free 3 x 450 MB + local_compute 2 x 1800 MB "
        "+ billed_api 8 x 260 MB = 7030 MB, against 0.8 of this machine's 16384 MB (13107 MB)"
    )


def test_d10_the_container_fails_and_names_max_workers(tmp_path: Path) -> None:
    """08:731: eight visible CPUs inside a 4 GB limit need 11,080 MB, over 3,276 MB."""
    container = HostFacts(cpus=8, ram_bytes=4 * GB, free_disk_bytes=GB)
    found = local.check_ram(_config(tmp_path / "p"), memory_mb=ROSTER, cwd=tmp_path, host=container)
    assert found.severity == "error"
    assert "need more RAM than this machine has" in found.detail
    assert "= 11080 MB, against 0.8 of this machine's 4096 MB (3276 MB)" in found.detail
    assert found.fix == (
        "lower max_workers under [drivers] in omniweave.toml "
        "(here it runs free = 4, local_compute = 4, billed_api = 8)"
    )


def test_d10_the_configured_workers_are_what_it_sums(tmp_path: Path) -> None:
    """08:735's own fix, `{free = 2, local_compute = 1, billed_api = 2}`, is 3,220 MB: it fits."""
    text = "[drivers]\nmax_workers = { free = 2, local_compute = 1, billed_api = 2 }\n"
    container = HostFacts(cpus=8, ram_bytes=4 * GB, free_disk_bytes=GB)
    found = local.check_ram(
        _config(tmp_path / "p", text), memory_mb=ROSTER, cwd=tmp_path, host=container
    )
    assert found.severity == "ok"
    assert "= 3220 MB" in found.detail


def test_d10_a_machine_that_will_not_say_its_ram_warns(tmp_path: Path) -> None:
    unknown = HostFacts(cpus=4, ram_bytes=0, free_disk_bytes=GB)
    found = local.check_ram(_config(tmp_path / "p"), memory_mb=ROSTER, cwd=tmp_path, host=unknown)
    assert found.severity == "warning"
    assert "does not report physical RAM" in found.detail
    assert found.fix.startswith("compare free 3 x 450 MB + ")


def test_d10_measures_this_machine_when_no_host_is_handed_in(tmp_path: Path) -> None:
    found = local.check_ram(_config(tmp_path / "p"), memory_mb=ROSTER, cwd=tmp_path / "p")
    assert found.severity in {"ok", "error"}, "every CI cell reports its RAM (D958)"


# --- D-25 (D961) ----------------------------------------------------------------------------


def _shard(project: Path, name: str, body: bytes, *, mtime_s: int) -> Path:
    events = project / ".omniweave" / "events"
    events.mkdir(parents=True, exist_ok=True)
    shard = events / name
    shard.write_bytes(gzip.compress(body) if name.endswith(".gz") else body)
    os.utime(shard, (mtime_s, mtime_s))
    return shard


def test_d25_no_shard_is_nothing_to_grep(tmp_path: Path) -> None:
    found = local.check_canary(_config(tmp_path / "p"), env={}, cwd=tmp_path / "p")
    assert (found.check, found.severity) == ("D-25", "ok")
    assert found.detail == "no event shard to grep: no run wrote one here"


def test_d25_only_the_newest_shard_is_grepped(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    _shard(project, "r_old.ndjson", f'{{"m":"{CANARY}"}}\n'.encode(), mtime_s=1_000)
    _shard(project, "r_new.ndjson", b'{"m":"clean"}\n', mtime_s=2_000)
    found = local.check_canary(config, env={}, cwd=project, posix=False)
    assert (found.severity, found.detail) == (
        "ok",
        "the newest event shard r_new.ndjson carries no redaction canary",
    )


def test_d25_the_canary_in_the_newest_shard_fails(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    shard = _shard(project, "r_1.ndjson", f'{{"m":"page {CANARY}"}}\n'.encode(), mtime_s=2_000)
    found = local.check_canary(config, env={}, cwd=project)
    assert found.severity == "error"
    assert found.detail.startswith(f"the redaction canary {CANARY} is in the newest event shard")
    assert found.fix == f"delete the shards under {shard.parent.as_posix()}, and file a bug"


def test_d25_a_rolled_shard_is_read_through_gzip(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    _shard(project, "r_1.0001.ndjson.gz", f"{CANARY}\n".encode(), mtime_s=2_000)
    assert local.check_canary(config, env={}, cwd=project).severity == "error"


def test_d25_a_damaged_rolled_shard_warns(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    events = project / ".omniweave" / "events"
    events.mkdir(parents=True)
    (events / "r_1.0001.ndjson.gz").write_bytes(b"not gzip")
    found = local.check_canary(config, env={}, cwd=project)
    assert found.severity == "warning"
    assert "could not be read" in found.detail


def test_d25_the_newest_runs_path_map_must_be_0600(tmp_path: Path) -> None:
    """15:1330: `{run_id}.paths.json` maps every token back to a path; only its owner reads it."""
    from omniweave.surface.ingest import root_of  # noqa: PLC0415

    project = tmp_path / "p"
    config = _config(project)
    _shard(project, "r_7.ndjson", b"{}\n", mtime_s=2_000)
    mapping = root_of(config, "roots.output", project) / "runs" / "r_7.paths.json"
    mapping.parent.mkdir(parents=True)
    mapping.write_text("{}", encoding="utf-8")
    mapping.chmod(0o644)
    found = local.check_canary(config, env={}, cwd=project, posix=True)
    assert found.severity == "error"
    assert found.fix == f"chmod 600 {mapping.as_posix()}"
    assert local.check_canary(config, env={}, cwd=project, posix=False).severity == "ok"


# --- D-26 (D963) ----------------------------------------------------------------------------

ENDPOINT = "http://collector.invalid:4318/v1/traces?token=secret"


def _manifests(project: Path, config: Config, bodies: dict[str, object]) -> Path:
    from omniweave.surface.ingest import root_of  # noqa: PLC0415

    runs = root_of(config, "roots.output", project) / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        (runs / name).write_text(body if isinstance(body, str) else json.dumps(body), "utf-8")
    return runs


def test_d26_unset_says_so_and_counts_the_recorded_runs(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    found = local.check_otlp(config, cwd=project)
    assert (found.check, found.severity, found.fix) == ("D-26", "ok", "")
    assert found.detail == (
        "[observe] otlp_endpoint is not set; no run manifest here records it yet"
    )
    _manifests(
        project,
        config,
        {
            "r_1.json": {"run_id": "r_1", "otlp_endpoint_set": True},
            "r_2.json": {"run_id": "r_2", "otlp_endpoint_set": False},
            "r_3.json": {"run_id": "r_3"},
            "r_1.paths.json": {"otlp_endpoint_set": True},
            "r_4.json": "not json",
        },
    )
    found = local.check_otlp(config, cwd=project)
    assert found.detail.endswith("; 1 of 2 recorded run(s) had it set"), found.detail


def test_d26_set_names_its_source_and_never_its_url(tmp_path: Path) -> None:
    project = tmp_path / "p"
    project.mkdir()
    (project / "omniweave.toml").write_text(
        CORPUS + f'[observe]\notlp_endpoint = "{ENDPOINT}"\n', encoding="utf-8"
    )
    config = load(cwd=project, env={"OMNIWEAVE_HOME": str(tmp_path / "home")})
    found = local.check_otlp(config, cwd=project)
    assert found.severity == "ok"
    assert found.detail.startswith("[observe] otlp_endpoint is set, from ")
    assert "omniweave.toml" in found.detail
    assert "collector.invalid" not in found.detail
    assert "secret" not in found.detail
