"""`read_back_artifact()`: a sealed artefact read back into the corpus, and the loop closed. D788.

02-architecture.md section 4.3's re-ingest table and 09-generation.md Q4. The store, the seal,
the CAS and `parse.docx.native`'s card are real. The read_back's fragment is written here, so
each ruling can be held to one fragment. `test_out_back_verb.py` runs the real read_back in a
worker over a real `.docx`.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the read-back wrote.
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.run import out_back
from omniweave.run.operators.parse import declared
from omniweave.run.out_back import ReadWorker, in_process, read_back_artifact, reader_card
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.blobs import BlobStore, format_ref
from omniweave_core.discovery import discover
from omniweave_core.errors import TargetError
from omniweave_core.host import subproc
from omniweave_core.host.subproc import HostVerdict
from omniweave_core.model.enums import enum_val_rows
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.store import fragment as fragment_module
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.artifact import (
    ArtifactDraft,
    ArtifactRow,
    ElRow,
    PureKey,
    SqliteArtifactStore,
    UnitRow,
)
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode, records_of
from omniweave_ports import ArtifactRef, DriverResult, FailureClass
from omniweave_ports.types import UnitRef

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from omniweave_ports import DriverIO

ORD = {(domain, name): ordinal for domain, ordinal, name in enum_val_rows()}
MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
BODY = b"PK the sealed memo"
SHA = hashlib.sha256(BODY).hexdigest()
URI = "/out/memo@1/memo.docx"
BARRED = 1 << 3
[READER] = [one for one in discover(env={}).cards if one.identity.id == "parse.docx.native"]
[COMPILER] = [one for one in discover(env={}).cards if one.identity.id == "compile.docx.native"]


def d(n: int) -> str:
    return f"sha256:{n:064x}"


class Clock:
    def wall_ns(self) -> int:
        return 1_700_000_000_000_000_000

    def monotonic_ns(self) -> int:
        return 1


def block(
    tmp: str,
    kind: str,
    text: str | None,
    *,
    parent: str | None = None,
    layer: str = "body",
    **x: Any,
) -> Any:
    """One `owdoc-fragment/1` block record, spelled as `parse.docx.native` spells it."""
    record: dict[str, Any] = {
        "t": "block",
        "tmp": tmp,
        "parent": parent,
        "page": 0,
        "kind": kind,
        "layer": layer,
        "text": text,
        "quote": "normalized",
        "trust": "inferred",
        "method": "roundtrip",
        "os": {"k": "none"},
        "quad": None,
        "marks": [],
        "payload": None,
    }
    if x:
        record["x"] = {f"x.ow.{key}": value for key, value in x.items()}
    return record


def fragment(*blocks: Any) -> bytes:
    records = [
        {"t": "doc", "format": "docx", "media_type": MEDIA, "page_count": 1},
        {
            "t": "page",
            "page": 0,
            "page_kind": "stream",
            "w_mpt": None,
            "h_mpt": None,
            "quad_origin": None,
            "quad_unit": None,
            "quad_dpi": None,
            "rotation": 0,
            "method": "roundtrip",
        },
        *blocks,
        {"t": "end", "status": "ok", "page_stats": {"0": {"blocks": len(blocks)}}},
    ]
    return "".join(json.dumps(r) + "\n" for r in records).encode()


MEMO = fragment(
    block("b1", "section", None, el="u01/e1"),
    block("b2", "paragraph", "Revenue rose.", parent="b1", el="u01/e2", cites=["d7#1"]),
    block("b3", "section", None, el="u02/e1"),
    block("b4", "paragraph", "Margins held.", parent="b3", el="u02/e2"),
    block("b5", "comment", "ow:manual later", layer="annotation"),
)


@dataclass
class World:
    path: Path
    thread: ow.StoreThread
    blobs: BlobStore
    artifacts: SqliteArtifactStore
    row: ArtifactRow
    units: tuple[UnitRow, ...]
    asked: list[UnitRef] = field(default_factory=list)

    def read(self, body: bytes = MEMO, **over: Any) -> out_back.Closed:
        def reading(unit: UnitRef) -> bytes:
            self.asked.append(unit)
            return body

        arguments: dict[str, Any] = {
            "units": self.units,
            "card": READER,
            "effective_config": READER.config.effective(),
            "reading": reading,
            "thread": self.thread,
            "blobs": self.blobs,
            "artifacts": self.artifacts,
            "uri": URI,
        }
        arguments.update(over)
        return read_back_artifact(self.row, **arguments)

    def rows(self, sql: str, params: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        connection = sqlite3.connect(self.path)
        try:
            return connection.execute(sql, params).fetchall()
        finally:
            connection.close()

    def loop(self) -> tuple[Any, list[tuple[Any, ...]]]:
        [(doc_ord,)] = self.rows("SELECT read_back_doc_ord FROM artifact")
        return doc_ord, self.rows("SELECT unit, el, block_id FROM artifact_el ORDER BY el")


def _unit(n: int) -> UnitRow:
    return UnitRow(
        unit=f"u{n:02d}",
        ord=n,
        outcome=UnitOutcome.NATIVE,
        il_path=f"il/u{n:02d}.html",
        il_sha256=d(100 + n),
        nsig=f"{n:08x}",
    )


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1)
        connection.execute(
            "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint,"
            " options_digest) VALUES (1, 'compile.docx.native', 1, '', X'00')"
        )
        connection.commit()
    finally:
        connection.close()
    (tmp_path / "cas").mkdir()
    blobs = BlobStore(tmp_path / "cas")
    units = (_unit(1), _unit(2))
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        artifacts = SqliteArtifactStore(thread, clock=Clock())
        sealed = artifacts.seal(
            ArtifactDraft(
                key=PureKey(
                    target="docx",
                    slug="memo",
                    delivery="release",
                    il_digest=d(1),
                    constructs_digest=d(2),
                    ledger_digest=d(3),
                    card_sha256=d(4),
                    brief_digest=d(5),
                    toolchain_digest=None,
                ),
                artifact_gen=1,
                origin="authored",
                compile_driver="compile.docx.native",
                media_type=MEDIA,
                path="memo@1/memo.docx",
                sha256="sha256:" + SHA,
                byte_len=len(BODY),
                part_digest=d(11),
                il_store_ref="cas://00/00/" + "0" * 64,
                determinism=("part", "byte"),
                gate_status=GateStatus.PASSED,
                report_sha256=d(12),
                receipt_sha256=d(13),
                producer_id=1,
                units=units,
                restriction_bits=BARRED,
            )
        )
        yield World(path, thread, blobs, artifacts, sealed.row, units)


# ---------------------------------------------------------------------------------------------
# Rulings 2, 5 and 7: the sealed bytes, an ordinary parse's document, the loop closed
# ---------------------------------------------------------------------------------------------


def test_the_loop_closes_on_the_blocks_the_store_minted(world: World) -> None:
    closed = world.read()
    doc_ord, mapped = world.loop()
    assert closed.row.read_back_doc_ord == doc_ord is not None
    minted = dict(
        world.rows(
            "SELECT json_extract(x, '$.\"x.ow.el\"'), block_id FROM block"
            " WHERE json_extract(x, '$.\"x.ow.el\"') IS NOT NULL"
        )
    )
    assert mapped == [(el.split("/")[0], el, minted[el]) for el in sorted(minted)]
    assert closed.els == tuple(ElRow(*one) for one in mapped)
    assert world.artifacts.els(world.row.artifact_id) == closed.els
    assert sorted(minted) == ["u01/e1", "u01/e2", "u02/e1", "u02/e2"]
    [(el_text,)] = world.rows("SELECT text FROM block WHERE block_id = ?", (minted["u02/e2"],))
    assert el_text == "Margins held."


def test_the_unit_read_is_the_sealed_bytes_and_the_document_is_theirs(world: World) -> None:
    world.read()
    assert world.asked == [
        UnitRef(uri=URI, part="", content_sha256=SHA, byte_len=len(BODY), media_type=MEDIA)
    ]
    doc_ord, _ = world.loop()
    [(uri, key, source, media)] = world.rows(
        "SELECT uri, doc_key, source_sha256, media_type FROM doc WHERE doc_ord = ?", (doc_ord,)
    )
    assert (uri, bytes(key), bytes(source), media) == (
        URI,
        bytes.fromhex(SHA)[:16],
        bytes.fromhex(SHA),
        MEDIA,
    )


def test_the_document_is_an_ordinary_parse_carrying_the_artefacts_bits(world: World) -> None:
    world.read()
    blocks = world.rows(
        "SELECT DISTINCT b.origin_operator, b.origin_driver, b.method, b.restriction_bits,"
        " p.operator FROM block b JOIN producer p ON p.producer_id = b.producer_id"
    )
    assert blocks == [
        ("parse.docx", "parse.docx.native", ORD["method", "roundtrip"], BARRED, "parse.docx")
    ]


def test_a_closed_loop_is_read_back_once(world: World) -> None:
    """Ruling 8: the row is read again first, so a stale row reads nothing back."""
    world.read()
    row = world.artifacts.get("memo", 1)
    with pytest.raises(TargetError) as caught:
        world.read()
    assert caught.value.code() == "OW_TARGET_ARTIFACT_SEALED"
    assert str(caught.value) == f"memo@1 was already read back, as document {row.read_back_doc_ord}"
    assert len(world.asked) == 1, "the second call read nothing"
    assert world.artifacts.get("memo", 1) == row
    assert world.rows("SELECT gen FROM doc") == [(1,)]


# ---------------------------------------------------------------------------------------------
# Ruling 4: the addresses, checked before the store is touched
# ---------------------------------------------------------------------------------------------


def _refused(world: World, body: bytes, says: str) -> None:
    with pytest.raises(TargetError) as caught:
        world.read(body=body)
    assert caught.value.code() == "OW_TARGET_READ_BACK_FAILED"
    assert says in str(caught.value)
    assert "the loop stays open" in str(caught.value)
    assert caught.value.fix == "report the target's read_back: ow drivers verify parse.docx.native"
    assert world.loop() == (None, [])


def test_an_address_on_two_blocks_writes_nothing(world: World) -> None:
    twice = fragment(
        block("b1", "section", None, el="u01/e1"),
        block("b2", "paragraph", "One.", parent="b1", el="u01/e2"),
        block("b3", "paragraph", "Two.", parent="b1", el="u01/e2"),
    )
    _refused(world, twice, "it places ['u01/e2'] on more than one block")
    assert world.rows("SELECT count(*) FROM doc") == [(0,)]


def test_an_address_in_no_sealed_unit_writes_nothing(world: World) -> None:
    stray = fragment(block("b1", "section", None, el="u09/e1"))
    _refused(world, stray, "['u09/e1'] name no unit the artefact sealed (['u01', 'u02'])")
    assert world.rows("SELECT count(*) FROM doc") == [(0,)]


def test_a_fragment_that_is_not_json_is_refused(world: World) -> None:
    _refused(world, b"{not json\n", "its fragment is not owdoc-fragment/1")


def test_a_fragment_the_decoder_refuses_is_refused(world: World) -> None:
    _refused(world, MEMO.replace(b'{"t": "end"', b'{"t": "nope"'), "the store refused")


# ---------------------------------------------------------------------------------------------
# Rulings 6 and 7: a quarantined re-parse, and a head that lost its addresses
# ---------------------------------------------------------------------------------------------


def test_a_quarantined_read_back_leaves_the_loop_open(world: World) -> None:
    """An ingest of the output root read these bytes first, as other blocks (Q4)."""
    connection = sqlite3.connect(world.path)
    try:
        connection.execute(
            "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint,"
            " options_digest) VALUES (2, 'parse.office', 1, '', X'01')"
        )
        connection.commit()
    finally:
        connection.close()
    earlier = fragment(
        *(block(f"b{n}", "paragraph", f"Another reading, line {n}.") for n in range(1, 9))
    )
    sink = DocSink(
        world.thread,
        producer_id=2,
        origin_operator="parse.office",
        origin_driver="parse.office.anydoc",
        driver_schema_v=1,
        blobs=world.blobs,
    )
    first = decode(
        records_of(earlier),
        sink=sink,
        doc=FragmentDoc(
            doc_key=bytes.fromhex(SHA)[:16],
            source_sha256=bytes.fromhex(SHA),
            normalizer=None,
            uri=URI,
            source_bytes=len(BODY),
            declared=declared(READER),
            model_version="1.1",
        ),
    )
    assert first.record.gen == 1
    with pytest.raises(TargetError) as caught:
        world.read()
    assert caught.value.code() == "OW_TARGET_READ_BACK_FAILED"
    assert str(caught.value) == (
        f"memo@1's read-back was quarantined: the store holds these bytes as document "
        f"{first.record.doc_ord}, and parse.docx.native's parse of them did not commit over it"
    )
    assert (
        caught.value.fix
        == f"ow doc diff {URI}   # the uncommitted read-back is kept for inspection"
    )
    assert world.loop() == (None, [])
    assert world.rows("SELECT gen FROM doc") == [(1,)]


def test_a_head_that_lost_its_addresses_closes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D785's defect, the decoder dropping every block's `x`, is the case this guards."""
    monkeypatch.setattr(fragment_module, "_x", lambda *_: {})
    with pytest.raises(TargetError) as caught:
        world.read()
    assert "the committed document maps [], not ['u01/e1', 'u01/e2', 'u02/e1', 'u02/e2']" in str(
        caught.value
    )
    assert world.loop() == (None, [])


# ---------------------------------------------------------------------------------------------
# Rulings 1 and 3: which reader, and where it runs
# ---------------------------------------------------------------------------------------------


def test_the_reader_is_the_parse_card_the_compile_card_names() -> None:
    from omniweave_core.out.card import CompileCard  # noqa: PLC0415

    card = CompileCard.of(COMPILER)
    assert reader_card([COMPILER, READER], card) is READER
    assert reader_card([COMPILER], card) == (
        "parse.docx.native, compile.docx.native's read_back, is not installed"
    )
    assert reader_card([READER], _with(card, read_back="")) == (
        "compile.docx.native names no read_back"
    )
    assert reader_card([COMPILER], _with(card, read_back="compile.docx.native")) == (
        "compile.docx.native, compile.docx.native's read_back, is not installed"
    ), "a card of another port is not a reader"


def _with(card: Any, **changes: Any) -> Any:
    from dataclasses import replace  # noqa: PLC0415

    return replace(card, **changes)


@dataclass
class Reader:
    """A `parse/1` driver that answers with the refs it was given."""

    kinds: tuple[str, ...]

    def parse(self, unit: UnitRef, parts: Any, io: DriverIO) -> DriverResult:
        del unit, parts
        return DriverResult(
            outcome="ok", produced=tuple(ArtifactRef.of(k, MEMO, io) for k in self.kinds)
        )


def test_in_process_returns_the_one_fragment(tmp_path: Path) -> None:
    io = make_io(MemoryBlobStore(tmp_path / "kit"), tmp_path / "io")
    unit = UnitRef(uri=URI, part="", content_sha256=SHA, byte_len=1)
    reading = in_process(Reader(("doc_fragment", "asset")), io, "parse.docx.native")  # type: ignore[arg-type]
    assert reading(unit) == MEMO
    with pytest.raises(TargetError, match="it produced 2 doc_fragment refs; a parse produces one"):
        in_process(Reader(("doc_fragment",) * 2), io, "parse.docx.native")(unit)  # type: ignore[arg-type]


class Stopped:
    def __init__(self) -> None:
        self.stops = 0

    def stop(self) -> None:
        self.stops += 1


def _worker(tmp_path: Path) -> ReadWorker:
    return ReadWorker(
        card=READER,
        effective_config=READER.config.effective(),
        blobs=BlobStore(tmp_path),
        tmp=tmp_path / "s4",
        settings=subproc.HostSettings(
            worker_idle_ttl_s=300, crash_threshold=3, crash_window_s=60, tick_ms=50,
            max_workers={"free": 4},
        ),
        executable="python",
        env={},
        address="ow-test",
        now_ms=lambda: 0,
    )  # fmt: skip


def test_a_worker_is_stopped_and_its_failure_is_the_read_backs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[subproc.Invocation] = []
    verdict = HostVerdict(
        failure_class=FailureClass.CORRUPT_INPUT, message="no provenance part", permanent=True
    )

    def host(worker: Any, invocation: subproc.Invocation, **_: Any) -> subproc.InvokeReport:
        del worker
        sent.append(invocation)
        return subproc.InvokeReport(
            results=(None,), failures=(verdict,), event=subproc.BatchEvent.CLEAN
        )

    stopped = Stopped()
    monkeypatch.setattr(ReadWorker, "_launch", lambda *_: stopped)
    monkeypatch.setattr(out_back, "read_back_host", host)
    unit = UnitRef(uri=URI, part="", content_sha256=SHA, byte_len=1)
    with pytest.raises(TargetError) as caught:
        _worker(tmp_path)(unit)
    assert str(caught.value) == (
        "the read-back by parse.docx.native failed, and the loop stays open: the worker "
        "answered corrupt_input: no provenance part"
    )
    assert stopped.stops == 1
    [invocation] = sent
    assert (invocation.units, invocation.blob_refs) == (
        (unit,),
        (f"cas://{SHA[:2]}/{SHA[2:4]}/{SHA}",),
    )


def test_a_worker_that_never_answers_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ReadWorker, "_launch", lambda *_: Stopped())
    monkeypatch.setattr(
        out_back,
        "read_back_host",
        lambda *_a, **_k: subproc.InvokeReport(
            results=(None,), failures=(None,), event=subproc.BatchEvent.CLEAN
        ),
    )
    with pytest.raises(TargetError, match="the worker never answered the artefact's unit"):
        _worker(tmp_path)(UnitRef(uri=URI, part="", content_sha256=SHA, byte_len=1))


def test_a_workers_fragment_is_read_from_the_corpus_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io  # noqa: PLC0415

    cas = BlobStore(tmp_path)
    ref = ArtifactRef(
        kind="doc_fragment", byte_len=len(MEMO), blob=format_ref(cas.put(io.BytesIO(MEMO)))
    )
    monkeypatch.setattr(ReadWorker, "_launch", lambda *_: Stopped())
    monkeypatch.setattr(
        out_back,
        "read_back_host",
        lambda *_a, **_k: subproc.InvokeReport(
            results=(DriverResult(outcome="ok", produced=(ref,)),),
            failures=(None,),
            event=subproc.BatchEvent.CLEAN,
        ),
    )
    assert _worker(tmp_path)(UnitRef(uri=URI, part="", content_sha256=SHA, byte_len=1)) == MEMO
