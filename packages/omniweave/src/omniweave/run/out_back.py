"""`read_back_artifact()` -- 02 section 4.3's re-ingest: the loop as a foreign key. **D788.**

02-architecture.md section 4.3 prints the re-ingest table. The target's own `read_back`, an
ordinary `parse/1` driver, reads the artefact. `DocSink` writes it as a `doc`, and "the host"
writes an `artifact_el` row for each block's `x["x.ow.el"]`. `artifact.read_back_doc_ord`, a
foreign key into `doc`, is what closes the loop. 09 Q4 says where this runs at release 1: the
routing policy does not prefer a target's `read_back`, so an ordinary `ow ingest` over the output
root never reaches it, and `artifact_el` is "populated only through `ow out back`". This module is
that step. Its one write is `SqliteArtifactStore.close_loop()` (D751's ruling 6), which had no
caller.

## Rulings

1. **The read_back is the parse card the compile card names.** `[compile.round_trip] read_back`
   is a driver id, found among the discovered `parse/1` cards. A card that names none, or names
   one nothing discovered declares, leaves the loop open, and `reader_card()` says which. That is
   an answer, not an error, because `ow out back`'s restore does not need the loop: owtext, the
   reference target, names `parse.text.owtext`, which nothing ships.
2. **The bytes read are the sealed ones**, out of the corpus CAS by the row's `sha256`. The copy
   placed on `output_root` is not read, because a user may have saved over it. The document's URI
   is that placed path, the one an ingest of the output root would give the same bytes, and its
   key is the content's (`sha256[:16]`), as an ingest's is.
3. **Where the read_back runs is the caller's**, as a compile's `Lowering` is (D772). A `Reading`
   takes the unit and returns the parse's one `doc_fragment`. `in_process()` runs the driver here,
   the tests' seam. `ReadWorker` runs it in an S4 worker launched for one read and stopped after
   it, through `pipeline.read_back_host()`: every parse card asks for `subproc`, and G8 keeps
   `invoke()` in the pipeline.
4. **The addresses are checked before the store is touched.** Each `x.ow.el` names one of the
   artefact's units and stands on exactly one block (R2's "exactly one"). A fragment that breaks
   either writes nothing. One the decoder refuses leaves no committed generation, as a refused
   ingest leaves none. Each is `OW_TARGET_READ_BACK_FAILED`, and the loop stays open.
5. **The document is an ordinary parse's.** Its producer is the read_back card's identity and
   effective configuration, as the parse operator's is. Its operator is the card's
   `parse.<family>`, the spelling a routed parse row carries. Its declared capabilities are the
   card's `[capability.parse]`. Its blocks carry the artefact's `restriction_bits`, because a
   document read out of an artefact holds what the artefact holds (INV-16).
6. **A read-back the store quarantined closes nothing.** When the store already holds these bytes
   as another parse's document (an ingest of the output root, Q4), the read-back is a re-parse.
   Below the rebind threshold the store keeps the earlier generation as the head and the new one
   uncommitted (03:1300). The committed generation must therefore have moved, or the read-back is
   `OW_TARGET_READ_BACK_FAILED`, naming `ow doc diff`, and the loop stays open.
7. **The map is read from the committed head, and is exactly the fragment's addresses.**
   `artifact_el.block_id` is the durable id the store minted, so each address's block is selected
   from the document's head generation. `close_loop()` then sets `read_back_doc_ord` and writes
   the `artifact_el` rows in one transaction.
8. **A generation is read back once.** The row is read again before anything runs, and a loop
   already closed is `OW_TARGET_ARTIFACT_SEALED`, the store's own refusal of a second
   `close_loop()`, raised before the read rather than after a second document generation.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol, cast

from omniweave_core.blobs import format_ref
from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import ModelError, TargetError
from omniweave_core.host import subproc
from omniweave_core.model.records import Producer
from omniweave_core.out.compile import ref_bytes
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.artifact import ArtifactRow, ElRow, ensure_producer
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode, records_of
from omniweave_ports import ArtifactKind, Isolation
from omniweave_ports.types import PartSelector, UnitRef

from omniweave.run.operators.parse import (
    DEFAULT_EGRESS_MODE,
    MAX_OUTPUT_BYTES,
    MODEL_VERSION,
    declared,
)
from omniweave.run.pipeline import read_back_host

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.blobs import BlobStore
    from omniweave_core.canonical import JsonValue
    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.out.card import CompileCard
    from omniweave_core.out.ledger import BlobReader
    from omniweave_core.store.artifact import SqliteArtifactStore, UnitRow
    from omniweave_ports import DriverIO, DriverResult, ParseV1

__all__ = [
    "Closed",
    "ReadWorker",
    "Reading",
    "in_process",
    "read_back_artifact",
    "reader_card",
]

_EL: Final = "x.ow.el"
_FIX_REPORT: Final = "report the target's read_back: ow drivers verify {driver}"
_HELLO_DEADLINES: Final = subproc.Deadlines(progress_ms=0, wall_ms_hard=60_000, deadline_ms=0)
"""The `HELLO` exchange's bound, the parse operator's: a minute to start and activate."""
_DOC_GEN_SQL: Final = "SELECT gen FROM doc WHERE doc_key = ?"
_HEAD_ELS_SQL: Final = (
    "SELECT json_extract(b.x, '$.\"x.ow.el\"'), b.block_id"
    " FROM block b JOIN doc d ON d.doc_ord = b.doc_ord AND b.gen = d.gen"
    " WHERE b.doc_ord = ? AND b.state = 0 AND json_extract(b.x, '$.\"x.ow.el\"') IS NOT NULL"
)


@dataclass(frozen=True, slots=True)
class Closed:
    """Ruling 7: the row with its loop closed, and the `artifact_el` map written beside it."""

    row: ArtifactRow
    els: tuple[ElRow, ...]


class Reading(Protocol):
    """Ruling 3: the read_back over one sealed artefact, wherever it runs: its fragment's bytes."""

    def __call__(self, unit: UnitRef) -> bytes: ...


def reader_card(cards: Sequence[DriverCard], card: CompileCard) -> DriverCard | str:
    """Ruling 1: the parse card `read_back` names, or why the loop cannot close."""
    if not card.read_back:
        return f"{card.driver} names no read_back"
    for one in cards:
        if one.identity.id == card.read_back and str(one.identity.port) == "parse":
            return one
    return f"{card.read_back}, {card.driver}'s read_back, is not installed"


def in_process(reader: ParseV1, io: DriverIO, driver: str) -> Reading:
    """Ruling 3: the read_back `driver` in this process, reading the unit from `io.blobs`."""

    def reading(unit: UnitRef) -> bytes:
        return _fragment(reader.parse(unit, PartSelector(), io), io.blobs, driver)

    return reading


@dataclass(frozen=True, slots=True)
class ReadWorker:
    """Ruling 3: the read_back in an S4 worker, launched for one read and stopped after it.

    `blobs` is the corpus CAS: the worker reads the sealed bytes from it by digest and writes
    the fragment into it.
    """

    card: DriverCard
    effective_config: Mapping[str, JsonValue]
    blobs: BlobStore
    tmp: Path
    settings: subproc.HostSettings
    executable: str
    env: Mapping[str, str]
    address: str
    now_ms: Callable[[], int]
    deadline_ms: int = 0
    spawn: Callable[..., subproc.WorkerProcess] = field(default=subproc.spawn_worker)

    def __call__(self, unit: UnitRef) -> bytes:
        spec = self.card.isolation
        worker = self._launch()
        try:
            report = read_back_host(
                worker,
                subproc.Invocation(
                    invoke_id=f"read-back-{unit.content_sha256[:16]}",
                    units=(unit,),
                    deadline_ms=self.deadline_ms,
                    budget_micros=0,
                    blob_refs=(format_ref(unit.content_sha256),),
                ),
                deadlines=subproc.Deadlines(
                    progress_ms=spec.progress_ms,
                    wall_ms_hard=spec.wall_ms_hard,
                    deadline_ms=self.deadline_ms,
                ),
                memory_mb=spec.memory_mb,
            )
        finally:
            worker.stop()
        result, failure = report.results[0], report.failures[0]
        if failure is not None:
            raise _failed(
                self.card.identity.id,
                f"the worker answered {failure.failure_class.value}: {failure.message}",
            )
        if result is None:
            raise _failed(self.card.identity.id, "the worker never answered the artefact's unit")
        return _fragment(result, self.blobs, self.card.identity.id)

    def _launch(self) -> subproc.Worker:
        card = self.card
        self.tmp.mkdir(parents=True, exist_ok=True)
        isolation, _shortfalls = subproc.grant_isolation(
            mode=Isolation.SUBPROC,
            batch_max_units=card.isolation.batch_max_units,
            platform=sys.platform,
            address_space_capped=sys.platform == "win32" and card.isolation.memory_mb > 0,
            net_blocked_requested=not card.hardware.needs_network,
            cpu_cap_requested=False,
            fd_cap_requested=False,
        )
        port = f"{card.identity.port.value}/{card.identity.port_major}"
        hello = {
            "port": port,
            "card_schema": card.card_schema,
            "card_sha256": card.card_sha256,
            "driver_id": card.identity.id,
            "effective_config": dict(self.effective_config),
            "roots": {"source_ro": str(self.blobs.root), "tmp": str(self.tmp)},
            "blob_base": str(self.blobs.root),
            "isolation_granted": dict(isolation.as_header()),
            "traceparent": "",
            "max_output_bytes": MAX_OUTPUT_BYTES,
            "egress_mode": DEFAULT_EGRESS_MODE,
            "card_source": card.source,
            "card_origin": card.origin,
        }
        worker, _ack = subproc.launch(
            subproc.WorkerKey(card.identity.id, sha256_canonical(dict(self.effective_config))),
            subproc.SpawnRequest(
                argv=subproc.worker_argv(self.executable, self.address),
                cwd=str(self.tmp),
                env=dict(self.env),
                address=self.address,
            ),
            hello=hello,
            expect={
                "driver_id": card.identity.id,
                "version": card.identity.version,
                "schema_version": card.identity.schema_version,
                "port": port,
            },
            deadlines=_HELLO_DEADLINES,
            settings=self.settings,
            now_ms=self.now_ms,
            memory_mb=card.isolation.memory_mb,
            spawn=self.spawn,
        )
        return worker


def read_back_artifact(
    row: ArtifactRow,
    *,
    units: Sequence[UnitRow],
    card: DriverCard,
    effective_config: Mapping[str, JsonValue],
    reading: Reading,
    thread: store_sqlite.StoreThread,
    blobs: BlobStore,
    artifacts: SqliteArtifactStore,
    uri: str,
) -> Closed:
    """Rulings 2-7: read the sealed bytes back, write the document, and close the loop."""
    driver = card.identity.id
    current = artifacts.get(row.slug, row.artifact_gen)
    if current.read_back_doc_ord is not None:
        raise TargetError(
            f"{row.slug}@{row.artifact_gen} was already read back, as document "
            f"{current.read_back_doc_ord}",
            symbol="OW_TARGET_ARTIFACT_SEALED",
            fix=f"ow out back {row.slug}   # reports the closed loop and restores",
        )
    sha = row.sha256.removeprefix("sha256:")
    fragment = reading(
        UnitRef(
            uri=uri, part="", content_sha256=sha, byte_len=row.byte_len, media_type=row.media_type
        )
    )
    try:
        records = list(records_of(fragment))
    except ModelError as refused:
        raise _failed(driver, f"its fragment is not owdoc-fragment/1: {refused}") from refused
    addresses = _addresses(records, {u.unit for u in units}, driver)
    doc_key = bytes.fromhex(sha)[:16]
    before = cast("tuple[int] | None", _read(thread, _DOC_GEN_SQL, (doc_key,), one=True))
    producer = Producer(
        operator=".".join(driver.split(".")[:2]),
        op_version=card.identity.schema_version,
        code_fingerprint="",
        options_digest=bytes.fromhex(sha256_canonical(dict(effective_config))),
    )
    producer_id = cast(
        "int",
        thread.run(
            store_sqlite.Unit(
                name="out.back.producer",
                run=lambda connection: ensure_producer(connection, producer),
                cost_class="free",
            )
        ),
    )
    sink = DocSink(
        thread,
        producer_id=producer_id,
        origin_operator=producer.operator,
        origin_driver=driver,
        driver_schema_v=card.identity.schema_version,
        blobs=blobs,
        restriction_bits=row.restriction_bits,
    )
    try:
        decoded = decode(
            records,
            sink=sink,
            doc=FragmentDoc(
                doc_key=doc_key,
                source_sha256=bytes.fromhex(sha),
                normalizer=None,
                uri=uri,
                source_bytes=row.byte_len,
                declared=declared(card),
                model_version=MODEL_VERSION,
            ),
        )
    except ModelError as refused:
        raise _failed(driver, f"the store refused its fragment: {refused}") from refused
    doc_ord = decoded.record.doc_ord
    if decoded.record.gen <= (0 if before is None else before[0]):
        raise TargetError(
            f"{row.slug}@{row.artifact_gen}'s read-back was quarantined: the store holds these "
            f"bytes as document {doc_ord}, and {driver}'s parse of them did not commit over it",
            symbol="OW_TARGET_READ_BACK_FAILED",
            fix=f"ow doc diff {uri}   # the uncommitted read-back is kept for inspection",
        )
    head = dict(cast("list[tuple[str, int]]", _read(thread, _HEAD_ELS_SQL, (doc_ord,))))
    if sorted(head) != sorted(addresses):
        raise _failed(
            driver, f"the committed document maps {sorted(head)}, not {sorted(addresses)}"
        )
    els = tuple(ElRow(unit=el.split("/", 1)[0], el=el, block_id=head[el]) for el in sorted(head))
    return Closed(artifacts.close_loop(row.artifact_id, doc_ord, els), els)


def _addresses(records: Sequence[Mapping[str, Any]], units: set[str], driver: str) -> list[str]:
    """Ruling 4: every block's address, each once and each in one of the artefact's units."""
    found = [
        str(x[_EL])
        for record in records
        if record.get("t") == "block"
        for x in [record.get("x") or {}]
        if isinstance(x, Mapping) and _EL in x
    ]
    twice = sorted(el for el, n in Counter(found).items() if n > 1)
    if twice:
        raise _failed(driver, f"it places {twice} on more than one block; R2 asks for one")
    stray = sorted({el for el in found if el.split("/", 1)[0] not in units})
    if stray:
        raise _failed(driver, f"{stray} name no unit the artefact sealed ({sorted(units)})")
    return found


def _fragment(result: DriverResult, blobs: BlobReader, driver: str) -> bytes:
    """Ruling 3: the parse's one `doc_fragment`, read inline or from the CAS."""
    refs = [r for r in result.produced if r.kind == ArtifactKind.DOC_FRAGMENT]
    if len(refs) != 1:
        raise _failed(driver, f"it produced {len(refs)} doc_fragment refs; a parse produces one")
    return ref_bytes(refs[0], blobs)


def _read(
    thread: store_sqlite.StoreThread, sql: str, params: tuple[Any, ...], *, one: bool = False
) -> object:
    def run(connection: Any) -> object:  # the store thread's connection (G8: no sqlite3 here)
        cursor = connection.execute(sql, params)
        return cursor.fetchone() if one else cursor.fetchall()

    return thread.run(store_sqlite.Unit(name="out.back.read", run=run, cost_class="free"))


def _failed(driver: str, detail: str) -> TargetError:
    return TargetError(
        f"the read-back by {driver} failed, and the loop stays open: {detail}",
        symbol="OW_TARGET_READ_BACK_FAILED",
        fix=_FIX_REPORT.format(driver=driver),
    )
