"""`Corpus.session()` and `Session`: the emission ledger across one caller's calls. D867.

The store is `test_sdk_api.py`'s, with the second block lengthened past `MIN_COVERED_CHARS`, so a
block sent once is worth withholding the second time (`answer.dedup.worth_withholding`).
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import sqlite3  # the fixture lengthens a REAL store's block (pyproject.toml, D867)
import sys
from pathlib import Path
from typing import Any

import pytest
from omniweave.sdk import api
from omniweave.sdk.session import MARKER_SUFFIX, Session, default_key
from omniweave_core.answer.dedup import LEDGER_RESET_KIND

from omniweave import aio


def _load_sync() -> Any:
    path = Path(__file__).with_name("test_sdk_api.py")
    spec = importlib.util.spec_from_file_location("_test_sdk_api_for_session", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SYNC = _load_sync()
QUESTION = "terminate agreement notice"
FILLER = " The notice must be written and delivered to the other party." * 12


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    store = tmp_path / ".omniweave" / "index.owstore"
    SYNC._seed(store)
    conn = sqlite3.connect(store)
    try:
        conn.execute("UPDATE block SET text = text || ? WHERE block_id = 2", (FILLER,))
        conn.commit()
    finally:
        conn.close()
    return tmp_path


def _corpus(project: Path) -> api.Corpus:
    return SYNC._corpus(project)


def _cites(answer: Any) -> list[str]:
    return [block.cite for block in answer.evidence]


def _parameters(member: Any) -> list[tuple[str, Any, Any]]:
    return [
        (one.name, one.kind, one.default)
        for one in inspect.signature(member).parameters.values()
        if one.name != "self"
    ]


@pytest.mark.parametrize(
    ("member", "original"),
    [
        (Session.query, api.Corpus.query),
        (Session.open, api.Corpus.open),
        (aio.AsyncSession.query, api.Corpus.query),
        (aio.AsyncSession.open, api.Corpus.open),
    ],
    ids=lambda member: getattr(member, "__qualname__", str(member)),
)
def test_a_sessions_calls_take_the_corpus_signatures(member: Any, original: Any) -> None:
    assert _parameters(member) == _parameters(original)


def test_without_a_session_a_repeat_is_sent_again(project: Path) -> None:
    handle = _corpus(project)
    first, second = handle.query(QUESTION), handle.query(QUESTION)
    assert _cites(first) == _cites(second) == ["d1#2"]
    assert second.withheld == ()


def test_inside_a_session_a_repeat_is_withheld_and_counted(project: Path) -> None:
    handle = _corpus(project)
    with handle.session() as session:
        first = session.query(QUESTION)
        assert first == handle.query(QUESTION)
        second = session.query(QUESTION)
        assert _cites(second) == []
        [pointer] = second.withheld
        assert (pointer.cites, pointer.reason) == (("d1#2",), "sent_earlier")
        assert second.budget is not None
        assert second.budget.call_ord == 2
        saved = second.budget.chars_deduped
        assert saved > 0
        assert dict(session.stats()) == {
            "calls": 2,
            "docs": 1,
            "blocks": 1,
            "chars_sent": saved,
            "saved": saved,
        }


def test_a_block_too_short_to_point_at_is_sent_again(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    SYNC._seed(tmp_path / ".omniweave" / "index.owstore")
    with _corpus(tmp_path).session() as session:
        first, second = session.query(QUESTION), session.query(QUESTION)
    assert _cites(first) == _cites(second) == ["d1#2"]


def test_a_block_opened_is_withheld_from_a_later_query(project: Path) -> None:
    with _corpus(project).session() as session:
        opened = session.open("d1#2")
        assert _cites(opened) == ["d1#2"]
        assert _cites(session.query(QUESTION)) == []
        assert session.stats()["calls"] == 2


def test_clear_sends_everything_again(project: Path) -> None:
    with _corpus(project).session() as session:
        session.query(QUESTION)
        session.clear()
        assert _cites(session.query(QUESTION)) == ["d1#2"]
        assert session.stats()["blocks"] == 1


def test_the_ledger_dies_with_the_block_and_two_sessions_share_nothing(project: Path) -> None:
    handle = _corpus(project)
    with handle.session() as one:
        one.query(QUESTION)
        with handle.session() as two:
            assert _cites(two.query(QUESTION)) == ["d1#2"]
    assert one.stats()["blocks"] == 0
    assert _cites(one.query(QUESTION)) == ["d1#2"]


def test_the_key_is_given_or_a_digest_of_pid_corpus_and_opening(project: Path) -> None:
    handle = _corpus(project)
    with handle.session("mine") as session:
        assert session.key == "mine"
    with handle.session() as session:
        assert len(session.key) == 16
        assert set(session.key) <= set("0123456789abcdef")
    assert default_key(pid=1, corpus="a", opened_ns=2) != default_key(
        pid=1, corpus="b", opened_ns=2
    )
    assert default_key(pid=1, corpus="a", opened_ns=2) == default_key(
        pid=1, corpus="a", opened_ns=2
    )


def test_a_compaction_marker_clears_the_ledger_once_and_says_so(project: Path) -> None:
    sessions = project / ".omniweave" / "sessions"
    sessions.mkdir()
    stale = sessions / f"old{MARKER_SUFFIX}"
    stale.write_text("", encoding="utf-8")
    os.utime(stale, ns=(1, 1))
    with _corpus(project).session() as session:
        session.query(QUESTION)
        assert _cites(session.query(QUESTION)) == []
        marker = sessions / f"host{MARKER_SUFFIX}"
        marker.write_text("", encoding="utf-8")
        future = 4_000_000_000 * 10**9
        os.utime(marker, ns=(future, future))
        reset = session.query(QUESTION)
        assert _cites(reset) == ["d1#2"]
        assert LEDGER_RESET_KIND in reset.degradations
        again = session.query(QUESTION)
        assert _cites(again) == []
        assert LEDGER_RESET_KIND not in again.degradations


def test_the_async_session_withholds_as_the_sync_one_does(project: Path) -> None:
    async def run() -> tuple[list[str], list[str], dict[str, int]]:
        corpus = await aio.corpus("handbook", cwd=project, env=SYNC._env(project))
        async with corpus.session() as session:
            first = await session.query(QUESTION)
            second = await session.query(QUESTION)
            return _cites(first.answer), _cites(second.answer), dict(session.stats())

    first, second, stats = asyncio.run(run())
    assert (first, second) == (["d1#2"], [])
    assert stats["calls"] == 2
