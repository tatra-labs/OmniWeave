"""`ow_query` over `tools/call`, and the `Caller` that routes `ow_open` to `opening`.

D511 left `tools/call` a seam with nothing plugged in, waiting on a `retrieve()` in core. W7.3q
built it, and `omniweave_core.answer.pack` turns its result into the Answer document. This module
is the part only the server can do: take the tool's arguments off the wire, choose the corpus,
open its store read-only, and put the rendered document into a `tools/call` result.

## THE SHAPE OF EVERY ANSWER, AND THE ONE RULE 10:920 GIVES IT

*"`isError: true` is reserved for "stop trying"."* Every outcome here is `isError: false`, and they
come in three shapes:

| condition | shape | code |
|---|---|---|
| the query ran | the Answer document | the Verdict's |
| no corpus / not found / unreadable | an Answer with `ow:blocking` | `OW-A-001`, `OW-A-002` |
| an argument this build cannot honour | a one-line text refusal | `OW-A-008`, or none (D526) |

10:920's reason is measured behaviour: *"an `isError: true` early in a session teaches the agent the
toolset is broken and it stops calling codegraph entirely"*. None of the rows above is a security
refusal, which is the only kind the table gives `isError`.

## THE CORPUS

`corpora` is `[corpora]` resolved by the launcher (name -> absolute store path), and `default` is
what step 5 decided `[serve] default_corpus` resolves to (`Servable.corpus`), or `None`. An explicit
`corpus` argument beats the default and must name a declared corpus; with neither, the answer is
10:920's first row. A store that is declared and not on disk is 10:920's third row, *"corpus
present but unreadable"*. 10:540: *"Tool availability is never gated on index presence"* -- the
tool is listed and callable, and the answer says what is missing.

## THE LEDGER, AND WHERE ITS WRITE IS

Given an `emission.StdioSession`, each call reads the compaction marker, packs against the
session's ledger -- a document already sent, unchanged and fresh becomes an `ow:sent-earlier` row --
and returns the commit as `Reply.after_send`, which `stdio.serve()` runs only after the write and
the flush succeeded. That is 10:977's ordering, and it is the only place this module writes the
ledger: `respond()` reads it and never records. What is committed is `pack.emitted()` over the
rendered document, so a block the truncator cut is never recorded as sent (10:991).

With no session -- the unit tests, and any dispatcher built without one -- dedup is off, as 18:475
says it is without a session, and `after_send` is `None`.

## WHAT IS NOT HERE

`scope` (10:395's four forms), `want` other than `passages`, and `route_hints` are refused by name
rather than ignored: an ignored `scope` answers over the whole corpus, which is the recall error
that presents as a confident answer. `serve_emission`, 10:984's accounting row, has no writer
(D533).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.answer import render
from omniweave_core.answer.dedup import LEDGER_RESET_KIND
from omniweave_core.answer.pack import emitted, pack
from omniweave_core.clock import SystemClock
from omniweave_core.errors import OwError, UsageError
from omniweave_core.retrieve.execute import execute
from omniweave_core.retrieve.types import Query, RetrievalPolicy
from omniweave_core.store import reader as store_reader
from omniweave_core.store import sqlite as store_sqlite

from omniweave_serve import opening
from omniweave_serve.answers import blocked, refusal, text_result, unreadable
from omniweave_serve.stdio import INVALID_PARAMS, METHOD_NOT_FOUND, Reply, failure, result

if TYPE_CHECKING:
    from omniweave_core.answer.dedup import Emission
    from omniweave_core.retrieve.execute import Retrieval

    from omniweave_serve.dispatch import Surface
    from omniweave_serve.emission import StdioSession
    from omniweave_serve.stdio import Request

__all__ = ["MAX_QUERY_CHARS", "QUERY_TOOL", "QueryCaller", "text_result"]

QUERY_TOOL: Final[str] = "ow_query"
MAX_QUERY_CHARS: Final[int] = 4_096
"""10:374's `query` cap, and `OW-A-008 / OW_QUERY_TOO_LONG`'s. Enforced before any store read
(10:946). Not `channels.MAX_QUERY_CHARS = 4_000`, which is the sanitiser's bound on the text it
reads. The two disagree by 96 characters and D529 is that; a test binds this one to the
published schema and another measures the window between them."""

_ARGUMENTS: Final[frozenset[str]] = frozenset(
    {"query", "corpus", "scope", "want", "route_hints", "max_chars"}
)
"""`ow_query`'s published `inputSchema` properties. A test binds this set to the catalogue."""

_NOT_SERVED: Final[frozenset[str]] = frozenset({"scope", "route_hints"})
_MAX_CHARS: Final[tuple[int, int]] = (1_000, 24_000)
_PENDING: Final[str] = "ow_query and ow_open are the tools this build answers; {name} is not built"


@dataclass(slots=True)
class QueryCaller:
    """A `dispatch.Caller`. The resolved corpora, and the session whose ledger it reads.

    `session` is the one mutable thing, and it is mutated in two places only: `compacted()` before
    a retrieval, and `commit()` from `after_send`.
    """

    corpora: Mapping[str, Path]
    default: str | None = None
    policy: RetrievalPolicy = field(default_factory=RetrievalPolicy)
    wall_ns: Callable[[], int] = field(default_factory=lambda: SystemClock().wall_ns)
    session: StdioSession | None = None

    async def call(self, request: Request, surface: Surface) -> Reply:
        """Answer one `tools/call`. `ow_query` and `ow_open` are built; the other two say so."""
        del surface
        params = request.params
        name = params.get("name")
        if name not in {QUERY_TOOL, opening.OPEN_TOOL}:
            return Reply(
                body=failure(
                    request.ident,
                    METHOD_NOT_FOUND,
                    _PENDING.format(name=name),
                    data={"owed": "ow_corpora and ow_add have no Caller yet"},
                )
            )
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return Reply(body=failure(request.ident, INVALID_PARAMS, "arguments is not an object"))
        respond = self.respond if name == QUERY_TOOL else self.respond_open
        body, sent = respond(arguments)
        session = self.session
        if session is None or not sent:
            return Reply(body=result(request.ident, body))
        return Reply(body=result(request.ident, body), after_send=lambda: session.commit(sent))

    def answer(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """The `tools/call` result for one set of `ow_query` arguments, committing nothing."""
        return self.respond(arguments)[0]

    def respond(self, arguments: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[Emission, ...]]:
        """The result, and what it would record as sent. Synchronous and pure of the transport,
        so a test drives it without a loop; the ledger is read here and written by the caller."""
        refused = _check(arguments)
        if refused is not None:
            return refused, ()
        chosen = self._corpus(arguments.get("corpus"))
        if isinstance(chosen, dict):
            return chosen, ()
        corpus, path = chosen
        retrieval = self._retrieve(corpus, path, str(arguments["query"]))
        if isinstance(retrieval, dict):
            return retrieval, ()
        session = self.session
        reset = session is not None and session.compacted()
        packed = pack(
            retrieval,
            corpus=corpus,
            qualify=len(self.corpora) > 1,
            max_chars=arguments.get("max_chars"),
            ledger=None if session is None else session.ledger,
            call_ord=1 if session is None else session.calls + 1,
            degradations=(LEDGER_RESET_KIND,) if reset else (),
        )
        document = render(packed.answer, max_chars=packed.max_chars)
        if session is not None:
            session.calls += 1
        return text_result(document), emitted(packed, document)

    def respond_open(
        self, arguments: Mapping[str, Any]
    ) -> tuple[dict[str, Any], tuple[Emission, ...]]:
        """`ow_open`'s result, and what it would record as sent. See `opening`."""
        refused = opening.check(arguments)
        if refused is not None:
            return refused, ()
        named = opening.named_corpus(opening.refs_of(arguments), arguments.get("corpus"))
        if isinstance(named, dict):
            return named, ()
        chosen = self._corpus(named)
        if isinstance(chosen, dict):
            return chosen, ()
        corpus, path = chosen
        return opening.respond(
            arguments,
            corpus=corpus,
            path=path,
            qualify=len(self.corpora) > 1,
            now_ns=self.wall_ns(),
            session=self.session,
        )

    def _retrieve(self, corpus: str, path: Path, text: str) -> Retrieval | dict[str, Any]:
        """One read-only retrieval over one store, or the result that says why there is none."""
        try:
            connection = store_sqlite.connect_readonly(path)
        except OwError as error:
            return unreadable(corpus, path, error)
        try:
            reader = store_reader.SqliteReader(connection, now_ns=self.wall_ns())
            return execute(reader, Query(text=text), self.policy)
        except UsageError as error:
            return refusal(error.numeric(), str(error), error.fix)
        except OwError as error:
            return unreadable(corpus, path, error)
        finally:
            connection.close()

    def _corpus(self, named: object) -> tuple[str, Path] | dict[str, Any]:
        """The corpus to search and its store, or the blocking Answer saying why there is none."""
        corpus = named or self.default
        if corpus is None:
            return blocked(
                "-",
                "OW-A-001",
                "no corpus is configured, so there is nothing to search",
                "ow add <path>",
            )
        path = self.corpora.get(str(corpus))
        if path is None:
            declared = ", ".join(sorted(self.corpora)) or "none"
            return blocked(
                str(corpus),
                "OW-A-002",
                f"corpus {corpus!r} is not in [corpora]; declared: {declared}",
                "ow_corpora",
            )
        return str(corpus), path


def _check(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Every argument refusal, before any store read (10:946). `None` means the call may run."""
    for check in (_known, _query, _served, _bounded):
        refused = check(arguments)
        if refused is not None:
            return refused
    return None


def _known(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    unknown = sorted(set(arguments) - _ARGUMENTS)
    if not unknown:
        return None
    return refusal(
        "",
        f"ow_query takes no argument {', '.join(unknown)}; its arguments are "
        f"{', '.join(sorted(_ARGUMENTS))}",
        "call ow_query with the arguments tools/list publishes",
    )


def _query(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return refusal("", "ow_query needs a non-empty query string", 'ow_query query="..."')
    if len(query) > MAX_QUERY_CHARS:
        return refusal(
            "OW-A-008",
            f"the query is {len(query)} characters and the cap is {MAX_QUERY_CHARS}",
            "ask a shorter question, or ow_open the address you already hold",
        )
    return None


def _served(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    named = sorted(name for name in _NOT_SERVED if name in arguments)
    if arguments.get("want", "passages") != "passages":
        named.append(f"want={arguments['want']}")
    if not named:
        return None
    return refusal(
        "",
        f"{', '.join(named)} is published and not served by this build; answering without it "
        f"would search more than was asked",
        "omit it and narrow with the kind:, page: and sec: prefixes in the query text",
    )


def _bounded(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    max_chars = arguments.get("max_chars")
    low, high = _MAX_CHARS
    if max_chars is not None and (
        not isinstance(max_chars, int)
        or isinstance(max_chars, bool)
        or not low <= max_chars <= high
    ):
        return refusal("", f"max_chars must be an integer in {low}-{high}", "omit max_chars")
    corpus = arguments.get("corpus")
    if corpus is not None and not isinstance(corpus, str):
        return refusal("", "corpus must be a string", "ow_corpora")
    return None
