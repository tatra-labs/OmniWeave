"""`ow doctor`'s store rows: D-24, a live `store.write` lock (D959), and D-23, an abandoned
parse's pages (D969).

Each row is asked of a configuration `load()` resolved from a temp project. The lock files are
real: one acquired in this process through `store_write_lock`, and one written by a holder that
does not exist.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omniweave.doctor import store
from omniweave_core.config import load
from omniweave_core.locks import LockHolder, store_write_lock

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.config import Config

CORPUS = '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
ACQUIRED_NS = 1_700_000_000_000_000_000
NOW_NS = ACQUIRED_NS + 42 * 1_000_000_000


def _config(project: Path, text: str = CORPUS) -> Config:
    project.mkdir(parents=True, exist_ok=True)
    (project / "omniweave.toml").write_text(text, encoding="utf-8")
    return load(cwd=project, env={"OMNIWEAVE_HOME": str(project.parent / "home")})


def test_d24_no_corpus_declared_holds_no_lock(tmp_path: Path) -> None:
    (found,) = store.check_write_locks(_config(tmp_path / "p", ""), cwd=tmp_path, now_ns=NOW_NS)
    assert (found.check, found.severity, found.fix) == ("D-24", "ok", "")
    assert found.detail == "no corpus is declared, so no store.write lock can be held"


def test_d24_no_lock_file_is_no_lock(tmp_path: Path) -> None:
    (found,) = store.check_write_locks(_config(tmp_path / "p"), cwd=tmp_path, now_ns=NOW_NS)
    assert found.detail == "corpus 'docs': no store.write lock is held"


def test_d24_a_live_lock_prints_host_pid_create_time_and_age(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    (project / ".omniweave").mkdir()
    lock = store_write_lock(project / ".omniweave" / "docs.owstore", now_ns=lambda: ACQUIRED_NS)
    lock.acquire(wait_ms=0)
    try:
        (found,) = store.check_write_locks(config, cwd=project, now_ns=NOW_NS)
        held = lock.identity()
    finally:
        lock.release()
    assert found.severity == "ok", "15:1537's severity is info, never a warning"
    assert found.detail == (
        f"corpus 'docs': store.write is held by host {held.host}, pid {held.pid}, "
        f"process_create_time {held.process_create_time} ({held.process_create_time_source}), "
        "acquired 42 s ago"
    )


def test_d24_a_lock_whose_writer_is_gone_is_stale_not_held(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    (project / ".omniweave").mkdir()
    gone = LockHolder(
        host="gone",
        pid=999_999,
        process_create_time=1.0,
        process_create_time_source="unavailable",
        acquired_ns=ACQUIRED_NS,
    )
    path = store_write_lock(project / ".omniweave" / "docs.owstore", now_ns=lambda: 0).path
    path.write_text(gone.as_json() + "\n", encoding="utf-8")
    (found,) = store.check_write_locks(config, cwd=project, now_ns=NOW_NS)
    assert found.detail == (
        "corpus 'docs': a stale store.write lock from host gone, pid 999999, process_create_time "
        "1.0 (unavailable), acquired 42 s ago: that process is gone, so the next writer breaks it"
    )
    assert path.exists(), "the doctor looks; breaking the file is acquire()'s job"


def test_d24_an_unreadable_holder_is_named(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    (project / ".omniweave").mkdir()
    path = store_write_lock(project / ".omniweave" / "docs.owstore", now_ns=lambda: 0).path
    path.write_text("not json\n", encoding="utf-8")
    (found,) = store.check_write_locks(config, cwd=project, now_ns=NOW_NS)
    assert found.detail == (
        "corpus 'docs': a stale store.write lock from a holder that could not be read: that "
        "process is gone, so the next writer breaks it"
    )


def test_d24_asks_each_corpus_its_own_lock(tmp_path: Path) -> None:
    text = CORPUS + '[corpora.notes]\npath = ".omniweave/notes.owstore"\n'
    project = tmp_path / "p"
    config = _config(project, text)
    (project / ".omniweave").mkdir()
    lock = store_write_lock(project / ".omniweave" / "notes.owstore", now_ns=lambda: ACQUIRED_NS)
    lock.acquire(wait_ms=0)
    try:
        found = store.check_write_locks(config, cwd=project, now_ns=NOW_NS)
    finally:
        lock.release()
    assert [one.detail.split(": ", 1)[1].split(" by ")[0] for one in found] == [
        "no store.write lock is held",
        "store.write is held",
    ]


# --- D-23 (D969) ----------------------------------------------------------------------------


def _store(project: Path) -> Path:
    from omniweave_core.store import migrate  # noqa: PLC0415
    from omniweave_core.store import sqlite as ow  # noqa: PLC0415

    path = project / ".omniweave" / "docs.owstore"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    return path


def test_d23_a_real_store_with_nothing_staged_is_ok(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    _store(project)
    (found,) = store.check_abandoned(config, cwd=project)
    assert (found.check, found.severity, found.fix) == ("D-23", "ok", "")
    assert found.detail == ("corpus 'docs': no page sits above its document's committed generation")


def test_d23_abandoned_pages_warn_with_the_re_add(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    path = _store(project)
    rows = [("/w/a.pdf", 40, False), ("/w/b.pdf", 1, False), ("/w/c.pdf", 2, False)]
    rows += [("/w/d.pdf", 3, False)]
    (found,) = store.check_abandoned(config, cwd=project, read=lambda _store: rows)
    assert found.severity == "warning"
    assert found.detail == (
        "corpus 'docs': 46 page(s) of an abandoned parse in 4 document(s), invisible to every "
        "reader: /w/a.pdf (40), /w/b.pdf (1), /w/c.pdf (2), and 1 more"
    )
    assert found.fix == "ow add /w/a.pdf   # a re-parse sweeps the abandoned generation"
    assert path.is_file()


def test_d23_a_run_holding_the_store_is_a_parse_in_flight(tmp_path: Path) -> None:
    project = tmp_path / "p"
    config = _config(project)
    path = _store(project)
    lock = store_write_lock(path, now_ns=lambda: ACQUIRED_NS)
    lock.acquire(wait_ms=0)
    try:
        staged = [("/w/a.pdf", 3, False)]
        (found,) = store.check_abandoned(config, cwd=project, read=lambda _s: staged)
    finally:
        lock.release()
    assert found.severity == "ok"
    assert "a run holds store.write, so they may be a parse in flight" in found.detail


def test_d23_no_store_yet_and_no_corpus(tmp_path: Path) -> None:
    (found,) = store.check_abandoned(_config(tmp_path / "p"), cwd=tmp_path / "p")
    assert found.detail == "corpus 'docs': no store yet"
    (none,) = store.check_abandoned(_config(tmp_path / "q", ""), cwd=tmp_path / "q")
    assert none.detail == "no corpus is declared, so no generation is staged"


def test_d23_a_quarantined_generation_is_kept_for_doc_diff_not_warned(tmp_path: Path) -> None:
    """03:1298-1302: a quarantined generation stays *"for inspection by `ow doc diff`"*."""
    project = tmp_path / "p"
    config = _config(project)
    _store(project)
    found = store.check_abandoned(
        config, cwd=project, read=lambda _s: [("/w/q.pdf", 7, True), ("/w/a.pdf", 2, False)]
    )
    assert [(one.severity, one.detail) for one in found] == [
        ("ok", "corpus 'docs': 7 page(s) of 1 quarantined generation(s), kept for `ow doc diff` "
         "(03:1298-1302)"),
        ("warning", "corpus 'docs': 2 page(s) of an abandoned parse in 1 document(s), invisible "
         "to every reader: /w/a.pdf (2)"),
    ]  # fmt: skip
    (only,) = store.check_abandoned(config, cwd=project, read=lambda _s: [("/w/q.pdf", 7, True)])
    assert only.severity == "ok", "quarantined alone is no warning"
