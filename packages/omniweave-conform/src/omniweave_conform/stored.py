"""A parse decoded through the host's own `DocSink` into a scratch store. D912, D939.

`labels.candidate()` (D912) has decoded a parse into a throwaway `.owstore` since the labelled
parse suite landed, so a label is judged against the document `ow` would serve. D939 moves the
decode here, because the `contract` suite asks the same question of every fixture: is the fragment
a driver returned one the host stores? The conformance template answered no three ways while
passing all eleven suites (D935, D938), because no suite asked.

## Rulings

1. **The decode is the host's**: `store.fragment.decode()` into a real `DocSink` over a freshly
   migrated store, with the blob store the parse wrote its assets into, and the fixture's own bytes
   as the retained source part, so a verbatim claim is checked as `ow add` checks it.
2. **A refusal is the `ModelError` the host raises**, unchanged, for the caller to report. A parse
   the sink quarantines (`gen == 0`) is returned, not raised: the caller says which it is.
3. **The producer is the card's operator** (`parse.<family>`), at the card's `schema_version`, as
   the host's parse operator names it, with no code fingerprint, because nothing here is cached.

Specified in 04-driver-system.md section 6.5 and 03-document-model.md section 17.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.blobs import BlobStore
from omniweave_core.errors import QualityError
from omniweave_core.model.block import Capabilities
from omniweave_core.model.records import Producer
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.artifact import ensure_producer
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode, records_of

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.model.records import DocRecord
    from omniweave_ports import ArtifactRef

    from omniweave_conform.harness import ParseRun

__all__ = ["STORE", "Stored", "into_store"]

STORE: Final = "candidate.owstore"
"""The store `into_store()` writes into its `workdir`."""

_NOW_NS: Final = 0
"""The scratch store's migration clock: the store is thrown away, so no instant is recorded."""

_FIX: Final = "see packages/omniweave-conform/src/omniweave_conform/stored.py's rulings"


@dataclass(frozen=True, slots=True)
class Stored:
    """Where the decoded document is, its `doc` record, and how many pages it has."""

    path: Path
    record: DocRecord
    pages: int

    @property
    def quarantined(self) -> bool:
        """Ruling 2: the sink kept no visible generation."""
        return self.record.gen == 0


def into_store(parse: ParseRun, card: DriverCard, *, workdir: Path) -> Stored:
    """Rulings 1-3: `parse`'s fragment through the host's `DocSink`. Raises `ModelError` when the
    host refuses it."""
    path = workdir / STORE
    cas = workdir / "cas"
    cas.mkdir(parents=True, exist_ok=True)
    connection = store_sqlite.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=_NOW_NS)
    finally:
        connection.close()
    operator = ".".join(card.identity.id.split(".")[:2])
    producer = Producer(
        operator=operator,
        op_version=card.identity.schema_version,
        code_fingerprint="",
        options_digest=b"\0",
    )
    sha = bytes.fromhex(parse.fixture.digest.removeprefix("sha256:"))
    with store_sqlite.StoreThread(lambda: store_sqlite.connect(path)) as thread:
        producer_id = cast(
            "int",
            thread.run(
                store_sqlite.Unit(
                    name="stored.producer",
                    run=lambda conn: ensure_producer(conn, producer),
                    cost_class="free",
                )
            ),
        )
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator=operator,
            origin_driver=card.identity.id,
            driver_schema_v=card.identity.schema_version,
            blobs=BlobStore(cas),
        )
        decoded = decode(
            list(records_of(parse.body)),
            sink=sink,
            assets=[ref for ref in parse.result.produced if ref.kind == "asset"],
            open_ref=lambda ref: _open(parse, ref),
            open_part=lambda digest: io.BytesIO(parse.fixture.data) if digest == sha else None,
            doc=FragmentDoc(
                doc_key=sha[:16],
                source_sha256=sha,
                normalizer=None,
                uri=parse.fixture.path.as_uri(),
                source_bytes=len(parse.fixture.data),
                declared=_declared(card),
                model_version="1.1",
            ),
        )
    return Stored(path=path, record=decoded.record, pages=decoded.pages)


def _open(parse: ParseRun, ref: ArtifactRef) -> BinaryIO:
    """Ruling 1: a blob-backed asset's bytes, from the store the parse wrote it into."""
    if parse.blobs is None:
        raise QualityError("the parse kept no blob store to read its assets from", fix=_FIX)
    return parse.blobs.open(str(ref.blob).removeprefix("cas://"))


def _declared(card: DriverCard) -> Capabilities:
    """The card's `[capability.parse]` as the fifteen fields, as the host builds them
    (`omniweave.run.operators.parse.declared`, which this layer may not import)."""
    caps: Any = card.parse
    names = Capabilities.__dataclass_fields__
    return Capabilities(**{name: getattr(caps, name) for name in names if hasattr(caps, name)})
