"""`ow_add` over `tools/call`: the one listed writer, and the half of it this build can do.

10:1113-1117 gives `ow_add` three steps, because the router lives in `omniweave` and the server may
not import it:

> *"(a) writes `unit` rows plus one `ingest_scope` row in a single transaction,
> enqueue-before-lock; (b) spawns a detached `ow ingest --scope <scope_id>` child, exactly as a
> `PostToolUse` hook does; (c) polls the roster to its deadline and reports what completed, what
> remains, and the pending cost **with the approving command**."*

**(a) is here** and is core's (`acquire.add_sources`). **(b) and (c) are not** (D554).
`ow ingest` is not a root this build's `__main__` dispatches, so a spawned child would exit 70.
`subprocess` is banned outside `toolchain` and `host.subproc` (the TID251 row), and neither has a
detached spawn. With nothing draining the roster, polling it to a 20-second deadline would wait
for nothing. So the report says what was rostered and that nothing drains it: `completed` is empty,
every queued unit is `pending` with that reason, and `deadline_reached` is false because no deadline
was waited on.

## THE ONE REFUSAL THAT IS `isError: true`

10:486: *"A path outside every configured root is `OW-A-007 / OW_PATH_OUTSIDE_ROOTS` with `isError:
true` and **no retry guidance** -- abandoning that path is the desired agent reaction."* It is
10:920's security row, and the only `isError` any tool on this surface returns. The roots are every
declared corpus's `corpora.*.source` (which inherits `[roots] source`), resolved by the launcher. A
relative source resolves against the chosen corpus's own. Containment is tested on the resolved
path, so `..` and a symlink out of the tree are both refused.

## WHAT IS REFUSED BEFORE ANYTHING IS READ

| argument | rule |
|---|---|
| `source` | one string or 1-256 strings, each non-empty and at most 4,096 bytes (10:946) |
| `source` | a URL is refused by name: no `acquire` connector is built (02:329) |
| `dry_run` | a boolean |
| `corpus` | a declared corpus, or the default |
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.acquire import Added, add_sources
from omniweave_core.errors import OwError, ResourceLimit

from omniweave_serve.answers import refusal, text_result, unreadable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["ADD_TOOL", "MAX_PATH_BYTES", "MAX_SOURCES", "PENDING_MAX", "respond", "sources_of"]

ADD_TOOL: Final[str] = "ow_add"
MAX_SOURCES: Final[int] = 256
"""10:485's *"one string or ≤ 256 strings"*, and 10:946's `source` cap."""

MAX_PATH_BYTES: Final[int] = 4_096
"""10:946: *"a path ≤ 4,096 bytes"*."""

PENDING_MAX: Final[int] = 32
"""How many `pending` rows one report names. The plan sets none (D557): a 20,000-unit add would
otherwise be a multi-megabyte text block, and `pending_more` counts the rest."""

SCHEMA_VERSION: Final[int] = 1
_ARGUMENTS: Final[frozenset[str]] = frozenset({"source", "corpus", "dry_run"})
_DRAIN: Final[str] = "ow ingest"
_NOT_DRAINED: Final[str] = (
    "rostered; nothing drains it in this build, because ow ingest is not a dispatched command"
)
_DRY_RUN: Final[str] = "would be rostered; dry_run wrote nothing"


def sources_of(arguments: Mapping[str, Any]) -> tuple[str, ...]:
    """`source` as a tuple. Call after `check()`."""
    source = arguments["source"]
    return (source,) if isinstance(source, str) else tuple(source)


def check(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """Every argument refusal, before anything is read (10:946). `None` means the call may run."""
    for rule in (_known, _sources, _each, _flags):
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
        f"ow_add takes no argument {', '.join(unknown)}; its arguments are corpus, dry_run, source",
        "call ow_add with the arguments tools/list publishes",
    )


def _sources(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    source = arguments.get("source")
    sources = [source] if isinstance(source, str) else source
    if not isinstance(sources, list) or not sources:
        return refusal("", "ow_add needs source: one path or a list of them", 'source="docs/"')
    if len(sources) > MAX_SOURCES:
        return refusal(
            "OW-A-008",
            f"source holds {len(sources)} paths and the cap is {MAX_SOURCES}",
            f"split the call into batches of {MAX_SOURCES}",
        )
    return None


def _each(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    source = arguments["source"]
    for one in [source] if isinstance(source, str) else source:
        if not isinstance(one, str) or not one.strip():
            return refusal("", "every source is a non-empty string", 'source="docs/"')
        if len(one.encode("utf-8", "surrogatepass")) > MAX_PATH_BYTES:
            return refusal("", f"a source path is at most {MAX_PATH_BYTES} bytes", "a shorter path")
        if "://" in one:
            return refusal(
                "",
                f"{one} is a URL, and this build has no acquire connector for URLs",
                "download it into a [roots] source directory and add that path",
            )
    return None


def _flags(arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    if not isinstance(arguments.get("dry_run", False), bool):
        return refusal("", "dry_run is a boolean", "omit dry_run")
    corpus = arguments.get("corpus")
    if corpus is not None and not isinstance(corpus, str):
        return refusal("", "corpus must be a string", "ow_corpora")
    return None


def respond(
    arguments: Mapping[str, Any],
    *,
    corpus: str,
    store: Path,
    source_root: Path,
    roots: Sequence[Path],
    now_ns: int,
) -> dict[str, Any]:
    """The `tools/call` result for checked arguments and a chosen corpus."""
    resolved = _contained(sources_of(arguments), source_root, roots)
    if isinstance(resolved, dict):
        return resolved
    dry_run = bool(arguments.get("dry_run", False))
    try:
        added = add_sources(store, resolved, now_ns=now_ns, dry_run=dry_run)
    except ResourceLimit as error:
        return refusal(error.numeric(), str(error), error.fix)
    except OwError as error:
        return unreadable(corpus, store, error)
    report = _report(corpus, added, dry_run=dry_run)
    return text_result(json.dumps(report, ensure_ascii=False, separators=(",", ":")))


def _contained(
    sources: Sequence[str], source_root: Path, roots: Sequence[Path]
) -> list[Path] | dict[str, Any]:
    """Each source resolved, or `OW-A-007` for the first outside every root, or a missing path."""
    real_roots = [root.resolve() for root in roots]
    out: list[Path] = []
    for source in sources:
        path = Path(source)
        real = (path if path.is_absolute() else source_root / path).resolve()
        if not any(real == root or root in real.parents for root in real_roots):
            return _outside(source)
        if not real.exists():
            return refusal(
                "", f"{source} does not exist under the corpus source", "check the path and retry"
            )
        out.append(real)
    return out


def _outside(source: str) -> dict[str, Any]:
    """10:486: `isError: true` and no retry guidance -- no `Fix:`, by design."""
    return {
        "content": [
            {
                "type": "text",
                "text": f"ow: OW-A-007: {source} is outside every [roots] source, and ow_add will "
                f"not read it",
            }
        ],
        "isError": True,
    }


def _report(corpus: str, added: Added, *, dry_run: bool) -> dict[str, Any]:
    """10:1100-1108's `add-out-v1` object, and D555's text `scope_id`."""
    pending = [
        {
            "uri": uri,
            "reason": _DRY_RUN if dry_run else _NOT_DRAINED,
            "cost_class": "free",
            "est_micros": 0,
            "approve": _DRAIN,
        }
        for uri in added.queued[:PENDING_MAX]
    ]
    return {
        "scope_id": added.scopes[0] if len(added.scopes) == 1 else None,
        "corpus": corpus,
        "discovered": added.discovered,
        "unchanged": added.unchanged,
        "queued": 0 if dry_run else len(added.queued),
        "skipped": added.skipped,
        "completed": [],
        "pending": pending,
        "pending_more": max(0, len(added.queued) - PENDING_MAX),
        "degradations": [],
        "deadline_reached": False,
        "schema": SCHEMA_VERSION,
    }
