"""`ow query "<q>"`: one read-only retrieval, packed and rendered. 10 section 6, row 1.

The `query` ActionSpec and the generated parser have existed since W7.1, and `ow_query` has been
served over MCP since W7.3. The CLI verb was refused as a root *"not dispatched by this build"*
(D529's "not here", D608's V01-15). This module composes the same four core calls the MCP
handler composes -- `connect_readonly`, `SqliteReader`, `execute`, `pack` -- and renders with
the same `render()`. So the two surfaces are one implementation (SV19, 10:101-102), and neither
imports the other: `omniweave` may not import `omniweave_serve` (02:356).

**What is served**, by flag:
- `--corpus N`: one declared corpus, or `[serve] default_corpus`.
- `--k`, `--mode`: passed to `Query` as they are.
- `--max-chars`: passed to `pack()`. Below 1,000 is refused (10:476); above the tier is clamped
  and disclosed in the trailer.
- `--fail-on absent,degraded`: exit 3 or 4 (10:1486-1487).
- `--render text` (the default): the rendered Answer. `--render json`: one object of the out type.
- `--quiet`: the verdict state and nothing else (10:1542).

**What is refused by name, and why each is not silently ignored.** A flag the parser accepts and
the verb ignores answers a different question than the one asked (the MCP handler's rule, 10:946):
- `--scope`, `--want` other than `passages`, `--max-rung`: the planner that reads them is not
  wired, as `ow_query` refuses them too.
- `--explain`: nothing prints a routing decision for a query.
- a comma list in `--corpus`: the rank-merged fan-out of 10:1440-1443 is not built.
- `--render jsonl` and `--render rows`: `owrows/1` and the progress stream have no writer here.
- `--quiet` with `--render json`: 10:1546 makes them exclusive.
- `--verbose`, and any other global flag `switches.READS` does not give this verb (D631).
  `--json-errors` is served: 18:898's object on stderr, through `switches.report()`.

**`--render json` is the Answer as `schema/answer-v1.json` publishes it**, and that schema has
`additionalProperties: false` and no `schema` field, while 10:1530 asks for `schema` first. So
the object carries no `schema` key and validates against the published contract (D614). An error
under `--render json` is 10:1539-1540's object, on stdout, which does carry `schema`.

Exit codes are 10 section 6.2's: 0, 1 usage, 2 not found, 3 and 4 only under `--fail-on`, and an
error's own EXIT otherwise.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import enum
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import NotFoundError, OwError, UsageError

from omniweave.surface.serve import stores
from omniweave.surface.startup import corpora, declared_corpus
from omniweave.surface.switches import check, error_object, report

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.answer.render import Answer
    from omniweave_core.config import Config

__all__ = [
    "ABSENT_EXIT",
    "DEGRADED_EXIT",
    "FAIL_ON",
    "QUERY_WORD",
    "answer_json",
    "corpus_of",
    "error_object",
    "main",
    "parse",
    "store_of",
]

QUERY_WORD: Final[str] = "query"

ABSENT_EXIT: Final[int] = 3
DEGRADED_EXIT: Final[int] = 4
"""10:1486-1487: *"3 verdict=absent (only with --fail-on absent)"*, *"4 verdict=degraded (only with
--fail-on degraded)"*."""

FAIL_ON: Final[dict[str, int]] = {"absent": ABSENT_EXIT, "degraded": DEGRADED_EXIT}

_USAGE: Final[int] = UsageError.EXIT
_ARGPARSE_USAGE: Final[int] = 2


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    """`ow query ...` from argv (starting at the root word). The exit is 10 section 6.2's."""
    parsed = parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    try:
        check(QUERY_WORD, parsed)
        return _query(parsed, env=env, cwd=cwd, stdout=stdout)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _query(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    from omniweave_core.answer.pack import pack  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.answer.render import render  # noqa: PLC0415

    fail_on = _refuse_unserved(parsed)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_of(config, parsed.corpus, verb="ow query")
    store = store_of(config, name, cwd=cwd)
    retrieval = _retrieve(store, parsed, config)
    try:
        #  `qualify` is `ow_query`'s rule: with more than one corpus declared, every cite names
        #  its corpus, so a cite pasted into `ow open` cannot resolve against the wrong one.
        packed = pack(
            retrieval,
            corpus=name,
            qualify=len(corpora(config)) > 1,
            max_chars=parsed.max_chars,
        )
    except ValueError as error:
        #  `effective_max_chars` refuses below 1,000 as a ValueError and leaves the exit to the
        #  surface (answer/budget.py), and this surface's is a usage error.
        raise UsageError(str(error), fix="pass --max-chars between 1000 and 24000") from error
    answer = packed.answer
    if parsed.quiet:
        stdout.write(answer.state + "\n")
    elif parsed.render == "json":
        stdout.write(json.dumps(answer_json(answer), ensure_ascii=False) + "\n")
    else:
        stdout.write(render(answer, max_chars=packed.max_chars))
        stdout.write("\n")
    return fail_on.get(answer.state, 0)


def _retrieve(store: Path, parsed: argparse.Namespace, config: Config | None = None) -> Any:
    """One read-only `execute()` over one store, as `ow_query` makes it (serve's `_retrieve`)."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415
    from omniweave_core.retrieve.execute import execute  # noqa: PLC0415
    from omniweave_core.retrieve.plan import budget_of  # noqa: PLC0415
    from omniweave_core.retrieve.types import Query, RetrievalPolicy  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    fields: dict[str, Any] = {"text": parsed.query}
    if parsed.k is not None:
        fields["k"] = parsed.k
    if parsed.mode is not None:
        fields["mode"] = parsed.mode
    clock = SystemClock()
    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=clock.wall_ns())
        #  D650: the project's `[retrieval.budget]`, which no query read until now.
        policy = RetrievalPolicy() if config is None else RetrievalPolicy(budget=budget_of(config))
        return execute(reader, Query(**fields), policy)
    finally:
        connection.close()


def _refuse_unserved(parsed: argparse.Namespace) -> dict[str, int]:
    """Every flag this build parses and cannot honour, refused by name; then `--fail-on`."""
    named = [
        flag
        for flag, value in (
            ("--scope", parsed.scope),
            ("--max-rung", parsed.max_rung),
            ("--explain", parsed.explain or None),
        )
        if value is not None
    ]
    if parsed.want != "passages":
        named.append(f"--want {parsed.want}")
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if parsed.corpus is not None and "," in parsed.corpus:
        named.append("a comma list in --corpus")
    if named:
        raise UsageError(
            f"{', '.join(named)} is parsed and not served by this build; answering without it "
            "would answer a different question than the one asked",
            fix="omit it, and narrow with the kind:, page: and sec: prefixes in the query text",
        )
    if parsed.quiet and parsed.render != "text":
        raise UsageError(
            "--quiet and --render are exclusive (10:1546)", fix="pass one of them, not both"
        )
    if not parsed.query.strip():
        raise UsageError("ow query needs a non-empty question", fix='ow query "<question>"')
    if parsed.fail_on is None:
        return {}
    states = [one.strip() for one in parsed.fail_on.split(",") if one.strip()]
    unknown = [one for one in states if one not in FAIL_ON]
    if unknown or not states:
        raise UsageError(
            f"--fail-on takes absent and degraded, not {', '.join(unknown) or 'nothing'}",
            fix="ow query ... --fail-on absent,degraded",
        )
    return {state: FAIL_ON[state] for state in states}


def store_of(config: Config, name: str, *, cwd: Path) -> Path:
    """The corpus's `.owstore`, which must exist: a read never creates one. Missing is 2."""
    store = Path(stores(config, [name], cwd=cwd)[name])
    if not store.is_file():
        raise NotFoundError(
            f"corpus {name!r} has no store at {store} yet: nothing has been ingested into it",
            symbol="OW_CORPUS_NOT_FOUND",
            fix=f"ow add --corpus {name} <path>",
        )
    return store


def corpus_of(config: Config, wanted: str | None, *, verb: str) -> str:
    """`--corpus`, else `[serve] default_corpus` as startup step 5 resolves it. Missing is 2.

    `ow open` resolves its corpus here too (W7.8i), after a qualified cite has named one.
    """
    declared = corpora(config)
    if wanted is not None:
        if wanted not in declared:
            raise NotFoundError(
                f"--corpus {wanted!r} names no declared corpus; [corpora] declares "
                f"{', '.join(declared) or 'nothing'}",
                symbol="OW_CORPUS_NOT_FOUND",
                fix="declare [corpora.<name>] in omniweave.toml, or pass one it declares",
            )
        return wanted
    name, why = declared_corpus(config)
    if name is None:
        raise NotFoundError(
            f"{verb} needs a corpus and none resolves: {why}",
            symbol="OW_CORPUS_NOT_FOUND",
            fix=f"{verb} --corpus <name> ..., or set [serve] default_corpus",
        )
    return name


def parse(argv: Sequence[str], stderr: TextIO) -> argparse.Namespace | int:
    """The namespace, or the parser's exit: `--help` is 0 and a parse error is 1 (10:1484).

    Any root of the generated tree; `ow add` parses through it too (W7.8h).
    """
    from omniweave.cli import build_parser  # noqa: PLC0415 -- only a CLI verb pays for the tree

    try:
        with contextlib.redirect_stderr(stderr):
            return build_parser().parse_args(list(argv))
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else _USAGE
        return _USAGE if code == _ARGPARSE_USAGE else code


def answer_json(answer: Answer) -> dict[str, Any]:
    """The Answer as `schema/answer-v1.json` publishes it: every field, tuples as arrays.

    The schema is reflected from the same dataclass (D279), so walking its fields is the
    serialisation, and `test_query_verb.py` validates the result against the schema file.
    """
    return _plain(answer)


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name)) for field in dataclasses.fields(value)
        }
    if isinstance(value, enum.Enum):
        return _plain(value.value)
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value
