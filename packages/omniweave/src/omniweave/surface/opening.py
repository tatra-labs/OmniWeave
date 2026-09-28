"""`ow open <ref>...`: addresses the caller already holds, resolved exactly. 10 section 6, row 2.

`ow_query` searches and `ow_open` resolves. 18:346: *"Resolve addresses the caller already holds --
no ranking, no fusion, no absence gates."* `ow_open` has been served over MCP since W7.3, and the
CLI verb was refused as a root *"not dispatched by this build"*. This module makes the calls the MCP
handler makes -- `connect_readonly`, `SqliteReader`, `resolve.fetch()`, `pack_open()` -- and renders
with the same `render()`, so the two surfaces are one implementation (SV19, 10:101-102). Neither
imports the other: `omniweave` may not import `omniweave_serve` (02:356).

**What is served**, by flag:
- `<ref>...`: 1-64 addresses in any of the five forms `resolve.parse()` reads. A qualified cite
  (`handbook:d7#412`) names its corpus.
- `--corpus N`: one declared corpus, or `[serve] default_corpus`. It must agree with every
  qualified cite, or the call is `OW-A-015` (18:335).
- `--context K`: 0-8 neighbouring blocks each side, default 1.
- `--layers L,...`: members of `Layer`, default `body` (18:344).
- `--max-chars`: passed to `pack_open()`, as `ow query` passes it to `pack()`.
- `--render text` (the default) and `--render json`: the Answer, as `schema/open-out-v1.json`
  publishes it.

**What is refused by name**, each exit 1, because a flag parsed and ignored answers a different
question than the one asked (`ow query`'s rule, D614):
- `--raw`: nothing returns the retained bytes without the packer, and the packer is where
  defanging happens (10:1423's *"`--raw` is the defanging escape hatch"*);
- `--want-impact`: `ow:impact` reads `artifact_cite`, which is not rendered (D544);
- `--quiet`: 10:1542-1545 has each Action declare its one scalar, and `open` declares none;
- `--render jsonl` and `--render rows`, which have no writer.

**Exits are 10:1423's `0/2/6`, plus 1 for usage.** 0 when every ref resolved. 2 when any did not:
the Answer is still printed, with the refs that resolved as evidence and an `ow:blocking` line for
each that did not, because a batch of 64 refs with one stale cite should still return the other 63
-- and a script that opens a cite it holds must be able to tell that it went stale (D616). An
undeclared corpus, or one with no store, is 2 as well. 6 is `OW-A-015`, refs that address two
corpora, which 18:335 makes a `PolicyRefusal`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import NotFoundError, OwError, PolicyRefusal, UsageError

from omniweave.surface.query import answer_json, corpus_of, error_object, parse, store_of
from omniweave.surface.startup import corpora

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core.config import Config
    from omniweave_core.model.enums import Layer

__all__ = ["OPEN_WORD", "corpus_for", "main"]

OPEN_WORD: Final[str] = "open"

_RESOLVED: Final[str] = "ok"


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """`ow open ...` from argv (starting at the root word). The exit is 10:1423's."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    as_json = parsed.render == "json"
    try:
        return _open(parsed, env=env, cwd=cwd, stdout=stdout)
    except OwError as error:
        if as_json:
            stdout.write(json.dumps(error_object(error), ensure_ascii=False) + "\n")
        else:
            stderr.write(f"ow: {error.numeric() or error.code()}: {error}\n  fix: {error.fix}\n")
        return type(error).EXIT


def _open(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    from omniweave_core.answer.pack import pack_open  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.answer.render import render  # noqa: PLC0415

    refs = _refuse_unserved(parsed)
    layers = _layers(parsed.layers)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, refs, parsed.corpus, verb="ow open")
    store = store_of(config, name, cwd=cwd)
    opening = _fetch(store, refs, context=parsed.context, layers=layers)
    try:
        packed = pack_open(
            opening,
            corpus=name,
            qualify=len(corpora(config)) > 1,
            max_chars=parsed.max_chars,
        )
    except ValueError as error:
        #  The budget refuses below 1,000 as a ValueError and leaves the exit to the surface.
        raise UsageError(str(error), fix="pass --max-chars between 1000 and 24000") from error
    answer = packed.answer
    if parsed.render == "json":
        stdout.write(json.dumps(answer_json(answer), ensure_ascii=False) + "\n")
    else:
        stdout.write(render(answer, max_chars=packed.max_chars))
        stdout.write("\n")
    return 0 if answer.state == _RESOLVED else NotFoundError.EXIT


def _fetch(store: Path, refs: Sequence[str], *, context: int, layers: frozenset[Layer]) -> Any:
    """One read-only `resolve.fetch()` over one store, as `ow_open` makes it."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import resolve  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        return resolve.fetch(reader, refs, context=context, layers=layers)
    finally:
        connection.close()


def _refuse_unserved(parsed: argparse.Namespace) -> tuple[str, ...]:
    """Every flag this build parses and cannot honour, refused by name; then the refs' caps."""
    from omniweave_core.store import resolve  # noqa: PLC0415

    named = [
        flag
        for flag, value in (
            ("--raw", parsed.raw),
            ("--want-impact", parsed.want_impact),
            ("--quiet", parsed.quiet),
        )
        if value
    ]
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by this build; opening without it "
            "would answer a different question than the one asked",
            fix="omit it; ow open prints the packed Answer, as text or --render json",
        )
    refs = tuple(parsed.ref)
    if not all(ref.strip() for ref in refs):
        raise UsageError("every ref is a non-empty address", fix="ow open d7#412")
    if len(refs) > resolve.MAX_REFS:
        raise UsageError(
            f"{len(refs)} refs and the cap is {resolve.MAX_REFS} (10:437)",
            fix=f"split the call into batches of {resolve.MAX_REFS}",
        )
    if not 0 <= parsed.context <= resolve.MAX_CONTEXT:
        raise UsageError(
            f"--context is 0-{resolve.MAX_CONTEXT}, not {parsed.context}", fix="omit --context"
        )
    return refs


def _layers(raw: str | None) -> frozenset[Layer]:
    """`--layers body,note`, each a `Layer`; `body` alone when omitted (18:344)."""
    from omniweave_core.model.enums import Layer  # noqa: PLC0415

    if raw is None:
        return frozenset({Layer.BODY})
    names = [one.strip() for one in raw.split(",") if one.strip()]
    known = {layer.value: layer for layer in Layer}
    unknown = [one for one in names if one not in known]
    if unknown or not names:
        raise UsageError(
            f"--layers takes {', '.join(known)}, not {', '.join(unknown) or 'nothing'}",
            fix="ow open <ref> --layers body,note",
        )
    return frozenset(known[one] for one in names)


def corpus_for(config: Config, refs: Sequence[str], wanted: str | None, *, verb: str) -> str:
    """The one corpus these refs address: a qualified cite's, `--corpus`, or the default.

    `OW-A-015` when they name two (18:335). A cite qualified with an undeclared corpus is 2 and
    names the ref, because `corpus_of()`'s refusal names `--corpus` and none was passed.
    `ow doc grid` resolves its ref here too (W7.8n), so the two verbs cannot pick different
    corpora for one cite.
    """
    named = _named(refs, wanted)
    if wanted is None and named is not None and named not in corpora(config):
        raise NotFoundError(
            f"a ref is qualified with corpus {named!r}, which is not declared; [corpora] "
            f"declares {', '.join(corpora(config)) or 'nothing'}",
            symbol="OW_CORPUS_NOT_FOUND",
            fix="open the cite with the corpus prefix [corpora] declares, or declare it",
        )
    return corpus_of(config, named, verb=verb)


def _named(refs: Sequence[str], corpus: str | None) -> str | None:
    """The corpus the refs and `--corpus` agree on, or `OW-A-015` when they do not (18:335)."""
    from omniweave_core.store import resolve  # noqa: PLC0415

    named = {
        parsed.corpus
        for ref in refs
        for parsed in resolve.parse(ref)[:1]
        if parsed.corpus is not None
    }
    if corpus is not None:
        named.add(corpus)
    if len(named) > 1:
        raise PolicyRefusal(
            f"these refs address {len(named)} corpora ({', '.join(sorted(named))}); one ow open "
            "addresses one",
            symbol="OW_CROSS_CORPUS_UNSUPPORTED",
            fix="run ow open once per corpus",
        )
    return next(iter(named), None)
