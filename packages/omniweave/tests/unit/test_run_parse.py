"""`run/operators/parse.py`: hops 10-17 through a real `ow ingest`, a real worker, a real store.

The office fixtures are the corpus because each one's expected outcome is already written in its
own `.meta.toml`: `deck.ppt` is a valid but EMPTY stream the host must turn into
`EMPTY_RESULT`, `memo.doc` has no valid FIB and must be `CORRUPT_INPUT`, `encrypted.odt` is
`ENCRYPTED`. Ten of them parse -- more than `batch_max_units = 8` -- so one run dispatches two
batches on two threads, which is the shape that found D588 (two workers under one pipe name) and
D589 (two sinks minting one id).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import sys
from pathlib import Path
from typing import Any

import pytest
from omniweave.run import ingest as ingest_module
from omniweave.run.dispatch import Batch, dispatch_key
from omniweave.run.ingest import Receipt, ingest
from omniweave.run.operators import parse as parse_module
from omniweave.run.operators.parse import (
    PARSE_FAILED_SQL,
    SETTLED_SQL,
    InprocNotHostedError,
    ParseLedger,
    ParseOperator,
    ParseTally,
)
from omniweave.run.routing import resolve_policy
from omniweave_core.acquire import locator_for, scope_id_for
from omniweave_core.blobs import BlobStore
from omniweave_core.canonical import sha256_canonical
from omniweave_core.clock import SystemClock
from omniweave_core.config import Config, load
from omniweave_core.contract import SCHEMA
from omniweave_core.discovery import catalog
from omniweave_core.errors import RouteError
from omniweave_core.model.records import Producer
from omniweave_core.operator import Outcome, Roots
from omniweave_core.retrieve.types import SCORER_VERSION
from omniweave_core.store import sqlite as ow
from omniweave_core.store.indexlock import FIELD_SEP, LOCK_PATH
from omniweave_core.store.queue import SqliteStore
from omniweave_core.store.verify import VerifyClause, verify_store
from omniweave_ports.types import FailureClass

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the named-pipe arm of S4")

FIXTURES = Path(__file__).resolve().parents[3] / "omniweave-office" / "fixtures"
PROJECT = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
OPT_IN = "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
PARSEABLE = (
    "rich.docx", "sheet.xlsx", "deck.pptx", "rows.csv", "book.epub",
    "memo.rtf", "notes.odt", "sheet.xls", "deck.odp", "sheet.ods",
)  # fmt: skip
REFUSED = {"deck.ppt": "empty_result", "memo.doc": "corrupt_input", "encrypted.odt": "encrypted"}


def _project(tmp_path: Path, names: tuple[str, ...]) -> tuple[Path, Config]:
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in names:
        shutil.copy(FIXTURES / name, docs / name)
    (tmp_path / "omniweave.toml").write_text(PROJECT + OPT_IN, encoding="utf-8")
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    return tmp_path / ".omniweave" / "index.owstore", config


def _run(tmp_path: Path, store: Path, config: Config, *, paths: bool = True) -> Any:
    return ingest(
        store,
        config=config,
        source_root=tmp_path,
        output_root=tmp_path / "out",
        cache_root=tmp_path / ".omniweave" / "cache",
        argv=["ow", "ingest"],
        paths=[tmp_path / "docs"] if paths else (),
        sweep_ms=20,
    )


def _rows(store: Path, sql: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(store)
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def _state(store: Path, name: str) -> tuple[Any, ...]:
    rows = _rows(
        store,
        f"SELECT state, acq_failure_class FROM unit WHERE unit_uri LIKE '%{name}'",  # noqa: S608
    )
    assert len(rows) == 1, (name, rows)
    return rows[0]


# ---------------------------------------------------------------------------------------------
# a real corpus
# ---------------------------------------------------------------------------------------------


def test_every_routed_document_reaches_a_terminal_row_in_one_run(tmp_path: Path) -> None:
    """Ten documents settle, each with one committed generation; three fail with the class their
    own fixture manifest names; nothing is left `claimed` -- which is what D588 and D589 did."""
    store, config = _project(tmp_path, (*PARSEABLE, *REFUSED))
    report = _run(tmp_path, store, config)
    assert report.parsed is not None
    assert dict(report.parsed.parsed) == {"parse.office.anydoc": len(PARSEABLE)}
    assert dict(report.parsed.failed) == {"corrupt_input": 1, "empty_result": 1, "encrypted": 1}
    assert report.parsed.workers == 1, "one worker per (driver_id, config_digest), reused"
    assert report.parsed.calls >= 2, "thirteen rows over batch_max_units = 8 is two batches"
    for name in PARSEABLE:
        assert _state(store, name) == ("settled", None), name
    for name, failure in REFUSED.items():
        assert _state(store, name) == ("failed", failure), name
    statuses = "SELECT status, count(*) FROM work WHERE operator = 'parse.office' GROUP BY 1"
    assert _rows(store, statuses) == [("done", 10), ("failed_permanent", 3)]
    assert _rows(store, "SELECT count(*), min(gen), max(gen) FROM doc") == [(10, 1, 1)]
    assert _rows(store, "SELECT count(DISTINCT block_id) = count(*) FROM block") == [(1,)]
    assert report.status == "ok"
    lines = report.lines()
    assert "  settled   10 units have a committed document" in lines
    assert all(line.isascii() for line in lines)


def test_a_second_run_parses_nothing_and_writes_no_second_generation(tmp_path: Path) -> None:
    """A settled unit is not re-parsed: its `work` row is `done` under its recorded `cache_key`,
    and an unchanged file is not re-acquired, so nothing is re-planned (I1)."""
    store, config = _project(tmp_path, ("rich.docx", "rows.csv"))
    _run(tmp_path, store, config)
    blocks = _rows(store, "SELECT count(*) FROM block")
    second = _run(tmp_path, store, config, paths=False)
    assert second.parsed is None
    assert _rows(store, "SELECT count(*), max(gen) FROM doc") == [(2, 1)]
    assert _rows(store, "SELECT count(*) FROM block") == blocks
    assert _rows(store, "SELECT count(*) FROM work WHERE operator = 'parse.office'") == [(2,)]


# ---------------------------------------------------------------------------------------------
# hop 19: the receipt, the generation, the manifest
# ---------------------------------------------------------------------------------------------


def _generation(store: Path) -> str:
    ((value,),) = _rows(store, "SELECT v FROM index_state WHERE k = 'generation'")
    return str(value)


def test_the_first_parse_writes_the_receipt_and_moves_the_generation(tmp_path: Path) -> None:
    """Hop 19 over a committed document: the receipt beside `.omniweave/`, its uri relative to
    the source root (D591), `index_state.generation` moved to the run's (D594), `run.lock_digest`
    the file's own sha256, and `ow store verify --lock` agreeing with it line for line."""
    store, config = _project(tmp_path, ("rich.docx",))
    report = _run(tmp_path, store, config)
    path = tmp_path / LOCK_PATH
    raw = path.read_bytes()
    assert b"\r" not in raw, "11 section 1.9: the line ending is written, never inherited"
    header, line = raw.decode("ascii").splitlines()
    assert header == f"# schema={SCHEMA} scorer={SCORER_VERSION} segmenter=none space=none"
    key, gen, status, blocks, segments, digest, uri = line.split(FIELD_SEP)
    ((doc_key, root),) = _rows(
        store,
        "SELECT hex(d.doc_key), hex(b.content_digest) FROM doc d JOIN block b"
        " ON b.doc_ord = d.doc_ord AND b.gen = d.gen AND b.addr = 'doc'",
    )
    assert (key, digest) == (str(doc_key).lower(), str(root).lower())
    assert (gen, status, segments, uri) == ("1", "ok", "0", "docs/rich.docx")
    assert int(blocks) > 0
    assert _generation(store) == str(report.generation) == "1"
    sha = hashlib.sha256(raw).hexdigest()
    assert _rows(store, "SELECT lock_digest FROM run") == [(sha,)]
    assert report.receipt == Receipt(path, documents=1, changed=True, written=True, digest=sha)
    assert f"  receipt   {LOCK_PATH} written, 1 documents, generation 1" in report.lines()

    connection = sqlite3.connect(store)
    try:
        root_uri = scope_id_for(locator_for(tmp_path.resolve()))
        clauses = [VerifyClause.LOCK_STORE_MATCH]
        text = raw.decode("ascii")
        agreed = verify_store(
            connection, now_ns=0, clauses=clauses, lock_text=text, uri_root=root_uri
        )
        unrooted = verify_store(connection, now_ns=0, clauses=clauses, lock_text=text)
    finally:
        connection.close()
    assert agreed.ok and not agreed.clauses[0].findings, agreed
    assert not unrooted.ok, "without the root the store derives the absolute uri"

    manifest = json.loads(Path(report.manifest).read_bytes())
    assert manifest["outcomes"] == {"ok": 2}, "one op.identify and one parse.office commit"
    assert manifest["stage_entries"] == {"discover": 1, "plan": 1, "parse": 1}
    assert manifest["provenance"]["lock_digest"] == sha


def test_a_run_that_changes_no_row_keeps_the_receipt_and_the_generation(tmp_path: Path) -> None:
    """D594's other half: a run whose derived rows equal the committed ones leaves the file's
    bytes and `index_state.generation` alone -- and a receipt a merge left conflict markers in is
    replaced by the store's own, with the generation moved, because nothing it said can be read."""
    store, config = _project(tmp_path, ("rich.docx",))
    _run(tmp_path, store, config)
    path = tmp_path / LOCK_PATH
    first = path.read_bytes()
    second = _run(tmp_path, store, config, paths=False)
    assert (second.generation, _generation(store)) == (2, "1")
    assert path.read_bytes() == first
    assert second.receipt is not None
    assert (second.receipt.changed, second.receipt.written) == (False, False)
    assert f"  receipt   {LOCK_PATH} unchanged, 1 documents, generation not moved" in second.lines()
    digests = _rows(store, "SELECT lock_digest FROM run ORDER BY generation")
    assert digests == [(hashlib.sha256(first).hexdigest(),)] * 2

    path.write_bytes(first + b"<<<<<<< ours\n=======\n>>>>>>> theirs\n")
    third = _run(tmp_path, store, config, paths=False)
    assert path.read_bytes() == first
    assert (third.generation, _generation(store)) == (3, "3")


def test_the_cas_is_beside_the_store_and_holds_the_source_and_the_asset(tmp_path: Path) -> None:
    """D582: the unit's raw bytes are staged into `.omniweave/cas/` at dispatch, and the office
    driver's asset lands there through the worker's `io.blobs.put()`."""
    store, config = _project(tmp_path, ("rich.docx",))
    _run(tmp_path, store, config)
    cas = store.parent / ingest_module.CAS_DIR
    blobs = [path for path in cas.rglob("*") if path.is_file() and len(path.name) == 64]
    assert len(blobs) == 2, blobs
    ((ref,),) = _rows(store, "SELECT store_ref FROM asset")
    assert str(ref).startswith("cas://")


# ---------------------------------------------------------------------------------------------
# the pieces
# ---------------------------------------------------------------------------------------------


class _View:
    def __init__(self, outcome: Outcome, failure: str | None = None) -> None:
        self.outcome = outcome
        self.failure_class = failure


def test_the_ledger_settles_a_success_fails_a_permanent_and_leaves_a_transient() -> None:
    ledger = ParseLedger()
    ledger.record(1, "u1", 7)
    ((settled,),) = [ledger(1, _View(Outcome.OK))]  # type: ignore[arg-type]
    assert (settled.sql, dict(settled.params)) == (SETTLED_SQL, {"unit_uri": "u1", "gen": 7})
    ((failed,),) = [ledger(1, _View(Outcome.FAILED_PERMANENT, "encrypted"))]  # type: ignore[arg-type]
    assert failed.sql == PARSE_FAILED_SQL
    assert failed.params["failure_class"] == "encrypted"
    assert ledger(1, _View(Outcome.FAILED_TRANSIENT, "timeout")) == ()  # type: ignore[arg-type]
    unknown = ledger(2, _View(Outcome.OK))  # type: ignore[arg-type]
    assert unknown == (), "a row the ledger does not know contributes nothing"
    ledger.forget(1)
    assert len(ledger) == 0


def _operator(tmp_path: Path, store: Path, config: Config, thread: ow.StoreThread) -> ParseOperator:
    roots = Roots(source=tmp_path, output=tmp_path / "out", cache=tmp_path / ".omniweave" / "cache")
    ctx = ingest_module._context("r_test", 2, config=config, roots=roots, clock=SystemClock())
    cas = store.parent / "cas"
    cas.mkdir(exist_ok=True)
    return ParseOperator(
        thread,
        ctx=ctx,
        config=config,
        catalog=catalog(),
        resolving=resolve_policy(config),
        cas=BlobStore(cas),
        ledger=ParseLedger(),
        tally=ParseTally(),
    )


def _planned_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the run after hop 9, so a test holds a `pending` parse row to hand the Operator."""
    monkeypatch.setattr(ingest_module, "_pending_parse", lambda _thread: False)


def test_a_dispatch_key_minted_for_inproc_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The office card's own request, under a pinned trust, is `inproc`; the S1 host is not built,
    so such a row is refused like D578's rows -- held for the reaper, nothing false written."""
    _planned_only(monkeypatch)
    store, config = _project(tmp_path, ("rich.docx",))
    _run(tmp_path, store, config)
    with ow.StoreThread(lambda: ow.connect(store)) as thread:
        operator = _operator(tmp_path, store, config, thread)
        card = catalog().cards["parse.office.anydoc"]
        digest = sha256_canonical(card.config.effective({}))
        granted = operator._granted(
            card.identity.id, dispatch_key(card.identity.id, digest, "inproc")
        )
        assert str(granted.isolation) == "inproc"
        with pytest.raises(RouteError, match="matches neither isolation"):
            operator._granted(card.identity.id, "0" * 16)
        (row,) = SqliteStore(thread).claim(8, 2, "w:1:1", 60_000)
        forged = dataclasses.replace(
            row, dispatch_key=dispatch_key(card.identity.id, digest, "inproc")
        )
        with pytest.raises(InprocNotHostedError, match=r"parse\.office\.anydoc"):
            operator(Batch(invoke_id="i", rows=(forged,)))
        operator.close()


def test_a_source_that_changed_after_identify_is_not_parsed_under_its_old_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D582: the unit's raw bytes no longer hash to the digest identify recorded, so the key on
    the row describes other bytes. The row fails as `corrupt_input` and names why."""
    _planned_only(monkeypatch)
    store, config = _project(tmp_path, ("rows.csv",))
    _run(tmp_path, store, config)
    (tmp_path / "docs" / "rows.csv").write_text("x,y\n9,9\n", encoding="utf-8")
    with ow.StoreThread(lambda: ow.connect(store)) as thread:
        operator = _operator(tmp_path, store, config, thread)
        (row,) = SqliteStore(thread).claim(8, 2, "w:1:1", 60_000)
        producer = Producer(operator="parse.office", op_version=1, code_fingerprint="")
        staged = operator._stage(row, producer)
        assert not isinstance(staged, parse_module._Staged)
        assert staged.outcome is Outcome.FAILED_PERMANENT
        assert staged.failure_class is FailureClass.CORRUPT_INPUT
        assert "changed after it was identified" in str(staged.failure_message)
        operator.close()
