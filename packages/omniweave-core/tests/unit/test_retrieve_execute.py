"""`retrieve()` over a REAL store: the composition P6 built the parts of and never ran in order.

Every store here is migrated by the shipped migrations and seeded with SQL, the way
`test_store_reader.py` seeds one, and every query goes through the real `SqliteReader` on a
read-only connection. So what these tests assert is the whole L4 edge 16:92 draws --
`retrieve() -> identity + lexical channels over block_fts, fuse(), ceiling()` -- plus the Verdict
built from what actually ran.

**The sharpest tests are the three that make the honesty machinery move**:
- `test_a_commit_between_the_ranking_and_the_pack_is_gate_3`: a writer commits while the query is
  inside its snapshot, the ranked text stays the ranked generation's, and the Verdict says the
  store moved;
- `test_a_channel_over_its_own_budget_is_gate_1_and_the_query_deadline_is_not`: the two-deadline
  split, with a clock the test spends;
- `test_no_ingest_scope_row_is_degraded_and_never_absent`: nothing matched, and the answer is
  still not citable as absence, because nobody recorded what was scanned.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the fixtures seed a REAL store, as test_store_reader.py's do.
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import NamedTuple

import pytest
from omniweave_core.errors import UsageError
from omniweave_core.model.enums import Kind, Layer, Method, OsKind, Quote, Trust
from omniweave_core.retrieve import Hit, Response, retrieve
from omniweave_core.retrieve import execute as ex
from omniweave_core.retrieve.channels import DSL_FIELDS
from omniweave_core.retrieve.types import (
    CHANNELS,
    ChannelStatus,
    OffReason,
    Query,
    QueryBudget,
    RetrievalPolicy,
    Rule,
)
from omniweave_core.retrieve.verdict import VerdictState
from omniweave_core.store import migrate
from omniweave_core.store import reader as rd
from omniweave_core.store import sqlite as ow
from omniweave_core.store.types import Coverage, Expand, Filters

NOW_NS = 1_757_400_000_000_000_000
DIGEST = b"\x00" * 16
POLICY = RetrievalPolicy()
TEXTS = {
    1: "Termination",
    2: "Either party may terminate this agreement with thirty days notice.",
    3: "Fees are payable monthly in arrears.",
}


class Built(NamedTuple):
    path: Path
    writer: sqlite3.Connection


@pytest.fixture
def built(tmp_path: Path) -> Iterator[Built]:
    path = tmp_path / "index.owstore"
    writer = ow.connect(path)
    migrate.apply_pending(writer, now_ns=NOW_NS)
    try:
        yield Built(path=path, writer=writer)
    finally:
        writer.close()


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    return int(row[0])


def _seed(built: Built, *, scope: bool = True, texts: dict[int, str] | None = None) -> None:
    """One document, three blocks on page 1: a heading and two paragraphs. `scope` writes the
    `ingest_scope` row that says the scan finished, which gate 4 reads."""
    conn = built.writer
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
        "VALUES('op.parse', 1, 'fp', X'00')"
    )
    producer = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
    conn.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
        "                format_evidence, source_bytes, gen, status, model_version, declared, "
        "                achieved) "
        "VALUES(1, ?, ?, 'file:///corpus/contract.pdf', 'application/pdf', 'pdf', '{}', 1, 1, "
        "       'ok', '1.1', '{}', '{}')",
        (b"\x01" * 16, DIGEST),
    )
    conn.execute(
        "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
        "VALUES(1, 1, 1, ?, ?, ?)",
        (_code(conn, "page_kind", "page"), _code(conn, "method", "native"), producer),
    )
    for block_id, text in (texts or TEXTS).items():
        kind = "heading" if block_id == 1 else "paragraph"
        conn.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, "
            "                  label, text, content_digest, os_kind, producer_id, method, trust, "
            "                  quote, origin_operator, origin_driver, driver_schema_v, "
            "                  restriction_bits, state) "
            "VALUES(?, 1, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, 4, 'op.parse', 'drv', 1, 0, 0)",
            (
                block_id,
                f"p1/{block_id}",
                f"d1#{block_id}",
                block_id,
                _code(conn, "kind", kind),
                _code(conn, "layer", "body"),
                text if block_id == 1 else None,
                text,
                DIGEST,
                _code(conn, "origin_span_kind", "none"),
                producer,
                _code(conn, "method", "native"),
            ),
        )
    if scope:
        conn.execute(
            "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, "
            "                         complete) VALUES('corpus', 1, 1, 0, ?, 1)",
            (NOW_NS,),
        )
    conn.execute("COMMIT")


def _reader(built: Built) -> rd.SqliteReader:
    return rd.SqliteReader(ow.connect_readonly(built.path), now_ns=NOW_NS)


def _ask(built: Built, q: Query, pol: RetrievalPolicy = POLICY) -> Response:
    return retrieve(_reader(built), q, pol)


# ---------------------------------------------------------------------------------------------
# the composition, end to end
# ---------------------------------------------------------------------------------------------


def test_a_lexical_match_is_a_cited_hit_and_an_honest_verdict(built: Built) -> None:
    _seed(built)
    response = _ask(built, Query(text="terminate agreement notice"))
    first = response.hits[0]
    assert (first.block_id, first.cite, first.addr) == (2, "d1#2", "p1/2")
    assert first.text == TEXTS[2]
    assert first.channel_ranks == {"lexical": 1}
    assert first.trust is Trust.EXTRACTED
    assert first.quote is Quote.VERBATIM
    assert first.byte_exact is False, "achieved never reaches origin_span=exact in this build"
    verdict = response.verdict
    assert verdict.gates == ()
    assert verdict.state in {VerdictState.OK, VerdictState.LOW_CONFIDENCE}
    assert verdict.best_score == first.score
    assert verdict.freshness == "fresh"
    assert verdict.matches_before_packing == len(response.hits)


def test_every_channel_is_named_and_the_two_that_cannot_run_say_why(built: Built) -> None:
    """07:2016: all five keys, always. `semantic` is `OFF(vectors)` on a store with no backend,
    and `structural` is `OFF(not_in_plan)` when the query binds no `Expand` (D518)."""
    _seed(built)
    verdict = _ask(built, Query(text="fees")).verdict
    assert set(verdict.channels) == set(CHANNELS)
    assert verdict.channels["lexical"] is ChannelStatus.OK
    assert verdict.channels["semantic"] is ChannelStatus.OFF
    assert verdict.channels["structural"] is ChannelStatus.OFF
    assert "channel_unavailable" not in verdict.gates


def test_nothing_matching_in_a_whole_corpus_is_absent_and_citable(built: Built) -> None:
    _seed(built)
    response = _ask(built, Query(text="unicorn"))
    assert response.hits == ()
    assert response.verdict.state is VerdictState.ABSENT
    assert response.verdict.citable_as_absence


def test_no_ingest_scope_row_is_degraded_and_never_absent(built: Built) -> None:
    """Gate 4: *"No row means coverage UNKNOWN, never clean"*. The same empty result as the test
    above, and the one fact that differs is whether anything recorded what was scanned."""
    _seed(built, scope=False)
    verdict = _ask(built, Query(text="unicorn")).verdict
    assert verdict.state is VerdictState.DEGRADED
    assert "coverage_incomplete" in verdict.gates
    assert not verdict.citable_as_absence


def test_an_address_the_caller_holds_resolves_at_the_identity_tier(built: Built) -> None:
    _seed(built)
    response = _ask(built, Query(refs=("d1#3",)))
    first = response.hits[0]
    assert first.block_id == 3
    assert first.identity_grade == "cite_exact"
    assert "identity" in first.channel_ranks


def test_a_cite_in_the_text_is_lifted_to_identity_and_not_searched(built: Built) -> None:
    _seed(built)
    first = _ask(built, Query(text="what does d1#3 say")).hits[0]
    assert first.block_id == 3
    assert first.identity_grade == "cite_exact"


# ---------------------------------------------------------------------------------------------
# the DSL fields onto Filters (D516)
# ---------------------------------------------------------------------------------------------


def test_the_field_table_is_the_sanitisers_eight_fields() -> None:
    assert tuple(ex._FIELDS) == DSL_FIELDS


def test_a_kind_field_narrows_what_every_channel_scores(built: Built) -> None:
    _seed(built)
    everything = _ask(built, Query(text="termination terminate"))
    headings = _ask(built, Query(text="termination terminate kind:heading"))
    assert {hit.block_id for hit in everything.hits} >= {1, 2}
    assert [hit.block_id for hit in headings.hits] == [1]


@pytest.mark.parametrize(
    ("text", "legal"),
    [("fees kind:novel", "paragraph"), ("fees trust:certainly", "extracted")],
)
def test_an_invalid_field_value_is_a_usage_error_naming_the_legal_set(
    built: Built, text: str, legal: str
) -> None:
    _seed(built)
    with pytest.raises(UsageError, match=legal):
        _ask(built, Query(text=text))


def test_a_field_and_a_filter_that_disagree_are_refused_rather_than_ranked(built: Built) -> None:
    _seed(built)
    q = Query(text="fees kind:heading", filters=Filters(kinds=frozenset({Kind.PARAGRAPH})))
    with pytest.raises(UsageError, match="both set the same filter"):
        _ask(built, q)


def test_the_page_field_is_an_inclusive_range() -> None:
    assert ex._field("page", "2-4") == ("pages", range(2, 5))
    assert ex._field("page", "7") == ("pages", range(7, 8))
    with pytest.raises(UsageError):
        ex._field("page", "4-2")


# ---------------------------------------------------------------------------------------------
# the deadlines, the short circuit, and the pack
# ---------------------------------------------------------------------------------------------


@dataclass
class Clock:
    """A monotonic clock the test spends: every read advances it by `step_ms`."""

    step_ms: int
    now_ns: int = 0
    reads: list[int] = field(default_factory=list)

    def __call__(self) -> int:
        self.now_ns += self.step_ms * 1_000_000
        self.reads.append(self.now_ns)
        return self.now_ns


def test_a_channel_over_its_own_budget_is_gate_1_and_the_query_deadline_is_not(
    built: Built,
) -> None:
    """07:1789. Each Channel read costs 30 ms of this clock and `identity`'s own budget is 15:
    UNAVAILABLE(timeout), gate 1. Then the query deadline arrives and the rest are
    OFF(query_deadline), which is ceiling-bearing and gates nothing."""
    _seed(built)
    budget = QueryBudget(query_ms=130, hydration_reserve_ms=40)
    q = Query(text="fees", budget=budget)
    pol = RetrievalPolicy(rules=(Rule(rule_id="three", channels=("identity", "exact", "lexical")),))
    budget_ok = replace(budget, channel_ms={"identity": 15, "exact": 25, "lexical": 50})
    response = retrieve(_reader(built), replace(q, budget=budget_ok), pol, monotonic_ns=Clock(30))
    results = response.verdict.channels
    assert results["identity"] is ChannelStatus.UNAVAILABLE
    assert "timed_out" in response.verdict.gates
    assert results["lexical"] is ChannelStatus.OFF
    assert response.verdict.state is VerdictState.DEGRADED


def test_a_satisfied_short_circuit_turns_the_remaining_channels_off(built: Built) -> None:
    _seed(built)
    rule = Rule(
        rule_id="cite",
        channels=("identity", "exact", "lexical"),
        short_circuit="identity>=@thresholds.certain and mode=cite",
    )
    pol = RetrievalPolicy(rules=(rule,), thresholds={"certain": 50.0})
    verdict = _ask(built, Query(refs=("d1#2",), mode="cite"), pol).verdict
    assert verdict.channels["identity"] is ChannelStatus.OK
    assert verdict.channels["exact"] is ChannelStatus.OFF
    assert verdict.channels["lexical"] is ChannelStatus.OFF


def test_prove_absent_never_short_circuits(built: Built) -> None:
    """07:1825: an absence claim is licensed by all Channels having looked."""
    _seed(built)
    rule = Rule(rule_id="cite", channels=("identity", "lexical"), short_circuit="identity>=50")
    verdict = _ask(
        built, Query(refs=("d1#2",), mode="prove_absent"), RetrievalPolicy(rules=(rule,))
    ).verdict
    assert verdict.channels["lexical"] is not ChannelStatus.OFF


def test_a_short_circuit_form_nothing_evaluates_is_refused(built: Built) -> None:
    _seed(built)
    rule = Rule(rule_id="bad", channels=("identity",), short_circuit="identity ~ 50")
    with pytest.raises(UsageError, match="is not a form"):
        _ask(built, Query(refs=("d1#2",)), RetrievalPolicy(rules=(rule,)))


def test_max_chars_cuts_at_a_block_boundary_and_a_cut_to_nothing_is_gate_12(built: Built) -> None:
    _seed(built)
    q = Query(text="termination terminate agreement")
    whole = _ask(built, q)
    assert len(whole.hits) >= 2
    first_chars = len(whole.hits[0].text or "")
    one = _ask(built, replace(q, max_chars=first_chars))
    assert [hit.block_id for hit in one.hits] == [whole.hits[0].block_id]
    none = _ask(built, replace(q, max_chars=first_chars - 1))
    assert none.hits == ()
    assert "truncated_by_packing" in none.verdict.gates
    assert none.verdict.matches_before_packing == whole.verdict.matches_before_packing


# ---------------------------------------------------------------------------------------------
# the snapshot: one view, and the generation compared across its boundary
# ---------------------------------------------------------------------------------------------


@dataclass
class Committing:
    """A `Reader` that commits a re-index through the writer the moment the pack starts."""

    inner: rd.SqliteReader
    writer: sqlite3.Connection

    def snapshot(self):
        return self.inner.snapshot()

    def capabilities(self):
        return self.inner.capabilities()

    def narrow(self, s, f):
        return self.inner.narrow(s, f)

    def channel(self, s, spec, n):
        return self.inner.channel(s, spec, n)

    def hydrate(self, s, ids):
        self.writer.execute("BEGIN IMMEDIATE")
        self.writer.execute("UPDATE block SET text = 'reindexed' WHERE block_id = 3")
        self.writer.execute("UPDATE index_state SET v = '1' WHERE k = 'generation'")
        self.writer.execute("COMMIT")
        return self.inner.hydrate(s, ids)

    def coverage(self, s, f):
        return self.inner.coverage(s, f)


def test_a_commit_between_the_ranking_and_the_pack_is_gate_3(built: Built) -> None:
    _seed(built)
    reader = Committing(_reader(built), built.writer)
    response = retrieve(reader, Query(text="fees payable"), POLICY)  # type: ignore[arg-type]
    assert response.hits[0].text == TEXTS[3], "the payload is the generation that was ranked"
    assert response.verdict.snapshot_gen == 0
    assert "store_changed_mid_query" in response.verdict.gates


# ---------------------------------------------------------------------------------------------
# the small decisions, each at its one site
# ---------------------------------------------------------------------------------------------


def _row(
    *, quote: Quote = Quote.VERBATIM, achieved: str = '{"origin_span": "exact"}'
) -> rd.HydratedRow:
    return rd.HydratedRow(
        block_id=1,
        cite="d1#1",
        addr="p1/1",
        page=1,
        kind=Kind.PARAGRAPH,
        layer=Layer.BODY,
        text="x",
        trust=Trust.EXTRACTED,
        quote=quote,
        restriction_bits=0,
        os_kind=OsKind.NONE,
        os_part=None,
        segment_id=None,
        method=Method.NATIVE,
        chars=1,
        uri="file:///a",
        achieved=achieved,
    )


def test_byte_exact_is_the_four_conjuncts_and_nothing_else() -> None:
    assert ex.byte_exact(_row())
    assert not ex.byte_exact(_row(quote=Quote.NORMALIZED))
    assert not ex.byte_exact(_row(achieved='{"origin_span": "normalized"}'))
    assert not ex.byte_exact(_row(achieved='{"origin_span": "exact", "forfeits": ["citation"]}'))
    assert not ex.byte_exact(_row(achieved="not json"))
    assert not ex.byte_exact(_row(), fmt="docx")


def _coverage(**over: int) -> Coverage:
    fields = {
        "discovered": 1,
        "indexed": 1,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "scope_rows": 1,
        "pending_work": 0,
        "stale_units": 0,
        "unreadable_units": 0,
    }
    fields.update(over)
    return Coverage(complete=True, gaps=(), **fields)


@pytest.mark.parametrize(
    ("over", "expected"),
    [
        ({}, "fresh"),
        ({"pending_work": 2}, "refreshing"),
        ({"stale_units": 1, "pending_work": 2}, "stale"),
        ({"unreadable_units": 1, "stale_units": 1}, "unknown"),
        ({"discovered": 0, "indexed": 0, "scope_rows": 0}, "not_tracked"),
    ],
)
def test_freshness_is_rolled_up_most_specific_first(over: dict[str, int], expected: str) -> None:
    assert ex.freshness(_coverage(**over)) == expected


def test_the_structural_channel_runs_when_the_query_binds_an_expand(built: Built) -> None:
    """D518's other side: with an `Expand` the Channel is REQUESTED, so it runs, and an `off`
    for it would degrade (gate 2's `requested` clause)."""
    _seed(built)
    built.writer.execute(
        "INSERT INTO relation_vocab(relation, symmetric, actor_rule, source) "
        "VALUES('refers_to', 0, 'source refers to target', 'builtin')"
    )
    built.writer.commit()
    q = Query(text="fees", expand=Expand(relations=frozenset({"refers_to"})))
    verdict = _ask(built, q).verdict
    assert verdict.channels["structural"] is not ChannelStatus.OFF


def test_the_off_reasons_this_module_writes_are_members_of_the_closed_set() -> None:
    """07:1201: `OffReason` is closed because `ceiling()` branches on it."""
    assert {OffReason.VECTORS, OffReason.NOT_IN_PLAN, OffReason.QUERY_DEADLINE} <= set(OffReason)


def test_retrieve_is_bound_at_the_package_and_hit_has_fourteen_fields() -> None:
    import dataclasses  # noqa: PLC0415

    assert len(dataclasses.fields(Hit)) == 14
    assert [f.name for f in dataclasses.fields(Response)] == ["hits", "verdict", "cost"]


# ---------------------------------------------------------------------------------------------
# answer.pack: the Retrieval to the Answer document (02:252's row 28, D523)
# ---------------------------------------------------------------------------------------------


def _document(built: Built, q: Query, **pack_kw: object) -> str:
    from omniweave_core.answer import render  # noqa: PLC0415
    from omniweave_core.answer.pack import pack  # noqa: PLC0415

    retrieval = ex.execute(_reader(built), q, POLICY)
    packed = pack(retrieval, corpus="handbook", **pack_kw)  # type: ignore[arg-type]
    return render(packed.answer, max_chars=packed.max_chars)


def test_a_retrieval_renders_as_the_nine_section_document(built: Built) -> None:
    _seed(built)
    document = _document(built, Query(text="terminate agreement notice"))
    assert document.startswith("ow/1 ")
    assert "corpus=handbook@0 fresh" in document
    assert "**ow:evidence**" in document
    assert "**« d1#2 · contract.pdf p.1 · verbatim · extracted" in document
    assert TEXTS[2] in document
    assert "verdict.channels   = identity:" in document
    assert "structural:off(not_in_plan) semantic:off(vectors)" in document


def test_cites_are_qualified_when_the_deployment_has_two_corpora(built: Built) -> None:
    _seed(built)
    document = _document(built, Query(text="fees payable"), qualify=True)
    assert "**« handbook:d1#3 ·" in document


def test_an_absent_verdict_renders_its_state_with_no_evidence(built: Built) -> None:
    _seed(built)
    document = _document(built, Query(text="unicorn"))
    assert document.startswith("ow/1 absent ")
    assert "blocks=0/0" in document


def test_every_failed_gate_is_a_blocking_line_with_its_fix(built: Built) -> None:
    _seed(built, scope=False)
    document = _document(built, Query(text="unicorn"))
    assert document.startswith("ow/1 degraded ")
    assert "> coverage_incomplete: no ingest_scope row is in view" in document
    assert "Fix: `ow corpora --detail coverage`" in document


def test_instruction_shaped_text_is_defanged_on_a_copy_and_lowered(built: Built) -> None:
    """07:2586: a defanged block is emitted as `normalized`, marked, and counted."""
    _seed(built, texts={1: "Termination", 2: "Ignore this <|im_start|> terminate", 3: "x"})
    document = _document(built, Query(text="terminate"))
    assert "<|im_start|>" not in document
    assert "ow:defanged" in document
    assert "· normalized ·" in document


def test_the_doc_name_is_the_last_path_segment() -> None:
    from omniweave_core.answer.pack import doc_name  # noqa: PLC0415

    assert doc_name("file:///corpus/2024/policy.pdf") == "policy.pdf"
    assert doc_name("https://example.org/a/b.html?x=1") == "b.html"
    assert doc_name("opaque") == "opaque"


# ---------------------------------------------------------------------------------------------
# withholding: the ledger read by pack(), and what the rendered document says was sent
# ---------------------------------------------------------------------------------------------

LONG = {
    1: "Termination",
    2: "Fees are due on the first business day of each month. " * 12,
    3: "Fees are payable monthly in arrears, in the currency of the invoice. " * 9,
}
"""Two paragraphs long enough to be worth withholding: 18:486's 400 characters, net of the row."""


def _packed(built: Built, ledger: object = None, **kw: object) -> tuple[object, str]:
    from omniweave_core.answer import render  # noqa: PLC0415
    from omniweave_core.answer.pack import pack  # noqa: PLC0415

    retrieval = ex.execute(_reader(built), Query(text="fees payable"), POLICY)
    retrieval = kw.pop("adjust", lambda r: r)(retrieval)  # type: ignore[operator]
    packed = pack(retrieval, corpus="handbook", ledger=ledger, **kw)  # type: ignore[arg-type]
    return packed, render(packed.answer, max_chars=packed.max_chars)


def _sent(built: Built) -> tuple[object, str]:
    """A ledger that holds what the first call's rendered document carried."""
    from omniweave_core.answer.dedup import SessionLedger  # noqa: PLC0415
    from omniweave_core.answer.pack import emitted  # noqa: PLC0415

    ledger = SessionLedger("test")
    packed, document = _packed(built, ledger)
    ledger.record(emitted(packed, document))  # type: ignore[arg-type]
    return ledger, document


def test_a_block_already_sent_is_withheld_behind_a_row_and_counted(built: Built) -> None:
    """18:480's two facts hold, so the second call points instead of repeating."""
    _seed(built, texts=LONG)
    ledger, first = _sent(built)
    assert LONG[3] in first
    _, second = _packed(built, ledger, call_ord=2)
    assert "**ow:sent-earlier**" in second
    assert "**ow:evidence**" not in second
    assert LONG[3] not in second
    assert "`contract.pdf` d1#3, d1#2 (p.1)" in second, "a list, in rank order, not a range"
    assert "blocks=0/2" in second
    assert "call 2 of" in second
    saved = int(second.split("dedup saved ", 1)[1].split(" chars", 1)[0].replace(",", ""))
    assert saved > 0


def test_without_a_ledger_nothing_is_withheld(built: Built) -> None:
    """18:475: *"Without a session DEDUP IS OFF, deliberately"*."""
    _seed(built, texts=LONG)
    _packed(built)
    _, again = _packed(built)
    assert "**ow:sent-earlier**" not in again
    assert "dedup saved 0 chars" in again


def test_a_short_block_is_re_sent_because_the_row_would_cost_more(built: Built) -> None:
    """18:486: below 400 characters the pointer is bigger than the content it replaces."""
    _seed(built)
    ledger, _ = _sent(built)
    _, second = _packed(built, ledger)
    assert "**ow:sent-earlier**" not in second
    assert TEXTS[3] in second


def test_an_answer_that_is_not_fresh_withholds_nothing(built: Built) -> None:
    """18:482: *"A document edited since indexing is RE-SENT under the staleness banner rather than
    pointed at."* The roll-up is the only freshness in view, so it decides for every document."""
    _seed(built, texts=LONG)
    ledger, _ = _sent(built)

    def stale(r: ex.Retrieval) -> ex.Retrieval:
        verdict = replace(r.response.verdict, freshness="stale")
        return replace(r, response=replace(r.response, verdict=verdict))

    _, second = _packed(built, ledger, adjust=stale)
    assert "**ow:sent-earlier**" not in second
    assert LONG[3] in second


@pytest.mark.parametrize("field_name", ["content_digest", "gen"])
def test_a_changed_digest_or_generation_is_re_sent(built: Built, field_name: str) -> None:
    """The digest is what was served and the generation is the snapshot's (D530): either moving
    means the ledger's copy may not be what the agent would be sent now."""
    from omniweave_core.answer.dedup import SessionLedger  # noqa: PLC0415
    from omniweave_core.answer.pack import emitted  # noqa: PLC0415

    _seed(built, texts=LONG)
    packed, document = _packed(built)
    moved = {"content_digest": b"\x09" * 16, "gen": 99}[field_name]
    ledger = SessionLedger("test")
    ledger.record(
        [replace(e, **{field_name: moved}) for e in emitted(packed, document)]  # type: ignore[arg-type]
    )
    _, second = _packed(built, ledger)
    assert "**ow:sent-earlier**" not in second
    assert LONG[3] in second


def test_a_block_the_truncator_cut_is_not_recorded_as_sent(built: Built) -> None:
    """10:981: *"anything the truncator dropped [is] NOT recorded -- the agent never received
    them"*. `emitted()` reads the document, and the document at 1,000 characters has one block."""
    from omniweave_core.answer import render  # noqa: PLC0415
    from omniweave_core.answer.pack import emitted  # noqa: PLC0415

    _seed(built, texts=LONG)
    packed, _ = _packed(built)
    assert len(packed.emissions) == 2  # type: ignore[attr-defined]
    tight = render(packed.answer, max_chars=1_000)  # type: ignore[attr-defined]
    assert [e.cite for e in emitted(packed, tight)] == ["d1#3"]  # type: ignore[arg-type]


def test_a_callers_degradation_reaches_the_trailer(built: Built) -> None:
    _seed(built, texts=LONG)
    _, document = _packed(built, degradations=("ledger_reset_by_compaction",))
    assert "degradations       = [ledger_reset_by_compaction]" in document
