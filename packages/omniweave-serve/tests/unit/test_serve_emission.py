"""`omniweave_serve.emission`: one stdio session's ledger, and the marker that clears it.

The marker tests set file times with `os.utime` rather than sleeping, because the rule is a
comparison of two instants and the test should choose both.
"""

from __future__ import annotations

import os
import string
from pathlib import Path

import pytest
from omniweave_core.answer.dedup import Emission
from omniweave_serve.emission import MARKER_SUFFIX, StdioSession, stdio_key

STARTED_NS = 1_757_400_000_000_000_000
BLOCK = Emission(
    corpus_id="handbook", doc_key=b"file:///a.pdf", gen=0, cite="d1#1", content_digest=b"\x01" * 16
)


def _marker(root: Path, at_ns: int, key: str = "0123456789abcdef") -> Path:
    marker = root / f"{key}{MARKER_SUFFIX}"
    marker.write_text("{}", encoding="utf-8")
    os.utime(marker, ns=(at_ns, at_ns))
    return marker


def _held(session: StdioSession) -> int:
    return session.ledger.stats()["blocks"]


def test_the_key_is_sixteen_hex_of_the_process_and_its_start() -> None:
    """18:474's recipe without the corpus, at `hooks.session.session_key()`'s width."""
    key = stdio_key(pid=7, started_ns=STARTED_NS)
    assert len(key) == 16
    assert set(key) <= set(string.hexdigits.lower())
    assert key == stdio_key(pid=7, started_ns=STARTED_NS)
    assert key != stdio_key(pid=8, started_ns=STARTED_NS)
    assert key != stdio_key(pid=7, started_ns=STARTED_NS + 1)


def test_commit_records_what_it_is_handed() -> None:
    session = StdioSession.open(sessions=None, pid=1, started_ns=STARTED_NS)
    session.commit([BLOCK])
    assert _held(session) == 1


def test_with_no_sessions_directory_nothing_is_ever_cleared() -> None:
    """D403's deployment: no `omniweave.toml`, so no `<sessions>` and no marker to read."""
    session = StdioSession.open(sessions=None, pid=1, started_ns=STARTED_NS)
    session.commit([BLOCK])
    assert session.compacted() is False
    assert _held(session) == 1


def test_a_directory_that_does_not_exist_has_no_markers(tmp_path: Path) -> None:
    """A host that never installed the hooks. 10:994's retention window is then the backstop."""
    session = StdioSession.open(sessions=tmp_path / "absent", pid=1, started_ns=STARTED_NS)
    session.commit([BLOCK])
    assert session.compacted() is False
    assert _held(session) == 1


def test_a_marker_older_than_the_process_is_a_previous_sessions(tmp_path: Path) -> None:
    _marker(tmp_path, STARTED_NS - 1)
    session = StdioSession.open(sessions=tmp_path, pid=1, started_ns=STARTED_NS)
    session.commit([BLOCK])
    assert session.compacted() is False
    assert _held(session) == 1


def test_a_newer_marker_clears_once_and_advances_the_clear(tmp_path: Path) -> None:
    session = StdioSession.open(sessions=tmp_path, pid=1, started_ns=STARTED_NS)
    session.commit([BLOCK])
    _marker(tmp_path, STARTED_NS + 1_000)
    assert session.compacted() is True
    assert _held(session) == 0
    assert session.cleared_at_ns == STARTED_NS + 1_000
    session.commit([BLOCK])
    assert session.compacted() is False, "the same marker is not a second compaction"
    assert _held(session) == 1


def test_any_sessions_marker_clears_because_ours_cannot_be_named(tmp_path: Path) -> None:
    """D534: the host's key never reaches a stdio server, so another key's marker clears too --
    re-sending is the cheap failure and a pointer to compacted content is the expensive one."""
    session = StdioSession.open(sessions=tmp_path, pid=1, started_ns=STARTED_NS)
    session.commit([BLOCK])
    _marker(tmp_path, STARTED_NS + 1_000, key="ffffffffffffffff")
    assert session.compacted() is True
    assert _held(session) == 0


def test_a_sessions_directory_that_cannot_be_listed_clears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The server cannot tell whether a compaction happened, so it takes the safe direction."""

    def refused(_self: Path, pattern: str) -> object:
        raise PermissionError(pattern)

    session = StdioSession.open(sessions=tmp_path, pid=1, started_ns=STARTED_NS)
    session.commit([BLOCK])
    monkeypatch.setattr(Path, "glob", refused)
    assert session.compacted() is True
    assert _held(session) == 0
