"""`ow graph locate` and `ow graph why`: the two walks between the graph and the page. D694, D695.

`ow graph locate` is D694's, from an assertion to where it was witnessed; `ow graph why --cite`
is D695's, from a block to every assertion observed in it (06:2119-2121). Both resolve the
corpus, open one read snapshot, and print what `omniweave_core.store` read.

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

**`ow graph why --cite <ref>`** resolves `ref` as `ow open` does, to exactly one block, and prints
`store.observed.observed()`: the block's live mentions (each with its entity and that entity's
head), the edges and the claims observed in it, each with its span. `--render json` is that
`Observed`; `--render text` is a head line and one line per row.

**Refused by name**, exit 1, for both verbs, as `ow doc grid` refuses them: `--quiet`,
`--render jsonl` and `--render rows`. The other fourteen `ow graph` verbs are rostered
(`registry.CLI_ROSTER`) and have no `ActionSpec` yet, so the parse refuses them.

Exits: 0; 1 for usage; 2 for a cite or id that names nothing, or an undeclared corpus; 6 for a
qualified cite and a `--corpus` that disagree (`OW-A-015`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TextIO, cast

from omniweave_core.config import load
from omniweave_core.errors import OwError, PolicyRefusal, UsageError

from omniweave.surface.opening import corpus_for
from omniweave.surface.query import parse, store_of
from omniweave.surface.startup import corpora
from omniweave.surface.switches import check, report

if TYPE_CHECKING:
    import argparse
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_core.model.locus import Located, Locus
    from omniweave_core.model.merges import Decided, MergeLog
    from omniweave_core.model.observed import Observed
    from omniweave_core.model.residue import GraphResidue
    from omniweave_core.model.review import Review

    from omniweave.sdk.reports import GraphDoctorReport

__all__ = [
    "GRAPH_WORD",
    "decided_document",
    "doctor_document",
    "located_document",
    "main",
    "merges_document",
    "observed_document",
    "residue_document",
    "review_document",
]

GRAPH_WORD: Final[str] = "graph"

_SCHEMA: Final[int] = 1
_SELECTORS: Final[tuple[str, ...]] = ("entity", "claim", "edge", "mention")
_FIX: Final[str] = "ow graph locate --entity e412"
_WHY_FIX: Final[str] = "ow graph why --cite d7#412"
_WHY: Final[str] = "graph.why"
_MERGES: Final[str] = "graph.merges"
_MERGES_FIX: Final[str] = "ow graph merges --entity e412"
_MERGE: Final[str] = "graph.merge"
_MERGE_FIX: Final[str] = 'ow graph merge e412 e997 --reason "why they are one"'
_SPLIT: Final[str] = "graph.split"
_SPLIT_FIX: Final[str] = 'ow graph split e412 --into d7#412,d19#88 --reason "why they are two"'
_RESIDUE: Final[str] = "graph.residue"
_RESIDUE_FIX: Final[str] = "ow graph residue --akind identifier"
_REVIEW: Final[str] = "graph.review"
_DOCTOR: Final[str] = "graph.doctor"
_DOCTOR_FIX: Final[str] = "ow graph doctor --check dangling_tmp,trust_clamped,ungrounded"


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
        verb = _VERBS.get(parsed.ow_action, _locate)
        return verb(parsed, env=env, cwd=cwd, stdout=stdout)
    except OwError as error:
        return report(error, parsed, stdout=stdout, stderr=stderr)


def _locate(
    parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO
) -> int:
    _refuse_unserved(parsed, verb="ow graph locate", fix=_FIX)
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


def _refuse_unserved(parsed: argparse.Namespace, *, verb: str, fix: str) -> None:
    named = ["--quiet"] if parsed.quiet else []
    if parsed.render in ("jsonl", "rows"):
        named.append(f"--render {parsed.render}")
    if named:
        raise UsageError(f"{', '.join(named)} is parsed and not served by {verb}", fix=fix)


def _why(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    _refuse_unserved(parsed, verb="ow graph why", fix=_WHY_FIX)
    if parsed.cite is None or not str(parsed.cite).strip():
        raise UsageError("ow graph why needs --cite, a block's cite", fix=_WHY_FIX)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    ref = str(parsed.cite)
    name = corpus_for(config, [ref], parsed.corpus, verb="ow graph why")
    store = store_of(config, name, cwd=cwd)
    found = _observe(store, ref)
    document = observed_document(found, corpus=name, qualify=len(corpora(config)) > 1)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        stdout.write("\n".join(_why_text(document)) + "\n")
    return 0


def _observe(store: Path, ref: str) -> Observed:
    """`ref` to one block, through `ow open`'s ladder, then the reverse walk: one snapshot."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.errors import NotFoundError  # noqa: PLC0415
    from omniweave_core.model.enums import Layer  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import resolve  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.observed import observed  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot() as s:
            (found,) = reader.resolve_refs(s, [ref], context=0, layers=frozenset(Layer))
            if isinstance(found, resolve.Missed):
                raise found.error
            if len(found.block_ids) != 1:
                raise UsageError(
                    f"{ref} names {len(found.block_ids)} blocks, and ow graph why reads one",
                    fix="ow graph why --cite <one block's cite>   # ow open lists them",
                )
            result = observed(connection, int(found.block_ids[0]))
            if result is None:  # pragma: no cover -- resolve_refs returned it from this snapshot
                raise NotFoundError(f"no block {ref}", fix=_WHY_FIX)
            return result
    finally:
        connection.close()


def observed_document(found: Observed, *, corpus: str, qualify: bool) -> dict[str, Any]:
    """The JSON render: `Observed`'s three lists, every cite qualified when two corpora exist."""

    def cite(text: str) -> str:
        return f"{corpus}:{text}" if qualify else text

    return {
        "schema": _SCHEMA,
        "cite": cite(found.cite),
        "mentions": [
            {
                "mention": m.mention,
                "entity": cite(m.entity),
                "head": cite(m.head),
                "etype": m.etype,
                "key": m.key,
                "span": list(m.span),
                "surface": m.surface,
                "trust": m.trust,
            }
            for m in found.mentions
        ],
        "edges": [
            {
                "edge": e.edge,
                "src": cite(e.src),
                "dst": cite(e.dst),
                "relation": e.relation,
                "span": None if e.span is None else list(e.span),
                "trust": e.trust,
            }
            for e in found.edges
        ],
        "claims": [
            {
                "claim": cite(c.claim),
                "subject": cite(c.subject),
                "claim_type": c.claim_type,
                "predicate": c.predicate,
                "object": c.object,
                "status": c.status,
                "span": list(c.span),
                "trust": c.trust,
            }
            for c in found.claims
        ],
    }


def _why_text(document: Mapping[str, Any]) -> list[str]:
    lines = [
        f"{document['cite']}  {len(document['mentions'])} mention(s), "
        f"{len(document['edges'])} edge(s), {len(document['claims'])} claim(s)"
    ]
    for m in document["mentions"]:
        lines.append(
            f"  mention {m['entity']} ({m['etype']} {m['key']})  [{m['span'][0]}, {m['span'][1]})"
            f"  {m['surface']!r}"
        )
    for e in document["edges"]:
        where = "whole block" if e["span"] is None else f"[{e['span'][0]}, {e['span'][1]})"
        lines.append(f"  edge {e['edge']}  {e['src']} {e['relation']} {e['dst']}  {where}")
    for c in document["claims"]:
        lines.append(
            f"  claim {c['claim']}  {c['subject']} {c['predicate']} = {c['object']!r}  "
            f"{c['status']}  [{c['span'][0]}, {c['span'][1]})"
        )
    return lines


def _merges(
    parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO
) -> int:
    _refuse_unserved(parsed, verb="ow graph merges", fix=_MERGES_FIX)
    prefix, bare = (None, None) if parsed.entity is None else _qualified(str(parsed.entity))
    if prefix is not None and parsed.corpus is not None and prefix != parsed.corpus:
        raise PolicyRefusal(
            f"--entity {parsed.entity} names corpus {prefix!r} and --corpus names "
            f"{parsed.corpus!r}",
            symbol="OW_CROSS_CORPUS_UNSUPPORTED",
            fix="run ow graph merges once per corpus",
        )
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, [], prefix or parsed.corpus, verb="ow graph merges")
    store = store_of(config, name, cwd=cwd)
    log = _log(store, bare)
    document = merges_document(log, corpus=name, qualify=len(corpora(config)) > 1)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        stdout.write("\n".join(_merges_text(document)) + "\n")
    return 0


def _log(store: Path, entity: str | None) -> MergeLog:
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.merges import merge_log  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot():
            try:
                return merge_log(connection, entity)
            except ValueError as error:
                raise UsageError(str(error), fix=_MERGES_FIX) from error
    finally:
        connection.close()


def merges_document(log: MergeLog, *, corpus: str, qualify: bool) -> dict[str, Any]:
    """The JSON render: `MergeLog`'s closures, every cite qualified when two corpora exist."""

    def cite(text: str) -> str:
        return f"{corpus}:{text}" if qualify else text

    return {
        "schema": _SCHEMA,
        "entity": None if log.entity is None else cite(log.entity),
        "closures": [
            {
                "head": cite(closure.head),
                "members": [cite(m) for m in closure.members],
                "decisions": [
                    {
                        "merge": d.merge,
                        "loser": cite(d.loser),
                        "winner": cite(d.winner),
                        "polarity": d.polarity,
                        "stage": d.stage,
                        "method": d.method,
                        "trust": d.trust,
                        "score": d.score,
                        "score_kind": d.score_kind,
                        "guards": list(d.guards),
                        "reason": d.reason,
                        "decided_at_gen": d.decided_at_gen,
                        "retired_at_gen": d.retired_at_gen,
                    }
                    for d in closure.decisions
                ],
            }
            for closure in log.closures
        ],
    }


def _merges_text(document: Mapping[str, Any]) -> list[str]:
    closures = document["closures"]
    if not closures:
        return ["no closure of two or more: nothing is merged"]
    lines: list[str] = []
    for closure in closures:
        lines.append(
            f"{closure['head']}  {len(closure['members'])} member(s): "
            f"{' '.join(closure['members'])}  {len(closure['decisions'])} decision(s)"
        )
        for d in closure["decisions"]:
            verb = "merge" if d["polarity"] == 1 else "split"
            score = "" if d["score"] is None else f"  {d['score_kind']} {d['score']}"
            state = (
                "live" if d["retired_at_gen"] is None else f"retired at gen {d['retired_at_gen']}"
            )
            why = "" if d["reason"] is None else f"  reason {d['reason']!r}"
            lines.append(
                f"  {verb} {d['merge']}  {d['loser']} -> {d['winner']}  {d['stage']}{score}  "
                f"gen {d['decided_at_gen']}, {state}{why}"
            )
    return lines


def _merge(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    """`ow graph merge`: the one `ow graph` verb that writes, under the store's write lock."""
    _refuse_unserved(parsed, verb="ow graph merge", fix=_MERGE_FIX)
    if parsed.reason is None or not str(parsed.reason).strip():
        raise UsageError("ow graph merge needs --reason, the user's grounds for it", fix=_MERGE_FIX)
    first_prefix, first = _qualified(str(parsed.first))
    second_prefix, second = _qualified(str(parsed.second))
    named = {p for p in (first_prefix, second_prefix, parsed.corpus) if p is not None}
    if len(named) > 1:
        raise PolicyRefusal(
            f"these cites and --corpus name {len(named)} corpora ({', '.join(sorted(named))}); a "
            "merge is within one",
            symbol="OW_CROSS_CORPUS_UNSUPPORTED",
            fix=_MERGE_FIX,
        )
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, [], next(iter(named), None), verb="ow graph merge")
    store = store_of(config, name, cwd=cwd)
    reason = str(parsed.reason)
    decided = _decide(
        store, _MERGE, lambda decide, c: decide.merge(c, first=first, second=second, reason=reason)
    )
    return _decided(decided, parsed, config=config, corpus=name, stdout=stdout)


def _split(parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO) -> int:
    """`ow graph split`: the user's partition of one closure, under the store's write lock."""
    _refuse_unserved(parsed, verb="ow graph split", fix=_SPLIT_FIX)
    if parsed.reason is None or not str(parsed.reason).strip():
        raise UsageError("ow graph split needs --reason, the user's grounds for it", fix=_SPLIT_FIX)
    refs = [one.strip() for one in str(parsed.into or "").split(",") if one.strip()]
    if len(refs) < 2:  # noqa: PLR2004 -- a split has two sides
        raise UsageError(
            "ow graph split needs --into, a block cite per side and two at least", fix=_SPLIT_FIX
        )
    prefix, entity = _qualified(str(parsed.entity))
    if prefix is not None and parsed.corpus is not None and prefix != parsed.corpus:
        raise PolicyRefusal(
            f"{parsed.entity} names corpus {prefix!r} and --corpus names {parsed.corpus!r}",
            symbol="OW_CROSS_CORPUS_UNSUPPORTED",
            fix=_SPLIT_FIX,
        )
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, refs, prefix or parsed.corpus, verb="ow graph split")
    store = store_of(config, name, cwd=cwd)
    reason = str(parsed.reason)
    decided = _decide(
        store, _SPLIT, lambda decide, c: decide.split(c, entity=entity, into=refs, reason=reason)
    )
    return _decided(decided, parsed, config=config, corpus=name, stdout=stdout)


def _decided(
    decided: Decided, parsed: argparse.Namespace, *, config: Any, corpus: str, stdout: TextIO
) -> int:
    document = decided_document(decided, corpus=corpus, qualify=len(corpora(config)) > 1)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        stdout.write("\n".join(_decided_text(document)) + "\n")
    return 0


def _decide(store: Path, name: str, decision: Callable[[Any, Any], Decided]) -> Decided:
    """One unit under the store's write lock: the rows, then the graph settled, or neither."""
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.errors import NotFoundError  # noqa: PLC0415
    from omniweave_core.locks import store_write_lock  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    from omniweave.graph import decide  # noqa: PLC0415

    if not store.exists():
        raise NotFoundError(f"no store at {store}", fix="ow add <source> first")
    lock = store_write_lock(store, now_ns=SystemClock().wall_ns)
    with store_sqlite.StoreThread(lambda: store_sqlite.connect(store), lock=lock) as thread:
        return cast(
            "Decided",
            thread.run(
                store_sqlite.Unit(name=name, run=lambda c: decision(decide, c), cost_class="free")
            ),
        )


def decided_document(decided: Decided, *, corpus: str, qualify: bool) -> dict[str, Any]:
    """The JSON render: what the decision wrote, and the closure's log after it."""
    return {
        "polarity": decided.polarity,
        "written": decided.written,
        "retired": decided.retired,
        "followed": decided.followed,
        "unassigned": [f"{corpus}:{cite}" if qualify else cite for cite in decided.unassigned],
        **merges_document(decided.log, corpus=corpus, qualify=qualify),
    }


def _decided_text(document: Mapping[str, Any]) -> list[str]:
    verb = "merge" if document["polarity"] == 1 else "split"
    wrote = "written" if document["written"] else "already stood: nothing written"
    retired = f"; {document['retired']} opposing decision(s) retired" if document["retired"] else ""
    took = (
        "the graph follows"
        if document["followed"]
        else "another user decision keeps the graph from following: ow graph merges shows it"
    )
    lines = [f"{verb} {wrote}{retired}; {took}"]
    if document["unassigned"]:
        lines.append("  unassigned, a tie between sides: " + " ".join(document["unassigned"]))
    return [*lines, *_merges_text(document)]


def _residue(
    parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO
) -> int:
    """`ow graph residue`: both halves of 06:885's residue, grouped, from one read snapshot."""
    _refuse_unserved(parsed, verb="ow graph residue", fix=_RESIDUE_FIX)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, [], parsed.corpus, verb="ow graph residue")
    store = store_of(config, name, cwd=cwd)
    document = residue_document(_residual(store, parsed.akind))
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        stdout.write("\n".join(_residue_text(document)) + "\n")
    return 0


def _residual(store: Path, akind: str | None) -> GraphResidue:
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.graph_residue import graph_residue  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot():
            try:
                return graph_residue(connection, akind=akind)
            except ValueError as error:
                raise UsageError(str(error), fix=_RESIDUE_FIX) from error
    finally:
        connection.close()


def residue_document(found: GraphResidue) -> dict[str, Any]:
    """The JSON render: `GraphResidue` as it is, every group a mapping."""
    from dataclasses import asdict  # noqa: PLC0415

    return {"schema": _SCHEMA, **asdict(found)}


def _residue_text(document: Mapping[str, Any]) -> list[str]:
    kind = f" ({document['akind']})" if document["akind"] else ""
    groups = document["unresolved"]
    lines = [
        f"residue{kind}: {document['unresolved_sites']} unresolved of {document['sites']} "
        f"reference site(s), {document['quarantined']} quarantined row(s)"
    ]
    if groups:
        lines.append("  unresolved")
        lines.extend(
            f"    {g['akind']}  {g['name_norm']}  {g['sites']} site(s) in {g['docs']} "
            f"document(s)  {g['surface']!r}"
            for g in groups
        )
        if document["truncated"]:
            lines.append(f"    the first {len(groups)} groups; more names are unresolved")
    else:
        lines.append("  nothing unresolved")
    if document["quarantine"]:
        lines.append("  quarantined")
        lines.extend(
            f"    {g['code']}  {g['row_kind']}  {g['rows']} row(s) from {g['runs']} run(s), "
            f"generations {g['first_gen']}-{g['last_gen']}"
            for g in document["quarantine"]
        )
    else:
        lines.append("  nothing quarantined")
    return lines


def _review(
    parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO
) -> int:
    """`ow graph review`: the four review lists, weakest first, from one read snapshot."""
    _refuse_unserved(parsed, verb="ow graph review", fix="ow graph review")
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, [], parsed.corpus, verb="ow graph review")
    store = store_of(config, name, cwd=cwd)
    found = _reviewed(store, over_merge=bool(parsed.over_merge))
    document = review_document(found, corpus=name, qualify=len(corpora(config)) > 1)
    if parsed.render == "json":
        stdout.write(json.dumps(document, ensure_ascii=False) + "\n")
    else:
        stdout.write("\n".join(_review_text(document)) + "\n")
    return 0


def _reviewed(store: Path, *, over_merge: bool) -> Review:
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415
    from omniweave_core.store.review import review  # noqa: PLC0415

    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot():
            return review(connection, over_merge=over_merge)
    finally:
        connection.close()


def review_document(found: Review, *, corpus: str, qualify: bool) -> dict[str, Any]:
    """The JSON render: `Review` as it is, every cite qualified when two corpora exist."""
    from dataclasses import asdict  # noqa: PLC0415

    def cite(text: str) -> str:
        return f"{corpus}:{text}" if qualify else text

    document = {"schema": _SCHEMA, **asdict(found)}
    for row in document["closures"]:
        row["head"] = cite(row["head"])
    for row in document["entities"]:
        row["entity"] = cite(row["entity"])
    for row in document["mentions"]:
        row["entity"], row["cite"] = cite(row["entity"]), cite(row["cite"])
    for row in document["edges"]:
        row["src"], row["dst"], row["cite"] = cite(row["src"]), cite(row["dst"]), cite(row["cite"])
    for row in document["over_merges"] or ():
        row["head"] = cite(row["head"])
        for member in row["members"]:
            member["entity"] = cite(member["entity"])
            member["communities"] = [cite(c) for c in member["communities"]]
            member["witness"] = None if member["witness"] is None else cite(member["witness"])
        row["apart"] = [cite(a) for a in row["apart"]]
        witness = {m["entity"]: m["witness"] for m in row["members"]}
        sides = [witness[a] for a in row["apart"]]
        row["split"] = (
            f'ow graph split {row["head"]} --into {",".join(sides)} --reason "..."'
            if all(sides)
            else None
        )
    return document


def _review_text(document: Mapping[str, Any]) -> list[str]:
    from omniweave_core.model.enums import Trust  # noqa: PLC0415

    def named(trust: int) -> str:
        return Trust(trust).name.lower()

    def tainted(taint: int) -> str:
        return f", taint {taint}" if taint else ""

    lines = [
        f"review: {document['closures_total']} closure(s) resolved below extracted, "
        f"{document['entities_total']} entities tainted or overloaded, "
        f"{document['mentions_total']} mention(s), {document['edges_total']} edge(s)"
    ]
    sections: list[tuple[str, str, list[str]]] = [
        (
            "closures",
            "closures_total",
            [
                f"    {c['head']}  {c['title']} ({c['etype']})  {c['members']} members  "
                f"{named(c['resolution_trust'])}"
                for c in document["closures"]
            ],
        ),
        (
            "entities",
            "entities_total",
            [
                f"    {e['entity']}  {e['title']} ({e['etype']})  "
                + ("overloaded" if e["overloaded"] else f"trust {named(e['trust'])}")
                + tainted(e["taint"])
                for e in document["entities"]
            ],
        ),
        (
            "mentions",
            "mentions_total",
            [
                f"    m{m['mention']}  {m['entity']}  {m['cite']}  {m['surface']!r}  "
                f"{named(m['trust'])}{tainted(m['taint'])}"
                for m in document["mentions"]
            ],
        ),
        (
            "edges",
            "edges_total",
            [
                f"    g{g['edge']}  {g['src']} {g['relation']} {g['dst']}  {g['cite']}  "
                f"{named(g['trust'])}{tainted(g['taint'])}"
                for g in document["edges"]
            ],
        ),
    ]
    for title, total, rows in sections:
        if not rows:
            continue
        lines.extend([f"  {title}", *rows])
        if document[total] > len(rows):
            lines.append(f"    the first {len(rows)} of {document[total]}")
    if document["over_merges"] is not None:
        lines.extend(_over_merge_text(document))
    return lines


def _over_merge_text(document: Mapping[str, Any]) -> list[str]:
    suspects = document["over_merges"]
    if not suspects:
        return ["  over-merge: no closure's members fall apart"]
    lines = [f"  over-merge: {document['over_merges_total']} closure(s) whose members fall apart"]
    for row in suspects:
        lines.append(
            f"    {row['head']}  {row['title']} ({row['etype']})  {len(row['members'])} members in "
            f"{row['doc_count']} document(s), reaching {row['communities']} top-level communities"
        )
        lines.extend(
            f"      {m['entity']}  {' '.join(m['communities']) or 'no neighbours'}  "
            f"witness {m['witness'] or 'none alone'}"
            for m in row["members"]
        )
        if row["split"]:
            lines.append(f"      try: {row['split']}")
    if document["over_merges_total"] > len(suspects):
        lines.append(f"    the first {len(suspects)} of {document['over_merges_total']}")
    return lines


def _doctor(
    parsed: argparse.Namespace, *, env: Mapping[str, str], cwd: Path, stdout: TextIO
) -> int:
    """`ow graph doctor`: the eleven checks, or those `--check` names; exit 1 when one fails.

    `--quiet` is served, as `ow doctor` serves it: nothing printed, the exit code alone.
    """
    if parsed.render in ("jsonl", "rows"):
        raise UsageError(
            f"--render {parsed.render} is parsed and not served by ow graph doctor", fix=_DOCTOR_FIX
        )
    checks = None
    if parsed.check is not None:
        checks = [one.strip() for one in str(parsed.check).split(",") if one.strip()]
        if not checks:
            raise UsageError("--check names no check", fix=_DOCTOR_FIX)
    explicit = Path(parsed.config) if parsed.config else None
    config = load(cwd=cwd, env=env, explicit=explicit)
    name = corpus_for(config, [], parsed.corpus, verb="ow graph doctor")
    report = _diagnosed(store_of(config, name, cwd=cwd), checks)
    if not parsed.quiet:
        if parsed.render == "json":
            stdout.write(json.dumps(doctor_document(report), ensure_ascii=False) + "\n")
        else:
            stdout.write("\n".join(_doctor_text(report)) + "\n")
    return 1 if report.failed else 0


def _diagnosed(store: Path, checks: Sequence[str] | None) -> GraphDoctorReport:
    from omniweave_core.clock import SystemClock  # noqa: PLC0415 -- a usage error never pays
    from omniweave_core.errors import NotFoundError  # noqa: PLC0415
    from omniweave_core.store import reader as store_reader  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    from omniweave.graph.doctor import doctor  # noqa: PLC0415

    if not store.exists():
        raise NotFoundError(f"no store at {store}", fix="ow add <source> first")
    connection = store_sqlite.connect_readonly(store)
    try:
        reader = store_reader.SqliteReader(connection, now_ns=SystemClock().wall_ns())
        with reader.snapshot():
            try:
                return doctor(connection, checks=checks)
            except ValueError as error:
                raise UsageError(str(error), fix=_DOCTOR_FIX) from error
    finally:
        connection.close()


def doctor_document(report: GraphDoctorReport) -> dict[str, Any]:
    """The JSON render: the three tuples, each finding a mapping."""
    from dataclasses import asdict  # noqa: PLC0415

    return {"schema": _SCHEMA, **asdict(report)}


def _doctor_text(report: GraphDoctorReport) -> list[str]:
    lines: list[str] = []
    for label, group in (("FAIL", report.failed), ("warn", report.warned), ("ok", report.ok)):
        for one in group:
            lines.append(f"{label:4} {one.check}: {one.detail}")
            if one.fix:
                lines.append(f"     fix: {one.fix}")
    ran = len(report.ok) + len(report.warned) + len(report.failed)
    lines.append(
        f"graph doctor: {'fails' if report.failed else 'passes'} the {ran} check(s) it ran"
    )
    return lines


_VERBS: Final = {
    _WHY: _why,
    _MERGES: _merges,
    _MERGE: _merge,
    _SPLIT: _split,
    _RESIDUE: _residue,
    _REVIEW: _review,
    _DOCTOR: _doctor,
}
"""Each Action's handler; `graph.locate` is the default, as the first verb built."""


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
