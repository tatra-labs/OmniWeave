"""G19's corpus, its script, and one real convergence run over a corpus small enough to be fast.

`fixtures/gen/gen_incremental.py` is W4.10's fixture and `tools/incremental_index.py` is its
indexer and rebuilder. This file tests both, and it is split by what each half can afford:

* **the corpus and the script** are pure functions of one seed, so every property of them --
  the two numbers the register owns, the mutation mix, `plan.toml`'s agreement with `SCRIPT`, the
  pin in `EXPECTED.sha256`, and the determinism regime 13-quality.md:586-589 imposes -- is checked
  here in milliseconds.
* **the convergence itself** is checked end to end over EIGHT documents and four mutations. The
  shipped gate runs 300 and 40 and measures ~130 s; a unit suite that paid that is a unit suite
  people learn to skip, and the property under test does not need 300 documents to be true or
  false. What 300 buys is the chance of finding a case eight will not, and that is G19's job in
  CI rather than this file's.

**Nothing here imports either module.** Both are scripts under `fixtures/` and `tools/`, neither
is a distribution, and `importlib.import_module` is banned outside `host/` -- so they are loaded
by path, which is the mechanism `test_gate_crash.py` and `tools/p2_demo.py` already use.

Specified in 16-roadmap.md:550, 01-principles.md:506, 06-structure-extraction.md:2405,
07-store-and-retrieval.md:2971, 12-performance.md:1519 and 13-quality.md:586-589.
"""

from __future__ import annotations

import ast
import collections
import dataclasses
import hashlib
import importlib.util
import sys
import tomllib
import types
from pathlib import Path
from typing import Any

import pytest


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO = _repo_root(Path(__file__).resolve())
GENERATOR = REPO / "fixtures" / "gen" / "gen_incremental.py"
INDEXER = REPO / "tools" / "incremental_index.py"
PLAN = REPO / "fixtures" / "incremental" / "plan.toml"
PINS = REPO / "fixtures" / "gen" / "EXPECTED.sha256"
REGISTER = REPO / "tools" / "gates.toml"
GATE = REPO / "tools" / "gate_incremental.py"


def _load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def corpus() -> types.ModuleType:
    return _load("ow_test_gen_incremental", GENERATOR)


@pytest.fixture(scope="session")
def indexer() -> types.ModuleType:
    return _load("ow_test_incremental_index", INDEXER)


@pytest.fixture(scope="session")
def gate() -> types.ModuleType:
    return _load("ow_test_gate_incremental_for_fixture", GATE)


# ---------------------------------------------------------------------------
# 1. The two numbers, and who owns them
# ---------------------------------------------------------------------------


def test_the_generators_two_numbers_are_the_registers(corpus: types.ModuleType) -> None:
    """01-principles.md:506 makes `tools/gates.toml`'s G19 row the owner of both.

    The generator transcribes them, on `gate_incremental.py`'s own rule for the same pair --
    *"a harness that carried its own copy would let the two drift"* -- so the copy is checked
    here rather than trusted. Three files now hold these numbers and this is the only place all
    three meet.
    """
    row = next(
        entry
        for entry in tomllib.loads(REGISTER.read_text("utf-8"))["gate"]
        if entry["id"] == "G19"
    )
    assert f"{corpus.DOCUMENTS} docs" in row["assertion"]
    assert f"{corpus.MUTATIONS} mutations" in row["assertion"]
    assert len(corpus.SCRIPT) == corpus.MUTATIONS


def test_the_committed_plan_is_what_the_generator_produces(corpus: types.ModuleType) -> None:
    """`plan.toml` is a projection of `SCRIPT`, so a hand edit to it is a lie the gate would read.

    `gate_incremental.py` reads the committed file and checks its two counts; what it cannot check
    is whether the file describes the corpus the generator builds. This does.
    """
    assert PLAN.read_text("utf-8") == corpus.plan_toml()
    document = tomllib.loads(PLAN.read_text("utf-8"))
    assert document["documents"] == corpus.DOCUMENTS
    assert document["mutations"] == [mutation.name for mutation in corpus.SCRIPT]


def test_the_mutation_mix_scales_gr8s_three_named_kinds(corpus: types.ModuleType) -> None:
    """06-structure-extraction.md:2405 is the only mix the plan states: GR8's 3 edits, 2 deletions
    and 1 driver-version re-parse in 20 steps.

    G19's mix is stated nowhere, so the generator's docstring argues each row. What this asserts is
    that the argument and the script agree -- and that every kind the docstring names is actually
    exercised, because a kind with a count of zero is a paragraph of prose about nothing.
    """
    counted = collections.Counter(mutation.kind for mutation in corpus.SCRIPT)
    assert dict(counted) == dict(corpus.MIX)
    assert sum(corpus.MIX.values()) == corpus.MUTATIONS
    assert min(corpus.MIX.values()) > 0
    assert counted["driver_version"] == 2, "GR8's one, at twice the step count"


def test_every_mutation_targets_a_document_that_exists_when_it_runs(
    corpus: types.ModuleType,
) -> None:
    """A delete of an already-deleted document is not a mutation, and 40 of those are not 40.

    The script is built by a walk over the live roster for exactly this reason; this is the walk's
    output checked against the rosters it claims to describe.
    """
    for step, mutation in enumerate(corpus.SCRIPT):
        live = {document.slot for document in corpus.corpus_at(step)}
        if mutation.kind == "driver_version":
            assert mutation.slot == -1
        elif mutation.kind == "add":
            assert mutation.slot not in live, f"step {step} adds a slot that is already live"
        else:
            assert mutation.slot in live, f"step {step} is a {mutation.kind} of an absent slot"


def test_the_roster_ends_where_it_started(corpus: types.ModuleType) -> None:
    """Seven adds and seven deletes, so the register's 300 describes both ends of the script."""
    assert len(corpus.corpus_at(0)) == corpus.DOCUMENTS
    assert len(corpus.corpus_at(corpus.MUTATIONS)) == corpus.DOCUMENTS


def test_the_driver_version_is_one_plus_the_re_parses_so_far(corpus: types.ModuleType) -> None:
    """Both sides read it from the script: a rebuild at a different version stamps a different
    `producer` on every block and reports a difference that says nothing about convergence."""
    assert corpus.driver_version_at(0) == 1
    assert corpus.driver_version_at(corpus.MUTATIONS) == 1 + corpus.MIX["driver_version"]


# ---------------------------------------------------------------------------
# 2. Determinism -- 13-quality.md:586-589's regime
# ---------------------------------------------------------------------------


def test_the_generator_reaches_none_of_the_five_banned_names(corpus: types.ModuleType) -> None:
    """*"...with `random`, `secrets`, `uuid4`, `time.time` and `datetime.now` monkeypatched to
    raise."* None of the five is imported, which is stronger than none of them being called."""
    tree = ast.parse(GENERATOR.read_text("utf-8"), filename=str(GENERATOR))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {"random", "secrets", "uuid", "time", "datetime"}
    assert len(corpus.SCRIPT) == corpus.MUTATIONS


def test_a_documents_bytes_are_a_pure_function_of_its_slot_and_revision(
    corpus: types.ModuleType,
) -> None:
    """Two calls, two processes and two machines must produce one file. Two calls is what is
    checkable here; the pin in `EXPECTED.sha256` is what carries it across the other two."""
    document = corpus.corpus_at(0)[7]
    assert corpus.document_bytes(document) == corpus.document_bytes(document)
    rebuilt = corpus.Document(slot=document.slot, revision=document.revision)
    assert corpus.document_bytes(rebuilt) == corpus.document_bytes(document)


def test_an_edit_changes_the_bytes_and_a_rename_does_not(corpus: types.ModuleType) -> None:
    """The two mutations that look alike from outside the store and must not from inside it.

    An edit is new bytes at the same uri; a rename is the same bytes at a new one. If an edit did
    not move the bytes the incremental side would skip it, and the gate would pass a step that
    never happened.
    """
    document = corpus.corpus_at(0)[3]
    edited = dataclasses.replace(document, revision=document.revision + 1)
    renamed = dataclasses.replace(document, renames=document.renames + 1)
    assert corpus.document_bytes(edited) != corpus.document_bytes(document)
    assert renamed.uri != document.uri
    assert renamed.contents == document.contents, "a rename moves the name, not the pages"


def test_the_pin_is_the_digest_of_a_freshly_generated_initial_roster(
    corpus: types.ModuleType, tmp_path: Path
) -> None:
    """13-quality.md:588: the pin makes a corpus change *"a one-line visible diff"*.

    Pinned through a manifest rather than document by document, because 300 lines that all turn
    over together is the unreadable diff the pin exists to prevent.
    """
    line = next(
        row for row in PINS.read_text("utf-8").splitlines() if row.endswith("roster-step0.manifest")
    )
    pinned, _, path = line.partition("  ")
    assert path == "fixtures/generated/incremental/roster-step0.manifest"

    written = corpus.write_manifest(tmp_path, corpus.corpus_at(0), step=0)
    assert corpus.sha256_of(written) == pinned
    assert hashlib.sha256(written.read_bytes()).hexdigest() == pinned
    assert b"\r\n" not in written.read_bytes(), "the pin is a digest; line endings are bytes"


# ---------------------------------------------------------------------------
# 3. The identities the indexer fixes
# ---------------------------------------------------------------------------


def test_no_two_documents_of_any_step_share_a_doc_ord(
    corpus: types.ModuleType, indexer: types.ModuleType
) -> None:
    """A 2^32 space and ~313 documents, so a collision is a red test rather than a `UNIQUE`
    violation in the middle of a 130-second gate run."""
    seen: dict[int, str] = {}
    for step in range(corpus.MUTATIONS + 1):
        for document in corpus.corpus_at(step):
            ordinal = indexer.doc_ord(document.uri)
            assert seen.setdefault(ordinal, document.uri) == document.uri
    assert len(seen) >= corpus.DOCUMENTS


def test_the_doc_key_survives_an_edit_and_moves_on_a_rename(corpus: types.ModuleType) -> None:
    """An archive is named `{doc_key}.owdoc`, so the key is what makes the two sides comparable.

    `0001_init.sql:150` would make it a content hash, under which an edit is a different document;
    `03:1316-1370` re-parses the same `doc_ord` at `gen = 2` after the source changed. Both cannot
    hold. `tools/p2_demo.py` took this side first and the generator's docstring records why G19
    must take it too.
    """
    document = corpus.corpus_at(0)[11]
    edited = dataclasses.replace(document, revision=document.revision + 1)
    renamed = dataclasses.replace(document, renames=document.renames + 1)
    assert corpus.doc_key(edited.uri) == corpus.doc_key(document.uri)
    assert corpus.doc_key(renamed.uri) != corpus.doc_key(document.uri)
    assert len(corpus.doc_key(document.uri)) == 16


def test_the_code_fingerprint_is_derived_from_the_version_and_not_chosen(
    indexer: types.ModuleType,
) -> None:
    """Two builds at one version must stamp one producer; two versions must not."""
    assert indexer.code_fingerprint(1) == indexer.code_fingerprint(1)
    assert indexer.code_fingerprint(1) != indexer.code_fingerprint(2)
    assert len(indexer.code_fingerprint(3)) == 64


# ---------------------------------------------------------------------------
# 4. One real convergence run, over eight documents
# ---------------------------------------------------------------------------


def _small(corpus: types.ModuleType, documents: int = 8) -> types.SimpleNamespace:
    """The real generator over a roster of `documents`, with a four-step script of its own.

    A stand-in for the module rather than a stub of it: every document is a real `Document`, every
    byte is `document_bytes`, and the only thing replaced is which documents there are and what
    happens to them. `Incremental` and `rebuild` take the corpus as a parameter for exactly this.
    """
    roster = corpus.corpus_at(0)[:documents]
    script = (
        corpus.Mutation("edit", roster[0].slot).labelled(),
        corpus.Mutation("delete", roster[1].slot).labelled(),
        corpus.Mutation("driver_version").labelled(),
        corpus.Mutation("edit", roster[2].slot).labelled(),
    )

    def corpus_at(step: int) -> tuple[Any, ...]:
        live = {document.slot: document for document in roster}
        for mutation in script[:step]:
            if mutation.kind == "delete":
                live.pop(mutation.slot, None)
            elif mutation.kind == "edit":
                current = live[mutation.slot]
                live[mutation.slot] = dataclasses.replace(current, revision=current.revision + 1)
        return tuple(sorted(live.values(), key=lambda document: document.uri))

    return types.SimpleNamespace(
        SCRIPT=script,
        MUTATIONS=len(script),
        corpus_at=corpus_at,
        document_bytes=corpus.document_bytes,
        doc_key=corpus.doc_key,
        driver_version_at=lambda step: (
            1 + sum(1 for m in script[:step] if m.kind == "driver_version")
        ),
    )


def test_an_incremental_build_converges_to_a_full_rebuild(
    corpus: types.ModuleType,
    indexer: types.ModuleType,
    gate: types.ModuleType,
    tmp_path: Path,
) -> None:
    """INV-18 over eight documents and four mutations. The shipped gate runs 300 and 40.

    Every mutation kind that can diverge is here: an edit (a re-parse at a new generation with
    carried cites), a delete (which must leave BOTH stores), a driver-version re-parse (which
    restamps every block), and an edit AFTER that re-parse. What the gate adds at 300 and 40 is
    the chance of finding a case eight documents will not.
    """
    small = _small(corpus)
    side = indexer.Incremental(root=tmp_path / "inc", corpus=small, parser=indexer.stub())
    side.start()
    for step in range(small.MUTATIONS):
        side.step(step)
    incremental = tmp_path / "inc" / "exports"
    side.export(incremental)
    full = indexer.rebuild(tmp_path / "full", small.MUTATIONS, corpus=small, parser=indexer.stub())

    divergences, provenance, archives, _ = gate._diff_checkpoint(
        gate.Checkpoint(step=small.MUTATIONS, incremental=incremental, full=full)
    )
    assert archives == 7, "eight documents, one deleted"
    assert divergences == [], [difference.line() for difference in divergences[:5]]
    assert provenance, "an edit and a driver-version re-parse move gen and revision"


def test_a_document_deleted_incrementally_leaves_no_archive_behind(
    corpus: types.ModuleType, indexer: types.ModuleType, tmp_path: Path
) -> None:
    """The single most likely shape of an incremental bug, and `ON DELETE CASCADE` is the answer.

    `foreign_keys` is OFF by default in SQLite and is per-connection, so a delete issued without
    it removes the `doc` row and orphans every block beneath it -- and `export_portable` reads
    `doc`, so the archive would vanish and the orphans would not. This asserts the archive is gone
    AND that the store still verifies, which is the half a `doc`-only delete would pass.
    """
    small = _small(corpus, documents=4)
    side = indexer.Incremental(root=tmp_path / "inc", corpus=small, parser=indexer.stub())
    side.start()
    gone = small.corpus_at(0)[1]
    for step in range(2):
        side.step(step)

    exports = tmp_path / "inc" / "exports"
    assert side.export(exports) == 3
    assert not (exports / f"{small.doc_key(gone.uri).hex()}.owdoc").exists()

    connection = indexer._connect(side.store)
    try:
        orphans = connection.execute(
            "SELECT count(*) FROM block WHERE doc_ord NOT IN (SELECT doc_ord FROM doc)"
        ).fetchone()[0]
    finally:
        connection.close()
    assert orphans == 0, "the cascade ran; a doc-only delete would leave every block behind"


def test_a_touch_step_re_parses_nothing(
    corpus: types.ModuleType, indexer: types.ModuleType, tmp_path: Path
) -> None:
    """The one mutation kind GR8 does not name, and the only one that tests the other direction.

    Every other kind asks whether the incremental build did enough work. A `touch` asks whether it
    did work it should not have: the bytes are unchanged, so a correct build re-parses nothing and
    a build that quietly rebuilds everything reports the whole roster.
    """
    roster = corpus.corpus_at(0)[:4]
    script = (corpus.Mutation("touch", roster[0].slot).labelled(),)
    small = types.SimpleNamespace(
        SCRIPT=script,
        MUTATIONS=1,
        corpus_at=lambda _step: roster,
        document_bytes=corpus.document_bytes,
        doc_key=corpus.doc_key,
        driver_version_at=lambda _step: 1,
    )
    side = indexer.Incremental(root=tmp_path / "inc", corpus=small, parser=indexer.stub())
    side.start()
    report = side.step(0)

    assert (report.added, report.changed, report.removed) == (0, 0, 0)
    assert report.reparsed == 0
