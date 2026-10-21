"""A Tier A fixture's labels: its assertions file, and the candidate text they are judged over.
**D912.**

13-quality.md section 8.1 defines an assertion as *"a claim about one page of one document"* and
the charter's `eval_assertion` DDL gives its row (`store.oweval.Assertion`). The plan names no file
an assertion is written in for a committed fixture: section 4.4's sidecar declares a fixture's
`slices` and the metrics it `asserts`, and Tier B's assertions arrive in a fetched corpus. Until
now no Tier A file carried one, so `judge()` (D827) and `rollup()` (D816) were called by nothing
but their tests.

## Rulings

1. **A fixture's assertions are `<file>.assertions.toml` beside it**, as its `.meta.toml` sidecar
   is. TOML and not JSONL, because a reviewer verifies an assertion by editing one key of one row,
   and a TOML row is a few lines that diff as such. The file holds `schema =
   "omniweave.assertions/1"` and one `[[assertion]]` table per assertion.
2. **A row is `id`, `type`, the row keys, and the type's own spec keys.** `id` is unique in the
   file. The row keys are `page` (1-based, as a reader counts; absent is the whole document),
   `checked`, `max_diffs` (default 0), `slices`, `addr` and `evaluable_in`. Every other key is the
   assertion's `spec`, which the evaluator for its type reads: `text` for `present` and `absent`,
   `before` and `after` for `order`, and `cell` with its relations for `table` (D825). A type
   outside 13:998-1013's fifteen, a row key of the wrong shape, or a repeated `id` is a
   `QualityError` naming the file and the row.
3. **`checked` is absent until a reviewer writes it.** TOML has no null, so an absent `checked`
   is the DDL's NULL: the assertion runs and never scores (13:1022). `verified` and `rejected`
   are the only values. A drafted assertion is therefore inert until someone signs it.
4. **An assertion's slices are its own, else its fixture's sidecar's** (`[fixture.tests] slices`),
   else none. A gate row's slice is matched against them (13:1148).
5. **Identity is the corpus's.** `assertion_id` is `<corpus_id>/<relpath>#<id>@<version>`, so a
   changed corpus names new assertions rather than editing immutable ones (`store.oweval` ruling
   6), as the roundtrip suite's ids do. `doc` is the fixture's path relative to its fixture
   directory, POSIX. `derived_from_sha256` is the fixture's sha256, the bytes the assertion was
   written about (Q-G26). `evaluable_in` defaults to `owdoc` for the five owdoc-only types and
   `text` for the rest.
6. **The candidate is what a reader of the corpus gets.** A parse's fragment is decoded into a
   scratch store exactly as `ow add` writes one, and each page is `Doc.serialize("md")` over that
   page, the Markdown `ow` serves. So a `table` assertion meets a Markdown table, and `order` the
   serialized reading order, never the driver's raw record order. Pages are keyed 1-based to
   match ruling 2. The store's declared capabilities are the card's `[capability.parse]`, as the
   host's are, and the fixture's bytes are its retained source part, so a verbatim claim is
   checked as `ow add` checks it. A parse the store quarantines is a `QualityError`, never a
   document with no pages: every assertion on it would fail as a dropped page.

Specified in 13-quality.md sections 4.4, 8.1 and 8.3, and the charter's `eval_assertion` DDL.
"""

from __future__ import annotations

import hashlib
import io
import re
import tomllib
from typing import TYPE_CHECKING, Any, Final, cast

from omniweave_core.blobs import BlobStore
from omniweave_core.errors import ModelError, QualityError
from omniweave_core.model.block import Capabilities
from omniweave_core.model.doc import Doc
from omniweave_core.model.records import Producer
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.artifact import ensure_producer
from omniweave_core.store.doc import DocSink
from omniweave_core.store.docread import StoreDocReader
from omniweave_core.store.fragment import FragmentDoc, decode, records_of
from omniweave_core.store.oweval import Assertion

from omniweave_conform.assertions import OWDOC_ONLY

if TYPE_CHECKING:
    from pathlib import Path
    from typing import BinaryIO

    from omniweave_core.drivers.card import DriverCard
    from omniweave_ports import ArtifactRef

    from omniweave_conform.harness import ParseRun

__all__ = ["SCHEMA", "SUFFIX", "TYPES", "candidate", "labels_of", "load"]

SUFFIX: Final = ".assertions.toml"
"""Ruling 1: `<file>.assertions.toml` beside the fixture."""
SCHEMA: Final = "omniweave.assertions/1"
TYPES: Final = frozenset(
    {
        "baseline", "present", "absent", "order", "table", "math", "format", "footnote",
        "cell_rel", "field", "span", "cite", "roundtrip", "absent_field", "null_kept",
    }
)  # fmt: skip
"""13-quality.md:998-1013's fifteen assertion types."""
CHECKED: Final = frozenset({"verified", "rejected"})
_ROW: Final = frozenset({"id", "type", "page", "checked", "max_diffs", "slices", "addr"})
_EVALUABLE: Final = frozenset({"owdoc", "text", "both"})
_ID: Final = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_SIDECAR: Final = ".meta.toml"
_NOW_NS: Final = 0
"""The scratch store's migration clock: the store is thrown away, so no instant is recorded."""
_FIX: Final = "see packages/omniweave-conform/src/omniweave_conform/labels.py's rulings"


def labels_of(fixture: Path) -> Path:
    """Ruling 1: the assertions file a fixture's labels live in."""
    return fixture.with_name(fixture.name + SUFFIX)


def load(
    fixture: Path, *, fixtures_dir: Path, corpus_id: str, corpus_version: str
) -> tuple[Assertion, ...]:
    """Rulings 1-5: the fixture's assertions, or `()` when it carries no assertions file."""
    path = labels_of(fixture)
    if not path.is_file():
        return ()
    where = path.name
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise QualityError(f"{where} does not load: {error}", fix=_FIX) from error
    if raw.get("schema") != SCHEMA:
        raise QualityError(f"{where}: schema is {raw.get('schema')!r}, not {SCHEMA!r}", fix=_FIX)
    if set(raw) - {"schema", "assertion"}:
        raise QualityError(
            f"{where}: unknown key(s) {sorted(set(raw) - {'schema', 'assertion'})}", fix=_FIX
        )
    rows = raw.get("assertion", [])
    if not isinstance(rows, list):
        raise QualityError(f"{where}: [[assertion]] is an array of tables", fix=_FIX)
    doc = fixture.relative_to(fixtures_dir).as_posix()
    sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
    default_slices = _sidecar_slices(fixture)
    seen: set[str] = set()
    out = []
    for at, row in enumerate(rows, 1):
        assertion = _assertion(
            row, where=f"{where} [[assertion]] #{at}", doc=doc, sha256=sha256, slices=default_slices
        )
        local = assertion.assertion_id
        if local in seen:
            raise QualityError(f"{where}: id {local!r} repeats", fix=_FIX)
        seen.add(local)
        out.append(
            Assertion(
                assertion_id=f"{corpus_id}/{doc}#{local}@{corpus_version}",
                corpus_id=corpus_id,
                corpus_version=corpus_version,
                doc=assertion.doc,
                page=assertion.page,
                type=assertion.type,
                spec=assertion.spec,
                addr=assertion.addr,
                evaluable_in=assertion.evaluable_in,
                checked=assertion.checked,
                derived_from_sha256=assertion.derived_from_sha256,
                max_diffs=assertion.max_diffs,
                slices=assertion.slices,
            )
        )
    return tuple(out)


def _assertion(
    row: object, *, where: str, doc: str, sha256: str, slices: tuple[str, ...]
) -> Assertion:
    """Ruling 2's one row, its `assertion_id` still the file-local `id`."""
    if not isinstance(row, dict):
        raise QualityError(f"{where} is not a table", fix=_FIX)
    local, kind = row.get("id"), row.get("type")
    if not isinstance(local, str) or _ID.fullmatch(local) is None:
        raise QualityError(f"{where}: id {local!r} is not [a-z0-9._-], 1-64 long", fix=_FIX)
    if kind not in TYPES:
        raise QualityError(
            f"{where} ({local}): type {kind!r} is not one of 13:998-1013's", fix=_FIX
        )
    page = row.get("page")
    if page is not None and (isinstance(page, bool) or not isinstance(page, int) or page < 1):
        raise QualityError(f"{where} ({local}): page {page!r} is a 1-based page number", fix=_FIX)
    checked = row.get("checked")
    if checked is not None and checked not in CHECKED:
        raise QualityError(
            f"{where} ({local}): checked {checked!r} is verified or rejected, or absent",
            fix=_FIX,
        )
    max_diffs = row.get("max_diffs", 0)
    if isinstance(max_diffs, bool) or not isinstance(max_diffs, int) or max_diffs < 0:
        raise QualityError(f"{where} ({local}): max_diffs {max_diffs!r} is an int >= 0", fix=_FIX)
    own = row.get("slices")
    if own is not None and (
        not isinstance(own, list) or not all(isinstance(s, str) and s for s in own)
    ):
        raise QualityError(f"{where} ({local}): slices is a list of slice names", fix=_FIX)
    addr = row.get("addr")
    if addr is not None and not isinstance(addr, str):
        raise QualityError(f"{where} ({local}): addr is a string", fix=_FIX)
    evaluable = row.get("evaluable_in", "owdoc" if kind in OWDOC_ONLY else "text")
    if evaluable not in _EVALUABLE:
        raise QualityError(
            f"{where} ({local}): evaluable_in {evaluable!r} is not one of {sorted(_EVALUABLE)}",
            fix=_FIX,
        )
    return Assertion(
        assertion_id=local,
        corpus_id="",
        corpus_version="",
        doc=doc,
        page=page,
        type=str(kind),
        spec={k: v for k, v in row.items() if k not in _ROW and k != "evaluable_in"},
        addr=addr,
        evaluable_in=str(evaluable),
        checked=checked,
        derived_from_sha256=sha256,
        max_diffs=max_diffs,
        slices=tuple(own) if own is not None else slices,
    )


def _sidecar_slices(fixture: Path) -> tuple[str, ...]:
    """Ruling 4: `[fixture.tests] slices` from the fixture's `.meta.toml`, or none."""
    sidecar = fixture.with_name(fixture.name + _SIDECAR)
    if not sidecar.is_file():
        return ()
    tests = tomllib.loads(sidecar.read_text(encoding="utf-8")).get("fixture", {}).get("tests", {})
    slices = tests.get("slices", []) if isinstance(tests, dict) else []
    return tuple(str(s) for s in slices if isinstance(s, str))


def candidate(
    parse: ParseRun, card: DriverCard, *, doc: str, workdir: Path
) -> dict[tuple[str, int], str]:
    """Ruling 6: each page of the parse as `ow` serves it, keyed `(doc, page)`, 1-based."""
    path = workdir / "candidate.owstore"
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
                    name="labels.producer",
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
        try:
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
        except ModelError as refused:
            raise QualityError(
                f"{doc}: the store refused {card.identity.id}'s fragment: {refused}",
                fix=f"ow conform {card.identity.id}   # the fragment suite names the record",
            ) from refused
    record, pages = decoded.record, decoded.pages
    if record.gen == 0:
        raise QualityError(
            f"{doc}: the store quarantined {card.identity.id}'s parse, so there is no page to "
            "judge; a quarantined parse is not an empty one",
            fix=f"ow conform {card.identity.id}   # the fragment suite names the failed clause",
        )
    reader = store_sqlite.connect_readonly(path)
    try:
        handle = Doc(StoreDocReader(reader), record.doc_ord, record.gen)
        return {
            (doc, page + 1): handle.serialize("md", pages=range(page, page + 1))[0]
            for page in range(pages)
        }
    finally:
        reader.close()


def _open(parse: ParseRun, ref: ArtifactRef) -> BinaryIO:
    """Ruling 6: a blob-backed asset's bytes, from the store the parse wrote it into."""
    if parse.blobs is None:
        raise QualityError("the parse kept no blob store to read its assets from", fix=_FIX)
    return parse.blobs.open(str(ref.blob).removeprefix("cas://"))


def _declared(card: DriverCard) -> Capabilities:
    """Ruling 6: the card's `[capability.parse]` as the fifteen fields, as the host builds them
    (`omniweave.run.operators.parse.declared`, which this layer may not import)."""
    caps: Any = card.parse
    names = Capabilities.__dataclass_fields__
    return Capabilities(**{name: getattr(caps, name) for name in names if hasattr(caps, name)})
