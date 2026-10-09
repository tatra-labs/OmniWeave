"""`op.lexicon`'s store half: the corpus's names as an artefact, and who read which one. **D683.**

06-structure-extraction.md section 3.7. `op.lexicon` reads `entity_alias(name_norm)` -- the index
`entity_alias_name` exists for exactly this -- filters it, and writes the result as an artefact
`derive.entity.gazetteer` builds its automaton from. This module is everything that touches the
store: the read and its filters (`build`), the artefact's bytes (`owgraph-lexicon/1`), the pointer
to the current one (`index_state.lexicon`), the `dep` row each gazetteer row records, and the
query that finds the rows a moved lexicon invalidates. `omniweave.run.operators.lexicon` runs it.

    {"t":"lexicon","format":"owgraph-lexicon/1","names":2,"truncated":false}
    {"t":"name","name":"acme_holdings_ltd","entities":[{"etype":"org","key":"acme_holdings_ltd",
     "title":"Acme Holdings Ltd."}]}
    {"t":"name","name":"beta_corp","entities":[...]}

## Rulings (the ledger's D683)

1. **Only corpus-scoped, live entities.** The gazetteer binds a hit by proposing the entity again
   (06:628), and a `document`-scoped proposal is scoped to the document it is made in: a hit on
   another document's defined term would mint a new entity there, where 06:1216 allows none. So the
   lexicon is `entity.scope = 0 AND entity.state = 0`; an overloaded entity (`state = 1`) is not a
   target either.
2. **`doc_count` is counted, not read.** `entity_alias.doc_count` is written as 1 and never
   maintained, because the sink leaves every count to GR16's recount (`graph.py` `_roll_up`). The
   lexicon counts a name's documents itself: the live documents holding a live mention of an entity
   carrying it -- **excluding the gazetteer's own mentions**. A count that included them would feed
   the lexicon from its own output: a name in half the corpus's text would be dropped, its mentions
   replaced away, re-admitted, and so on, one flip per run. Without them, nothing the gazetteer
   writes can move the lexicon, so a rebuild after its drain is a fixed point.
3. **The share rule needs two documents.** 06:1203 drops a name occurring in more than
   `LEXICON_MAX_DOC_SHARE` of documents as a template word. In a one-document corpus every name is
   in all of it; a name seen in one document is never a template across a corpus. So the rule fires
   at `docs >= 2`. **It measures definitions, not text** (ruling 2): a footer word defined once and
   printed everywhere passes it. Measuring occurrences without the feedback needs the gazetteer to
   report the names it saw but did not emit, which is owed.
4. **The untrusted rule is per entity.** `(taint & UNTRUSTED_SOURCE) AND doc_count = 1` drops that
   entity's claim to the name when every alias row of the pair carries the bit -- one untainted
   observation vouches for it -- and the name's counted documents are one.
5. **The cap is a flag on the artefact, not a `diag` row.** 06:1213's `Diag(OW_RESOURCE_LIMIT)` has
   no document to hang off (`diag.doc_ord` is NOT NULL), so the header says `truncated` and the run
   report prints it.
6. **The `dep` row is upserted.** `dep_statements` writes `INSERT OR IGNORE`, right for a row whose
   deps are written once. A gazetteer row is re-opened in place when the lexicon moves (same
   `work.id`), so its `dep` must take the new digest, or it would be stale forever.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.model.enums import Taint
from omniweave_core.store import NO_JOB_DOCS

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DEP_KEY",
    "DEP_KIND",
    "EMPTY",
    "GAZETTEER",
    "LEXICON_FORMAT",
    "LEXICON_MAX_DOC_SHARE",
    "LEXICON_MIN_LEN",
    "MAX_LEXICON_ENTRIES",
    "STATE_KEY",
    "Built",
    "build",
    "current",
    "frame",
    "record_dep",
    "set_current",
    "stale",
]

LEXICON_MIN_LEN: Final = 4
"""06:1198. The minimum `LENGTH(name_norm)`; below it a surface match is noise."""
LEXICON_MAX_DOC_SHARE: Final = 0.5
"""06:1203. A name in more than this share of the corpus's documents is a template word."""
MAX_LEXICON_ENTRIES: Final = 200_000
"""06:1209. The automaton's measured ceiling: ~3.6M goto nodes, ~600 MB of CPython dicts."""
LEXICON_FORMAT: Final = "owgraph-lexicon/1"
"""The artefact's format; `omniweave_graph.gazetteer.rules` decodes it."""
GAZETTEER: Final = "derive.entity.gazetteer"
"""The Pass whose mentions are not counted (ruling 2)."""
STATE_KEY: Final = "lexicon"
"""`index_state.lexicon`: the current artefact's CAS digest, hex. Absent until the first build."""
DEP_KIND: Final = "name"
"""06:1189: *"`dep(kind='name', digest=<the lexicon artefact digest>)`"*."""
DEP_KEY: Final = "lexicon"
"""The key 06:1189 does not print. An anchor's `name` key is always `akind:name_norm`, so a key
without a colon can never collide with one."""


@dataclass(frozen=True, slots=True)
class Built:
    """One build: the artefact and what the filters did."""

    body: bytes
    names: int
    truncated: bool
    candidates: int
    """Distinct names among live corpus aliases of `LEXICON_MIN_LEN` or more."""
    dropped: Mapping[str, int] = field(default_factory=dict)
    """`no_evidence`, `template`, `untrusted` -> names (or, for `untrusted`, entity claims)."""


def _artefact(names: Mapping[str, list[dict[str, str]]], *, truncated: bool) -> bytes:
    head = {"t": "lexicon", "format": LEXICON_FORMAT, "names": len(names), "truncated": truncated}
    lines = [head] + [{"t": "name", "name": n, "entities": names[n]} for n in sorted(names)]
    return "".join(
        json.dumps(line, separators=(",", ":"), ensure_ascii=False, sort_keys=True) + "\n"
        for line in lines
    ).encode("utf-8")


EMPTY: Final = _artefact({}, truncated=False)
"""The lexicon before the first build: no name. A view is never handed no lexicon at all, so every
gazetteer row records a digest, and the first build that finds a name moves it."""

_ALIASES_SQL: Final = """
SELECT a.name_norm, e.etype, e.key, e.title, min(a.taint & :untrusted)
  FROM entity_alias AS a JOIN entity AS e ON e.entity_id = a.entity_id
 WHERE e.scope = 0 AND e.state = 0 AND length(a.name_norm) >= :min_len
 GROUP BY a.name_norm, e.entity_id
"""
_DOCS_SQL: Final = """
SELECT a.name_norm, count(DISTINCT b.doc_ord)
  FROM entity_alias AS a
  JOIN entity AS e ON e.entity_id = a.entity_id AND e.scope = 0 AND e.state = 0
  JOIN mention AS m ON m.entity_id = e.entity_id AND m.state = 0
  JOIN derive_run AS r ON r.run_id = m.run_id AND r.origin_operator <> :self
  JOIN block AS b ON b.block_id = m.block_id AND b.state = 0
 WHERE length(a.name_norm) >= :min_len
 GROUP BY a.name_norm
"""
_LIVE_DOCS_SQL: Final = (
    f"SELECT count(*) FROM doc WHERE {NO_JOB_DOCS} AND status IN ('ok', 'partial')"  # noqa: S608
    " AND json_extract(x, '$.ow.retired') IS NULL"
)
_CURRENT_SQL: Final = "SELECT v FROM index_state WHERE k = :k"
_SET_CURRENT_SQL: Final = (
    "INSERT INTO index_state(k, v) VALUES(:k, :v) ON CONFLICT(k) DO UPDATE SET v = excluded.v"
)
_RECORD_DEP_SQL: Final = """
INSERT INTO dep(dependent_id, kind, key, digest) VALUES(:id, :kind, :key, :digest)
ON CONFLICT(dependent_id, kind, key) DO UPDATE SET digest = excluded.digest
"""
_STALE_SQL: Final = """
SELECT w.id, w.cost_class FROM dep AS d JOIN work AS w ON w.id = d.dependent_id
 WHERE d.kind = :kind AND d.key = :key AND d.digest <> :digest
 ORDER BY w.id
"""
"""07:2954's invalidation query for a delta of one `(kind, key)`, on `dep_reverse(kind, key)`."""


def build(connection: Any) -> Built:
    """Read the corpus's names and filter them (rulings 1-5). Deterministic: one store, one body."""
    params = {"untrusted": int(Taint.UNTRUSTED_SOURCE), "min_len": LEXICON_MIN_LEN}
    pairs: dict[str, list[tuple[str, str, str, bool]]] = defaultdict(list)
    for name, etype, key, title, untrusted in connection.execute(_ALIASES_SQL, params).fetchall():
        pairs[str(name)].append((str(etype), str(key), str(title or key), bool(untrusted)))
    docs = {
        str(name): int(count)
        for name, count in connection.execute(
            _DOCS_SQL, {"self": GAZETTEER, "min_len": LEXICON_MIN_LEN}
        ).fetchall()
    }
    live = int(connection.execute(_LIVE_DOCS_SQL).fetchone()[0])
    dropped: dict[str, int] = defaultdict(int)
    kept: dict[str, list[dict[str, str]]] = {}
    for name, found in pairs.items():
        seen = docs.get(name, 0)
        if seen == 0:
            dropped["no_evidence"] += 1
            continue
        if seen >= 2 and seen > LEXICON_MAX_DOC_SHARE * live:  # noqa: PLR2004 -- ruling 3
            dropped["template"] += 1
            continue
        targets = sorted({(e, k, t) for e, k, t, bad in found if not (bad and seen == 1)})
        dropped["untrusted"] += len({(e, k) for e, k, _t, bad in found if bad and seen == 1})
        if targets:
            kept[name] = [{"etype": e, "key": k, "title": t} for e, k, t in targets]
    truncated = len(kept) > MAX_LEXICON_ENTRIES
    if truncated:
        ranked = sorted(kept, key=lambda n: (-docs[n], -len(n), n))[:MAX_LEXICON_ENTRIES]
        kept = {n: kept[n] for n in ranked}
    return Built(
        body=_artefact(kept, truncated=truncated),
        names=len(kept),
        truncated=truncated,
        candidates=len(pairs),
        dropped={k: v for k, v in sorted(dropped.items()) if v},
    )


def current(connection: Any) -> str | None:
    """The current artefact's digest, or `None` before the first build."""
    row = connection.execute(_CURRENT_SQL, {"k": STATE_KEY}).fetchone()
    return None if row is None else str(row[0])


def set_current(connection: Any, digest: str) -> None:
    connection.execute(_SET_CURRENT_SQL, {"k": STATE_KEY, "v": digest})


def frame(digest: str) -> bytes:
    """The line the host puts in front of a gazetteer view: which artefact to read (D683)."""
    return json.dumps({"t": "lexicon", "blob": digest}, separators=(",", ":")).encode() + b"\n"


def record_dep(connection: Any, work_id: int, digest: str) -> None:
    """Ruling 6: the lexicon this row's committed answer read, replacing what it read before."""
    connection.execute(
        _RECORD_DEP_SQL, {"id": work_id, "kind": DEP_KIND, "key": DEP_KEY, "digest": digest}
    )


def stale(connection: Any, digest: str) -> dict[int, str]:
    """`work.id` -> `cost_class` for every row that read a lexicon other than `digest`."""
    rows = connection.execute(
        _STALE_SQL, {"kind": DEP_KIND, "key": DEP_KEY, "digest": digest}
    ).fetchall()
    return {int(row[0]): str(row[1]) for row in rows}
