"""`ow corpora [<name>]`: what exists, what is in it, and what is missing. 10 section 4, row 3.

10:1003: *"An agent must be able to answer *what exists, what is in it, and what is missing from
it* without reading anything."* `ow_corpora` has answered it over MCP since W7.3, and the CLI verb
was refused as a root *"not dispatched by this build"*. The three store-reading documents are
`omniweave_core.store.card`'s -- `corpora_list`, `corpora_card`, `corpora_coverage` -- which W7.8j
moved there from `omniweave_serve.corpora`, so the CLI and the server print one document (SV19,
10:101-102) and neither imports the other (02:356).

**What is served**, by flag:
- `<name>`: one declared corpus, or a prefix ending in `*` for `list` (10:1027-1028). The global
  `--corpus` names it too, on either side of the verb: the positional shares its `dest` and, since
  W7.8q, declines a default, so it no longer overwrites the flag (D617, D624). Written both ways,
  the last one wins, as a repeated `--corpus` does.
- `--detail list` (the default), `card` and `coverage`: 10:1007-1011's modes, the documents
  `ow_corpora` returns. A store that will not open is a row with `readable: false`, never an
  error (10:1031-1032).
- `--detail actions`: 10:1012's *"generated catalog: every Action with an `mcp_name`, `summary`
  and `decision`"*, read from `ACTIONS`. The server refuses it because it may not import the
  registry (D551); this verb is in the package that owns it.
- `--render text` (the default): one line per corpus, or one line per field. `--render json`: the
  document, `schema` first (10:1530).

**What is refused by name**, each exit 1, because a flag parsed and ignored answers a different
question than the one asked (`ow query`'s rule, D614):
- `--summarize`: it writes an LLM-written abstract, and no summariser is wired (10:1089);
- `--scope`: `corpus.coverage`'s scope; core's coverage reads the whole corpus;
- `--quiet`: 10:1542-1545 has each Action declare its one scalar, and `corpora` declares none;
- `--render jsonl` and `--render rows`, which have no writer.

Exits are 10:1424's `0/2`, plus 1 for usage. 2 is a named corpus that is not declared, or a `card`
or `coverage` with no corpus named and no default.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import NotFoundError, OwError, UsageError

from omniweave.surface.query import error_object, parse
from omniweave.surface.serve import stores
from omniweave.surface.startup import corpora, declared_corpus

if TYPE_CHECKING:
    import argparse
    from collections.abc import Mapping, Sequence

    from omniweave_core.config import Config

__all__ = ["CORPORA_WORD", "actions_document", "main"]

CORPORA_WORD: Final[str] = "corpora"

_SCHEMA: Final[int] = 1


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """`ow corpora ...` from argv (starting at the root word). The exit is 10:1424's."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    as_json = parsed.render == "json"
    try:
        return _corpora(parsed, env=env, cwd=cwd, stdout=stdout)
    except OwError as error:
        if as_json:
            stdout.write(json.dumps(error_object(error), ensure_ascii=False) + "\n")
        else:
            stderr.write(f"ow: {error.numeric() or error.code()}: {error}\n  fix: {error.fix}\n")
        return type(error).EXIT


def _corpora(
    parsed: argparse.Namespace,
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
) -> int:
    _refuse_unserved(parsed)
    if parsed.detail == "actions":
        document = actions_document()
    else:
        explicit = Path(parsed.config) if parsed.config else None
        document = _document(load(cwd=cwd, env=env, explicit=explicit), parsed, cwd=cwd)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        for line in _text(document, detail=parsed.detail):
            stdout.write(line + "\n")
    return 0


def _refuse_unserved(parsed: argparse.Namespace) -> None:
    """Every flag this build parses and cannot honour, refused by name, before a store is read."""
    named = [
        flag
        for flag, value in (
            ("--summarize", parsed.summarize),
            ("--scope", parsed.scope is not None),
            ("--quiet", parsed.quiet),
        )
        if value
    ]
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by ow corpora; answering without it "
            "would answer a different question than the one asked",
            fix="ow corpora [<name>] [--detail list|card|coverage|actions] [--render json]",
        )


def _document(config: Config, parsed: argparse.Namespace, *, cwd: Path) -> dict[str, Any]:
    """The `list`, `card` or `coverage` document, as `ow_corpora` builds it, `schema` first."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.store import card as store_card  # noqa: PLC0415

    declared = {name: Path(path) for name, path in stores(config, corpora(config), cwd=cwd).items()}
    default, _ = declared_corpus(config)
    named: str | None = parsed.corpus
    if parsed.detail == "list":
        if named is not None and not named.endswith(store_card.WILDCARD):
            _declared(declared, named)
        built = store_card.corpora_list(declared, default=default, named=named)
    else:
        name = _one(declared, named or default, parsed.detail)
        if parsed.detail == "card":
            built = store_card.corpora_card(name, declared[name], default=default)
        else:
            built = store_card.corpora_coverage(
                name, declared[name], default=default, now_ns=SystemClock().wall_ns()
            )
    return {"schema": built.pop("schema"), **built}


def _declared(declared: Mapping[str, Path], name: str) -> None:
    if name not in declared:
        raise NotFoundError(
            f"corpus {name!r} is not in [corpora]; declared: "
            f"{', '.join(sorted(declared)) or 'none'}",
            symbol="OW_CORPUS_NOT_FOUND",
            fix="ow corpora   # lists every declared corpus",
        )


def _one(declared: Mapping[str, Path], named: str | None, detail: str) -> str:
    """The one corpus `card` and `coverage` read. 10:1027-1028: exactly one, and no wildcard."""
    from omniweave_core.store import card as store_card  # noqa: PLC0415

    if named is None:
        raise NotFoundError(
            f"--detail {detail} reads one corpus and none was named or is the default; declared: "
            f"{', '.join(sorted(declared)) or 'none'}",
            symbol="OW_CORPUS_NOT_FOUND" if declared else "OW_NO_CORPUS_CONFIGURED",
            fix=f"ow corpora <name> --detail {detail}",
        )
    if named.endswith(store_card.WILDCARD):
        raise UsageError(
            f"--detail {detail} accepts exactly one corpus and refuses a wildcard",
            fix=f"ow corpora {named}   # the list accepts a prefix",
        )
    _declared(declared, named)
    return named


def actions_document() -> dict[str, Any]:
    """10:1012's catalog: every Action with an `mcp_name`, its `summary` and its `decision`."""
    from omniweave.surface.registry import ACTIONS  # noqa: PLC0415 -- only this mode pays

    rows = [
        {"mcp_name": spec.mcp_name, "summary": spec.summary, "decision": spec.decision}
        for spec in ACTIONS.values()
        if spec.mcp_name
    ]
    return {"schema": _SCHEMA, "actions": rows}


def _text(document: Mapping[str, Any], *, detail: str) -> list[str]:
    """One line per corpus for `list`; a head line and one line per field otherwise."""
    if detail == "actions":
        return [
            line
            for row in document["actions"]
            for line in (
                f"{row['mcp_name']:<16}{row['summary']}",
                f"{'':<16}when: {row['decision']}",
            )
        ]
    rows: list[dict[str, Any]] = document["corpora"]
    lines: list[str] = []
    if not rows:
        lines.append("no declared corpus matches")
    for row in rows:
        lines.append(_head_line(row))
        if detail != "list":
            lines.extend(
                f"  {key:<18} {json.dumps(value, ensure_ascii=False)}"
                for key, value in row.items()
                if key not in _HEAD
            )
    if document.get("truncated"):
        lines.append(f"truncated: more corpora are declared than the {len(rows)} shown")
    lines.extend(f"  {one}" for one in document["degradations"])
    return lines


_HEAD: Final[frozenset[str]] = frozenset(
    {"name", "default", "readable", "reason", "card_stale", "card_gen"}
)


def _head_line(row: Mapping[str, Any]) -> str:
    """`name (default)  readable  card_gen=N` and, for a `list` row, its counts."""
    name = f"{row['name']}{' (default)' if row['default'] else ''}"
    if not row["readable"]:
        state = f"unreadable: {row['reason']}"
    else:
        state = "readable, card stale" if row["card_stale"] else "readable"
    line = f"{name:<24}{state}   card_gen={row['card_gen']}"
    counts = row.get("counts") or {}
    if counts and "verbatim_fraction" in row and "formats" not in row:
        line += (
            f"   docs {counts['docs_indexed']}/{counts['docs_discovered']} indexed"
            f"   pages {counts['pages']}   blocks {counts['blocks']}"
            f"   verbatim_fraction {row['verbatim_fraction']:.3f}"
        )
    return line
