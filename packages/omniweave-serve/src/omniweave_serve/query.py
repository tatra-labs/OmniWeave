"""`ow_query` over `tools/call`: the first `Caller`, and the first tool an agent can call.

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

## WHAT IS NOT HERE

`scope` (10:395's four forms), `want` other than `passages`, and `route_hints` are refused by name
rather than ignored: an ignored `scope` answers over the whole corpus, which is the recall error
that presents as a confident answer. The emission ledger is not held, so nothing is withheld as
`ow:sent-earlier` and `Reply.after_send` is `None` -- there is nothing to commit (D525).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.answer import Answer, render
from omniweave_core.answer.pack import pack
from omniweave_core.clock import SystemClock
from omniweave_core.errors import OwError, UsageError
from omniweave_core.retrieve.execute import execute
from omniweave_core.retrieve.types import Query, RetrievalPolicy
from omniweave_core.store import reader as store_reader
from omniweave_core.store import sqlite as store_sqlite

from omniweave_serve.stdio import INVALID_PARAMS, METHOD_NOT_FOUND, Reply, failure, result

if TYPE_CHECKING:
    from omniweave_serve.dispatch import Surface
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
_PENDING: Final[str] = "ow_query is the one tool this build answers; {name} is listed and not built"


def text_result(text: str) -> dict[str, Any]:
    """A `tools/call` result: one text content block, never `isError` (10:920)."""
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _refusal(code: str, message: str, fix: str) -> dict[str, Any]:
    """10:920's *"text refusal"* shape: one line, the code, and the command that clears it."""
    prefix = f"{code}: " if code else ""
    return text_result(f"ow: {prefix}{message}. Fix: {fix}")


@dataclass(slots=True)
class QueryCaller:
    """A `dispatch.Caller`. Holds the resolved corpora and nothing mutable across calls."""

    corpora: Mapping[str, Path]
    default: str | None = None
    policy: RetrievalPolicy = field(default_factory=RetrievalPolicy)
    wall_ns: Callable[[], int] = field(default_factory=lambda: SystemClock().wall_ns)

    async def call(self, request: Request, surface: Surface) -> Reply:
        """Answer one `tools/call`. Only `ow_query` is built; the other listed tools say so."""
        del surface
        params = request.params
        name = params.get("name")
        if name != QUERY_TOOL:
            return Reply(
                body=failure(
                    request.ident,
                    METHOD_NOT_FOUND,
                    _PENDING.format(name=name),
                    data={"owed": "ow_open, ow_corpora and ow_add have no Caller yet"},
                )
            )
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return Reply(body=failure(request.ident, INVALID_PARAMS, "arguments is not an object"))
        return Reply(body=result(request.ident, self.answer(arguments)))

    def answer(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """The `tools/call` result for one set of `ow_query` arguments. Synchronous and pure of
        the transport, so a test drives it without a loop."""
        refused = _check(arguments)
        if refused is not None:
            return refused
        chosen = self._corpus(arguments.get("corpus"))
        if isinstance(chosen, dict):
            return chosen
        corpus, path = chosen
        try:
            connection = store_sqlite.connect_readonly(path)
        except OwError as error:
            return _unreadable(corpus, path, error)
        try:
            reader = store_reader.SqliteReader(connection, now_ns=self.wall_ns())
            retrieval = execute(reader, Query(text=str(arguments["query"])), self.policy)
        except UsageError as error:
            return _refusal(error.numeric(), str(error), error.fix)
        except OwError as error:
            return _unreadable(corpus, path, error)
        finally:
            connection.close()
        packed = pack(
            retrieval,
            corpus=corpus,
            qualify=len(self.corpora) > 1,
            max_chars=arguments.get("max_chars"),
        )
        return text_result(render(packed.answer, max_chars=packed.max_chars))

    def _corpus(self, named: object) -> tuple[str, Path] | dict[str, Any]:
        """The corpus to search and its store, or the blocking Answer saying why there is none."""
        corpus = named or self.default
        if corpus is None:
            return _blocked(
                "-",
                "OW-A-001",
                "no corpus is configured, so there is nothing to search",
                "ow add <path>",
            )
        path = self.corpora.get(str(corpus))
        if path is None:
            declared = ", ".join(sorted(self.corpora)) or "none"
            return _blocked(
                str(corpus),
                "OW-A-002",
                f"corpus {corpus!r} is not in [corpora]; declared: {declared}",
                "ow_corpora",
            )
        return str(corpus), path


def _unreadable(corpus: str, path: Path, error: OwError) -> dict[str, Any]:
    """10:920's third row: the corpus is declared and its store cannot be read."""
    return _blocked(corpus, "OW-A-002", f"{path} is not readable: {error}", "ow doctor")


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
    return _refusal(
        "",
        f"ow_query takes no argument {', '.join(unknown)}; its arguments are "
        f"{', '.join(sorted(_ARGUMENTS))}",
        "call ow_query with the arguments tools/list publishes",
    )


def _query(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return _refusal("", "ow_query needs a non-empty query string", 'ow_query query="..."')
    if len(query) > MAX_QUERY_CHARS:
        return _refusal(
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
    return _refusal(
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
        return _refusal("", f"max_chars must be an integer in {low}-{high}", "omit max_chars")
    corpus = arguments.get("corpus")
    if corpus is not None and not isinstance(corpus, str):
        return _refusal("", "corpus must be a string", "ow_corpora")
    return None


def _blocked(corpus: str, code: str, message: str, fix: str) -> dict[str, Any]:
    """An Answer carrying only `ow:blocking` -- 10:920's success shape for a recoverable condition.

    `degraded` is the state: nothing was searched, and the one Verdict state that says so is the
    one that is never citable as absence.
    """
    answer = Answer(
        state="degraded",
        corpus=corpus,
        generation=0,
        freshness="unknown",
        blocking=(f"> {message}. Fix: `{fix}` [{code}]",),
        trailer_extra=(("verdict.gates", "[]"),),
    )
    return text_result(render(answer))
