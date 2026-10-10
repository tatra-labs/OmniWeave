"""`ow graph locate`: where on the page an entity, claim, edge or mention was witnessed. D694.

10:811 gives `ow_locate` one row -- *"where on the page a mention, edge or claim was witnessed
(`Locus`)"* -- and 06:2521 the verb: `ow graph locate --edge/--mention/--claim/--entity <id>`,
*"the `Locus` tuple per witness"*. `omniweave_core.store.locate.locate()` is the walk (06 section
8); this module resolves the corpus, opens one read snapshot, and prints what the walk found.

**Two renders, one per consumer** (10 section 6.3).
- `--render json` is the `Located` itself: the subject, and per witness its kind, id, slot, the
  entity it mentions, the witnessed text, and the `Locus` -- cite, document, generation, page,
  address, span, the quad's eight integers or `null`, the precision, the origin span and the
  reason there is no quad.
- `--render text`, the default, is one head line and one line per witness: where it is, the text,
  and either the quad's rectangle or the reason.

**One selector.** `--entity` and `--claim` take a cite an answer printed (`e412`, `k9001`), bare
or qualified with its corpus (`handbook:e412`), or its number; `--edge` and `--mention` take the
number. None, or two, is exit 1 naming them.

**Refused by name**, exit 1, as `ow doc grid` refuses them: `--quiet`, `--render jsonl` and
`--render rows`. Every other `ow graph` verb is rostered (`registry.CLI_ROSTER`) and has no
`ActionSpec` yet, so the parse refuses it.

Exits: 0; 1 for usage; 2 for a cite or id that names nothing, or an undeclared corpus; 6 for a
qualified cite and a `--corpus` that disagree (`OW-A-015`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import OwError, PolicyRefusal, UsageError

from omniweave.surface.opening import corpus_for
from omniweave.surface.query import parse, store_of
from omniweave.surface.startup import corpora
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core.model.locus import Located, Locus

__all__ = ["GRAPH_WORD", "located_document", "main"]

GRAPH_WORD: Final[str] = "graph"

_SCHEMA: Final[int] = 1
_SELECTORS: Final[tuple[str, ...]] = ("entity", "claim", "edge", "mention")
_FIX: Final[str] = "ow graph locate --entity e412"


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """`ow graph <verb> ...` from argv (starting at the root word)."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(GRAPH_WORD, parsed)
        return _locate(parsed, env=env, cwd=cwd, stdout=stdout)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _locate(
    parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO
) -> int:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow graph locate", fix=_FIX
        )
    given = [name for name in _SELECTORS if getattr(parsed, name) is not None]
    if len(given) != 1:
        spelled = ", ".join(f"--{name}" for name in given) or "none"
        raise UsageError(
            f"ow graph locate takes exactly one of --entity, --claim, --edge and --mention; "
            f"got {spelled}",
            fix=_FIX,
        )
    [selector] = given
    value = getattr(parsed, selector)
    prefix, bare = _qualified(str(value)) if selector in ("entity", "claim") else (None, value)
    if prefix is not None and parsed.corpus is not None and prefix != parsed.corpus:
        raise PolicyRefusal(
            f"--{selector} {value} names corpus {prefix!r} and --corpus names {parsed.corpus!r}",
            symbol="OW_CROSS_CORPUS_UNSUPPORTED",
            fix="run ow graph locate once per corpus",
        )
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, [], prefix or parsed.corpus, verb="ow graph locate")
    store = store_of(config, name, cwd=cwd)
    located = _read(store, **{selector: bare})
    document = located_document(located, corpus=name, qualify=len(corpora(config)) > 1)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        stdout.write("\n".join(_text(document)) + "\n")
    return 0


def _qualified(value: str) -> tuple[str | None, str]:
    """`handbook:e412` -> (`handbook`, `e412`); a bare cite has no corpus."""
    corpus, sep, bare = value.rpartition(":")
    return (corpus, bare) if sep and corpus else (None, value)


def _read(store: Path, **selector: Any) -> Located:
    """The walk, inside one read snapshot so every witness describes one state of the store."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.locate import locate  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot():
            try:
                return locate(connection, **selector)
            except ValueError as error:
                raise UsageError(str(error), fix=_FIX) from error
    finally:
        connection.close()


def located_document(located: Located, *, corpus: str, qualify: bool) -> dict[str, Any]:
    """The JSON render: `Located`'s fields, each `Locus` spelled out."""

    def cite(text: str | None) -> str | None:
        return None if text is None else (f"{corpus}:{text}" if qualify else text)

    return {
        "schema": _SCHEMA,
        "subject": cite(located.subject) if located.subject[:1] in ("e", "k") else located.subject,
        "witnesses": [
            {
                "kind": witness.kind,
                "id": witness.id,
                "slot": witness.slot,
                "entity": cite(witness.entity),
                "surface": witness.surface,
                **_locus(witness.locus, cite),
            }
            for witness in located.witnesses
        ],
    }


def _locus(locus: Locus, cite: Any) -> dict[str, Any]:
    from dataclasses import asdict  # noqa: PLC0415

    origin = asdict(locus.origin)
    return {
        "cite": cite(str(locus.cite)),
        "doc_ord": locus.doc_ord,
        "gen": locus.gen,
        "page": locus.page,
        "addr": str(locus.addr),
        "span": [locus.span.a, locus.span.b],
        "quad": None if locus.quad is None else list(locus.quad),
        "precision": locus.precision.value,
        "origin": {"os_kind": locus.origin.os_kind.value, **_plain(origin)},
        "reason": locus.reason,
    }


def _plain(value: Any) -> Any:
    """`asdict()`'s output with tuples as lists, so a nested `Quad` prints as eight integers."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _text(document: Mapping[str, Any]) -> list[str]:
    witnesses = document["witnesses"]
    lines = [f"{document['subject']}  {len(witnesses)} witness(es)"]
    for w in witnesses:
        where = f"{w['cite']}  p{w['page']}  [{w['span'][0]}, {w['span'][1]})"
        if w["quad"] is not None:
            xs, ys = w["quad"][0::2], w["quad"][1::2]
            box = f"box ({min(xs)}, {min(ys)})-({max(xs)}, {max(ys)})"
        else:
            box = f"no box: {w['reason']}"
        label = w["kind"] if w["slot"] is None else f"{w['kind']} {w['slot']}"
        lines.append(f"  {label} {w['id']}  {where}  {w['surface']!r}  {w['precision']}  {box}")
    return lines
