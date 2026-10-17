"""`omniweave.aio`: the SDK's async twins, `asyncio.to_thread` wrappers and nothing more. D863.

18-api-sketch.md section 1.5: *"Every `Corpus` method and module-level function has a twin in
`omniweave.aio` with an identical signature and identical errors. They are `asyncio.to_thread`
wrappers, and the documentation says so."* They exist so an async MCP server or web handler does
not block its loop, not because the store is async. **The whole module is `@provisional`**
(10 section 9.4): a `@stable` async surface would promise the threading strategy, which is the one
thing here most likely to change.

## Rulings

1. **Each twin runs its `omniweave.sdk.api` twin on a worker thread, with the same arguments, and
   lets its errors through unchanged.** No twin re-implements a body, so a sync and an async call
   cannot answer differently. `test_sdk_aio.py` holds every signature to its sync twin's.
2. **`AsyncCorpus` is the handle, and an async context manager** (18:803's
   `async with await acorpus(...) as c`). It holds the sync `Corpus` and nothing else, so entering
   and leaving it opens and closes nothing: the sync handle holds no connection (D858 ruling 4).
3. **`AsyncAnswer` is the `Answer`, with `evidence` an async iterator over the same rows** (18:805's
   `async for e in a.evidence`). Every other field is the `Answer`'s, read through.
4. **A single handle is not safe to share across concurrent tasks** (18:810): one call runs one
   snapshot on one thread at a time. Take a handle per task. And cancelling an awaitable does not
   interrupt a statement already running on its thread (18:812).
5. **`AsyncCorpus.doc()` resolves on a worker thread and returns the sync `Doc`** (D865). 18:797's
   rule is a twin for every `Corpus` method and module-level function, and `Doc` is neither: its
   accessors are 03 section 13.5's, iterators over the store. A caller on a loop that walks a large
   document wraps that walk in `asyncio.to_thread` itself.
6. **`AsyncCorpus.session()` is an async context manager over `Corpus.session()`** (D867), and
   the `AsyncSession` it yields runs `Session.query()` and `Session.open()` on a worker thread,
   with the same signatures. `stats()` and `clear()` touch only the in-memory ledger, so they stay
   synchronous. One session is one ledger, so its calls are awaited one at a time (ruling 4).

`omniweave_core` stays asyncio-free (G23): this module is in `omniweave`, and nothing imports it
but a caller who names it.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from omniweave.sdk import api

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
    from pathlib import Path
    from types import TracebackType

    from omniweave_core.answer.render import Answer, RenderedBlock
    from omniweave_core.model.doc import Doc
    from omniweave_core.model.enums import Layer
    from omniweave_core.store.types import Coverage, Expand, Filters

    from omniweave.sdk.reports import AddReport, CodeRow, CorpusCard, DoctorReport
    from omniweave.sdk.session import Session

__all__ = ["AsyncAnswer", "AsyncCorpus", "AsyncSession", "corpora", "corpus", "doctor", "explain"]


async def corpus(
    name: str | None = None,
    *,
    config: str | Path | None = None,
    readonly: bool = True,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AsyncCorpus:
    """`omniweave.corpus()` on a worker thread (ruling 1)."""
    inner = await asyncio.to_thread(
        api.corpus, name, config=config, readonly=readonly, cwd=cwd, env=env
    )
    return AsyncCorpus(inner)


async def corpora(
    names: Sequence[str] | None = None, *, config: str | Path | None = None
) -> tuple[CorpusCard, ...]:
    """`omniweave.corpora()` on a worker thread (ruling 1)."""
    return await asyncio.to_thread(api.corpora, names, config=config)


async def doctor(*, runtime: bool = False) -> DoctorReport:
    """`omniweave.sdk.doctor()` on a worker thread (ruling 1)."""
    return await asyncio.to_thread(api.doctor, runtime=runtime)


async def explain(code: str) -> CodeRow:
    """`omniweave.explain()` on a worker thread (ruling 1)."""
    return await asyncio.to_thread(api.explain, code)


class AsyncCorpus:
    """The async handle over one `Corpus` (ruling 2)."""

    __slots__ = ("_inner",)

    def __init__(self, inner: api.Corpus) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def schema(self) -> int:
        return self._inner.schema

    @property
    def generation(self) -> int:
        return self._inner.generation

    async def __aenter__(self) -> AsyncCorpus:
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        return None

    async def query(
        self,
        text: str = "",
        *,
        refs: Sequence[str] = (),
        scope: str | None = None,
        want: str = "passages",
        filters: Filters | None = None,
        mode: str = "find",
        k: int = 20,
        max_blocks: int = api.MAX_BLOCKS,
        max_chars: int = 24_000,
        expand: Expand | None = None,
        route_hints: object | None = None,
    ) -> AsyncAnswer:
        """`Corpus.query()` on a worker thread (ruling 1)."""
        answer = await asyncio.to_thread(
            self._inner.query,
            text,
            refs=refs,
            scope=scope,
            want=want,
            filters=filters,
            mode=mode,
            k=k,
            max_blocks=max_blocks,
            max_chars=max_chars,
            expand=expand,
            route_hints=route_hints,
        )
        return AsyncAnswer(answer)

    async def open(
        self,
        ref: str | Sequence[str],
        *,
        context: int = 1,
        layers: Iterable[Layer] | None = None,
        raw: bool = False,
        want_impact: bool = False,
        max_chars: int = 24_000,
    ) -> AsyncAnswer:
        """`Corpus.open()` on a worker thread (ruling 1)."""
        answer = await asyncio.to_thread(
            self._inner.open,
            ref,
            context=context,
            layers=layers,
            raw=raw,
            want_impact=want_impact,
            max_chars=max_chars,
        )
        return AsyncAnswer(answer)

    async def add(
        self,
        source: str | Sequence[str],
        *,
        dry_run: bool = False,
        schema: Mapping[str, Any] | None = None,
        allow_cost: int = 0,
        allow_egress: str | None = None,
        wait_ms: int | None = None,
    ) -> AddReport:
        """`Corpus.add()` on a worker thread (ruling 1)."""
        return await asyncio.to_thread(
            self._inner.add,
            source,
            dry_run=dry_run,
            schema=schema,
            allow_cost=allow_cost,
            allow_egress=allow_egress,
            wait_ms=wait_ms,
        )

    async def card(self) -> CorpusCard:
        """`Corpus.card()` on a worker thread (ruling 1)."""
        return await asyncio.to_thread(self._inner.card)

    async def coverage(self) -> Coverage:
        """`Corpus.coverage()` on a worker thread (ruling 1)."""
        return await asyncio.to_thread(self._inner.coverage)

    async def doc(self, ref: str) -> Doc:
        """`Corpus.doc()` on a worker thread; the `Doc` it returns is synchronous (ruling 5)."""
        return await asyncio.to_thread(self._inner.doc, ref)

    @contextlib.asynccontextmanager
    async def session(self, key: str | None = None) -> AsyncIterator[AsyncSession]:
        """`Corpus.session()`, its calls on a worker thread (ruling 6)."""
        with self._inner.session(key) as inner:
            yield AsyncSession(inner)


class AsyncSession:
    """The async view of one `Session` (ruling 6)."""

    __slots__ = ("_inner",)

    def __init__(self, inner: Session) -> None:
        self._inner = inner

    @property
    def key(self) -> str:
        return self._inner.key

    async def query(
        self,
        text: str = "",
        *,
        refs: Sequence[str] = (),
        scope: str | None = None,
        want: str = "passages",
        filters: Filters | None = None,
        mode: str = "find",
        k: int = 20,
        max_blocks: int = api.MAX_BLOCKS,
        max_chars: int = 24_000,
        expand: Expand | None = None,
        route_hints: object | None = None,
    ) -> AsyncAnswer:
        """`Session.query()` on a worker thread (ruling 6)."""
        answer = await asyncio.to_thread(
            self._inner.query,
            text,
            refs=refs,
            scope=scope,
            want=want,
            filters=filters,
            mode=mode,
            k=k,
            max_blocks=max_blocks,
            max_chars=max_chars,
            expand=expand,
            route_hints=route_hints,
        )
        return AsyncAnswer(answer)

    async def open(
        self,
        ref: str | Sequence[str],
        *,
        context: int = 1,
        layers: Iterable[Layer] | None = None,
        raw: bool = False,
        want_impact: bool = False,
        max_chars: int = 24_000,
    ) -> AsyncAnswer:
        """`Session.open()` on a worker thread (ruling 6)."""
        answer = await asyncio.to_thread(
            self._inner.open,
            ref,
            context=context,
            layers=layers,
            raw=raw,
            want_impact=want_impact,
            max_chars=max_chars,
        )
        return AsyncAnswer(answer)

    def stats(self) -> Mapping[str, int]:
        return self._inner.stats()

    def clear(self) -> None:
        self._inner.clear()


class AsyncAnswer:
    """The `Answer`, its `evidence` an async iterator over the same rows (ruling 3)."""

    __slots__ = ("answer",)

    def __init__(self, answer: Answer) -> None:
        self.answer = answer

    def __getattr__(self, name: str) -> Any:
        return getattr(self.answer, name)

    @property
    def evidence(self) -> _Rows:
        return _Rows(self.answer.evidence)


class _Rows:
    """18:805's `async for e in a.evidence`: the rows, iterated asynchronously, and counted."""

    __slots__ = ("_rows",)

    def __init__(self, rows: tuple[RenderedBlock, ...]) -> None:
        self._rows = rows

    def __len__(self) -> int:
        return len(self._rows)

    def __aiter__(self) -> AsyncIterator[RenderedBlock]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[RenderedBlock]:
        for row in self._rows:
            yield row
