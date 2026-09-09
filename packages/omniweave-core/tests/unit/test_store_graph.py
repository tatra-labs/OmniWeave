"""`omniweave_core.store.graph` -- the twelve L3 write methods, over a real migrated store.

Every test here drives `SqliteGraphSink` against an `.owstore` the shipped migrations built, inside
one explicit transaction, exactly as a `Unit` would. Nothing is faked: the FK graph, the CHECKs and
the UNIQUE indexes are the ones 0001-0004 declare, so a column name this module got wrong fails
here rather than in P8.

**The highest-value test in the file is `test_a_draft_that_fails_every_check_is_retained...`
together with `test_no_public_method_and_no_statement_can_delete_a_row`.** 01-principles.md:744
names the violation this file exists to detect -- *"A violation looks like a
`GraphSink.drop()`"* -- and a name check alone would miss the interesting way to break it, which is
a `DELETE` inside a method called something else. So the property is asserted three ways: over the
twelve public names, over every non-docstring string constant in the module's AST, and over the
real statement stream a happy path issues, captured with `set_trace_callback`.

Specified in 06-structure-extraction.md section 1.7 (:337-477 for the signatures and the Drafts,
:565-618 for `ground()`, :684-698 for the codes), 01-principles.md INV-25 (:723-745, :838-848),
02-architecture.md:488 for the tables a Pass reaches through the sink, and
`store/schema/migrations/0002_graph.sql`, which is the authority on every column written.

`import sqlite3` below: this file drives a REAL store, so it holds the connection the sink writes
through and needs the module's exception types to assert what the DDL refuses. TID251's per-file
ignore covers `store/*.py` and not `tests/`, so the import is taken explicitly here, exactly as
`test_store_integration.py` takes it for the same reason.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import re
import sqlite3  # noqa: TID251 -- see the module docstring: this file drives a REAL store.
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from conftest import MIGRATIONS_DIR
from omniweave_core.errors import GraphError
from omniweave_core.model.block import Cite
from omniweave_core.model.enums import MAX_TRUST_BY_METHOD, AnchorKind, Method, Trust
from omniweave_core.model.spans import TextSpan
from omniweave_core.store import GraphSink, migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.graph import (
    OW_GRAPH_DANGLING_CITE,
    OW_GRAPH_DANGLING_TMP,
    OW_GRAPH_ETYPE_OUT_OF_VOCAB,
    OW_GRAPH_ITEM_BUDGET,
    OW_GRAPH_LABEL_TOO_LONG,
    OW_GRAPH_OUT_OF_SCOPE_BLOCK,
    OW_GRAPH_QUOTE_AMBIGUOUS,
    OW_GRAPH_TRUST_CLAMPED,
    OW_GRAPH_UNGROUNDED,
    OW_GRAPH_UNPARSED_ITEM,
    QUARANTINED_ID,
    AliasDraft,
    AnchorDraft,
    ClaimDraft,
    ClaimId,
    EdgeDraft,
    EdgeId,
    EntityDraft,
    EntityId,
    MentionDraft,
    MentionId,
    PassIdentity,
    RunId,
    SegmentRef,
    SqliteGraphSink,
    TmpRef,
    XrefDraft,
    ground,
)

NOW_NS = 1_757_400_000_000_000_000
"""A fixed timestamp: `time.time()` is banned in library code and injected everywhere in the
store, so a test reading the ambient clock would assert against a value production cannot make."""

DOC_ORD = 7
GEN = 1
SEGMENT_ID = 1

BLOCK_TEXTS: tuple[tuple[str, str], ...] = (
    ("d7#1", "Acme Corp entered into an agreement with Beta Ltd."),
    ("d7#2", "See section 4.2(b) for the indemnity, and section 4.2(b) again."),
    ("d7#3", "The hyphen­\nation rule and the ﬁle it governs."),
)
"""Three live blocks. `d7#2` carries a quote that occurs twice, which is the ambiguity branch;
`d7#3` carries a soft hyphen plus a line break and a U+FB01 ligature, which are the two shapes
`normalize_k` changes length on and therefore the two `ground()` cannot get right by accident."""

ALL_CITES = frozenset(Cite(cite) for cite, _ in BLOCK_TEXTS)

SOFT_HYPHEN_BREAK = "\u00ad\n"
"""`normalize_k` operation 1 deletes the pair and emits NOTHING in its place (06:520-527)."""

LIGATURE_FI = "\ufb01"
"""`normalize_k` operation 2 expands it to two characters, which is why the back-map exists."""


class _Spend:
    """A stand-in for P4's `Spend`, structurally satisfying `SpendVector`.

    `Spend` is 05-ingest-and-routing.md section 6.1's and has no module yet -- it is one of
    `test_store_protocols.py`'s pinned unresolved names. The sink reads eight attributes off it and
    nothing else, which is exactly what `SpendVector` declares, so eight attributes is a complete
    substitute and the substitution is the evidence that the Protocol is not over-specified.
    """

    def __init__(self, **fields: object) -> None:
        self.wall_ms = int(fields.get("wall_ms", 0))
        self.cpu_ms = int(fields.get("cpu_ms", 0))
        self.gpu_ms = int(fields.get("gpu_ms", 0))
        self.tokens_in = int(fields.get("tokens_in", 0))
        self.tokens_out = int(fields.get("tokens_out", 0))
        self.calls = int(fields.get("calls", 0))
        self.bytes_egress = int(fields.get("bytes_egress", 0))
        self.provider = str(fields.get("provider", ""))


# ---------------------------------------------------------------------------------------------
# The store, and the L2 rows an L3 row needs to hang off
# ---------------------------------------------------------------------------------------------


def _seed(connection: sqlite3.Connection) -> None:
    """One document, one page, three blocks, one Segment, one registered Pass, two vocabularies.

    P2's non-goals say the L3 tables *"exist and are empty"* (16-roadmap.md:468), which bounds who
    CALLS the sink and not what it implements. These rows are the minimum an L3 row's foreign keys
    require, written here rather than through `DocSink` because that sink is a concurrent wave's
    and this file must not depend on it.
    """
    connection.execute(
        "INSERT INTO producer (producer_id, operator, op_version, code_fingerprint, "
        "options_digest) VALUES (1, 'op.derive', 1, 'abc', X'00')"
    )
    connection.execute(
        "INSERT INTO doc (doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "format_evidence, source_bytes, gen, status, model_version, declared, achieved) "
        "VALUES (?, X'01', X'02', 'file:///a.pdf', 'application/pdf', 'pdf', '{}', 1, ?, 'ok', "
        "'1.1', '{}', '{}')",
        (DOC_ORD, GEN),
    )
    connection.execute(
        "INSERT INTO page (doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES (?, ?, 0, 0, 0, 1)",
        (DOC_ORD, GEN),
    )
    for index, (cite, text) in enumerate(BLOCK_TEXTS):
        connection.execute(
            "INSERT INTO block (block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text, "
            "content_digest, os_kind, producer_id, method, trust, quote, origin_operator, "
            "origin_driver, driver_schema_v) "
            "VALUES (?, ?, ?, 0, ?, ?, ?, 1, 0, ?, X'03', 4, 1, 0, 2, 4, 'op.parse', "
            "'parse.native', 1)",
            (index + 1, DOC_ORD, GEN, f"p0/{index}", cite, index, text),
        )
    connection.execute("UPDATE block SET restriction_bits = 5 WHERE block_id = 3")
    # `d7#3` is the RESTRICTED block. `restriction_bits` propagates OUTWARD from the source
    # (INV-13's OR-upward direction, 06:119-120), and a fixture in which every block reads 0
    # cannot tell a sink that propagates from one that writes a literal zero -- which is exactly
    # the mutation that survived the first pass here.
    connection.execute(
        "INSERT INTO segmenter (segmenter_id, driver_id, driver_schema_v, params_digest) "
        "VALUES (1, 'derive.segment.spine', 1, X'00')"
    )
    connection.execute(
        "INSERT INTO segment (segment_id, doc_ord, gen, ord, segmenter_id, layer, heading_path, "
        "n_blocks, n_tokens, n_chars, tokenizer_id, first_page, last_page, trust, quote_min, "
        "kind_mask, content_digest, origin_operator, origin_driver, driver_schema_v) "
        "VALUES (?, ?, ?, 0, 1, 0, '[]', 3, 10, 50, 'tok', 0, 0, 2, 4, 1, X'04', 'op.segment', "
        "'derive.segment.spine', 1)",
        (SEGMENT_ID, DOC_ORD, GEN),
    )
    for index in range(len(BLOCK_TEXTS)):
        connection.execute(
            "INSERT INTO segment_block (block_id, segment_id, ord) VALUES (?, ?, ?)",
            (index + 1, SEGMENT_ID, index),
        )
    connection.execute(
        "INSERT INTO derive_pass (pass_id, port, cost_class, cost_rank, phase, lanes, "
        "granularity, card_sha256, schema_version) "
        "VALUES ('derive.entity.table', 'derive/1', 'free', 0, 50, '[\"entity\"]', 'document', "
        "'sha', 1)"
    )
    for etype in ("org", "person"):
        connection.execute(
            "INSERT INTO etype_vocab (etype, scope, resolution, source) "
            "VALUES (?, 'corpus', 'exact_only', 'builtin')",
            (etype,),
        )
    connection.execute(
        "INSERT INTO relation_vocab (relation, symmetric, actor_rule, source) "
        "VALUES ('party_to', 0, 'source is the party; target is the agreement', 'builtin')"
    )
    connection.execute(
        "INSERT INTO relation_vocab (relation, symmetric, actor_rule, source) "
        "VALUES ('co_occurs_with', 1, 'symmetric; stored with src < dst', 'builtin')"
    )


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated `.owstore` with the L2 rows seeded, inside one open write transaction.

    The `BEGIN IMMEDIATE` is `StoreThread._transact`'s, spelled by hand: a run is one `Unit` and
    the sink is constructed inside it (see `store/graph.py`'s docstring), so a test that committed
    per statement would be testing a shape production never has.
    """
    path = tmp_path / "index.owstore"
    conn = ow.connect(path)
    try:
        applied = migrate.apply_pending(conn, now_ns=NOW_NS)
        assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
        conn.execute("BEGIN IMMEDIATE")
        _seed(conn)
        yield conn
        conn.execute("COMMIT")
    finally:
        conn.close()


def _identity(*, method: Method = Method.HEURISTIC, cost_class: str = "free") -> PassIdentity:
    return PassIdentity(
        pass_id="derive.entity.table",  # noqa: S106 -- a DriverId, not a credential.
        producer_id=1,
        method=method,
        origin_operator="op.derive",
        origin_driver="derive.entity.table",
        driver_schema_v=1,
        cost_class=cost_class,
    )


def _segment_ref() -> SegmentRef:
    return SegmentRef(
        segment_id=SEGMENT_ID,
        doc_ord=DOC_ORD,
        gen=GEN,
        content_digest=b"\x04",
        uncovered=bytes(64),
    )


def _open(
    conn: sqlite3.Connection,
    *,
    method: Method = Method.HEURISTIC,
    cost_class: str = "free",
    allowed: frozenset[Cite] | None = None,
) -> SqliteGraphSink:
    """A sink with a run already open. Every test starts here."""
    sink = SqliteGraphSink(conn)
    sink.begin_run(
        _segment_ref(),
        _identity(method=method, cost_class=cost_class),
        ALL_CITES if allowed is None else allowed,
    )
    return sink


def _org(tmp: str = "e1", **over: object) -> EntityDraft:
    fields: dict[str, object] = {
        "key": "Acme Corp",
        "etype": "org",
        "title": "Acme Corp",
        "scope": "corpus",
        "trust_claim": Trust.EXTRACTED,
        "tmp": TmpRef(tmp),
    }
    fields.update(over)
    return EntityDraft(**fields)  # type: ignore[arg-type]


def _rows(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])  # noqa: S608


def _quarantine(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    return [
        (str(code), str(row_kind), str(payload), str(detail))
        for code, row_kind, payload, detail in conn.execute(
            "SELECT code, row_kind, payload, detail FROM quarantine ORDER BY q_id"
        )
    ]


# ---------------------------------------------------------------------------------------------
# 1. There is no way to drop a row -- 01-principles.md:744's named violation
# ---------------------------------------------------------------------------------------------

_MODULE_PATH = Path(inspect.getsourcefile(SqliteGraphSink) or "")
_DISPOSAL_NAMES = frozenset({"drop", "delete", "remove", "discard", "purge", "skip", "prune"})


def _non_docstring_strings(tree: ast.Module) -> list[str]:
    """Every string constant in the module that is NOT a docstring.

    A docstring is a bare string expression statement -- which is also what an attribute docstring
    is -- so excluding `ast.Expr` values covers module, class, function and attribute docs in one
    rule. Comments never reach the AST, so a `-- DELETE` inside a SQL comment or a prose paragraph
    about the maintenance path cannot make this test lie.
    """
    docstrings = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_the_sink_exposes_no_method_whose_name_means_disposal() -> None:
    """`GraphSink` has no `drop()`, and no synonym of one either (GR10, 01-principles.md:744)."""
    public = {name for name in dir(SqliteGraphSink) if not name.startswith("_")}
    assert public & _DISPOSAL_NAMES == set(), f"{public & _DISPOSAL_NAMES} is a disposal path"


def test_no_statement_in_the_module_is_a_delete() -> None:
    """No SQL this module can execute removes a row. Asserted over the AST, not over the text.

    The interesting way to break INV-25 is not a method called `drop`; it is a `DELETE` inside a
    method called something else. Every SQL string in the module is a constant, so scanning the
    non-docstring constants sees all of them -- and the module's own prose about 06 section 10.2's
    owner-scoped replacement `DELETE`s lives in docstrings and comments, which this scan excludes
    by construction.
    """
    tree = ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))
    offenders = [
        text for text in _non_docstring_strings(tree) if re.search(r"\bDELETE\b", text, re.I)
    ]
    assert offenders == [], f"store/graph.py can execute {offenders}"


def test_a_happy_path_run_issues_no_delete_statement(connection: sqlite3.Connection) -> None:
    """The runtime witness: every statement a full run really executes, captured and checked.

    The AST test proves the module contains no `DELETE`; this one proves the module does not reach
    one through a helper it did not write, which is the half a source scan cannot see.
    """
    seen: list[str] = []
    connection.set_trace_callback(seen.append)
    try:
        _drive_happy_path(connection)
    finally:
        connection.set_trace_callback(None)
    deletes = [statement for statement in seen if re.search(r"\bDELETE\b", statement, re.I)]
    assert deletes == [], deletes
    assert len(seen) > 20, "the trace captured almost nothing; the callback did not arm"


def test_a_draft_that_fails_every_check_is_retained_in_quarantine_and_never_vanishes(
    connection: sqlite3.Connection,
) -> None:
    """The named violation, from the other side: a hopeless draft becomes DATA, not silence.

    This draft breaks four rules at once -- an over-long title, an etype outside both the charset
    and `etype_vocab`, a score with no `score_kind`, and a trust claim above the ceiling. Nothing
    is written to `entity`, one `quarantine` row appears, it carries a code and the draft VERBATIM,
    and the returned id is the sentinel rather than a plausible-looking number.
    """
    sink = _open(connection, method=Method.LLM)
    hopeless = _org(
        title="x" * 500,
        etype="NotAnEtype!",
        score=0.7,
        score_kind=None,
        trust_claim=Trust.EXTRACTED,
    )
    result = sink.entity(hopeless)
    assert result == QUARANTINED_ID
    assert _rows(connection, "entity") == 0
    rows = _quarantine(connection)
    assert len(rows) == 1, rows
    code, row_kind, payload, _detail = rows[0]
    assert code == OW_GRAPH_LABEL_TOO_LONG, "the first refusal is the one a reader would act on"
    assert row_kind == "entity"
    assert '"NotAnEtype!"' in payload, "the rejected draft is kept VERBATIM in payload"
    assert '"x' + "x" * 10 in payload


def test_quarantine_refuses_a_row_kind_outside_the_ddls_eight(
    connection: sqlite3.Connection,
) -> None:
    """`quarantine.row_kind`'s CHECK has eight members and the sink refuses the ninth early."""
    sink = _open(connection)
    with pytest.raises(GraphError, match="row_kind"):
        sink.quarantine("cover", OW_GRAPH_UNGROUNDED, {"a": 1})


def test_quarantine_refuses_an_empty_code(connection: sqlite3.Connection) -> None:
    """`code TEXT NOT NULL`, and the code is what makes the retained row explain itself."""
    sink = _open(connection)
    with pytest.raises(GraphError, match="code"):
        sink.quarantine("entity", "", {"a": 1})


# ---------------------------------------------------------------------------------------------
# 2. `cover` -- coverage, or a REASON (GR3)
# ---------------------------------------------------------------------------------------------


def test_cover_with_an_empty_cite_set_and_no_reason_raises(
    connection: sqlite3.Connection,
) -> None:
    """01-principles.md:840 lists this refusal among INV-25's schema-level enforcers."""
    sink = _open(connection)
    with pytest.raises(GraphError, match="empty_reason"):
        sink.cover("entity", ())
    assert _rows(connection, "derive_cover") == 0, "a refused cover writes nothing"


def test_cover_with_an_empty_cite_set_and_a_reason_succeeds_and_stores_the_reason(
    connection: sqlite3.Connection,
) -> None:
    """*"NOT NULL => covered with ZERO items. doctor reports the rate"* (0002:227-228)."""
    sink = _open(connection)
    sink.cover("entity", (), empty_reason="no candidate spans in this segment")
    row = connection.execute(
        "SELECT n_covered, empty_reason, length(cover_bits) FROM derive_cover"
    ).fetchone()
    assert row == (0, "no candidate spans in this segment", 64)
    report = sink.end_run("empty", _Spend())
    assert report.cover_empty == 1
    assert report.covered == 0


def test_cover_sets_one_bit_per_cited_block_at_its_segment_block_ord(
    connection: sqlite3.Connection,
) -> None:
    """*"`ord` IS the cover_bits bit index"* (06:112). Two cites, two bits, and no third."""
    sink = _open(connection)
    sink.cover("entity", (Cite("d7#1"), Cite("d7#3")))
    bits, covered = connection.execute("SELECT cover_bits, n_covered FROM derive_cover").fetchone()
    assert covered == 2
    assert bits[0] == 0b101, "ords 0 and 2, and nothing between them"
    report = sink.end_run("ok", _Spend())
    assert report.coverage_frac == pytest.approx(2 / 3), "two of the Segment's three blocks"


def test_cover_refuses_a_lane_outside_the_lane_domain(connection: sqlite3.Connection) -> None:
    """`derive_cover.lane` is the closed `lane` domain, read off `Lane` and not a second list."""
    sink = _open(connection)
    with pytest.raises(GraphError, match="lane"):
        sink.cover("entities", (Cite("d7#1"),))


def test_cover_refuses_a_cite_that_is_not_a_member_of_the_segment(
    connection: sqlite3.Connection,
) -> None:
    """The bitmap is indexed by `segment_block.ord`, so a non-member has no bit to set."""
    connection.execute("DELETE FROM segment_block WHERE block_id = 3")
    sink = _open(connection)
    with pytest.raises(GraphError, match="segment"):
        sink.cover("entity", (Cite("d7#3"),))


# ---------------------------------------------------------------------------------------------
# 3. A dangling `tmp` quarantines, names what dangled, and takes the Segment with it
# ---------------------------------------------------------------------------------------------


def test_a_dangling_tmp_reference_quarantines_and_the_row_names_what_dangled(
    connection: sqlite3.Connection,
) -> None:
    """06:626: a `TmpRef` referenced and never defined *"quarantines the whole Segment"*.

    Three things are asserted, and the third is the one graphrag gets wrong: the mention is not
    written, the quarantine row NAMES the token, and the draft itself is kept -- graphrag's
    `filter_orphan_relationships` deletes it, and *"a hallucinated entity name is very often a real
    entity the extractor failed to emit a row for"* (0002:496-498).
    """
    sink = _open(connection)
    ghost = MentionDraft(
        entity=TmpRef("e9"),
        at=(Cite("d7#1"), "Acme Corp"),
        surface="Acme Corp",
        trust_claim=Trust.EXTRACTED,
    )
    assert sink.mention(ghost) == QUARANTINED_ID
    assert _rows(connection, "mention") == 0
    code, row_kind, payload, detail = _quarantine(connection)[0]
    assert code == OW_GRAPH_DANGLING_TMP
    assert row_kind == "mention"
    assert '"dangling_tmp":"e9"' in detail, detail
    assert '"Acme Corp"' in payload


def test_a_dangling_tmp_forces_the_runs_status_to_quarantined(
    connection: sqlite3.Connection,
) -> None:
    """*"the whole Segment"* is the status half: a run cannot report `ok` over a dangling token."""
    sink = _open(connection)
    sink.entity(_org())
    sink.alias(
        AliasDraft(
            entity=TmpRef("e404"), surface="ACME", alias_kind="abbrev", trust_claim=Trust.INFERRED
        )
    )
    report = sink.end_run("ok", _Spend())
    assert report.status == "quarantined", "the runner asked for ok and does not get it"
    stored = connection.execute("SELECT status FROM derive_run").fetchone()[0]
    assert stored == "quarantined"
    assert _rows(connection, "entity") == 1, "the rows already written STAY; this is not a rollback"


def test_a_resolved_tmp_binds_every_later_draft_to_the_minted_id(
    connection: sqlite3.Connection,
) -> None:
    """`entity()` is the only binding mechanism a Pass has (06:628-634)."""
    sink = _open(connection)
    entity_id = sink.entity(_org("e1"))
    sink.alias(
        AliasDraft(
            entity=TmpRef("e1"), surface="ACME", alias_kind="abbrev", trust_claim=Trust.INFERRED
        )
    )
    stored = connection.execute("SELECT entity_id FROM entity_alias").fetchone()[0]
    assert stored == entity_id
    assert _quarantine(connection) == []


# ---------------------------------------------------------------------------------------------
# 4. `MAX_TRUST_BY_METHOD` is clamped in Python, because 0002 ships no trigger for it
# ---------------------------------------------------------------------------------------------


def test_the_trust_ceiling_is_applied_in_python_on_entity_mention_edge_and_claim(
    connection: sqlite3.Connection,
) -> None:
    """0002's header says this file ships NO trigger mirroring the ceiling; this is the enforcer.

    `Method.LLM`'s ceiling is `INFERRED` (03:1621), every draft below claims `EXTRACTED`, and all
    four tables must land at the ceiling with four `OW_GRAPH_TRUST_CLAMPED` rows carrying the
    driver's ORIGINAL claim -- *"so over-claiming is measurable in `ow graph doctor` rather than
    silently corrected"*.
    """
    assert MAX_TRUST_BY_METHOD[Method.LLM] is Trust.INFERRED, "the fixture's premise"
    sink = _open(connection, method=Method.LLM, cost_class="billed_api")
    sink.entity(_org("e1"))
    sink.entity(_org("e2", key="Beta Ltd", title="Beta Ltd"))
    sink.mention(
        MentionDraft(
            entity=TmpRef("e1"),
            at=(Cite("d7#1"), "Acme Corp"),
            surface="Acme Corp",
            trust_claim=Trust.EXTRACTED,
        )
    )
    sink.edge(
        EdgeDraft(
            src=TmpRef("e1"),
            dst=TmpRef("e2"),
            relation="party_to",
            observed=(Cite("d7#1"), "entered into an agreement"),
            trust_claim=Trust.EXTRACTED,
        )
    )
    sink.claim(
        ClaimDraft(
            subject=TmpRef("e1"),
            object_entity=None,
            object_literal="2026-06",
            object_datatype="xsd:date",
            claim_type="event",
            predicate="signed_on",
            description="Acme signed in June 2026",
            status="asserted",
            observed=(Cite("d7#1"), "an agreement"),
            trust_claim=Trust.EXTRACTED,
        )
    )
    for table in ("entity", "mention", "edge", "claim"):
        trusts = [
            int(value)
            for (value,) in connection.execute(f"SELECT trust FROM {table}")  # noqa: S608
        ]
        assert trusts and set(trusts) == {int(Trust.INFERRED)}, f"{table} kept an over-claim"
    clamped = [row for row in _quarantine(connection) if row[0] == OW_GRAPH_TRUST_CLAMPED]
    assert {row[1] for row in clamped} == {"entity", "mention", "edge", "claim"}
    assert all('"claimed":2' in row[3] and '"ceiling":1' in row[3] for row in clamped), clamped


def test_a_claim_below_the_ceiling_is_written_at_its_own_claim(
    connection: sqlite3.Connection,
) -> None:
    """**The clamp is a ceiling, never a floor.** `AMBIGUOUS` under an `EXTRACTED` ceiling stays."""
    sink = _open(connection, method=Method.HEURISTIC)
    sink.entity(_org(trust_claim=Trust.AMBIGUOUS))
    assert connection.execute("SELECT trust FROM entity").fetchone()[0] == int(Trust.AMBIGUOUS)
    assert _quarantine(connection) == []


# ---------------------------------------------------------------------------------------------
# 5. GR15 -- `mention` is still the only table referencing both spaces
# ---------------------------------------------------------------------------------------------


@pytest.fixture(scope="session")
def schema_lint(repo_root: Path) -> ModuleType:
    """`tools/gate_schema_lint.py`, loaded by path under a private name.

    By file path with `importlib.util` and never `importlib.import_module`, which the semgrep bank
    bans outside `host/`, and never by putting `tools/` on `sys.path`;
    `test_schema_lint.py` sets the pattern and this fixture follows it.
    """
    path = repo_root / "tools" / "gate_schema_lint.py"
    spec = importlib.util.spec_from_file_location("_owgate_gr15", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gr15_holds_over_the_schema_this_sink_writes_into(schema_lint: ModuleType) -> None:
    """*"`mention` is the only table in the framework referencing both a `block_id` and an
    `entity_id`"* (06:232). This sink writes into nine tables and creates none, so the property is
    a property of the DDL -- and the assertion is made with the gate's own clause rather than a
    hand-rolled scan that could disagree with it.

    The roster is FOUR and not one, and that is the gate's ruling rather than this file's: GR15's
    statement is false of the charter's own printed DDL at three further tables --
    `edge.observed_block` beside `src_entity`/`dst_entity`, `claim.observed_block` beside
    `subject_entity`/`object_entity`, and `anchor.block_id` beside `anchor.entity_id` -- so
    `tools/gate_schema_lint.py` carries them as an exemption ROSTER and reported the defect. The
    roster is pinned here so a FIFTH table growing the pair is still a decision somebody has to
    make in a pull request, which is the whole value of a roster over a widened rule.
    """
    schema = schema_lint.read_schema(MIGRATIONS_DIR)
    findings, _classified = schema_lint.clause_fk_targets(schema)
    assert findings == [], [str(finding) for finding in findings]
    assert set(schema_lint.GR15_BOTH_SPACES_EXEMPT) == {"mention", "edge", "claim", "anchor"}


def test_the_tables_this_sink_writes_are_the_ones_the_worked_trace_names(
    connection: sqlite3.Connection,
) -> None:
    """02-architecture.md:488 lists what a Pass reaches through the sink; the happy path hits them.

    `block_link` is on that list and has no Draft that produces one -- `EdgeDraft` is
    entity-to-entity and `block_link` is block-to-block, which 06:238-243 homes in
    [07] rather than here. Recorded rather than invented.
    """
    _drive_happy_path(connection)
    written = {
        table
        for table in (
            "segment",
            "segment_block",
            "anchor",
            "ref_site",
            "entity",
            "entity_alias",
            "mention",
            "edge",
            "claim",
        )
        if _rows(connection, table) > 0
    }
    assert written == {
        "segment",
        "segment_block",
        "anchor",
        "ref_site",
        "entity",
        "entity_alias",
        "mention",
        "edge",
        "claim",
    }
    assert _rows(connection, "block_link") == 0, "no Draft produces one; 07 owns that table"


# ---------------------------------------------------------------------------------------------
# 6. The full happy path against a real migrated store
# ---------------------------------------------------------------------------------------------


def _drive_happy_path(conn: sqlite3.Connection) -> object:
    """A run, a segment's blocks covered, an anchor, a ref_site, an entity with an alias, a
    mention, an edge, a claim, then `end_run`. Returns the `RunReport`."""
    sink = _open(conn)
    acme = sink.entity(_org("e1"))
    beta = sink.entity(_org("e2", key="Beta Ltd", title="Beta Ltd"))
    assert acme != beta
    sink.alias(
        AliasDraft(
            entity=TmpRef("e1"), surface="ACME", alias_kind="abbrev", trust_claim=Trust.INFERRED
        )
    )
    sink.mention(
        MentionDraft(
            entity=TmpRef("e1"),
            at=(Cite("d7#1"), "Acme Corp"),
            surface="Acme Corp",
            trust_claim=Trust.EXTRACTED,
        )
    )
    sink.anchor(
        AnchorDraft(
            name="section 4.2(b)",
            akind=AnchorKind.SECTION,
            at=(Cite("d7#1"), "Acme Corp"),
            scope="corpus",
            surface="Section 4.2(b)",
        )
    )
    sink.xref(
        XrefDraft(
            name="section 4.2(b)",
            akind=AnchorKind.SECTION,
            at=(Cite("d7#2"), "See section 4.2(b) for the indemnity"),
            surface="section 4.2(b)",
        )
    )
    sink.edge(
        EdgeDraft(
            src=TmpRef("e1"),
            dst=TmpRef("e2"),
            relation="party_to",
            observed=(Cite("d7#1"), "entered into an agreement"),
            trust_claim=Trust.EXTRACTED,
        )
    )
    sink.claim(
        ClaimDraft(
            subject=TmpRef("e1"),
            object_entity=TmpRef("e2"),
            object_literal=None,
            object_datatype=None,
            claim_type="obligation",
            predicate="indemnifies",
            description="Acme indemnifies Beta",
            status="asserted",
            observed=(Cite("d7#1"), "an agreement"),
            trust_claim=Trust.EXTRACTED,
        )
    )
    sink.cover("entity", (Cite("d7#1"), Cite("d7#2"), Cite("d7#3")))
    return sink.end_run("ok", _Spend(wall_ms=12, calls=0, provider=""))


def test_the_full_happy_path_writes_one_row_per_item_and_leaves_the_store_sound(
    connection: sqlite3.Connection,
) -> None:
    """The composition test: nine tables, no quarantine, and SQLite's own FK verdict."""
    report = _drive_happy_path(connection)
    counts = {
        table: _rows(connection, table)
        for table in (
            "derive_run",
            "entity",
            "entity_alias",
            "mention",
            "edge",
            "claim",
            "anchor",
            "ref_site",
            "derive_cover",
            "quarantine",
            "diag",
        )
    }
    assert counts == {
        "derive_run": 1,
        "entity": 2,
        "entity_alias": 1,
        "mention": 1,
        "edge": 1,
        "claim": 1,
        "anchor": 1,
        "ref_site": 1,
        "derive_cover": 1,
        "quarantine": 0,
        "diag": 0,
    }
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert report.status == "ok"  # type: ignore[attr-defined]
    assert report.emitted == 8  # type: ignore[attr-defined]
    assert report.quarantined == 0  # type: ignore[attr-defined]
    assert report.covered == 3  # type: ignore[attr-defined]
    assert report.coverage_frac == pytest.approx(1.0)  # type: ignore[attr-defined]
    assert report.xrefs_bound == 1  # type: ignore[attr-defined]
    assert report.xrefs_unresolved == 0  # type: ignore[attr-defined]
    assert report.grounded_frac is None, "a free Pass reports no grounded share"  # type: ignore[attr-defined]


def test_the_run_row_carries_the_identity_the_report_repeats(
    connection: sqlite3.Connection,
) -> None:
    """`derive_run` is provenance interned once per `(segment, pass)`, and `end_run` closes it."""
    _drive_happy_path(connection)
    row = connection.execute(
        "SELECT segment_id, pass_id, at_gen, producer_id, method, origin_operator, cost_class, "
        "status, n_items, n_quarantined, spend, length(cache_key) FROM derive_run"
    ).fetchone()
    assert row[0] == SEGMENT_ID
    assert row[1] == "derive.entity.table"
    assert row[2] == GEN
    assert row[5] == "op.derive"
    assert row[6] == "free"
    assert row[7] == "ok"
    assert (row[8], row[9]) == (8, 0)
    assert '"wall_ms":12' in row[10] and "micros" not in row[10], "no dollars in Spend (INV-15)"
    assert row[11] == 64, "cache_key is a 64-char sha256_canonical hex string (0002:189)"


def test_the_entity_and_claim_cites_use_the_sigils_p7_freezes(
    connection: sqlite3.Connection,
) -> None:
    """`e` for an Entity and `k` for a Claim -- two of the four sigils (16-roadmap.md:728)."""
    _drive_happy_path(connection)
    cites = [str(value) for (value,) in connection.execute("SELECT cite FROM entity ORDER BY cite")]
    assert all(re.fullmatch(r"e\d+", cite) for cite in cites), cites
    claim_cite = connection.execute("SELECT cite FROM claim").fetchone()[0]
    assert re.fullmatch(r"k\d+", claim_cite), claim_cite


def test_the_entity_key_is_the_blocking_normaliser_and_not_the_grounding_one(
    connection: sqlite3.Connection,
) -> None:
    """`entity.key` is `normalize_key(surface)` -- *"A BLOCKING key, NOT an id"* (0002:242).

    `normalize_key` is `\\w`-closed, so a space becomes `_`; `normalize_k` collapses it to a space
    and would have produced `"acme corp"`. The two normalisers differ by four characters in their
    names and by exactly this in their output, which is why the choice is asserted rather than
    assumed.
    """
    sink = _open(connection)
    sink.entity(_org())
    assert connection.execute("SELECT key FROM entity").fetchone()[0] == "acme_corp"


# ---------------------------------------------------------------------------------------------
# 7. Grounding -- one function, three outcomes, and no invented offsets
# ---------------------------------------------------------------------------------------------


def test_ground_returns_offsets_in_block_text_coordinates_through_the_back_map() -> None:
    """A soft hyphen plus a line break: the quote has neither and the span still slices right."""
    text = "The hyphen­\nation rule."
    hit = ground(text, "hyphenation")
    assert hit is not None
    ts_a, ts_b, occurrences = hit
    assert occurrences == 1
    assert text[ts_a:ts_b] == "hyphen­\nation", "the span is in block.text space"


def test_ground_refuses_a_span_whose_boundary_falls_inside_an_expansion() -> None:
    """The round-trip post-condition, at the one producer. `"the f"` against a U+FB01 ligature.

    `back[end - 1] + 1` turns the truncated span into a SUPERSET span, and a superset is still not
    the quote, so the honest answer is `None` (06:600-618). A `.find()`-shaped implementation
    returns a wrong span here and nothing downstream can tell.
    """
    assert ground("the ﬁle", "the f") is None


def test_ground_recovers_an_offset_that_a_preceding_expansion_has_moved() -> None:
    """`ts_a` comes from the BACK-MAP and is never `.find()`'s own index (03:2930, 07:2505).

    A U+FB01 ligature before the match expands to two characters under NFKC, so the normalised
    index and the `block.text` index differ by one from the match onward. Taking `.find()`'s index
    would put the span one character to the right, and `block_text[ts_a:ts_b]` would read `"yphen "`
    -- a plausible-looking span, off by one, unrepairable without re-grounding the corpus. This is
    `_notes/s10-fix-ledger.md` D3's defect, and a fixture whose expansions all sit AFTER the match
    cannot see it.
    """
    text = "ﬁle: hyphen here"
    normalised_index = text.replace("ﬁ", "fi").index("hyphen")
    hit = ground(text, "hyphen")
    assert hit is not None
    ts_a, ts_b, _occurrences = hit
    assert ts_a != normalised_index, "the two coordinate systems really do differ here"
    assert text[ts_a:ts_b] == "hyphen", "the span slices block.text, not normalised space"


def test_ground_counts_every_occurrence_and_grounds_the_first() -> None:
    """`occurrences > 1` is recorded, never silent (06:610-613)."""
    hit = ground("ab ab ab", "ab")
    assert hit == (0, 2, 3)


def test_ground_refuses_an_empty_normalised_quote() -> None:
    """*"an empty quote is OW_GRAPH_UNGROUNDED, never a match"* (06:573)."""
    assert ground("anything", "   ") is None


def test_an_ungroundable_quote_quarantines_and_keeps_the_draft(
    connection: sqlite3.Connection,
) -> None:
    """`OW_GRAPH_UNGROUNDED`, the draft KEPT verbatim, and no `mention` row."""
    sink = _open(connection, cost_class="billed_api")
    sink.entity(_org("e1"))
    assert (
        sink.mention(
            MentionDraft(
                entity=TmpRef("e1"),
                at=(Cite("d7#1"), "Zeta Trust"),
                surface="Zeta Trust",
                trust_claim=Trust.INFERRED,
            )
        )
        == QUARANTINED_ID
    )
    assert _rows(connection, "mention") == 0
    code, _kind, payload, detail = _quarantine(connection)[0]
    assert code == OW_GRAPH_UNGROUNDED
    assert "Zeta Trust" in payload and "Zeta Trust" in detail
    report = sink.end_run("partial", _Spend())
    assert report.grounded_frac == pytest.approx(0.0), "a billed Pass reports the share"
    assert report.quarantined == 1, "the retained row is COUNTED, not merely written"
    assert report.inputs == 2, "the entity and the mention were both offered"
    assert connection.execute("SELECT n_quarantined FROM derive_run").fetchone()[0] == 1


def test_a_mention_span_slices_block_text_and_survives_a_length_changing_character(
    connection: sqlite3.Connection,
) -> None:
    """The stored `ts_a`/`ts_b` are `block.text` offsets, end to end through the sink.

    `d7#3` carries both shapes `normalize_k` changes length on -- a soft hyphen plus a line break,
    and a U+FB01 ligature after it -- so the normalised index of `"rule"` and its `block.text`
    index are three apart. Reading the row back and slicing the block's own text is the only
    assertion that can tell a right span from a plausible one; 07:2505 says there is no CHECK
    constraint that can, because SQLite cannot call `normalize_k`.
    """
    text = BLOCK_TEXTS[2][1]
    sink = _open(connection)
    sink.entity(_org("e1"))
    sink.mention(
        MentionDraft(
            entity=TmpRef("e1"),
            at=(Cite("d7#3"), "rule"),
            surface="rule",
            trust_claim=Trust.INFERRED,
        )
    )
    ts_a, ts_b = connection.execute("SELECT ts_a, ts_b FROM mention").fetchone()
    assert text[ts_a:ts_b] == "rule"
    normalised = text.replace(SOFT_HYPHEN_BREAK, "").replace(LIGATURE_FI, "fi")
    assert ts_a != normalised.index("rule"), "the two coordinate spaces differ here"


def test_restriction_bits_are_stamped_from_the_observed_block_and_or_upward(
    connection: sqlite3.Connection,
) -> None:
    """The sink is *"the ONLY place `restriction_bits` ... are stamped"* (charter.md:5444-5445).

    A restricted block taints every L3 row observed in it, and the bits OR UPWARD onto the entity
    (06:119-120): the mention carries the block's bits, and so does the entity the mention belongs
    to. A draft carries no `restriction_bits` field and could not have supplied them.
    """
    sink = _open(connection)
    sink.entity(_org("e1"))
    sink.mention(
        MentionDraft(
            entity=TmpRef("e1"),
            at=(Cite("d7#3"), "rule"),
            surface="rule",
            trust_claim=Trust.INFERRED,
        )
    )
    assert connection.execute("SELECT restriction_bits FROM mention").fetchone()[0] == 5
    assert connection.execute("SELECT restriction_bits FROM entity").fetchone()[0] == 5
    unrestricted = connection.execute(
        "SELECT restriction_bits FROM block WHERE cite = 'd7#1'"
    ).fetchone()[0]
    assert unrestricted == 0, "the fixture's premise: only d7#3 is restricted"


def test_a_quote_occurring_twice_grounds_the_first_and_records_a_diag(
    connection: sqlite3.Connection,
) -> None:
    """`Diag(OW_GRAPH_QUOTE_AMBIGUOUS)` carrying the count.

    *"the FIRST occurrence, plus Diag(OW_GRAPH_QUOTE_AMBIGUOUS) carrying the count"* (06:437),
    *"so the choice is recorded rather than silent"* (06:611-613).
    """
    sink = _open(connection)
    sink.entity(_org("e1"))
    sink.mention(
        MentionDraft(
            entity=TmpRef("e1"),
            at=(Cite("d7#2"), "section 4.2(b)"),
            surface="section 4.2(b)",
            trust_claim=Trust.INFERRED,
        )
    )
    code, detail = connection.execute("SELECT code, detail FROM diag").fetchone()
    assert code == OW_GRAPH_QUOTE_AMBIGUOUS
    assert '"occurrences":2' in detail
    ts_a = connection.execute("SELECT ts_a FROM mention").fetchone()[0]
    assert ts_a == BLOCK_TEXTS[1][1].index("section 4.2(b)"), "the FIRST occurrence"


def test_a_span_form_is_bounds_checked_and_never_re_grounded(
    connection: sqlite3.Connection,
) -> None:
    """*"`span` means the host takes the driver's offsets on trust and can only bounds-check
    them"* (06:662-664). In range it is written; past the end it is `OW_GRAPH_UNGROUNDED`."""
    sink = _open(connection)
    sink.entity(_org("e1"))
    good = MentionDraft(
        entity=TmpRef("e1"),
        at=(Cite("d7#1"), TextSpan(0, 9)),
        surface="Acme Corp",
        trust_claim=Trust.INFERRED,
    )
    assert sink.mention(good) != QUARANTINED_ID
    bad = MentionDraft(
        entity=TmpRef("e1"),
        at=(Cite("d7#1"), TextSpan(0, 10_000)),
        surface="Acme Corp",
        trust_claim=Trust.INFERRED,
    )
    assert sink.mention(bad) == QUARANTINED_ID
    assert _quarantine(connection)[0][0] == OW_GRAPH_UNGROUNDED


# ---------------------------------------------------------------------------------------------
# 8. `allowed_cites` is the containment, and it is checked before anything else
# ---------------------------------------------------------------------------------------------


def test_a_cite_outside_allowed_cites_quarantines_out_of_scope_even_though_the_block_exists(
    connection: sqlite3.Connection,
) -> None:
    """GR9. *"Enforced by the SIGNATURE, not by a later audit"* (06:360-361).

    `d7#2` is a real live block in this store and is still refused, because the containment answer
    must not depend on what else the store happens to hold -- that is the difference between a
    scope check and an existence check, and INV-8's inbound half rests on it.
    """
    sink = _open(connection, allowed=frozenset({Cite("d7#1")}))
    sink.entity(_org("e1"))
    sink.mention(
        MentionDraft(
            entity=TmpRef("e1"),
            at=(Cite("d7#2"), "section 4.2(b)"),
            surface="s",
            trust_claim=Trust.INFERRED,
        )
    )
    assert _quarantine(connection)[0][0] == OW_GRAPH_OUT_OF_SCOPE_BLOCK
    assert _rows(connection, "mention") == 0


def test_an_in_scope_cite_naming_no_row_quarantines_dangling_cite(
    connection: sqlite3.Connection,
) -> None:
    """A pattern-valid cite naming no row in this corpus (06:685)."""
    ghost = Cite("d7#999")
    sink = _open(connection, allowed=frozenset({ghost}))
    sink.entity(_org("e1"))
    sink.mention(
        MentionDraft(
            entity=TmpRef("e1"), at=(ghost, "anything"), surface="x", trust_claim=Trust.INFERRED
        )
    )
    assert _quarantine(connection)[0][0] == OW_GRAPH_DANGLING_CITE


# ---------------------------------------------------------------------------------------------
# 9. Vocabularies, shapes and the rules the DDL also carries
# ---------------------------------------------------------------------------------------------


def test_an_etype_outside_the_charset_or_the_vocabulary_quarantines(
    connection: sqlite3.Connection,
) -> None:
    """Two arms, one code: *"an etype outside `etype_vocab`, or failing the charset"* (06:693)."""
    sink = _open(connection)
    assert sink.entity(_org(etype="Org")) == QUARANTINED_ID
    assert sink.entity(_org(etype="covenant_party")) == QUARANTINED_ID
    assert [row[0] for row in _quarantine(connection)] == [
        OW_GRAPH_ETYPE_OUT_OF_VOCAB,
        OW_GRAPH_ETYPE_OUT_OF_VOCAB,
    ]


def test_a_symmetric_relation_is_stored_with_the_lower_entity_first(
    connection: sqlite3.Connection,
) -> None:
    """*"A `symmetric` relation is stored with `src_entity < dst_entity`, so `co_occurs_with`
    cannot appear twice"* (06:322), and the symmetry is read off `relation_vocab`."""
    sink = _open(connection)
    first = sink.entity(_org("e1"))
    second = sink.entity(_org("e2", key="Beta Ltd", title="Beta Ltd"))
    sink.edge(
        EdgeDraft(
            src=TmpRef("e2"),
            dst=TmpRef("e1"),
            relation="co_occurs_with",
            observed=(Cite("d7#1"), "an agreement"),
            trust_claim=Trust.INFERRED,
        )
    )
    stored = connection.execute("SELECT src_entity, dst_entity FROM edge").fetchone()
    assert stored == (min(first, second), max(first, second))


def test_a_second_edge_with_the_same_identity_corroborates_and_never_promotes(
    connection: sqlite3.Connection,
) -> None:
    """*"Corroboration increments `corroborations`; it NEVER raises trust"* (06:199-200)."""
    sink = _open(connection)
    sink.entity(_org("e1"))
    sink.entity(_org("e2", key="Beta Ltd", title="Beta Ltd"))
    draft = EdgeDraft(
        src=TmpRef("e1"),
        dst=TmpRef("e2"),
        relation="party_to",
        observed=(Cite("d7#1"), "an agreement"),
        trust_claim=Trust.AMBIGUOUS,
    )
    first = sink.edge(draft)
    again = sink.edge(
        EdgeDraft(
            src=TmpRef("e1"),
            dst=TmpRef("e2"),
            relation="party_to",
            observed=(Cite("d7#1"), "an agreement"),
            trust_claim=Trust.EXTRACTED,
        )
    )
    assert first == again
    row = connection.execute("SELECT corroborations, trust FROM edge").fetchone()
    assert row == (2, int(Trust.AMBIGUOUS))
    assert _rows(connection, "edge") == 1


def test_a_self_edge_quarantines_rather_than_raising_the_ddls_check(
    connection: sqlite3.Connection,
) -> None:
    """`CHECK (src_entity <> dst_entity)`. A malformed draft must produce DATA (06:462-464)."""
    sink = _open(connection)
    sink.entity(_org("e1"))
    assert (
        sink.edge(
            EdgeDraft(
                src=TmpRef("e1"),
                dst=TmpRef("e1"),
                relation="party_to",
                observed=(Cite("d7#1"), "an agreement"),
                trust_claim=Trust.INFERRED,
            )
        )
        == QUARANTINED_ID
    )
    assert _quarantine(connection)[0][0] == OW_GRAPH_UNPARSED_ITEM
    assert _rows(connection, "edge") == 0


def test_a_claim_that_is_neither_bipartite_nor_typed_quarantines(
    connection: sqlite3.Connection,
) -> None:
    """Both DDL CHECKs, validated in the sink so the malformed draft survives as data."""
    sink = _open(connection)
    sink.entity(_org("e1"))
    both = ClaimDraft(
        subject=TmpRef("e1"),
        object_entity=TmpRef("e1"),
        object_literal="2026",
        object_datatype="xsd:date",
        claim_type="event",
        predicate="p",
        description="d",
        status="asserted",
        observed=(Cite("d7#1"), "an agreement"),
        trust_claim=Trust.INFERRED,
    )
    assert sink.claim(both) == QUARANTINED_ID
    assert _rows(connection, "claim") == 0
    assert _quarantine(connection)[0][0] == OW_GRAPH_UNPARSED_ITEM


def test_t_precision_is_derived_from_the_string_and_a_disagreeing_draft_quarantines(
    connection: sqlite3.Connection,
) -> None:
    """`TimePrecision` is *"DERIVED BY THE SINK ... never asked of a model"* (06:1450, 06:2535).

    Four characters is `year` and seven is `month`, so a draft supplying `day` over `"2026-06"`
    contradicts its own timestamp and is retained rather than silently overwritten.
    """
    sink = _open(connection)
    sink.entity(_org("e1"))
    base: dict[str, object] = {
        "subject": TmpRef("e1"),
        "object_entity": None,
        "object_literal": "signed",
        "object_datatype": "string",
        "claim_type": "event",
        "predicate": "p",
        "description": "d",
        "status": "asserted",
        "observed": (Cite("d7#1"), "an agreement"),
        "trust_claim": Trust.INFERRED,
    }
    assert sink.claim(ClaimDraft(**base, t_start="2026-06")) != QUARANTINED_ID  # type: ignore[arg-type]
    assert connection.execute("SELECT t_precision FROM claim").fetchone()[0] == "month"
    assert sink.claim(ClaimDraft(**base, t_start="2026-06", t_precision="day")) == QUARANTINED_ID  # type: ignore[arg-type]
    assert _quarantine(connection)[0][0] == OW_GRAPH_UNPARSED_ITEM
    assert '"derived":"month"' in _quarantine(connection)[0][3]


def test_a_second_anchor_definition_in_one_generation_keeps_both_surfaces(
    connection: sqlite3.Connection,
) -> None:
    """*"the document is ambiguous and picking one silently is wrong"* (06:115-118)."""
    sink = _open(connection)
    first = AnchorDraft(
        name="section 4.2(b)",
        akind=AnchorKind.SECTION,
        at=(Cite("d7#1"), "Acme Corp"),
        scope="document",
        surface="Section 4.2(b)",
    )
    sink.anchor(first)
    sink.anchor(
        AnchorDraft(
            name="Section 4.2(B)",
            akind=AnchorKind.SECTION,
            at=(Cite("d7#2"), "section 4.2(b)"),
            scope="document",
            surface="SECTION 4.2(B)",
        )
    )
    assert _rows(connection, "anchor") == 1
    code, kind, payload, detail = _quarantine(connection)[0]
    assert (code, kind) == (OW_GRAPH_UNPARSED_ITEM, "anchor")
    assert "SECTION 4.2(B)" in payload, "the rejected surface"
    assert "Section 4.2(b)" in detail, "and the one already stored"


def test_an_xref_whose_name_has_no_anchor_is_still_written_and_counted_unresolved(
    connection: sqlite3.Connection,
) -> None:
    """`ref_site` has *"NO status column, EVER"*: the occurrence is written either way."""
    sink = _open(connection)
    sink.xref(
        XrefDraft(
            name="exhibit c",
            akind=AnchorKind.EXHIBIT,
            at=(Cite("d7#2"), "the indemnity"),
            surface="Exhibit C",
        )
    )
    assert _rows(connection, "ref_site") == 1
    report = sink.end_run("ok", _Spend())
    assert (report.xrefs_bound, report.xrefs_unresolved) == (0, 1)
    assert _rows(connection, "ref_unresolved") == 1, "the anti-join view agrees with the counter"


def test_a_second_pass_proposing_the_same_entity_converges_and_may_only_weaken_trust(
    connection: sqlite3.Connection,
) -> None:
    """The upsert on `UNIQUE (scope, etype, key)` is the only binding mechanism (06:628-634)."""
    sink = _open(connection)
    first = sink.entity(_org("e1", trust_claim=Trust.EXTRACTED))
    again = sink.entity(_org("e2", title="ACME CORPORATION", trust_claim=Trust.AMBIGUOUS))
    assert first == again
    row = connection.execute("SELECT count(*), min(trust), min(title) FROM entity").fetchone()
    assert row == (1, int(Trust.AMBIGUOUS), "Acme Corp"), "trust fell; the title did not move"


# ---------------------------------------------------------------------------------------------
# 10. The frozen Protocol, the twelve, and the five ids
# ---------------------------------------------------------------------------------------------


def _declared(cls: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(member)
        for name, member in vars(cls).items()
        if callable(member) and not name.startswith("_")
    }


def test_the_sink_declares_exactly_the_protocols_twelve_methods_and_no_thirteenth() -> None:
    """4 + 6 + 11 + 12 = 33, and the twelve are this file's share (06:344, 02:702).

    Compared name by name against the frozen `GraphSink`, not against a transcribed list, so a
    method added here without an ADR fails just as a method added there would.
    """
    protocol = _declared(GraphSink)
    sink = _declared(SqliteGraphSink)
    assert len(protocol) == 12, sorted(protocol)
    assert set(sink) == set(protocol), set(sink) ^ set(protocol)


def test_every_method_takes_the_parameters_the_protocol_prints() -> None:
    """Parameter names and kinds, in order. The annotations are compared elsewhere; the SHAPE is
    what a runner binds against, and a renamed keyword is a silent break at the call site."""
    for name, signature in _declared(GraphSink).items():
        theirs = [
            (parameter.name, parameter.kind, parameter.default is inspect.Parameter.empty)
            for parameter in signature.parameters.values()
        ]
        ours = [
            (parameter.name, parameter.kind, parameter.default is inspect.Parameter.empty)
            for parameter in _declared(SqliteGraphSink)[name].parameters.values()
        ]
        assert ours == theirs, name


def test_the_sink_satisfies_the_protocol_as_a_type_and_at_runtime(
    connection: sqlite3.Connection,
) -> None:
    """A structural check the type checker also makes, done here so the file does not rely on one.

    `GraphSink` is deliberately NOT `@runtime_checkable` (`store/__init__.py` argues why), so
    `isinstance` is unavailable and the honest runtime witness is that every name resolves to a
    bound method on a real instance.
    """
    sink: GraphSink = SqliteGraphSink(connection)
    for name in _declared(GraphSink):
        assert callable(getattr(sink, name)), name


def test_the_five_id_newtypes_are_five_distinct_declarations() -> None:
    """An `EntityId` cannot be passed where a `MentionId` belongs.

    That is a TYPE-CHECK-time guarantee and the runtime cannot witness it: a `NewType` erases, so
    `EntityId(3) == MentionId(3)` and `type(EntityId(3)) is int` are both true. What the runtime
    CAN witness is that there are five distinct declarations with five distinct names, which is
    the thing a careless edit (one alias reused for two id spaces) would break -- and it is
    precisely the INV-21 failure the framework has already paid for once.
    """
    ids = (RunId, EntityId, MentionId, EdgeId, ClaimId)
    assert len({id(alias) for alias in ids}) == 5
    assert [alias.__name__ for alias in ids] == [
        "RunId",
        "EntityId",
        "MentionId",
        "EdgeId",
        "ClaimId",
    ]
    assert all(alias.__supertype__ is int for alias in ids)
    assert EntityId(3) == MentionId(3), "recorded: the runtime cannot tell them apart"


# ---------------------------------------------------------------------------------------------
# 11. Lifecycle refusals
# ---------------------------------------------------------------------------------------------


def test_every_method_refuses_before_begin_run(connection: sqlite3.Connection) -> None:
    """`begin_run` fixes the Segment, the identity and `allowed_cites`; nothing precedes it."""
    sink = SqliteGraphSink(connection)
    with pytest.raises(GraphError, match="no open run"):
        sink.entity(_org())
    with pytest.raises(GraphError, match="no open run"):
        sink.cover("entity", (), empty_reason="r")
    with pytest.raises(GraphError, match="no open run"):
        sink.quarantine("entity", OW_GRAPH_UNGROUNDED, {})


def test_a_method_after_end_run_refuses(connection: sqlite3.Connection) -> None:
    """`end_run` COMMITS ONE TXN (06:373); a write after it would land in the next one."""
    sink = _open(connection)
    sink.end_run("empty", _Spend())
    with pytest.raises(GraphError, match="finished"):
        sink.entity(_org())


def test_a_second_begin_run_on_one_sink_refuses(connection: sqlite3.Connection) -> None:
    """One sink drives one run, because the tmp table and the cite scope are per invocation."""
    sink = _open(connection)
    with pytest.raises(GraphError, match="already has a run"):
        sink.begin_run(_segment_ref(), _identity(), ALL_CITES)


def test_begin_run_refuses_a_cover_bitmap_of_the_wrong_width(
    connection: sqlite3.Connection,
) -> None:
    """*"a 513-block segment is a REFUSAL, never a truncation"* (0002:222-224)."""
    sink = SqliteGraphSink(connection)
    with pytest.raises(GraphError, match="64"):
        sink.begin_run(
            SegmentRef(
                segment_id=SEGMENT_ID,
                doc_ord=DOC_ORD,
                gen=GEN,
                content_digest=b"\x04",
                uncovered=bytes(8),
            ),
            _identity(),
            ALL_CITES,
        )


def test_begin_run_returns_the_run_id_the_row_carries(connection: sqlite3.Connection) -> None:
    """The id is minted INSIDE the sink and no Draft can name it (GR11)."""
    sink = SqliteGraphSink(connection)
    run_id = sink.begin_run(_segment_ref(), _identity(), ALL_CITES)
    stored = connection.execute("SELECT run_id FROM derive_run").fetchone()[0]
    assert run_id == stored


def test_end_run_refuses_a_status_outside_the_five(connection: sqlite3.Connection) -> None:
    """`RunStatus` narrows the charter's `status: str` to `derive_run`'s CHECK (06:391-393)."""
    sink = _open(connection)
    with pytest.raises(GraphError, match="five values"):
        sink.end_run("done", _Spend())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# 12. The item budget
# ---------------------------------------------------------------------------------------------


def test_the_item_budget_quarantines_naming_the_knob(connection: sqlite3.Connection) -> None:
    """*"emit 100,000 entities named ACME": `OW_GRAPH_ITEM_BUDGET`, naming the knob* (06:2154).

    The ceiling is `MAX_ITEMS_PER_SEGMENT` and it is not retyped here: the sink is driven past a
    patched value, so the test asserts the MECHANISM against `limits.py`'s name rather than
    against a second copy of its number (INV-21).
    """
    sink = _open(connection)
    sink._emitted = 10**9  # driving the budget without minting 2,048 rows first
    assert sink.entity(_org()) == QUARANTINED_ID
    code, _kind, _payload, detail = _quarantine(connection)[0]
    assert code == OW_GRAPH_ITEM_BUDGET
    assert '"limit":"MAX_ITEMS_PER_SEGMENT"' in detail
