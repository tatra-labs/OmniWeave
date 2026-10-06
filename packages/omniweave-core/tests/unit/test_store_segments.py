"""`store/segments.py` end to end: a real `DocSink` generation, the real segmenter, the rows.

A fragment goes through `fragment.decode` into a store; `build_view` reads it back as the document
form of `owgraph-segment/1`; `SpineSegmenter` answers in process; `decode_segments` and
`write_segments` write `segmenter`, `segment` and `segment_block`; and `ow store verify`'s
`segment_digest` clause recomputes every digest from the rows. D663.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the writer wrote.
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import GraphError
from omniweave_core.model.block import Capabilities
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode
from omniweave_core.store.segments import (
    SegmenterIdentity,
    SegmentView,
    build_view,
    decode_segments,
    write_segments,
)
from omniweave_core.store.verify import verify_store
from omniweave_graph.segment.driver import SpineSegmenter
from omniweave_ports.types import DeriveScope, UnitRef

NOW_NS = 1_700_000_000_000_000_000
DECLARED = Capabilities(
    spatial="none",
    origin_span="none",
    text_span=False,
    marks=False,
    reading_order="source",
    sections="outline_from_source",
    tables="cells_with_spans",
    math=frozenset(),
    assets="none",
    asset_origin=False,
    notes="linked",
    confidence="none",
    furniture="destroyed",
    round_trip="structure",
)
SPINE = SegmenterIdentity("derive.segment.spine", 1, {})


def block(tmp: str, text: str | None, kind: str = "paragraph", **extra: Any) -> dict[str, Any]:
    return {
        "t": "block",
        "tmp": tmp,
        "parent": None,
        "page": 0,
        "kind": kind,
        "layer": "body",
        "text": text,
        "quote": "normalized",
        "trust": "extracted",
        "method": "native_xml",
        "os": {"k": "none"},
        "quad": None,
        "marks": [],
        "payload": None,
        **extra,
    }


def memo(second: str = "The second section's only paragraph.") -> list[dict[str, Any]]:
    """Two sections, a list, a 2x2 table with a header row, and a footnote.

    The list is what makes reading order differ from 06:1002's `(page, ord)`: its items are
    `ord` 0 and 1 under the list, beside a heading and a paragraph at `ord` 0 and 1 on the page.
    The paragraph is `inferred` and `synthetic` (a claim no clamp raises) so a Segment's minima
    are not every member's value.
    """
    cells = [
        block(f"c{r}{c}", f"r{r}c{c}", "table_cell", parent="t", cell={"r": r, "c": c})
        for r in range(2)
        for c in range(2)
    ]
    return [
        {"t": "doc", "format": "docx", "media_type": "application/x-test", "page_count": 1},
        {"t": "page", "page": 0, "page_kind": "stream", "method": "native_xml"},
        block("h1", "One", "heading", payload={"level": 1}),
        block("p1", "The first section's paragraph.", trust="inferred", quote="synthetic"),
        block("l", None, "list"),
        block("li0", "Item one.", "list_item", parent="l"),
        block("li1", "Item two.", "list_item", parent="l"),
        block("t", None, "table", payload={"header_rows": 1}),
        *cells,
        block("h2", "Two", "heading", payload={"level": 1}),
        block("p2", second),
        block("n1", "A footnote.", "footnote", layer="note"),
        {"t": "end", "status": "ok", "page_stats": {"0": {"blocks": 11}}},
    ]


def store(tmp_path: Path) -> tuple[Path, BlobStore, int]:
    path = tmp_path / "index.owstore"
    (tmp_path / "cas").mkdir()
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        cursor = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('parse.office', 1, '', X'00')"
        )
        producer_id = int(cursor.lastrowid or 0)
    finally:
        connection.close()
    return path, BlobStore(tmp_path / "cas"), producer_id


def ingest(path: Path, blobs: BlobStore, producer_id: int, records: list[dict[str, Any]]) -> int:
    """One generation of the one document. Returns its `gen`."""
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=producer_id,
            origin_operator="parse.office",
            origin_driver="parse.office.anydoc",
            driver_schema_v=1,
            blobs=blobs,
        )
        doc = FragmentDoc(
            doc_key=b"\x01" * 16,
            source_sha256=bytes([len(json.dumps(records)) % 251]) * 32,
            normalizer=None,
            uri="c:/docs/memo.docx",
            source_bytes=100,
            declared=DECLARED,
            model_version="1.1",
        )
        return decode(records, sink=sink, doc=doc).record.gen


def answer(view: SegmentView, tmp: Path, **config: Any) -> bytes:
    """The real segmenter, in process, over the view's bytes."""
    blobs = MemoryBlobStore(tmp / "kit")
    unit = UnitRef(
        uri="view", part="", content_sha256=blobs.add(view.body), byte_len=len(view.body)
    )
    result = SpineSegmenter(**config).derive(
        DeriveScope(lane="segment", units=(unit,), allowed_cites=frozenset()),
        make_io(blobs, tmp / "kit-tmp"),
    )
    [ref] = result.produced
    return ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()


def segment_doc(path: Path, tmp: Path, gen: int, **config: Any) -> Any:
    connection = ow.connect(path)
    try:
        view = build_view(connection, 1, gen)
        decoded = decode_segments(answer(view, tmp, **config), view)
        connection.execute("BEGIN IMMEDIATE")
        report = write_segments(
            connection,
            view,
            SegmenterIdentity("derive.segment.spine", 1, config),
            decoded,
            origin_operator="derive.segment",
        )
        connection.execute("COMMIT")
        return report
    finally:
        connection.close()


def rows(path: Path, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()


def digests_verify(path: Path, disagree: int = 1) -> int:
    """Run verify's digest clause; `disagree` is the Segments whose members are not in
    `(page, ord)` order -- the list's, which verify reports by design (D663's fifth ruling)."""
    connection = ow.connect(path)
    try:
        report = verify_store(connection, now_ns=NOW_NS, clauses=["segment_digest"])
    finally:
        connection.close()
    [clause] = report.clauses
    assert not clause.findings, clause.findings
    assert clause.counts.get("member_order_disagreements", 0) == disagree
    return clause.checked


@pytest.fixture
def one(tmp_path: Path) -> tuple[Path, BlobStore, int]:
    path, blobs, producer = store(tmp_path)
    assert ingest(path, blobs, producer, memo()) == 1
    return path, blobs, producer


# ---------------------------------------------------------------------------
# the view
# ---------------------------------------------------------------------------


def test_the_view_is_reading_order_with_sections_defaults_and_table_geometry(one: Any) -> None:
    path, _, _ = one
    connection = ow.connect(path)
    try:
        view = build_view(connection, 1, 1)
    finally:
        connection.close()
    frames = [json.loads(line) for line in view.body.splitlines()]
    head = frames[0]
    assert head["doc"] == "d1"
    assert sorted(head["sections"].values()) == ["One", "Two"]
    assert head["defaults"]["layer"] == "body"
    texts = [f.get("text", f["kind"]) for f in frames[1:]]
    assert texts == [
        "One",
        "The first section's paragraph.",
        "Item one.",
        "Item two.",
        "table",
        "r0c0",
        "r0c1",
        "r1c0",
        "r1c1",
        "Two",
        "The second section's only paragraph.",
        "A footnote.",
    ]
    table = frames[5]
    assert table["grid"] == {"n_rows": 2, "n_cols": 2, "header_rows": 1}
    assert frames[6]["table"] == {"table_cite": table["cite"], "r": 0, "c": 0}
    assert frames[-1]["layer"] == "note"
    assert not {"layer", "page", "sec"} & set(frames[2]), "a default is elided"
    assert table["cite"] in view.tables and table["cite"] not in view.members
    assert len(view.members) == 11


# ---------------------------------------------------------------------------
# the rows
# ---------------------------------------------------------------------------


def test_a_generation_is_written_whole_and_every_digest_verifies(one: Any, tmp_path: Path) -> None:
    path, _, _ = one
    report = segment_doc(path, tmp_path, 1)
    assert (report.created, report.kept, report.retired) == (4, 0, 0)
    segs = rows(
        path,
        "SELECT ord, atom, heading_path, n_blocks, n_chars, tokenizer_id, origin_driver "
        "FROM segment ORDER BY ord",
    )
    assert [(s[0], s[1], json.loads(s[2]), s[3]) for s in segs] == [
        (0, None, ["One"], 4),
        (1, "table", ["One"], 4),
        (2, None, ["Two"], 2),
        (3, None, ["Two"], 1),
    ]
    assert segs[0][4] == len("OneThe first section's paragraph.Item one.Item two.")
    assert {s[5] for s in segs} == {"ow.bytes4/1"}
    assert {s[6] for s in segs} == {"derive.segment.spine"}
    assert rows(path, "SELECT count(*) FROM segment_block") == [(11,)]
    assert rows(path, "SELECT count(*) FROM ow_segment_head") == [(4,)]
    assert digests_verify(path) == 4


def test_the_derived_columns_are_the_members_minima_unions_and_layer(
    one: Any, tmp_path: Path
) -> None:
    path, _, _ = one
    segment_doc(path, tmp_path, 1)
    [(mask, trust, quote, layer)] = rows(
        path, "SELECT kind_mask, trust, quote_min, layer FROM segment WHERE ord = 3"
    )
    [(footnote,)] = rows(
        path, "SELECT ord FROM enum_val WHERE domain = 'kind' AND name = 'footnote'"
    )
    [(note,)] = rows(path, "SELECT ord FROM enum_val WHERE domain = 'layer' AND name = 'note'")
    assert (mask, layer) == (1 << footnote, note)
    [(block_trust, block_quote)] = rows(
        path, "SELECT trust, quote FROM block WHERE text = 'A footnote.'"
    )
    assert (trust, quote) == (block_trust, block_quote)
    [(first_trust, first_quote)] = rows(path, "SELECT trust, quote_min FROM segment WHERE ord = 0")
    assert (first_trust, first_quote) == (1, 0), "the paragraph's inferred and synthetic"


def test_a_new_generation_keeps_the_segments_whose_digest_held(one: Any, tmp_path: Path) -> None:
    """One paragraph edited: three Segments keep their ids and move to gen 2; one is replaced."""
    path, blobs, producer = one
    segment_doc(path, tmp_path / "g1", 1)
    before = dict(rows(path, "SELECT ord, segment_id FROM segment"))
    assert ingest(path, blobs, producer, memo("The second section, edited.")) == 2
    report = segment_doc(path, tmp_path / "g2", 2)
    assert (report.kept, report.created, report.retired) == (3, 1, 1)
    after = dict(rows(path, "SELECT ord, segment_id FROM ow_segment_head"))
    assert [after[o] == before[o] for o in range(4)] == [True, True, False, True]
    [(state, ord_, sid)] = rows(
        path, "SELECT state, ord, segment_id FROM segment WHERE segment_id = ?", before[2]
    )
    assert (state, ord_) == (1, -sid)
    assert rows(path, "SELECT count(*) FROM segment_block WHERE segment_id = ?", before[2]) == [
        (0,)
    ]
    assert digests_verify(path) == 4


def test_segmenting_one_generation_twice_changes_nothing(one: Any, tmp_path: Path) -> None:
    path, _, _ = one
    segment_doc(path, tmp_path / "a", 1)
    first = rows(path, "SELECT * FROM segment ORDER BY segment_id")
    report = segment_doc(path, tmp_path / "b", 1)
    assert (report.kept, report.created, report.retired) == (4, 0, 0)
    assert rows(path, "SELECT * FROM segment ORDER BY segment_id") == first
    assert rows(path, "SELECT count(*) FROM segmenter") == [(1,)]


def test_other_params_are_another_segmenter_and_new_segments(one: Any, tmp_path: Path) -> None:
    path, _, _ = one
    segment_doc(path, tmp_path / "a", 1)
    report = segment_doc(path, tmp_path / "b", 1, target_tokens=1000)
    assert (report.kept, report.created, report.retired) == (0, 4, 4)
    assert rows(path, "SELECT count(*) FROM segmenter") == [(2,)]
    assert digests_verify(path) == 4


def test_a_synopsis_leaves_its_cells_out_and_records_the_diag(one: Any, tmp_path: Path) -> None:
    path, _, _ = one
    report = segment_doc(path, tmp_path, 1, table_synopsis_cells=3)
    assert report.diags == 1
    [(synopsis_of, n_blocks)] = rows(
        path, "SELECT synopsis_of, n_blocks FROM segment WHERE synopsis_of IS NOT NULL"
    )
    assert rows(path, "SELECT kind FROM block WHERE block_id = ?", synopsis_of) == rows(
        path, "SELECT ord FROM enum_val WHERE domain = 'kind' AND name = 'table'"
    )
    assert n_blocks == 4  # the header row and the one data row: a 2-row table is all of it
    [(code, block_id)] = rows(
        path,
        "SELECT code, block_id FROM diag WHERE gen = 1 AND component = 'derive.segment.spine'",
    )
    assert (code, block_id) == ("OW_TABLE_SYNOPSIS_ONLY", synopsis_of)
    segment_doc(path, tmp_path / "again", 1, table_synopsis_cells=3)
    assert rows(path, "SELECT count(*) FROM diag WHERE component = 'derive.segment.spine'") == [
        (1,)
    ]


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def _answer_frames(one: Any, tmp_path: Path) -> tuple[SegmentView, list[dict[str, Any]]]:
    path, _, _ = one
    connection = ow.connect(path)
    try:
        view = build_view(connection, 1, 1)
    finally:
        connection.close()
    return view, [json.loads(line) for line in answer(view, tmp_path).splitlines()]


def _body(frames: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


@pytest.mark.parametrize(
    ("damage", "says"),
    [
        (lambda f: f.__setitem__(0, {"t": "doc", "doc": "d9"}), "doc frame of d1"),
        (lambda f: f.append({"t": "cover"}), "segment and diag frames only"),
        (lambda f: f[1]["blocks"].append("d1#999"), "no text block of the view"),
        (lambda f: f[2]["blocks"].append(f[1]["blocks"][0]), "in two Segments"),
        (lambda f: f[1]["blocks"].reverse(), "out of reading order"),
        (lambda f: f[1].__setitem__("layer", "note"), "members disagree"),
        (lambda f: f.pop(3), "is in no Segment"),
        (lambda f: f[1].__setitem__("synopsis_of", "d1#1"), "no table of the view"),
        (lambda f: f[1].__setitem__("n_tokens", -1), "not a count"),
        (
            lambda f: f.append({"t": "diag", "cite": "d1#999", "severity": "warning"}),
            "not in the view",
        ),
    ],
)
def test_a_wrong_answer_is_refused_whole(one: Any, tmp_path: Path, damage: Any, says: str) -> None:
    view, frames = _answer_frames(one, tmp_path)
    damage(frames)
    with pytest.raises(GraphError, match=says):
        decode_segments(_body(frames), view)


# ---------------------------------------------------------------------------
# across a process boundary
# ---------------------------------------------------------------------------


def test_the_segmenter_runs_in_a_real_worker_and_its_answer_is_written(
    one: Any, tmp_path: Path
) -> None:
    """D664, end to end: the view goes into the CAS, `launch()` spawns a real worker for the
    discovered `derive.segment.spine` card, one `INVOKE` with `lane = "segment"` comes back as one
    `RESULT` whose `graph_items` rode inline, and that answer decodes, writes and verifies exactly
    as the in-process one does."""
    import io  # noqa: PLC0415
    import os  # noqa: PLC0415
    import sys  # noqa: PLC0415
    import time  # noqa: PLC0415

    from omniweave_core.blobs import format_ref  # noqa: PLC0415
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_core.host import subproc as sp  # noqa: PLC0415

    path, blobs, _ = one
    card = catalog().cards["derive.segment.spine"]
    connection = ow.connect(path)
    try:
        view = build_view(connection, 1, 1)
    finally:
        connection.close()
    digest = blobs.put(io.BytesIO(view.body))
    (tmp_path / "tmp").mkdir()
    address = f"\\\\.\\pipe\\ow-test-segment-{time.monotonic_ns()}"
    worker, _ack = sp.launch(
        sp.WorkerKey(card.identity.id, "0" * 64),
        sp.SpawnRequest(
            argv=sp.worker_argv(sys.executable, address),
            cwd=str(tmp_path),
            env={key: os.environ[key] for key in ("SYSTEMROOT", "PATH") if key in os.environ},
            address=address,
        ),
        hello={
            "port": "derive/1",
            "card_schema": card.card_schema,
            "card_sha256": card.card_sha256,
            "driver_id": card.identity.id,
            "effective_config": {},
            "roots": {"source_ro": str(tmp_path), "tmp": str(tmp_path / "tmp")},
            "blob_base": str(tmp_path / "cas"),
            "isolation_granted": {"mode": "subproc"},
            "traceparent": "",
            "max_output_bytes": 64 * 1_048_576,
            "egress_mode": "granted",
        },
        expect={
            "driver_id": card.identity.id, "version": card.identity.version, "port": "derive/1"
        },
        deadlines=sp.Deadlines(0, 60_000, 0),
        settings=sp.HostSettings(
            worker_idle_ttl_s=300, crash_threshold=3, crash_window_s=60, tick_ms=50,
            max_workers={"free": 4},
        ),
        now_ms=lambda: time.monotonic_ns() // 1_000_000,
        memory_mb=1024,
    )  # fmt: skip
    try:
        unit = UnitRef(uri="view", part="", content_sha256=digest.hex(), byte_len=len(view.body))
        report = worker.invoke(
            sp.Invocation(
                invoke_id="seg1", units=(unit,), deadline_ms=60_000, budget_micros=0,
                blob_refs=(format_ref(digest),), lane="segment",
            ),
            deadlines=sp.Deadlines(15_000, 60_000, 60_000),
            memory_mb=1024,
        )  # fmt: skip
    finally:
        assert worker.stop() == 0
    assert report.failures == (None,)
    [result] = report.results
    assert result is not None
    [ref] = result.produced
    assert (ref.kind, ref.inline is not None) == ("graph_items", True)
    assert ref.inline == answer(view, tmp_path / "inproc"), "a worker answers as the driver does"
    decoded = decode_segments(ref.inline, view)
    connection = ow.connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        written = write_segments(connection, view, SPINE, decoded, origin_operator="derive.segment")
        connection.execute("COMMIT")
    finally:
        connection.close()
    assert written.created == 4
    assert digests_verify(path) == 4
