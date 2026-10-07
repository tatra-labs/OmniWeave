"""`store/items.py` end to end: a real generation, the real segmenter, the real defterm Pass.

A fragment goes through `fragment.decode` into a store and is segmented by `derive.segment.spine`
(D663's path). Each live Segment is then read back as the Segment form of `owgraph-segment/1` by
`build_segment_view`; `derive.anchor.defterm` answers in process; `decode_items` rebuilds the
Drafts; `drive_items` writes one `derive_run` per Segment through `SqliteGraphSink`. The
assertions read the rows. D667.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the sink wrote.
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import GraphError
from omniweave_core.model.block import Capabilities, Cite
from omniweave_core.model.enums import AnchorKind, Method, Trust
from omniweave_core.model.records import Diag
from omniweave_core.model.spans import TextSpan
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.doc import DocSink
from omniweave_core.store.fragment import FragmentDoc, decode
from omniweave_core.store.graph import (
    BUILTIN_ETYPES,
    AliasDraft,
    AnchorDraft,
    ClaimDraft,
    EdgeDraft,
    EntityDraft,
    MentionDraft,
    PassIdentity,
    SegmentRef,
    TmpRef,
    XrefDraft,
)
from omniweave_core.store.items import (
    Cover,
    ItemView,
    Rejected,
    build_segment_view,
    decode_items,
    drive_items,
)
from omniweave_core.store.segments import (
    SegmenterIdentity,
    build_view,
    decode_segments,
    write_segments,
)
from omniweave_graph.defterm.driver import DefinedTerms
from omniweave_graph.segment.driver import SpineSegmenter
from omniweave_graph.view import read_segment_view
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
DEFTERM = "derive.anchor.defterm"


class _Spend:
    wall_ms = cpu_ms = gpu_ms = tokens_in = tokens_out = calls = bytes_egress = 0
    provider = ""


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


def contract() -> list[dict[str, Any]]:
    """A recital, a Definitions section with a list and a two-column table, and a body clause.

    `Lender` is defined twice -- once in the recital and once in the glossary list -- so the
    second anchor is the duplicate 06:115-118 quarantines with both surfaces.
    """
    cells = [
        block(f"c{r}{c}", text, "table_cell", parent="t", cell={"r": r, "c": c})
        for r, row in enumerate([("Term", "Meaning"), ("Escrow Agent", "The bank.")])
        for c, text in enumerate(row)
    ]
    return [
        {"t": "doc", "format": "docx", "media_type": "application/x-test", "page_count": 1},
        {"t": "page", "page": 0, "page_kind": "stream", "method": "native_xml"},
        block("h0", "Recitals", "heading", payload={"level": 1}),
        block(
            "p0",
            'International Business Machines Corporation ("IBM") and Acme Holdings Ltd. '
            '(hereinafter, the "Company") agree. "Lender" means Beta Bank.',
        ),
        block("h1", "1. Definitions", "heading", payload={"level": 1}),
        block("l", None, "list"),
        block("li0", "Affiliate: any entity controlling a party.", "list_item", parent="l"),
        block("li1", "Lender: the bank named in Schedule 1.", "list_item", parent="l"),
        block("t", None, "table", payload={"header_rows": 1}),
        *cells,
        block("h2", "2. Payment", "heading", payload={"level": 1}),
        block("p2", "The Company pays IBM on each Business Day."),
        {"t": "end", "status": "ok", "page_stats": {"0": {"blocks": 12}}},
    ]


def store(tmp_path: Path) -> tuple[Path, int]:
    """A migrated store, one parsed and segmented generation, and the Pass's producer row."""
    path = tmp_path / "index.owstore"
    (tmp_path / "cas").mkdir()
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=NOW_NS)
        parse = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('parse.office', 1, '', X'00')"
        ).lastrowid
        derive = connection.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('derive.anchor', 1, '', X'00')"
        ).lastrowid
        connection.execute(
            "INSERT INTO derive_pass(pass_id, port, cost_class, cost_rank, phase, lanes, "
            "granularity, card_sha256, schema_version) VALUES(?, 'derive/1', 'free', 0, 30, "
            "'[\"anchor\",\"entity\"]', 'document', 'sha', 1)",
            (DEFTERM,),
        )
    finally:
        connection.close()
    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        sink = DocSink(
            thread,
            producer_id=int(parse or 0),
            origin_operator="parse.office",
            origin_driver="parse.office.anydoc",
            driver_schema_v=1,
            blobs=BlobStore(tmp_path / "cas"),
        )
        doc = FragmentDoc(
            doc_key=b"\x01" * 16,
            source_sha256=b"\x02" * 32,
            normalizer=None,
            uri="c:/docs/contract.docx",
            source_bytes=100,
            declared=DECLARED,
            model_version="1.1",
        )
        gen = decode(contract(), sink=sink, doc=doc).record.gen
    connection = ow.connect(path)
    try:
        view = build_view(connection, 1, gen)
        decoded = decode_segments(_answer(SpineSegmenter(), [view.body], tmp_path), view)
        connection.execute("BEGIN IMMEDIATE")
        write_segments(
            connection,
            view,
            SegmenterIdentity("derive.segment.spine", 1, {}),
            decoded,
            origin_operator="derive.segment",
        )
        connection.execute("COMMIT")
    finally:
        connection.close()
    return path, int(derive or 0)


def _answer(driver: Any, bodies: list[bytes], tmp: Path) -> bytes:
    blobs = MemoryBlobStore(tmp / "kit")
    units = tuple(
        UnitRef(uri=f"u{i}", part="", content_sha256=blobs.add(b), byte_len=len(b))
        for i, b in enumerate(bodies)
    )
    result = driver.derive(
        DeriveScope(lane="anchor", units=units, allowed_cites=frozenset()),
        make_io(blobs, tmp / "kit-tmp"),
    )
    [ref] = result.produced
    return ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()


def identity(producer_id: int) -> PassIdentity:
    return PassIdentity(
        pass_id=DEFTERM,
        producer_id=producer_id,
        method=Method.HEURISTIC,
        origin_operator="derive.anchor",
        origin_driver=DEFTERM,
        driver_schema_v=1,
        cost_class="free",
    )


def views(path: Path) -> list[ItemView]:
    connection = ow.connect(path)
    try:
        ids = [
            int(r[0])
            for r in connection.execute(
                "SELECT segment_id FROM segment WHERE state = 0 ORDER BY ord"
            )
        ]
        return [build_segment_view(connection, i) for i in ids]
    finally:
        connection.close()


def derive(path: Path, producer_id: int, tmp: Path) -> list[Any]:
    """The whole host half: views, the Pass in process, decode, one run per Segment."""
    vs = views(path)
    units = decode_items(_answer(DefinedTerms(), [v.body for v in vs], tmp), vs)
    connection = ow.connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        reports = [drive_items(connection, u, identity(producer_id), _Spend()) for u in units]
        connection.execute("COMMIT")
    finally:
        connection.close()
    return reports


def rows(path: Path, sql: str, *args: Any) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql, args).fetchall()
    finally:
        connection.close()


@pytest.fixture
def one(tmp_path: Path) -> tuple[Path, int]:
    return store(tmp_path)


# ---------------------------------------------------------------------------
# the seed
# ---------------------------------------------------------------------------


def test_a_migrated_store_holds_the_fifteen_builtin_etypes(one: Any) -> None:
    path, _ = one
    assert sorted(rows(path, "SELECT etype, scope, resolution, source FROM etype_vocab")) == sorted(
        (e, s, r, "builtin") for e, s, r in BUILTIN_ETYPES
    )
    assert len(BUILTIN_ETYPES) == 15


def test_a_store_missing_the_seed_gets_it_on_the_next_open_and_an_operator_row_is_kept(
    one: Any,
) -> None:
    path, _ = one
    connection = sqlite3.connect(path)
    connection.execute("DELETE FROM etype_vocab WHERE etype <> 'org'")
    connection.execute("UPDATE etype_vocab SET resolution = 'none', source = 'user'")
    connection.commit()
    connection.close()
    connection = ow.connect(path)
    try:
        assert migrate.apply_pending(connection, now_ns=NOW_NS) == ()
    finally:
        connection.close()
    assert len(rows(path, "SELECT 1 FROM etype_vocab")) == 15
    assert rows(path, "SELECT resolution, source FROM etype_vocab WHERE etype = 'org'") == [
        ("none", "user")
    ]


# ---------------------------------------------------------------------------
# the view
# ---------------------------------------------------------------------------


def test_the_segment_form_is_the_segment_then_its_members_in_cover_order(one: Any) -> None:
    path, _ = one
    vs = views(path)
    glossary = next(v for v in vs if b"1. Definitions" in v.body.splitlines()[0])
    frames = [json.loads(line) for line in glossary.body.splitlines()]
    head = frames[0]
    assert head["t"] == "segment"
    assert head["seg"] == "seg:" + glossary.ref.content_digest.hex()[:16] == glossary.seg
    assert head["heading_path"] == ["1. Definitions"]
    assert head["defaults"] == {"layer": "body", "page": 0, "covered": False}
    assert [f["ord"] for f in frames[1:]] == list(range(len(frames) - 1))
    assert all("block_id" not in f for f in frames)
    assert set(glossary.cites) == {f["cite"] for f in frames[1:]}
    decoded = read_segment_view(glossary.body)
    assert decoded.heading_path == ("1. Definitions",)


def test_a_cell_carries_its_table_position_and_width(one: Any) -> None:
    path, _ = one
    cells = [
        json.loads(line)
        for v in views(path)
        for line in v.body.splitlines()
        if b'"table_cell"' in line
    ]
    assert [(c["text"], c["table"]["r"], c["table"]["c"]) for c in cells] == [
        ("Term", 0, 0),
        ("Meaning", 0, 1),
        ("Escrow Agent", 1, 0),
        ("The bank.", 1, 1),
    ]
    assert {(c["table"]["header_rows"], c["table"]["n_cols"]) for c in cells} == {(1, 2)}


def test_the_view_refuses_a_retired_segment(one: Any) -> None:
    path, _ = one
    connection = sqlite3.connect(path)
    connection.execute("UPDATE segment SET state = 1, ord = -segment_id WHERE segment_id = 1")
    connection.commit()
    connection.close()
    connection = ow.connect(path)
    try:
        with pytest.raises(GraphError, match="not a live Segment"):
            build_segment_view(connection, 1)
        with pytest.raises(GraphError, match="not a live Segment"):
            build_segment_view(connection, 999)
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# the run, end to end
# ---------------------------------------------------------------------------


def test_defterm_through_the_host_writes_anchors_entities_aliases_and_cover(
    one: Any, tmp_path: Path
) -> None:
    path, producer = one
    reports = derive(path, producer, tmp_path)
    anchors = rows(
        path,
        "SELECT a.name_norm, a.surface, a.scope, b.cite FROM anchor a "
        "JOIN block b ON b.block_id = a.block_id WHERE a.akind = 'defined_term' ORDER BY 1",
    )
    names = [a[0] for a in anchors]
    assert names == ["affiliate", "company", "escrow_agent", "ibm", "lender"]
    assert all(a[2] == "document" for a in anchors)
    aliases = set(
        rows(
            path,
            "SELECT e.key, a.surface, a.alias_kind FROM entity_alias a "
            "JOIN entity e ON e.entity_id = a.entity_id",
        )
    )
    assert ("ibm", "International Business Machines Corporation", "expansion") in aliases
    assert ("ibm", "IBM", "abbrev") in aliases
    assert ("company", "Acme Holdings Ltd.", "variant") in aliases
    assert ("affiliate", "Affiliate", "canonical") in aliases
    entities = rows(path, "SELECT key, etype, scope, trust FROM entity ORDER BY key")
    assert [e[0] for e in entities] == names
    assert {(e[1], e[2], e[3]) for e in entities} == {("defined_term", 1, int(Trust.EXTRACTED))}
    assert len(reports) == len(views(path))
    assert {r.status for r in reports} <= {"ok", "empty"}
    assert sum(r.emitted for r in reports) > 0


def test_the_second_definition_of_one_term_is_quarantined_with_both_surfaces(
    one: Any, tmp_path: Path
) -> None:
    path, producer = one
    derive(path, producer, tmp_path)
    [(code, kind, payload, detail)] = rows(
        path, "SELECT code, row_kind, payload, detail FROM quarantine"
    )
    assert (code, kind) == ("OW_GRAPH_UNPARSED_ITEM", "anchor")
    assert json.loads(payload)["name"] == "Lender"
    assert json.loads(detail) == {"already_defined": "Lender"}


def test_every_segment_has_one_run_and_cover_or_a_reason_on_both_lanes(
    one: Any, tmp_path: Path
) -> None:
    path, producer = one
    derive(path, producer, tmp_path)
    segments = rows(path, "SELECT segment_id FROM segment WHERE state = 0")
    runs = rows(path, "SELECT segment_id, pass_id, status, method FROM derive_run")
    assert sorted(r[0] for r in runs) == sorted(s[0] for s in segments)
    assert {r[1] for r in runs} == {DEFTERM}
    covers = rows(
        path,
        "SELECT segment_id, lane, n_covered, empty_reason, LENGTH(cover_bits) FROM derive_cover",
    )
    assert len(covers) == 2 * len(segments)
    for segment_id, lane, n_covered, reason, width in covers:
        assert lane in {"anchor", "entity"}
        assert width == 64
        assert (n_covered == 0) == (reason is not None), (segment_id, lane)
    payment = rows(
        path,
        "SELECT dc.empty_reason FROM derive_cover dc JOIN segment s "
        "ON s.segment_id = dc.segment_id WHERE s.heading_path = '[\"2. Payment\"]'",
    )
    assert payment == [("no definition site in this Segment",)] * 2


def test_the_anchor_span_is_the_term_in_its_block(one: Any, tmp_path: Path) -> None:
    path, producer = one
    derive(path, producer, tmp_path)
    for name, surface, text in rows(
        path,
        "SELECT a.name_norm, a.surface, b.text FROM anchor a JOIN block b "
        "ON b.block_id = a.block_id",
    ):
        assert surface in text, name


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------


def body(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


def fake_view(seg: str = "seg:0000000000000001", cites: tuple[str, ...] = ("d1#1",)) -> ItemView:
    return ItemView(
        ref=SegmentRef(segment_id=1, doc_ord=1, gen=1, content_digest=b"\x00" * 16, uncovered=None),
        seg=seg,
        body=b"",
        cites={c: i for i, c in enumerate(cites, start=1)},
    )


SEG = {"t": "seg", "seg": "seg:0000000000000001"}


def test_each_item_kind_decodes_to_its_draft() -> None:
    [unit] = decode_items(
        body(
            SEG,
            {
                "t": "entity",
                "tmp": "e1",
                "key": "Acme",
                "etype": "org",
                "title": "Acme",
                "scope": "corpus",
                "trust": "inferred",
                "score": 0.5,
                "score_kind": "p",
            },
            {"t": "alias", "entity": "e1", "surface": "ACME", "alias_kind": "variant"},
            {
                "t": "mention",
                "entity": "e1",
                "cite": "d1#1",
                "quote": "Acme",
                "surface": "Acme",
                "trust": "extracted",
            },
            {
                "t": "edge",
                "src": "e1",
                "dst": "e2",
                "relation": "party_to",
                "observed": {"cite": "d1#1", "span": [0, 4]},
                "weight": 2,
            },
            {
                "t": "claim",
                "subject": "e1",
                "object_literal": "5",
                "object_datatype": "int",
                "claim_type": "metric",
                "predicate": "employees",
                "description": "d",
                "status": "asserted",
                "observed": {"cite": "d1#1", "quote": "5"},
                "t_start": "2020",
                "t_precision": "year",
            },
            {
                "t": "anchor",
                "name": "Acme",
                "akind": "defined_term",
                "cite": "d1#1",
                "span": [0, 4],
                "scope": "document",
                "surface": "Acme",
            },
            {
                "t": "xref",
                "name": "4.2",
                "akind": "section",
                "cite": "d1#1",
                "quote": "4.2",
                "surface": "Section 4.2",
            },
        ),
        [fake_view()],
    )
    entity, alias, mention, edge, claim, anchor, xref = unit.items
    assert entity == EntityDraft(
        key="Acme",
        etype="org",
        title="Acme",
        scope="corpus",
        trust_claim=Trust.INFERRED,
        score=0.5,
        score_kind="p",
        tmp=TmpRef("e1"),
    )
    assert alias == AliasDraft(TmpRef("e1"), "ACME", "variant", Trust.AMBIGUOUS)
    assert mention == MentionDraft(TmpRef("e1"), (Cite("d1#1"), "Acme"), "Acme", Trust.EXTRACTED)
    assert isinstance(edge, EdgeDraft)
    assert (edge.observed, edge.weight) == ((Cite("d1#1"), TextSpan(0, 4)), 2.0)
    assert isinstance(claim, ClaimDraft)
    assert (claim.status, claim.t_precision, claim.object_entity) == ("asserted", "year", None)
    assert anchor == AnchorDraft(
        "Acme", AnchorKind.DEFINED_TERM, (Cite("d1#1"), TextSpan(0, 4)), "document", "Acme"
    )
    assert xref == XrefDraft("4.2", AnchorKind.SECTION, (Cite("d1#1"), "4.2"), "Section 4.2")
    assert unit.has_items


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        ({"t": "entity", "key": 1, "etype": "org", "title": "x", "scope": "corpus"}, "key"),
        ({"t": "entity", "key": "k", "etype": "org", "title": "x", "scope": "world"}, "scope"),
        (
            {
                "t": "entity",
                "key": "k",
                "etype": "org",
                "title": "x",
                "scope": "corpus",
                "trust": "certain",
            },
            "trust",
        ),
        (
            {
                "t": "entity",
                "key": "k",
                "etype": "org",
                "title": "x",
                "scope": "corpus",
                "score": True,
            },
            "score",
        ),
        (
            {
                "t": "anchor",
                "name": "x",
                "akind": "chapter",
                "cite": "d1#1",
                "span": [0, 1],
                "scope": "document",
                "surface": "x",
            },
            "akind",
        ),
        (
            {
                "t": "anchor",
                "name": "x",
                "akind": "section",
                "cite": "d1#1",
                "span": [0, 1],
                "quote": "x",
                "scope": "document",
                "surface": "x",
            },
            "exactly one",
        ),
        (
            {
                "t": "anchor",
                "name": "x",
                "akind": "section",
                "cite": "d1#1",
                "scope": "document",
                "surface": "x",
            },
            "exactly one",
        ),
        (
            {
                "t": "xref",
                "name": "x",
                "akind": "section",
                "cite": "d1#1",
                "span": [3, 1],
                "surface": "x",
            },
            "a <= b",
        ),
        (
            {
                "t": "xref",
                "name": "x",
                "akind": "section",
                "cite": "d1#1",
                "span": [0],
                "surface": "x",
            },
            "span",
        ),
        ({"t": "edge", "src": "e1", "dst": "e2", "relation": "r", "observed": "d1#1"}, "observed"),
        (
            {
                "t": "claim",
                "subject": "e1",
                "claim_type": "c",
                "predicate": "p",
                "description": "d",
                "status": "maybe",
                "observed": {"cite": "d1#1", "quote": "q"},
            },
            "status",
        ),
    ],
)
def test_a_malformed_item_is_rejected_as_data_with_its_frame_kept(
    frame: dict[str, Any], reason: str
) -> None:
    [unit] = decode_items(body(SEG, frame), [fake_view()])
    [item] = unit.items
    assert isinstance(item, Rejected)
    assert item.row_kind == frame["t"]
    assert item.frame == frame
    assert reason in item.reason


def test_cover_and_cover_empty_and_diag_decode() -> None:
    [unit] = decode_items(
        body(
            SEG,
            {"t": "cover", "lane": "anchor", "cites": ["d1#1"]},
            {"t": "cover_empty", "lane": "entity", "reason": "nothing here"},
            {
                "t": "diag",
                "code": "OW_RESOURCE_LIMIT",
                "severity": "warning",
                "component": "p",
                "message": "m",
                "cite": "d1#1",
                "detail": {"limit": "X"},
                "fatal": False,
            },
            {
                "t": "diag",
                "code": "OW_RESOURCE_LIMIT",
                "severity": "info",
                "component": "p",
                "message": "m",
                "cite": "d9#9",
            },
        ),
        [fake_view()],
    )
    cover, empty, diag, stray = unit.items
    assert cover == Cover("anchor", (Cite("d1#1"),))
    assert empty == Cover("entity", (), "nothing here")
    assert isinstance(diag, Diag)
    assert diag.block == 1
    assert diag.detail == {"limit": "X", "cite": "d1#1"}
    assert isinstance(stray, Diag)
    assert stray.block is None
    assert stray.detail == {"cite": "d9#9"}
    assert not unit.has_items


def test_units_split_on_seg_frames_in_order() -> None:
    a, b = fake_view("seg:000000000000000a"), fake_view("seg:000000000000000b")
    units = decode_items(
        body(
            {"t": "seg", "seg": a.seg},
            {"t": "cover_empty", "lane": "anchor", "reason": "r"},
            {"t": "seg", "seg": b.seg},
            {"t": "cover", "lane": "anchor", "cites": ["d1#1"]},
        ),
        [a, b],
    )
    assert [u.view.seg for u in units] == [a.seg, b.seg]
    assert [len(u.items) for u in units] == [1, 1]


@pytest.mark.parametrize(
    ("raw", "says"),
    [
        (b"not json\n", "line 1 is not JSON"),
        (b"[1]\n", "line 1 is not an object"),
        (body({"t": "cover", "lane": "anchor", "cites": ["d1#1"]}), "before any seg frame"),
        (body({"t": "seg", "seg": "seg:ffffffffffffffff"}), "does not name unit 1"),
        (body(SEG, SEG), "does not name unit 2"),
        (b"", "covers 0 of 1"),
        (body(SEG, {"t": "segment"}), "'segment' frame"),
        (body(SEG, {"t": "cover", "lane": "anchor", "cites": ["d9#9"]}), "not a member"),
        (body(SEG, {"t": "cover", "lane": "anchor", "cites": []}), "names no cites"),
        (body(SEG, {"t": "cover", "cites": ["d1#1"]}), "names no lane"),
        (body(SEG, {"t": "cover_empty", "lane": "anchor", "reason": " "}), "gives no reason"),
        (body(SEG, {"t": "diag", "severity": "loud"}), "diag frame 2 is malformed"),
    ],
)
def test_an_unattributable_answer_is_refused_whole(raw: bytes, says: str) -> None:
    with pytest.raises(GraphError) as caught:
        decode_items(raw, [fake_view()])
    assert says in str(caught.value)


def test_a_rejected_item_is_quarantined_and_a_dangling_tmp_quarantines_the_run(
    one: Any,
) -> None:
    path, producer = one
    [view, *_] = views(path)
    cite = next(iter(view.cites))
    [unit] = decode_items(
        body(
            {"t": "seg", "seg": view.seg},
            {
                "t": "entity",
                "tmp": "e1",
                "key": "k",
                "etype": "org",
                "title": "x",
                "scope": "galaxy",
            },
            {"t": "alias", "entity": "e1", "surface": "K", "alias_kind": "variant"},
            {"t": "cover", "lane": "entity", "cites": [cite]},
        ),
        [view],
    )
    connection = ow.connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        report = drive_items(connection, unit, identity(producer), _Spend())
        connection.execute("COMMIT")
    finally:
        connection.close()
    assert report.status == "quarantined"
    assert (report.emitted, report.quarantined) == (0, 2)
    assert sorted(rows(path, "SELECT row_kind, code FROM quarantine")) == [
        ("alias", "OW_GRAPH_DANGLING_TMP"),
        ("entity", "OW_GRAPH_UNPARSED_ITEM"),
    ]
    [(payload, detail)] = rows(
        path, "SELECT payload, detail FROM quarantine WHERE row_kind = 'entity'"
    )
    assert json.loads(payload)["scope"] == "galaxy"
    assert "scope" in json.loads(detail)["reason"]


def test_an_answer_of_only_cover_is_an_empty_run(one: Any) -> None:
    path, producer = one
    [view, *_] = views(path)
    [unit] = decode_items(
        body({"t": "seg", "seg": view.seg}, {"t": "cover_empty", "lane": "anchor", "reason": "r"}),
        [view],
    )
    connection = ow.connect(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        report = drive_items(connection, unit, identity(producer), _Spend())
        connection.execute("COMMIT")
    finally:
        connection.close()
    assert report.status == "empty"
    assert rows(path, "SELECT status, n_items FROM derive_run") == [("empty", 0)]
