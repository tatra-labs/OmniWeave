"""The SDK entry points: `corpus()` with `query()`/`open()`, `corpora()`, `doctor()`, `explain()`.

18-api-sketch.md section 1 prints the Python API, and until this module none of its entry points
existed: `gen.sdk_stub.owed()` named five, and D323 recorded that no work item landed them. D858
landed three -- `corpus`, `Corpus` and `explain` -- with `Corpus.query` and `Corpus.open` as the two
methods a reader needs, and D860 the other two, `corpora` and `doctor`. None is owed now.

**One implementation under every surface** (SV19, 10:101-102). Each method composes the core calls
`ow query` and `ow open` compose, in the same order: the config loaded once, the corpus resolved,
the store opened read-only, `retrieve.execute()` or `store.resolve.fetch()` in one snapshot, then
`answer.pack()` or `pack_open()`. The CLI composes the MCP handler's calls the same way. So the
three surfaces return one `Answer` for one question, and none of them imports another's argv.

## Rulings

1. **The signatures are 18 section 1's, parameter for parameter.** `gen.sdk_stub.SDK_HOMES`
   transcribed them, and `test_sdk_api.py` holds each method's `inspect.signature` to its row, so
   the published shape is the printed one and `_mismatches()` keeps reporting the registry's
   differences (D324), not the SDK's.
2. **What the read path cannot yet honour is refused by name, never ignored.** `refs`, `scope`,
   `expand`, `route_hints`, a `want` other than `passages` and a `max_blocks` other than its default
   on `query`, and `raw` and `want_impact` on `open`, are each a `UsageError` naming the
   parameter, and so are `add()`'s four that `ow add` refuses (ruling 8). That is `ow query`'s
   and `ow_query`'s rule (10:946): a parameter accepted and dropped answers a different question
   than the one asked. An unknown
   `want` names the five members (18:279), and an unknown `mode` the four, which `ow query`'s
   parser refuses and `Query` itself does not.
3. **The working directory is an argument, and only the entry point may default it.** 18:154
   prints `corpus(name=None, *, config=None, readonly=True)`, and a `None` config walks up from the
   process's directory. Library code may not read that directory (G8's
   `omniweave-no-getcwd-in-library-code`, OUT14), so `corpus()` takes a keyword-only `cwd`. Left
   out, it is read once, in `sdk/_ambient.py`, the one file G8 exempts besides `__main__.py`. A
   test, or an embedder serving many projects, passes it. `env` is the same, defaulting to the
   process environment.
4. **A `Corpus` is a lazy handle that re-reads nothing at construction but its identity.** It opens
   the store once to read `generation` and `schema` (18:265), then closes it. Each `query` and
   `open` opens one read-only snapshot and closes it before returning (18:257, ST2). The handle
   holds no connection, so it is safe to keep.
5. **`corpora()` is the list's order, every card, uncapped** (D860). 18:180 prints
   `tuple[CorpusCard, ...]`, each corpus's whole card: `store.card.corpora_cards()`, the entries
   `ow corpora --detail card` prints, default first, then `card_gen` descending, then name. A
   tuple has no field to say it was cut at `CORPORA_LIST_MAX`, and that cap guards a wire budget
   the SDK does not spend, so nothing is cut. A store that will not open is a card with
   `readable=False` and its `reason`, never a raise (10:1032). A corpus with no card has the empty
   values and `achieved=None`, the same `None` `capability_floor()` returns for no documents: the
   bottom of every ladder would claim the corpus is incapable rather than unread.
   `corpora(names=[...])` is 18:186's fan-out handle, `CorpusSet`, which rank-merges N queries; no
   rank-merge is built (`ow query`'s comma list refuses it too), so it is refused by name. A user
   ruling of 2026-10-19 defers it past v1.0 (D904): it is not in V10's acceptance list.
6. **`doctor()` is `ow doctor`'s `run()`**, the checks and the report the verb prints (D860). Like
   `corpora()`, its printed signature has no directory, so both read the process's directory
   through `sdk._ambient`, the one read G8 exempts, and the process environment.
7. **`Corpus.card()` and `Corpus.coverage()` are the handle's two reads of itself** (D861).
   `card()` is 18:460's *"`corpus_card` row at `card_gen`, read once and memoised for the
   handle's life"*: the entry `corpora()` returns for this corpus, read on the first call and kept,
   with `card_stale` set rather than recomputed. `coverage()` is `Reader.coverage()` over the whole
   corpus in one snapshot, 18:464's gap list for absence gates 4-9, read fresh on every call because
   it is what changes while a handle is held. `scope_rows == 0` is coverage UNKNOWN, as 18 warns.
8. **`Corpus.add()` is `ow add`, in the caller's process** (D862). 18:399 prints a detached
   `ow ingest --scope` child polled under `wait_ms`, and no module in this build spawns a detached
   child (D554, D433), so the one write path is `ow add`'s: roster, drain in-process, read the
   roster back, through `surface.add.add_report()`, which `ow add` now calls too. The run's
   `run.trigger` is `sdk`, never `cli` (18:440). A handle opened `readonly=True`, the default,
   refuses with `OW_READONLY_HANDLE` (`OW-A-019`), naming `readonly=False`. A writable handle may
   name a corpus whose store does not exist yet, because `add()` is what creates it; it then has
   generation 0. `schema`, a nonzero `allow_cost`, `allow_egress` and `wait_ms` are refused by name,
   for the reasons `ow add` refuses them: nothing reads `unit.schema_requested`, nothing is priced,
   no connector fetches, and the drain is synchronous, so there is no deadline to wait to.
9. **`Corpus.doc(ref)` is 18:500's lazy handle, a `model.doc.Doc` over the store** (D865), read
   through `store.docread.StoreDocReader` (D864). `ref` is `d<doc_ord>`, or anything `ow open`
   resolves to one document: a cite, a URI, a file name. Resolving it reads the head generation,
   and the `Doc` is pinned to that generation. The handle still holds no connection (ruling 4):
   each of the `Doc`'s reads opens one read-only connection and closes it, and `blocks()` holds
   its connection until the cursor is exhausted or closed. So a `Doc` kept across a re-parse
   reads the retired generation's rows as misses, and its record as `NotFoundError`, rather than
   another generation's rows under its old identity. What `StoreDocReader` refuses, `frames()`
   among them, the `Doc` refuses too.
10. **`Corpus.session(key=None)` opens 18:470's emission ledger** (D867), `sdk.session.Session`,
    as a context manager whose exit clears it. `Session.query()` and `Session.open()` run
    `_query()` and `_open()`, the bodies of `query()` and `open()`, with the ledger passed to
    `pack()`. So outside a session dedup is off, and inside one the only difference is what it
    withholds.

Specified in 18-api-sketch.md section 1.1-1.2 and 10-interfaces.md section 9.1.
"""

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.errors import UsageError

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Iterator, Mapping, Sequence

    from omniweave_core.answer.pack import Packed
    from omniweave_core.answer.render import Answer
    from omniweave_core.config import Config
    from omniweave_core.model.block import Addr, Block, BlockId, Cite
    from omniweave_core.model.doc import Doc
    from omniweave_core.model.enums import Kind, Layer, RelKind, Trust
    from omniweave_core.model.grid import Grid
    from omniweave_core.model.records import AssetRef, DocRecord, Rel
    from omniweave_core.store.reader import SqliteReader
    from omniweave_core.store.types import Coverage, Expand, Filters

    from omniweave.sdk.reports import AddReport, CodeRow, CorpusCard, DoctorReport
    from omniweave.sdk.session import Session

__all__ = ["MODES", "WANTS", "Corpus", "corpora", "corpus", "doctor", "explain"]

WANTS: Final[tuple[str, ...]] = ("passages", "table", "fields", "outline", "related")
"""18:267's five packing presets, in printed order."""

MODES: Final[tuple[str, ...]] = ("find", "cite", "explore", "prove_absent")
"""18:270's four modes. `Query` does not refuse another string, and `ow query`'s parser does, so
the SDK refuses one by name here rather than run a mode nothing implements (ruling 2)."""

MAX_BLOCKS: Final = 60
"""18:271's default; another value has no `pack()` parameter to reach yet (ruling 2)."""

_FIX: Final = "omniweave.corpus(name).query(text, k=..., mode=..., max_chars=..., filters=...)"


def corpus(
    name: str | None = None,
    *,
    config: str | Path | None = None,
    readonly: bool = True,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Corpus:
    """18:154: open one corpus for reading (rulings 3 and 4). `None` is `[serve] default_corpus`."""
    from omniweave_core.config import load  # noqa: PLC0415 -- an import of omniweave never pays

    from omniweave.surface.query import corpus_of, store_of  # noqa: PLC0415

    if cwd is None:
        from omniweave.sdk._ambient import process_cwd  # noqa: PLC0415

        cwd = process_cwd()
    resolved = load(
        cwd=cwd,
        env=os.environ if env is None else env,
        explicit=None if config is None else Path(config),
    )
    chosen = corpus_of(resolved, name, verb="omniweave.corpus")
    env_used = os.environ if env is None else env
    if readonly:
        store = store_of(resolved, chosen, cwd=cwd)
        generation, schema = _identity(store)
    else:
        from omniweave_core.contract import SCHEMA  # noqa: PLC0415

        from omniweave.surface.serve import stores  # noqa: PLC0415

        store = Path(stores(resolved, [chosen], cwd=cwd)[chosen])
        generation, schema = _identity(store) if store.is_file() else (0, SCHEMA)
    return Corpus(
        name=chosen,
        schema=schema,
        generation=generation,
        _store=store,
        _config=resolved,
        _cwd=cwd,
        _env=env_used,
        _writable=not readonly,
    )


def corpora(
    names: Sequence[str] | None = None, *, config: str | Path | None = None
) -> tuple[CorpusCard, ...]:
    """18:180: every declared corpus's card, in the list's order (ruling 5)."""
    if names is not None:
        raise UsageError(
            "corpora(names=[...]) is the cross-corpus fan-out handle, CorpusSet, deferred past "
            "v1.0: the rank-merge it needs is not built; open each corpus on its own",
            fix="omniweave.corpora() lists them; omniweave.corpus(name).query(...) asks one",
        )
    from omniweave_core.config import load  # noqa: PLC0415
    from omniweave_core.store import card as store_card  # noqa: PLC0415

    from omniweave.sdk._ambient import process_cwd  # noqa: PLC0415
    from omniweave.surface.serve import stores  # noqa: PLC0415
    from omniweave.surface.startup import corpora as declared  # noqa: PLC0415
    from omniweave.surface.startup import declared_corpus  # noqa: PLC0415

    cwd = process_cwd()
    resolved = load(cwd=cwd, env=os.environ, explicit=None if config is None else Path(config))
    paths = {
        name: Path(path) for name, path in stores(resolved, declared(resolved), cwd=cwd).items()
    }
    default, _ = declared_corpus(resolved)
    document = store_card.corpora_cards(paths, default=default)
    rows = cast("list[Mapping[str, Any]]", document["corpora"])
    return tuple(_card(row) for row in rows)


def doctor(*, runtime: bool = False) -> DoctorReport:
    """18:211: the environment report `ow doctor` prints; never raises on a warning (ruling 6)."""
    from omniweave.doctor import run  # noqa: PLC0415
    from omniweave.sdk._ambient import process_cwd  # noqa: PLC0415

    return run(cwd=process_cwd(), env=os.environ, runtime=runtime)


def _card(row: Mapping[str, Any]) -> CorpusCard:
    """One `card` entry as 18:688's `CorpusCard`, a corpus with no card filled empty (ruling 5)."""
    from omniweave_core.model.records import Producer  # noqa: PLC0415
    from omniweave_core.store.card import Gap  # noqa: PLC0415
    from omniweave_core.store.doc import capabilities_from  # noqa: PLC0415

    from omniweave.sdk.reports import CorpusCard  # noqa: PLC0415

    achieved = row.get("achieved")
    producer = row.get("abstract_producer")
    return CorpusCard(
        name=row["name"],
        default=row["default"],
        readable=row["readable"],
        reason=row["reason"],
        card_stale=row["card_stale"],
        card_gen=row["card_gen"],
        built_at_ns=row.get("built_at_ns", 0),
        writer_version=row.get("writer_version", ""),
        counts=row.get("counts", {}),
        formats=row.get("formats", {}),
        langs=row.get("langs", {}),
        date_range=row.get("date_range", {}),
        outline=tuple(row.get("outline", ())),
        top_terms=tuple(row.get("top_terms", ())),
        achieved=None if achieved is None else capabilities_from(achieved),
        trust_hist=row.get("trust_hist", {}),
        quote_hist=row.get("quote_hist", {}),
        verbatim_fraction=row.get("verbatim_fraction", 0.0),
        restriction_bits=row.get("restriction_bits", 0),
        embedding=row.get("embedding"),
        gaps=tuple(Gap(**gap) for gap in row.get("gaps", ())),
        abstract=row.get("abstract"),
        abstract_producer=None
        if producer is None
        else Producer(**{**producer, "options_digest": bytes.fromhex(producer["options_digest"])}),
    )


def explain(code: str) -> CodeRow:
    """18:229: either spelling of a code, `OW-A-013` or `OW_PARSE_GAP_IN_SCOPE`, as its row."""
    from omniweave_core.errors import explain as lookup  # noqa: PLC0415

    from omniweave.sdk.reports import CodeRow  # noqa: PLC0415

    row = lookup(code)
    return CodeRow(
        numeric=row.numeric,
        symbol=row.symbol,
        meaning=row.meaning,
        fix=row.fix,
        owner_doc=row.owner_doc,
    )


@dataclass(frozen=True, slots=True)
class Corpus:
    """18:261's handle: one corpus, read through one snapshot per call (ruling 4)."""

    name: str
    schema: int
    generation: int
    _store: Path
    _config: Config
    _cwd: Path
    _env: Mapping[str, str] = field(repr=False)
    _writable: bool = False
    _memo: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def query(
        self,
        text: str = "",
        *,
        refs: Sequence[str] = (),
        scope: str | None = None,
        want: str = "passages",
        filters: Filters | None = None,
        mode: str = "find",
        k: int = 20,
        max_blocks: int = MAX_BLOCKS,
        max_chars: int = 24_000,
        expand: Expand | None = None,
        route_hints: object | None = None,
    ) -> Answer:
        """18:267: retrieve, fuse, gate and pack in one call, as `ow query` does (ruling 2)."""
        return self._query(
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
        ).answer

    def _query(
        self,
        text: str,
        *,
        refs: Sequence[str],
        scope: str | None,
        want: str,
        filters: Filters | None,
        mode: str,
        k: int,
        max_blocks: int,
        max_chars: int,
        expand: Expand | None,
        route_hints: object | None,
        **packing: Any,
    ) -> Packed:
        """`query()`'s body, `packing` passed on to `pack()`: a session's ledger (ruling 10)."""
        if want not in WANTS:
            raise UsageError(
                f"want={want!r} is not a packing preset; it is one of {', '.join(WANTS)}",
                fix=_FIX,
            )
        if mode not in MODES:
            raise UsageError(f"mode={mode!r} is not one of {', '.join(MODES)}", fix=_FIX)
        _refuse(
            refs=bool(refs),
            scope=scope is not None,
            want=want != WANTS[0],
            max_blocks=max_blocks != MAX_BLOCKS,
            expand=expand is not None,
            route_hints=route_hints is not None,
        )
        from omniweave_core.answer.pack import pack  # noqa: PLC0415
        from omniweave_core.retrieve.execute import execute  # noqa: PLC0415
        from omniweave_core.retrieve.types import Query  # noqa: PLC0415

        fields: dict[str, Any] = {"text": text, "k": k, "mode": mode}
        if filters is not None:
            fields["filters"] = filters
        retrieval = self._read(lambda reader: execute(reader, Query(**fields), self._policy()))
        return _packed(
            pack,
            retrieval,
            corpus=self.name,
            qualify=self._qualify(),
            max_chars=max_chars,
            **packing,
        )

    def open(
        self,
        ref: str | Sequence[str],
        *,
        context: int = 1,
        layers: Iterable[Layer] | None = None,
        raw: bool = False,
        want_impact: bool = False,
        max_chars: int = 24_000,
    ) -> Answer:
        """18:343: resolve addresses the caller already holds, as `ow open` does (ruling 2)."""
        return self._open(
            ref,
            context=context,
            layers=layers,
            raw=raw,
            want_impact=want_impact,
            max_chars=max_chars,
        ).answer

    def _open(
        self,
        ref: str | Sequence[str],
        *,
        context: int,
        layers: Iterable[Layer] | None,
        raw: bool,
        want_impact: bool,
        max_chars: int,
        **packing: Any,
    ) -> Packed:
        """`open()`'s body, `packing` passed on to `pack_open()` (ruling 10)."""
        _refuse(raw=raw, want_impact=want_impact)
        from omniweave_core.answer.pack import pack_open  # noqa: PLC0415
        from omniweave_core.model.enums import Layer  # noqa: PLC0415
        from omniweave_core.store import resolve  # noqa: PLC0415

        refs = (ref,) if isinstance(ref, str) else tuple(ref)
        wanted = frozenset((Layer.BODY,) if layers is None else layers)
        opening = self._read(
            lambda reader: resolve.fetch(reader, refs, context=context, layers=wanted)
        )
        return _packed(
            pack_open,
            opening,
            corpus=self.name,
            qualify=self._qualify(),
            max_chars=max_chars,
            **packing,
        )

    def add(
        self,
        source: str | Sequence[str],
        *,
        dry_run: bool = False,
        schema: Mapping[str, Any] | None = None,
        allow_cost: int = 0,
        allow_egress: str | None = None,
        wait_ms: int | None = None,
    ) -> AddReport:
        """18:399: index files and directories into this corpus, as `ow add` does (ruling 8)."""
        if not self._writable:
            raise UsageError(
                "Corpus.add writes, and this handle was opened readonly=True",
                symbol="OW_READONLY_HANDLE",
                fix=f"omniweave.corpus({self.name!r}, readonly=False).add(...)",
            )
        _refuse(
            schema=schema is not None,
            allow_cost=allow_cost != 0,
            allow_egress=allow_egress is not None,
            wait_ms=wait_ms is not None,
        )
        import shlex  # noqa: PLC0415

        from omniweave.surface.add import add_report  # noqa: PLC0415

        sources = (source,) if isinstance(source, str) else tuple(source)
        report, _ = add_report(
            self._config,
            self.name,
            sources,
            cwd=self._cwd,
            env=self._env,
            dry_run=dry_run,
            offline=False,
            argv=("omniweave.corpus.add", *sources),
            sweep_ms=None,
            trigger="sdk",
            rerun=shlex.join(["ow", "add", *sources, "--corpus", self.name]),
            verb="Corpus.add",
        )
        return _added(report)

    def card(self) -> CorpusCard:
        """18:460: this corpus's card, read on the first call and kept (ruling 7)."""
        if "card" not in self._memo:
            from omniweave_core.store import card as store_card  # noqa: PLC0415

            from omniweave.surface.startup import declared_corpus  # noqa: PLC0415

            default, _ = declared_corpus(self._config)
            document = store_card.corpora_card(self.name, self._store, default=default)
            [row] = cast("list[Mapping[str, Any]]", document["corpora"])
            self._memo["card"] = _card(row)
        return cast("CorpusCard", self._memo["card"])

    def coverage(self) -> Coverage:
        """18:464: the gap list absence gates 4-9 read, over the whole corpus (ruling 7)."""
        from omniweave_core.store.types import Filters  # noqa: PLC0415

        def read(reader: Any) -> Coverage:
            with reader.snapshot() as state:
                return reader.coverage(state, Filters())

        return cast("Coverage", self._read(read))

    def doc(self, ref: str) -> Doc:
        """18:500: a document's lazy handle, by `d<doc_ord>`, cite, URI or file (ruling 9)."""
        from omniweave_core.model.doc import Doc  # noqa: PLC0415

        doc_ord, gen = self._connected(
            lambda connection, reader: _document(connection, reader, ref)
        )
        return Doc(_DocRead(self._store), doc_ord, gen)

    @contextlib.contextmanager
    def session(self, key: str | None = None) -> Generator[Session]:
        """18:470: the emission ledger across calls, cleared when the block exits (ruling 10)."""
        from omniweave_core.clock import SystemClock  # noqa: PLC0415

        from omniweave.hooks.session import sessions_dir  # noqa: PLC0415
        from omniweave.sdk.session import Session  # noqa: PLC0415

        opened = Session(
            self, key, sessions=sessions_dir(self._cwd), opened_ns=SystemClock().wall_ns()
        )
        try:
            yield opened
        finally:
            opened.clear()

    def _read(self, call: Any) -> Any:
        """One read-only connection and reader for one call, closed before returning."""
        return self._connected(lambda _connection, reader: call(reader))

    def _connected(self, call: Any) -> Any:
        """`_read()`, handing the call the connection as well as the reader."""
        from omniweave_core.clock import SystemClock  # noqa: PLC0415
        from omniweave_core.store import reader as store_reader  # noqa: PLC0415
        from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

        connection = store_sqlite.connect_readonly(self._store)
        try:
            reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
            return call(connection, reader)
        finally:
            connection.close()

    def _policy(self) -> Any:
        """`ow query`'s policy: the project's `[retrieval.budget]` and `[licence]` mask."""
        from omniweave_core.retrieve.plan import budget_of, deny_of  # noqa: PLC0415
        from omniweave_core.retrieve.types import RetrievalPolicy  # noqa: PLC0415

        return RetrievalPolicy(
            budget=budget_of(self._config), deny_restriction_bits=deny_of(self._config)
        )

    def _qualify(self) -> bool:
        """`ow_query`'s rule: with more than one corpus declared, every cite names its corpus."""
        from omniweave.surface.startup import corpora  # noqa: PLC0415

        return len(corpora(self._config)) > 1


_DOC_ORD: Final = re.compile(r"d([0-9]+)")
"""18:500's `d7`: a document by its `doc_ord`, which no form of `ow open`'s ladder spells."""


def _document(connection: Any, reader: SqliteReader, ref: str) -> tuple[int, int]:
    """`ref` as `(doc_ord, head gen)`: `d<doc_ord>`, else `ow open`'s ladder (ruling 9)."""
    from omniweave_core.errors import NotFoundError  # noqa: PLC0415
    from omniweave_core.model.enums import Layer  # noqa: PLC0415
    from omniweave_core.store import resolve  # noqa: PLC0415

    named = _DOC_ORD.fullmatch(ref)
    if named is not None:
        doc_ord = int(named[1])
    else:
        with reader.snapshot() as state:
            (found,) = reader.resolve_refs(state, [ref], context=0, layers=frozenset(Layer))
        if isinstance(found, resolve.Missed):
            raise found.error
        (doc_ord,) = found.doc_ords
    row = connection.execute("SELECT gen FROM doc WHERE doc_ord = ?", (doc_ord,)).fetchone()
    if row is None:
        raise NotFoundError(
            f"no document d{doc_ord} in this corpus", fix="ow corpora --detail card"
        )
    return doc_ord, int(row[0])


class _DocRead:
    """`DocReadSide` over a store path: one read-only connection per read (ruling 9)."""

    __slots__ = ("_store",)

    def __init__(self, store: Path) -> None:
        self._store = store

    def doc_record(self, doc_ord: int, gen: int) -> DocRecord:
        return self._call("doc_record", doc_ord, gen)

    def block(self, doc_ord: int, gen: int, block: BlockId) -> Block | None:
        return self._call("block", doc_ord, gen, block)

    def block_at_addr(self, doc_ord: int, gen: int, addr: Addr) -> Block | None:
        return self._call("block_at_addr", doc_ord, gen, addr)

    def block_at_cite(self, doc_ord: int, gen: int, cite: Cite) -> Block | None:
        return self._call("block_at_cite", doc_ord, gen, cite)

    def blocks(
        self,
        doc_ord: int,
        gen: int,
        *,
        pages: range | None,
        kinds: frozenset[Kind] | None,
        layers: frozenset[Layer],
        under: BlockId | None,
        trust_below: Trust | None,
    ) -> Iterator[Block]:
        """The cursor, holding its one connection until it is exhausted or closed."""
        from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
        from omniweave_core.store.docread import StoreDocReader  # noqa: PLC0415

        connection = store_sqlite.connect_readonly(self._store)
        try:
            cursor = StoreDocReader(connection).blocks(
                doc_ord,
                gen,
                pages=pages,
                kinds=kinds,
                layers=layers,
                under=under,
                trust_below=trust_below,
            )
            try:
                yield from cursor
            finally:
                close = getattr(cursor, "close", None)
                if close is not None:
                    close()
        finally:
            connection.close()

    def payload(self, doc_ord: int, gen: int, block: BlockId) -> Mapping[str, Any]:
        return self._call("payload", doc_ord, gen, block)

    def frames(self, doc_ord: int, gen: int) -> Iterator[Any]:
        return self._call("frames", doc_ord, gen)

    def rels(
        self, doc_ord: int, gen: int, block: BlockId, kind: RelKind | None, *, inbound: bool
    ) -> Iterator[Rel]:
        return iter(list(self._call("rels", doc_ord, gen, block, kind, inbound=inbound)))

    def grid(self, doc_ord: int, gen: int, table: BlockId) -> Grid:
        return self._call("grid", doc_ord, gen, table)

    def page_render(self, doc_ord: int, page: int, dpi: int) -> AssetRef:
        return self._call("page_render", doc_ord, page, dpi)

    def asset(self, ref: AssetRef) -> Any:
        return self._call("asset", ref)

    def verify_quote(self, doc_ord: int, gen: int, block: BlockId) -> Any:
        return self._call("verify_quote", doc_ord, gen, block)

    def resolve_scope(
        self, doc_ord: int, gen: int, *, pages: range | None, under: BlockId | None
    ) -> Any:
        return self._call("resolve_scope", doc_ord, gen, pages=pages, under=under)

    def _call(self, read: str, *args: Any, **kw: Any) -> Any:
        """One `StoreDocReader` read on its own read-only connection, closed before returning."""
        from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
        from omniweave_core.store.docread import StoreDocReader  # noqa: PLC0415

        connection = store_sqlite.connect_readonly(self._store)
        try:
            return getattr(StoreDocReader(connection), read)(*args, **kw)
        finally:
            connection.close()


def _added(report: Mapping[str, Any]) -> AddReport:
    """`add-out-v1`'s object as 18:706's `AddReport` (ruling 8)."""
    from omniweave.sdk.reports import AddCompleted, AddPending, AddReport  # noqa: PLC0415

    return AddReport(
        scope_id=report["scope_id"],
        corpus=report["corpus"],
        discovered=report["discovered"],
        unchanged=report["unchanged"],
        queued=report["queued"],
        skipped=report["skipped"],
        completed=tuple(AddCompleted(**row) for row in report["completed"]),
        pending=tuple(AddPending(**row) for row in report["pending"]),
        degradations=tuple(report["degradations"]),
        deadline_reached=report["deadline_reached"],
        schema=report["schema"],
    )


def _identity(store: Path) -> tuple[int, int]:
    """Ruling 4: the store's `generation` and schema major, read once and closed."""
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=0)
        with reader.snapshot() as state:
            generation = int(state.generation)
        row = connection.execute("SELECT v FROM index_state WHERE k = 'schema'").fetchone()
    finally:
        connection.close()
    schema = int(str(row[0]).split(".", 1)[0]) if row is not None else 0
    return generation, schema


def _packed(
    pack: Any, result: Any, *, corpus: str, qualify: bool, max_chars: int, **packing: Any
) -> Packed:
    """`pack()` or `pack_open()`, its budget refusal a usage error, as both verbs make it."""
    try:
        return pack(result, corpus=corpus, qualify=qualify, max_chars=max_chars, **packing)
    except ValueError as error:
        raise UsageError(str(error), fix="pass max_chars between 1000 and 24000") from error


def _refuse(**given: bool) -> None:
    """Ruling 2: every parameter the read path cannot honour yet, named."""
    named = [name for name, used in given.items() if used]
    if named:
        raise UsageError(
            f"{', '.join(named)} {'is' if len(named) == 1 else 'are'} not served by this build; "
            "it would be dropped, so it is refused",
            fix=_FIX,
        )
