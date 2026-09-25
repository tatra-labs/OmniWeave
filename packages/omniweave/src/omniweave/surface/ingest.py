"""`ow ingest`: parse, config, the corpus, the roots, then `run.ingest.ingest()`. Startup steps 1-8.

18:928's row is *"`ow ingest --scope <id>` -- hidden; the detached child `add` and `PostToolUse`
spawn"*, and 02:467 runs it with a path: `ow ingest ./docs`. Both forms are here, and so is the one
`posttool.command()` actually builds, which is `ow ingest` with no argument at all.

## IT IS NOT IN `ACTIONS`, AND `ow hook` IS THE PRECEDENT

18:928 and 18:923 give `ow ingest` and `ow hook` the same word -- *hidden* -- and `ow hook` is the
one root `__main__` dispatches without a registry row: it is parsed by its own module and appears
in no generated artefact. An `ActionSpec` for `ingest` would put it in `llms.txt`, `AGENTS.md`, the
SDK stub and `ow --help`, which is four places a hidden command would be shown. So `ingest` follows
`hook`: its own parser, here, and no row (D565). The flags are 18:928's `--scope`, 10:1616's
`--corpus` (*"accepted on every corpus-scoped verb ... its omission uses `[serve]
default_corpus`"*), 02:467's positional path, and `--config`, which every command takes.

## THE STEPS, AND WHICH ONES ARE NOT HERE

| step | here |
|---|---|
| 1 dispatch | `_parse()`; a usage error is exit 1 with no config read |
| 2 config | `omniweave_core.config.load()` |
| 3 limits | not run: no `MAX_*` bounds an ingest this build can do (D382) |
| 4 digests | `run.ingest.open_run()` freezes them into the `run` row |
| 5 surface | serve only |
| 6 store | the store thread's own open: `CONN_PRAGMAS` and heal-on-open |
| 7 catalog | not run: nothing this build ingests resolves a driver (D563) |
| 8 write lock | `store.write` beside the store, taken per unit (D560) |
| 9 loop | `run.ingest`'s `asyncio.run` |

**A path outside the corpus's source root is refused**, which is 05:78's rule for the walk --
*"`OW_PATH_OUTSIDE_ROOTS` (`OW-A-007`) is a refusal, not a warning"* -- applied before the walk,
where the refusal can name the path. `OW-A-007`, exit 6. The same test `ow_add` makes, on resolved
paths, so `..` cannot step out of the root.

Everything the command prints is ASCII, for `__main__`'s reason: a piped child's streams on
Windows are cp1252 and a path is the user's.
"""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Final, TextIO

from omniweave_core.config import load
from omniweave_core.errors import OwError, PolicyRefusal, UsageError

from omniweave.surface.serve import stores
from omniweave.surface.startup import corpora, declared_corpus

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.config import Config

__all__ = ["INGEST_WORD", "main", "parser"]

INGEST_WORD: Final[str] = "ingest"

_USAGE: Final[int] = UsageError.EXIT
_ARGPARSE_USAGE: Final[int] = 2


def parser() -> argparse.ArgumentParser:
    """`ow ingest [PATH ...] [--scope S] [--corpus N] [--config PATH]`. Every flag an option."""
    built = argparse.ArgumentParser(
        prog="ow ingest",
        description=(
            "Drain the roster of one corpus: walk, acquire and identify. Hidden; the detached "
            "child ow_add and PostToolUse spawn."
        ),
    )
    built.add_argument("paths", nargs="*", metavar="PATH", help="walk these instead of the roster")
    built.add_argument("--scope", help="one stored ingest_scope: its prefix, or its directory")
    built.add_argument("--corpus", help="a [corpora] name; default [serve] default_corpus")
    built.add_argument("--config", help="an omniweave.toml to load instead of the one found")
    return built


def main(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
    sweep_ms: int | None = None,
) -> int:
    """Run `ow ingest` from argv (after `ingest`). 0 on a run that ended; an error's exit if not.

    A `partial` run exits 0: 08:911, *"`ow ingest` still exits 0, because a partial run is a result
    and not an error"* -- and the report's last line says what stopped it.
    """
    try:
        return _ingest(argv, env=env, cwd=cwd, stdout=stdout, stderr=stderr, sweep_ms=sweep_ms)
    except OwError as error:
        stderr.write(_line(error))
        return type(error).EXIT


def _ingest(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: Path,
    stdout: TextIO,
    stderr: TextIO,
    sweep_ms: int | None,
) -> int:
    from omniweave.run.ingest import ingest  # noqa: PLC0415 -- a usage error never pays for it

    parsed = _parse(argv, stderr)
    if isinstance(parsed, int):
        return parsed
    if parsed.paths and parsed.scope is not None:
        raise UsageError(
            "ow ingest takes paths or --scope, not both: --scope names a walk the roster holds",
            fix="ow ingest <path>..., or ow ingest --scope <prefix>",
        )
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = _corpus(config, parsed.corpus)
    store = Path(stores(config, [name], cwd=cwd)[name])
    source = Path(stores(config, [name], cwd=cwd, field="source")[name])
    paths = tuple(_contained(Path(raw), source=source, cwd=cwd) for raw in parsed.paths)
    report = ingest(
        store,
        config=config,
        source_root=source,
        output_root=_root(config, "roots.output", cwd),
        cache_root=_root(config, "roots.cache", cwd),
        argv=["ingest", *argv],
        paths=paths,
        scope=parsed.scope,
        sweep_ms=sweep_ms,
    )
    for line in report.lines():
        stdout.write(_ascii(line) + "\n")
    return 0


def _parse(argv: Sequence[str], stderr: TextIO) -> argparse.Namespace | int:
    """The namespace, or argparse's exit: `--help` is 0 and a parse error is 1 (10:1484)."""
    try:
        with contextlib.redirect_stderr(stderr):
            return parser().parse_args(list(argv))
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else _USAGE
        return _USAGE if code == _ARGPARSE_USAGE else code


def _corpus(config: Config, wanted: str | None) -> str:
    """`--corpus`, else `[serve] default_corpus` resolved as startup step 5 resolves it."""
    declared = corpora(config)
    if wanted is not None:
        if wanted not in declared:
            raise UsageError(
                f"--corpus {wanted!r} names no declared corpus; [corpora] declares "
                f"{', '.join(declared) or 'nothing'}",
                symbol="OW_CORPUS_NOT_FOUND",
                fix="declare [corpora.<name>] in omniweave.toml, or pass one it declares",
            )
        return wanted
    name, why = declared_corpus(config)
    if name is None:
        raise UsageError(
            f"ow ingest needs a corpus and none resolves: {why}",
            symbol="OW_CORPUS_NOT_FOUND",
            fix="ow ingest --corpus <name>, or set [serve] default_corpus",
        )
    return name


def _contained(raw: Path, *, source: Path, cwd: Path) -> Path:
    """A path argument resolved against `cwd`, and refused outside the corpus's source root."""
    resolved = (raw if raw.is_absolute() else cwd / raw).resolve()
    root = source.resolve()
    if resolved != root and root not in resolved.parents:
        raise PolicyRefusal(
            f"{raw} is outside the corpus source root {root}, and ow ingest will not walk it",
            symbol="OW_PATH_OUTSIDE_ROOTS",
            fix=f"move it under {root}, or set [corpora.<name>] source to a root that holds it",
        )
    if not resolved.exists():
        raise UsageError(f"{raw} does not exist", fix="pass a file or directory that does")
    return resolved


def _root(config: Config, key: str, cwd: Path) -> Path:
    """`[roots] output` or `cache`, resolved by `stores()`'s D527 rule for a `path` key."""
    raw = Path(str(config.get(key)))
    declared = config.source_of(key).path
    base = declared.parent if declared is not None else cwd
    return raw if raw.is_absolute() else (base / raw).resolve()


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _line(error: OwError) -> str:
    """10:294's one line: code, exit, message and fix. `surface.serve`'s shape, for its reason."""
    code = f"{error.code()} " if error.code() else ""
    return _ascii(f"ow: {code}(exit {type(error).EXIT}): {error}; fix: {error.fix}") + "\n"
