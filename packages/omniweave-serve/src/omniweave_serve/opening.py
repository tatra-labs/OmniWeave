"""`ow_open` over `tools/call`: an address the agent already holds, resolved exactly. 10:437-470.

`ow_query` searches; `ow_open` resolves. 18:346 draws the line: *"Resolve addresses the caller
already holds -- no ranking, no fusion, no absence gates."* This module takes the tool's arguments
off the wire and hands them to core: `store.resolve.fetch()` runs the five-form ladder, hydrates
and reads coverage in one snapshot, and `answer.pack.pack_open()` packs in the order asked.

## WHAT IS REFUSED BEFORE ANY STORE READ

10:946: *"Input caps are enforced before any store read"*. So every argument problem is a one-line
text refusal, 10:920's shape, before a connection is opened:

| argument | rule | code |
|---|---|---|
| `ref` | one string or 1-64 strings, none empty | `OW-A-008`-shaped over 64 (10:437) |
| `ref` | a qualified cite names one corpus, and it is `corpus` if given | `OW-A-015` |
| `context` | an integer 0-8, default 1 | none (D526's family) |
| `layers` | members of `Layer` | none; names the five (10:474) |
| `max_chars` | an integer 1,000-24,000 | none |

A ref that parses and does not resolve is not an argument problem: it is an Answer whose
`ow:blocking` carries `OW-M-030`, `OW-M-032` or `OW-A-016` for that ref, beside the refs that did
resolve. 10:920's table has no row for it (D543), and a batch of 64 refs with one stale cite should
still return the other 63.

## WHAT IS NOT HERE

- `ow:impact`, which 18:1368 has the MCP handler render *"by default when the ref is a single
  block"*. It reads `artifact_cite`, and F65 (10:2756) already questions the default (D544).
- `OW-A-014`, the ambiguous unqualified cite. With more than one corpus declared every cite in the
  Answer is qualified, so the corpus a block came from is printed rather than silent (D545).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.answer import render
from omniweave_core.answer.dedup import LEDGER_RESET_KIND
from omniweave_core.answer.pack import emitted, pack_open
from omniweave_core.errors import OwError
from omniweave_core.model.enums import Layer
from omniweave_core.store import reader as store_reader
from omniweave_core.store import resolve
from omniweave_core.store import sqlite as store_sqlite

from omniweave_serve.answers import refusal, text_result, unreadable

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.answer.dedup import Emission

    from omniweave_serve.emission import StdioSession

__all__ = ["DEFAULT_LAYERS", "OPEN_TOOL", "check", "named_corpus", "refs_of", "respond"]

OPEN_TOOL: Final[str] = "ow_open"
_ARGUMENTS: Final[frozenset[str]] = frozenset({"ref", "corpus", "context", "layers", "max_chars"})
"""`ow_open`'s published `inputSchema` properties. A test binds this set to the catalogue."""

DEFAULT_LAYERS: Final[frozenset[Layer]] = frozenset({Layer.BODY})
"""18:344's `layers=(Layer.BODY,)`, the SDK's default, which the MCP handler shares."""

_DEFAULT_CONTEXT: Final[int] = 1
_MAX_CHARS: Final[tuple[int, int]] = (1_000, 24_000)
_LAYER_NAMES: Final[str] = ", ".join(layer.value for layer in Layer)


def refs_of(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    """`ref` as a tuple, one string or many. Call after `check()`."""
    ref = arguments["ref"]
    return (ref,) if isinstance(ref, str) else tuple(ref)


def check(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Every argument refusal, before any store read (10:946). `None` means the call may run."""
    for rule in (_known, _ref, _context, _layers, _bounded):
        refused = rule(arguments)
        if refused is not None:
            return refused
    return None


def _known(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    unknown = sorted(set(arguments) - _ARGUMENTS)
    if not unknown:
        return None
    return refusal(
        "",
        f"ow_open takes no argument {', '.join(unknown)}; its arguments are "
        f"{', '.join(sorted(_ARGUMENTS))}",
        "call ow_open with the arguments tools/list publishes",
    )


def _ref(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    ref = arguments.get("ref")
    refs = [ref] if isinstance(ref, str) else ref
    if (
        not isinstance(refs, list)
        or not refs
        or not all(isinstance(r, str) and r.strip() for r in refs)
    ):
        return refusal(
            "", "ow_open needs ref: one non-empty string or a list of them", 'ow_open ref="d7#412"'
        )
    if len(refs) > resolve.MAX_REFS:
        return refusal(
            "OW-A-008",
            f"ref holds {len(refs)} addresses and the cap is {resolve.MAX_REFS}",
            f"split the call into batches of {resolve.MAX_REFS}",
        )
    return None


def _context(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    context = arguments.get("context", _DEFAULT_CONTEXT)
    if (
        isinstance(context, int)
        and not isinstance(context, bool)
        and 0 <= context <= resolve.MAX_CONTEXT
    ):
        return None
    return refusal("", f"context must be an integer in 0-{resolve.MAX_CONTEXT}", "omit context")


def _layers(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    layers = arguments.get("layers")
    if layers is None:
        return None
    known = {layer.value for layer in Layer}
    if (
        isinstance(layers, list)
        and layers
        and all(isinstance(n, str) and n in known for n in layers)
    ):
        return None
    return refusal("", f"layers must be a list of {_LAYER_NAMES}", 'layers=["body"]')


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


def named_corpus(refs: Sequence[str], corpus: str | None) -> str | dict[str, Any] | None:
    """The corpus the refs and the argument agree on, or `OW-A-015` when they do not.

    18:335: *"a `refs` entry qualified with a different corpus. One `Corpus` addresses one
    corpus."* A qualified cite with no `corpus` argument names the corpus by itself.
    """
    named = {
        parsed.corpus
        for ref in refs
        for parsed in resolve.parse(ref)[:1]
        if parsed.corpus is not None
    }
    if corpus is not None:
        named.add(corpus)
    if len(named) > 1:
        return refusal(
            "OW-A-015",
            f"these refs address {len(named)} corpora ({', '.join(sorted(named))}); one ow_open "
            f"call addresses one",
            "call ow_open once per corpus",
        )
    return next(iter(named), None)


def respond(
    arguments: Mapping[str, Any],
    *,
    corpus: str,
    path: Path,
    qualify: bool,
    now_ns: int,
    session: StdioSession | None,
) -> tuple[dict[str, Any], tuple[Emission, ...]]:
    """The `tools/call` result for checked arguments, and what it would record as sent."""
    layers = frozenset(Layer(name) for name in arguments.get("layers") or ()) or DEFAULT_LAYERS
    try:
        connection = store_sqlite.connect_readonly(path)
    except OwError as error:
        return unreadable(corpus, path, error), ()
    try:
        reader = store_reader.SqliteReader(connection, now_ns=now_ns)
        opening = resolve.fetch(
            reader,
            refs_of(arguments),
            context=arguments.get("context", _DEFAULT_CONTEXT),
            layers=layers,
        )
    except OwError as error:
        return unreadable(corpus, path, error), ()
    finally:
        connection.close()
    reset = session is not None and session.compacted()
    packed = pack_open(
        opening,
        corpus=corpus,
        qualify=qualify,
        max_chars=arguments.get("max_chars"),
        call_ord=1 if session is None else session.calls + 1,
        degradations=(LEDGER_RESET_KIND,) if reset else (),
    )
    document = render(packed.answer, max_chars=packed.max_chars)
    if session is not None:
        session.calls += 1
    return text_result(document), emitted(packed, document)
