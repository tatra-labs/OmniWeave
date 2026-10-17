"""The SDK read path: `omniweave.corpus()`, `Corpus.query()` and `.open()`, `explain()`. D858.

18-api-sketch.md section 1 prints the Python API, and until this module none of its entry points
existed: `gen.sdk_stub.owed()` named five, and D323 recorded that no work item landed them. This
lands three of the five -- `corpus`, `Corpus` and `explain` -- with `Corpus.query` and
`Corpus.open` as the two methods a reader needs. `corpora` and `doctor` stay owed.

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
   on `query`, `raw` and `want_impact` on `open`, and `readonly=False` on `corpus()` are each a
   `UsageError` naming the parameter. That is `ow query`'s and `ow_query`'s rule (10:946): a
   parameter accepted and dropped answers a different question than the one asked. An unknown
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

Specified in 18-api-sketch.md section 1.1-1.2 and 10-interfaces.md section 9.1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import UsageError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from omniweave_core.answer.render import Answer
    from omniweave_core.config import Config
    from omniweave_core.model.enums import Layer
    from omniweave_core.store.types import Expand, Filters

    from omniweave.sdk.reports import CodeRow

__all__ = ["MODES", "WANTS", "Corpus", "corpus", "explain"]

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
    if not readonly:
        raise UsageError(
            "readonly=False is not served: a Corpus opened here only reads",
            fix="ow add <path> --corpus <name> writes, as a command",
        )
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
    store = store_of(resolved, chosen, cwd=cwd)
    generation, schema = _identity(store)
    return Corpus(name=chosen, schema=schema, generation=generation, _store=store, _config=resolved)


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
            pack, retrieval, corpus=self.name, qualify=self._qualify(), max_chars=max_chars
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
            pack_open, opening, corpus=self.name, qualify=self._qualify(), max_chars=max_chars
        )

    def _read(self, call: Any) -> Any:
        """One read-only connection and reader for one call, closed before returning."""
        from omniweave_core.clock import SystemClock  # noqa: PLC0415
        from omniweave_core.store import reader as store_reader  # noqa: PLC0415
        from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

        connection = store_sqlite.connect_readonly(self._store)
        try:
            return call(store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns()))
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


def _packed(pack: Any, result: Any, *, corpus: str, qualify: bool, max_chars: int) -> Answer:
    """`pack()` or `pack_open()`, its budget refusal a usage error, as both verbs make it."""
    try:
        return pack(result, corpus=corpus, qualify=qualify, max_chars=max_chars).answer
    except ValueError as error:
        raise UsageError(str(error), fix="pass max_chars between 1000 and 24000") from error


def _refuse(**given: bool) -> None:
    """Ruling 2: every parameter the read path cannot honour yet, named."""
    named = [name for name, used in given.items() if used]
    if named:
        raise UsageError(
            f"{', '.join(named)} {'is' if len(named) == 1 else 'are'} not served by this build's "
            "read path; it would be dropped, so it is refused",
            fix=_FIX,
        )
