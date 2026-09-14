"""G19's indexer and its rebuilder: two stores over one corpus, one built step by step.

`tools/gate_incremental.py` shipped at P2 saying what it is not -- *"this file is the harness and
the comparator, and it is deliberately NOT the fixture, the indexer or the rebuilder"* -- and
listed the absent pieces with the phase that owns them. `fixtures/gen/gen_incremental.py` is the
fixture. **This file is the indexer and the rebuilder**, and it is the last of the four.

## What the two sides are

`07-store-and-retrieval.md:2971` gives the whole mechanism in one sentence: G19 *"builds a
300-document fixture through 40 scripted mutations and diffs the `.owdoc` exports against a full
rebuild into a second store"*. So:

* **the incremental side** opens one store, ingests the initial roster, and then applies each
  mutation by re-parsing ONLY what changed -- which is the property under test. What "changed"
  means is the digest rung of 05-ingest-and-routing.md section 1.4's change-detection ladder: a
  document whose bytes hash to what the previous step's did is not re-parsed, and a `touch` step
  is the fixture's way of asking whether that is true.
* **the full side** opens a fresh store for the roster at one step and ingests every document
  once. It is a rebuild in the ordinary sense: no history, no carried cites, one generation.

Both export with `omniweave_core.store.portable.export_portable`, which becomes
`ow store export --portable` at P7 (D25's standing pattern, the same one `tools/p2_demo.py`
records for four other verbs).

## Three identities this file fixes, and why each has to be fixed here

A store assigns three numbers that are functions of the ORDER work arrived in, and G19 compares two
stores that did the work in different orders. Two of the three can be made functions of the corpus
instead, and this file does that rather than teaching the comparator to ignore them:

**`doc_key`.** A store would use `sha256(normalized bytes)[:16]` (`0001_init.sql:150`); this
file uses `blake2b(uri)[:16]`. An archive is named `{doc_key}.owdoc`, so a key that moved when the
bytes moved would make an EDIT look like a delete plus an add on one side and a re-parse on the
other -- two "differences", neither of them the divergence the gate exists to find.

**`doc_ord`.** A store would allocate it in arrival order; this file uses
`1 + blake2b(uri)[:4]`. `doc_ord` is the `d7` in every `cite` and every `cite` is exported, so an
ingest order would reach the diff as a difference in every block of every document.

**`gen`.** Left alone, because it IS a count of parses and the two sides have parsed different
numbers of times. `gate_incremental.py`'s `PROVENANCE` is where that is dealt with, and it is dealt
with by being reported rather than by being made to agree.

The `doc_key` substitution is not this file's invention: `tools/p2_demo.py`'s clause 5 made the same
one first, and its docstring records the conflict behind it -- `0001_init.sql:150` makes the key a
content hash while `03:1316-1370`'s worked example re-parses the same `doc_ord` at `gen = 2` after
the source changed, and both cannot hold.

`doc_ord` collisions are refused rather than tolerated: the space is 2^32, the corpus is ~320
documents, and `test_fixture_incremental.py` asserts no two documents of any step collide, so a
collision is a red test rather than a `UNIQUE` violation in the middle of a gate run.

## Deletion is `ON DELETE CASCADE`, and that is the store's own answer

There is no `Store` method that removes a document: the boundary is four methods and none of them
deletes. `05-ingest-and-routing.md` names the verb (`ow store rm --doc d7`) and P7 owns it, so what
runs here is the statement that verb will issue -- `DELETE FROM doc WHERE doc_key = ?` -- against a
schema that already cascades: `0001_init.sql` declares `doc_ord INTEGER NOT NULL REFERENCES
doc(doc_ord) ON DELETE CASCADE` on `page`, `part`, `asset` and `block`, and 08-runtime.md section
1.2 names exactly that mechanism -- *"Rows leave the table only through compaction or `ON DELETE
CASCADE`"*.

## `sqlite3` here, and the ban it is outside of

`sqlite3` is banned to `omniweave_core.store` by ruff's `TID251`, scoped to `packages/*/src/**`.
`tools/` is outside that scope and `tools/p2_demo.py` takes the same escape in the open and for the
same kind of reason: the producer row every block is stamped with is resolved by the RUNNER before
a parse runs (`store/doc.py` says so in as many words), and the delete above is a verb that does
not exist yet. Both are host-side statements with no store-boundary method to reach them through.

Run it:

    uv run python tools/incremental_index.py --root DIR             # both sides, all 40 steps
    uv run python tools/incremental_index.py --root DIR --steps 5   # the first five

Specified in 16-roadmap.md:550, 07-store-and-retrieval.md:2971 and :3092, 08-runtime.md:1858,
and 05-ingest-and-routing.md section 1.4.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import shutil
import sqlite3  # noqa: TID251 -- not library code; see the module docstring's last section.
import sys
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from omniweave_core.blobs import BlobStore
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.portable import export_portable

__all__ = [
    "CODE_FINGERPRINT_SEED",
    "NOW_NS",
    "Incremental",
    "StepReport",
    "code_fingerprint",
    "doc_ord",
    "export_store",
    "fixture",
    "main",
    "rebuild",
    "stub",
]

NOW_NS: Final = 0
"""The migration clock. Zero, because a fixture build must not put a wall time in a store.

`migrate.apply_pending(connection, now_ns=...)` stamps `schema_migration.applied_ns`, which is not
exported and therefore cannot reach the diff -- but a build that read a clock would be a build that
`13-quality.md:586-589`'s regime forbids, and the regime is about the generator AND everything that
consumes it. `tools/p2_demo.py` uses the same constant for the same reason."""

CODE_FINGERPRINT_SEED: Final = "omniweave/incremental_index/1"
"""What a synthetic driver version hashes from. See `code_fingerprint`."""

_REPO: Final = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path) -> ModuleType:
    """A script loaded by path, as `tools/p2_demo.py` loads its two.

    `fixtures/` and `tools/` are not distributions, so there is nothing to import;
    `importlib.import_module` is banned outside `host/`, and a `sys.path` mutation leaks into
    everything loaded afterwards.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover -- a broken checkout.
        message = f"cannot load {path}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture() -> ModuleType:
    """`fixtures/gen/gen_incremental.py` -- the corpus and the script."""
    return _load("omniweave_fixture_incremental", _REPO / "fixtures" / "gen" / "gen_incremental.py")


def stub() -> ModuleType:
    """`tools/p2_stub_parse.py` -- the one parser in this tree that needs no driver system."""
    return _load("omniweave_p2_stub_parse", _REPO / "tools" / "p2_stub_parse.py")


# ---------------------------------------------------------------------------
# 1. The three identities
# ---------------------------------------------------------------------------


def doc_ord(uri: str) -> int:
    """A document's `doc_ord`, from its uri and nothing else. The module docstring's second row.

    `1 +` because `doc_ord` is an `INTEGER PRIMARY KEY` and a zero would be legal but would make
    `d0#1` the cite of whichever document happened to hash to it -- a cite that reads like an
    unset value is a cite somebody will eventually treat as one. Four bytes rather than sixteen
    because `doc_ord` is a SQLite integer and a 128-bit key does not fit one.
    """
    return 1 + int.from_bytes(hashlib.blake2b(uri.encode("utf-8"), digest_size=4).digest(), "big")


def code_fingerprint(op_version: int) -> str:
    """A 64-hex `producer.code_fingerprint` for one synthetic driver version.

    A `driver_version` mutation is 06-structure-extraction.md:2405's *"1 driver-version re-parse"*,
    and 08-runtime.md section 4.8 makes a driver upgrade an invalidation of everything that driver
    produced. What changes on an upgrade is the code, so what this fixture moves is the
    fingerprint -- derived from the version rather than chosen, so that two builds at the same
    version stamp the same producer and two builds at different versions cannot.
    """
    return hashlib.sha256(f"{CODE_FINGERPRINT_SEED}/{op_version}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# 2. A store, and the four statements this file issues against one
# ---------------------------------------------------------------------------

_PRODUCER_SQL: Final = """
INSERT INTO producer(operator, op_version, code_fingerprint, options_digest)
VALUES(?, ?, ?, X'00')
ON CONFLICT DO NOTHING
"""
"""The producer row every block is stamped with, inserted once per `(operator, op_version)`.

`ON CONFLICT DO NOTHING` because a `driver_version` mutation re-parses the whole corpus at a new
version and every later step keeps using it: the row is wanted once and asked for many times.
`store/doc.py`'s constructor docstring is why this is raw SQL and not a twelfth sink method --
*"the runner resolved the `producer` row before the parse ran"*."""

_PRODUCER_ID_SQL: Final = "SELECT producer_id FROM producer WHERE operator = ? AND op_version = ?"

_DELETE_DOC_SQL: Final = "DELETE FROM doc WHERE doc_key = ?"
"""`ow store rm --doc`, as the statement it will be. See the module docstring's deletion section."""

_FOREIGN_KEYS_SQL: Final = "PRAGMA foreign_keys = ON"
"""**Without this the delete does not cascade**, and that is a SQLite default, not a schema bug.

`foreign_keys` is OFF by default in SQLite and is per-connection, so `0001_init.sql`'s
`ON DELETE CASCADE` declarations are inert unless a connection asks for them. A delete issued
without it would remove the `doc` row and orphan every `block`, `page`, `part` and `asset` beneath
it -- and `export_portable` reads `doc`, so the archive would vanish and the orphans would not,
which is a corrupt store that passes the very gate that exists to find corruption.
"""


def _connect(path: Path) -> sqlite3.Connection:
    """A connection with `foreign_keys` on. Every connection this file opens goes through here."""
    connection = ow.connect(path)
    connection.execute(_FOREIGN_KEYS_SQL)
    return connection


def _open_store(root: Path) -> Path:
    """Create `<root>/index.owstore`, migrated, with its CAS beside it. Returns the store path."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "cas").mkdir(exist_ok=True)
    path = root / "index.owstore"
    connection = _connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        connection.commit()
    finally:
        connection.close()
    return path


def _producer_id(path: Path, operator: str, op_version: int) -> int:
    """Insert-or-select the producer row for one driver version, and return its surrogate id."""
    connection = _connect(path)
    try:
        connection.execute(_PRODUCER_SQL, (operator, op_version, code_fingerprint(op_version)))
        connection.commit()
        row = connection.execute(_PRODUCER_ID_SQL, (operator, op_version)).fetchone()
    finally:
        connection.close()
    if row is None:  # pragma: no cover -- the INSERT above cannot leave nothing.
        message = f"no producer row for {operator} v{op_version}"
        raise RuntimeError(message)
    return int(row[0])


def export_store(path: Path, cas: Path, directory: Path) -> int:
    """Export every document into a FRESH `directory` and return how many archives it holds.

    Fresh, and that is load-bearing: `export_portable` writes one archive per document and removes
    none, so exporting a later step over an earlier step's directory would leave a deleted
    document's archive behind. The gate would then see it on the incremental side and not on the
    full side and report a difference that the export produced rather than the build.
    """
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    connection = ow.connect_readonly(path)
    try:
        result = export_portable(connection, directory, blobs=BlobStore(cas))
    finally:
        connection.close()
    if result.skipped:  # pragma: no cover -- a document with no root block.
        message = f"export skipped {len(result.skipped)} document(s): {result.skipped[:3]}"
        raise RuntimeError(message)
    return len(result.artefacts)


# ---------------------------------------------------------------------------
# 3. Ingest
# ---------------------------------------------------------------------------


def _ingest_many(
    path: Path,
    cas: Path,
    documents: Sequence[Any],
    *,
    producer_id: int,
    parser: ModuleType,
    corpus: ModuleType,
    workspace: Path,
) -> int:
    """Parse and store every document in `documents`, one `DocSink` and one transaction each.

    One sink per document because `begin_doc` *"is called once, first"* (03:576) and a sink is the
    thing that call belongs to. One `StoreThread` for the whole batch because INV-17 makes it *"the
    only holder of a `Connection` in a process"* and opening one per document would be 300 threads
    to write 300 documents.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    with ow.StoreThread(lambda: _connect(path)) as thread:
        for document in documents:
            source = workspace / f"{doc_ord(document.uri)}.pdf"
            source.write_bytes(corpus.document_bytes(document))
            sink = DocSink(
                thread,
                producer_id=producer_id,
                origin_operator=str(parser.OPERATOR),
                origin_driver=str(parser.DRIVER_ID),
                driver_schema_v=int(parser.DRIVER_SCHEMA_V),
                blobs=BlobStore(cas),
            )
            parser.ingest(
                sink,
                pdf=source,
                uri=document.uri,
                doc_ord=doc_ord(document.uri),
                doc_key=corpus.doc_key(document.uri),
            )
            source.unlink()
    return len(documents)


def _delete_many(path: Path, uris: Iterable[str], *, corpus: ModuleType) -> int:
    """`DELETE FROM doc` for each uri, in one transaction, with the cascade switched on."""
    keys = [corpus.doc_key(uri) for uri in uris]
    if not keys:
        return 0
    connection = _connect(path)
    try:
        removed = sum(connection.execute(_DELETE_DOC_SQL, (key,)).rowcount for key in keys)
        connection.commit()
    finally:
        connection.close()
    return removed


# ---------------------------------------------------------------------------
# 4. The incremental side
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepReport:
    """What one mutation cost the incremental store. The gate prints these; nothing branches
    on them.

    `reparsed` is the number that makes a `touch` step meaningful: the step changes a document's
    mtime and nothing else, so a correct incremental build reports zero and a build that quietly
    rebuilds everything reports the whole roster.
    """

    index: int
    kind: str
    name: str
    added: int = 0
    changed: int = 0
    removed: int = 0
    seconds: float = 0.0

    @property
    def reparsed(self) -> int:
        return self.added + self.changed


@dataclass
class Incremental:
    """One store, carried forward through the script. The side under test.

    Holds the previous step's `{uri: sha256}` because that is what the change detection compares
    against -- 05-ingest-and-routing.md section 1.4's ladder, at the rung a synthetic corpus can
    honestly reach. The fixture has no mtimes worth trusting and no connector cursors, so the
    `stat_fresh` rung above it would be a test of a `Path.stat()` this build performed itself.
    """

    root: Path
    corpus: ModuleType
    parser: ModuleType
    store: Path = field(init=False)
    cas: Path = field(init=False)
    digests: dict[str, str] = field(default_factory=dict, init=False)
    op_version: int = field(default=1, init=False)
    steps: list[StepReport] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.store = _open_store(self.root)
        self.cas = self.root / "cas"

    def start(self) -> StepReport:
        """Ingest the initial roster. Reported as step -1, so the script's steps stay 0-based."""
        began = time.perf_counter()
        documents = self.corpus.corpus_at(0)
        self._ingest(documents)
        self.digests = {d.uri: self._digest(d) for d in documents}
        report = StepReport(
            index=-1,
            kind="initial",
            name="initial",
            added=len(documents),
            seconds=time.perf_counter() - began,
        )
        self.steps.append(report)
        return report

    def step(self, index: int) -> StepReport:
        """Apply mutation `index` to the store, re-parsing only what changed.

        A `driver_version` mutation is the one kind that re-parses everything: the producer moves,
        and 08-runtime.md section 4.8 makes a driver upgrade an invalidation of everything that
        driver produced. Every other kind is decided by the digest comparison, which is what makes
        `touch` a real test rather than a no-op the script happens to contain.
        """
        began = time.perf_counter()
        mutation = self.corpus.SCRIPT[index]
        documents = {d.uri: d for d in self.corpus.corpus_at(index + 1)}
        fresh = {uri: self._digest(document) for uri, document in documents.items()}

        removed = sorted(set(self.digests) - set(fresh))
        if mutation.kind == "driver_version":
            self.op_version = self.corpus.driver_version_at(index + 1)
            reparse = sorted(documents)
            added, changed = (), tuple(reparse)
        else:
            added = tuple(sorted(set(fresh) - set(self.digests)))
            both = set(fresh) & set(self.digests)
            changed = tuple(sorted(u for u in both if fresh[u] != self.digests[u]))
            reparse = [*added, *changed]

        _delete_many(self.store, removed, corpus=self.corpus)
        self._ingest([documents[uri] for uri in reparse])
        self.digests = fresh

        report = StepReport(
            index=index,
            kind=mutation.kind,
            name=mutation.name,
            added=len(added),
            changed=len(changed),
            removed=len(removed),
            seconds=time.perf_counter() - began,
        )
        self.steps.append(report)
        return report

    def export(self, directory: Path) -> int:
        """Export the store as it stands. See `export_store` for why the directory is cleared."""
        return export_store(self.store, self.cas, directory)

    def _digest(self, document: Any) -> str:
        return hashlib.sha256(self.corpus.document_bytes(document)).hexdigest()

    def _ingest(self, documents: Sequence[Any]) -> None:
        if not documents:
            return
        _ingest_many(
            self.store,
            self.cas,
            documents,
            producer_id=_producer_id(self.store, str(self.parser.OPERATOR), self.op_version),
            parser=self.parser,
            corpus=self.corpus,
            workspace=self.root / "work",
        )


# ---------------------------------------------------------------------------
# 5. The full side
# ---------------------------------------------------------------------------


def rebuild(root: Path, step: int, *, corpus: ModuleType, parser: ModuleType) -> Path:
    """A fresh store holding the roster at `step`, exported. Returns the export directory.

    No history: one generation, one producer, every document parsed once. That is what makes it a
    rebuild and what makes the comparison worth running -- an incremental store that agreed with a
    second incremental store would be a store that reproduced its own bugs.

    The root is cleared first, so a rebuild at step 20 cannot see a rebuild at step 10.
    """
    if root.exists():
        shutil.rmtree(root)
    store = _open_store(root)
    documents = corpus.corpus_at(step)
    op_version = corpus.driver_version_at(step)
    _ingest_many(
        store,
        root / "cas",
        documents,
        producer_id=_producer_id(store, str(parser.OPERATOR), op_version),
        parser=parser,
        corpus=corpus,
        workspace=root / "work",
    )
    exports = root / "exports"
    export_store(store, root / "cas", exports)
    return exports


# ---------------------------------------------------------------------------
# 6. Entry point
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incremental_index.py",
        description="Build G19's two stores over the incremental corpus (16-roadmap.md:550).",
    )
    parser.add_argument("--root", type=Path, required=True, help="working directory")
    parser.add_argument("--steps", type=int, default=None, help="how many mutations to apply")
    return parser


def main(argv: list[str] | None = None) -> int:
    """`python tools/incremental_index.py --root DIR [--steps N]`. Builds both sides, no diff.

    The diff is `tools/gate_incremental.py`'s; this entry point exists so the two builds can be
    run and inspected by hand, which is what a person debugging a divergence does first.
    """
    args = _parser().parse_args(argv)
    corpus, parser = fixture(), stub()
    upto = corpus.MUTATIONS if args.steps is None else args.steps
    if not 0 <= upto <= corpus.MUTATIONS:
        sys.stderr.write(f"incremental_index.py: --steps must be in [0, {corpus.MUTATIONS}]\n")
        return 2

    root: Path = args.root
    began = time.perf_counter()
    side = Incremental(root=root / "incremental", corpus=corpus, parser=parser)
    side.start()
    for index in range(upto):
        report = side.step(index)
        sys.stdout.write(
            f"  {report.index:>3} {report.name:<24} +{report.added} ~{report.changed} "
            f"-{report.removed}  {report.seconds * 1000:.0f} ms\n"
        )
    incremental = side.export(root / "incremental" / "exports")
    full = rebuild(root / "full", upto, corpus=corpus, parser=parser)

    sys.stdout.write(f"steps        {upto}\n")
    exports = root / "incremental" / "exports"
    sys.stdout.write(f"incremental  {incremental} archives in {exports}\n")
    sys.stdout.write(f"full         {len(list(full.glob('*.owdoc')))} archives in {full}\n")
    sys.stdout.write(f"seconds      {time.perf_counter() - began:.1f}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover -- the script path.
    raise SystemExit(main())
