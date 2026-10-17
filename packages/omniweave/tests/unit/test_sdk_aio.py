"""`omniweave.aio`: the SDK's async twins, held to their sync twins. D863.

18-api-sketch.md section 1.5: an identical signature and identical errors, `asyncio.to_thread`
wrappers. Each twin is run here with `asyncio.run`, as the transports' tests drive theirs, over the
store `test_sdk_api.py` seeds, which is loaded by file path rather than duplicated.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

import pytest
from omniweave.sdk import api
from omniweave_core.errors import UsageError

from omniweave import aio


def _load_sync_tests() -> Any:
    path = Path(__file__).with_name("test_sdk_api.py")
    spec = importlib.util.spec_from_file_location("_test_sdk_api_for_aio", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SYNC = _load_sync_tests()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    SYNC._seed(tmp_path / ".omniweave" / "index.owstore")
    return tmp_path


def _parameters(member: Any) -> list[tuple[str, Any, Any]]:
    return [
        (one.name, one.kind, one.default)
        for one in inspect.signature(member).parameters.values()
        if one.name != "self"
    ]


@pytest.mark.parametrize(
    ("twin", "original"),
    [
        (aio.corpus, api.corpus),
        (aio.corpora, api.corpora),
        (aio.doctor, api.doctor),
        (aio.explain, api.explain),
        (aio.AsyncCorpus.query, api.Corpus.query),
        (aio.AsyncCorpus.open, api.Corpus.open),
        (aio.AsyncCorpus.add, api.Corpus.add),
        (aio.AsyncCorpus.card, api.Corpus.card),
        (aio.AsyncCorpus.coverage, api.Corpus.coverage),
        (aio.AsyncCorpus.doc, api.Corpus.doc),
    ],
    ids=lambda member: getattr(member, "__qualname__", str(member)),
)
def test_every_twin_has_its_sync_twins_signature(twin: Any, original: Any) -> None:
    assert inspect.iscoroutinefunction(twin)
    assert _parameters(twin) == _parameters(original)


def test_asyncio_is_named_for_to_thread_and_nothing_else() -> None:
    """The scope of `aio.py`'s TID251 exemption in pyproject.toml, held over the AST."""
    source = Path(aio.__file__).read_text(encoding="utf-8")
    used = {
        node.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "asyncio"
    }
    assert used == {"to_thread"}


def test_a_query_is_the_sync_answer_and_its_evidence_iterates_asynchronously(
    project: Path,
) -> None:
    sync = SYNC._corpus(project).query("terminate agreement notice")

    async def ask() -> tuple[Any, list[Any], int]:
        async with await aio.corpus("handbook", cwd=project, env=SYNC._env(project)) as c:
            answer = await c.query("terminate agreement notice")
            rows = [row async for row in answer.evidence]
            return answer, rows, len(answer.evidence)

    answer, rows, count = asyncio.run(ask())
    assert answer.answer == sync
    assert answer.state == sync.state, "every other field reads through"
    assert rows == list(sync.evidence)
    assert count == len(sync.evidence)


def test_open_card_and_coverage_are_their_sync_twins(project: Path) -> None:
    handle = SYNC._corpus(project)

    async def read() -> tuple[Any, Any, Any, str]:
        c = await aio.corpus("handbook", cwd=project, env=SYNC._env(project))
        return (await c.open("d1#2")).answer, await c.card(), await c.coverage(), c.name

    opened, card, coverage, name = asyncio.run(read())
    assert opened == handle.open("d1#2")
    assert card == handle.card()
    assert coverage == handle.coverage()
    assert name == "handbook"


def test_doc_resolves_on_a_thread_and_returns_the_sync_doc(project: Path) -> None:
    from omniweave_core.model.doc import Doc  # noqa: PLC0415

    async def resolve() -> Any:
        c = await aio.corpus("handbook", cwd=project, env=SYNC._env(project))
        return await c.doc("contract.pdf")

    doc = asyncio.run(resolve())
    assert isinstance(doc, Doc)
    assert (doc.doc_ord, doc.gen) == (1, 1)
    assert list(doc.blocks()) == list(SYNC._corpus(project).doc("d1").blocks())


def test_an_error_is_the_sync_twins(project: Path) -> None:
    async def ask() -> None:
        c = await aio.corpus("handbook", cwd=project, env=SYNC._env(project))
        await c.query("fees", want="essay")

    with pytest.raises(UsageError, match="passages, table, fields, outline, related"):
        asyncio.run(ask())


def test_the_module_level_twins(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from omniweave.sdk import _ambient  # noqa: PLC0415

    monkeypatch.setattr(_ambient, "process_cwd", lambda: project)
    for key, value in SYNC._env(project).items():
        monkeypatch.setenv(key, value)

    async def gather() -> tuple[Any, Any, Any]:
        return await aio.explain("OW-R-030"), await aio.corpora(), await aio.doctor()

    row, cards, report = asyncio.run(gather())
    assert row == api.explain("OW-R-030")
    assert cards == api.corpora()
    assert report == api.doctor()


def test_add_is_its_sync_twin(tmp_path: Path) -> None:
    fresh = tmp_path
    (fresh / ".git").mkdir()
    (fresh / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
        "[runtime]\ndeferred_sweep_ms = 20\n",
        encoding="utf-8",
    )
    (fresh / "docs").mkdir()
    (fresh / "docs" / "a.txt").write_text("Fees are payable monthly.", encoding="utf-8")

    async def add() -> Any:
        c = await aio.corpus("handbook", readonly=False, cwd=fresh, env=SYNC._env(fresh))
        return await c.add("docs", dry_run=True)

    report = asyncio.run(add())
    assert (report.corpus, report.discovered, report.queued) == ("handbook", 1, 0)
