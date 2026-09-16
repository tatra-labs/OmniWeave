"""The emission ledger -- and the asymmetry that lets its bounds be this small.

Every bound in `SESSION_LIMITS` can forget an emission for a block that really was sent, and that is
safe in exactly one direction. Forgetting re-sends a few hundred characters; INVENTING one
withholds content the agent does not hold, prints 10:668's *"Use it from your context; do NOT Read
this file"* about something that is not there, and costs a round trip that reads as absence. So
the suite is organised around which way each
mechanism can be wrong:

* Section 3 runs `withhold()`'s three conjuncts one at a time, each moving ONE fact off a baseline
  that withholds, so a conjunct that stopped being checked fails here.
* Section 4 drives every bound past its limit and asserts what is forgotten -- never that a call
  raises, because a ledger that refused a ninth call would break the session rather than the
  saving.
* Section 6 asserts the un-withholding path: a document that does not clear both thresholds comes
  back WHOLE, because a row reading "already sent earlier" beside the same document's own text says
  two things at once.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st
from omniweave_core.answer.dedup import (
    DEDUP_OFF_MESSAGE,
    LEDGER_KEY_FIELDS,
    LEDGER_RESET_KIND,
    MAX_BLOCKS_PER_DOC,
    MAX_CALLS_RETAINED,
    MAX_CORPORA,
    MAX_DOCS_IN_POINTER,
    MAX_DOCS_PER_CALL,
    MAX_SPANS_IN_POINTER,
    MIN_COVERED_CHARS,
    MIN_DELTA_CHARS,
    POINTER_CHARS,
    Emission,
    SessionLedger,
    partition,
    withhold,
    worth_withholding,
)

if TYPE_CHECKING:
    from conftest import PlanDocs

CHARTER = "_notes/charter.md"
SKETCH = "18-api-sketch.md"
INTERFACES = "10-interfaces.md"

DOC_A = b"\xaa" * 8
DOC_B = b"\xbb" * 8
DIGEST = b"\x01" * 32
OTHER = b"\x02" * 32


def _emission(
    cite: str,
    *,
    corpus: str = "handbook",
    doc_key: bytes = DOC_A,
    gen: int = 41,
    digest: bytes = DIGEST,
    chars: int = 500,
) -> Emission:
    return Emission(
        corpus_id=corpus,
        doc_key=doc_key,
        gen=gen,
        cite=cite,
        content_digest=digest,
        chars=chars,
    )


def _ledger(*sent: Emission) -> SessionLedger:
    ledger = SessionLedger("test-session")
    if sent:
        ledger.record(sent)
    return ledger


# ---------------------------------------------------------------------------
# 1. The key and the constants are the charter's
# ---------------------------------------------------------------------------


def test_the_key_is_the_five_components_the_charter_prints(plan: PlanDocs) -> None:
    """charter.md:6681: `(corpus_id, doc_key, gen, cite, content_digest)`."""
    plan.require()
    hits = plan.grep(r"^LedgerKey = ", documents=(CHARTER,))
    assert hits
    printed = tuple(re.findall(r"\w+", hits[0].text.split("#", 1)[1]))
    assert printed == LEDGER_KEY_FIELDS
    assert len(LEDGER_KEY_FIELDS) == 5


def test_the_key_is_also_the_one_the_performance_document_names(plan: PlanDocs) -> None:
    """12:978 names the same five for the same mechanism, which is the second witness."""
    plan.require()
    assert plan.grep(
        r"\(corpus_id, doc_key, gen, cite, content_digest\)", documents=("12-performance.md",)
    )


def test_an_emission_reports_both_of_its_identities() -> None:
    """Four components identify a BLOCK; five identify an EMISSION. See the module docstring."""
    emission = _emission("handbook:d7#412")
    assert emission.lookup == ("handbook", DOC_A, 41, "handbook:d7#412")
    assert emission.key == ("handbook", DOC_A, 41, "handbook:d7#412", DIGEST)
    assert emission.key[:4] == emission.lookup


def test_the_session_limits_are_the_four_the_sketch_prints(plan: PlanDocs) -> None:
    """18:485's four: `MAX_CORPORA=4`, `MAX_CALLS_RETAINED=8`, `MAX_DOCS_PER_CALL=24`, 64."""
    plan.require()
    text = plan.text(SKETCH)
    body = text[text.index("Bounds (SESSION_LIMITS)") :][:220]
    printed = dict(re.findall(r"(MAX_\w+)=(\d+)", body))
    assert int(printed["MAX_CORPORA"]) == MAX_CORPORA
    assert int(printed["MAX_CALLS_RETAINED"]) == MAX_CALLS_RETAINED
    assert int(printed["MAX_DOCS_PER_CALL"]) == MAX_DOCS_PER_CALL
    assert int(printed["MAX_BLOCKS_PER_DOC"]) == MAX_BLOCKS_PER_DOC


def test_the_dedup_thresholds_are_the_ones_the_sketch_prints(plan: PlanDocs) -> None:
    """18:486: `MIN_COVERED_CHARS=400` and `MIN_DELTA_CHARS=200`."""
    plan.require()
    text = plan.text(SKETCH)
    body = text[text.index("A pointer is emitted only above DEDUP") :][:200]
    printed = dict(re.findall(r"(MIN_\w+)=(\d+)", body))
    assert int(printed["MIN_COVERED_CHARS"]) == MIN_COVERED_CHARS
    assert int(printed["MIN_DELTA_CHARS"]) == MIN_DELTA_CHARS


def test_the_pointer_caps_are_the_charter_s(plan: PlanDocs) -> None:
    """charter.md:6686: `MAX_SPANS_IN_POINTER=4`, `MAX_DOCS_IN_POINTER=5`."""
    plan.require()
    text = plan.text(CHARTER)
    body = text[text.index('"MAX_SPANS_IN_POINTER"') :][:120]
    printed = dict(re.findall(r'"(MAX_\w+)":\s*(\d+)', body))
    assert int(printed["MAX_SPANS_IN_POINTER"]) == MAX_SPANS_IN_POINTER
    assert int(printed["MAX_DOCS_IN_POINTER"]) == MAX_DOCS_IN_POINTER


def test_the_pointer_length_is_the_one_the_allocator_discount_is_measured_with(
    plan: PlanDocs,
) -> None:
    """10:718's *"140-character pointer"*, which is what `MIN_DELTA_CHARS` subtracts."""
    plan.require()
    assert plan.grep(r"140-character pointer", documents=(INTERFACES,))
    assert POINTER_CHARS == 140


def test_the_block_bound_is_not_the_document_models_one() -> None:
    """One name, two scopes. `limits.MAX_BLOCKS_PER_DOC` is what a document may HAVE."""
    from omniweave_core.limits import MAX_BLOCKS_PER_DOC as MODEL_BOUND  # noqa: PLC0415

    assert MAX_BLOCKS_PER_DOC == 64
    assert MODEL_BOUND == 8_388_608


# ---------------------------------------------------------------------------
# 2. The no-session case, which is a decision and not a degradation
# ---------------------------------------------------------------------------


def test_no_session_means_dedup_is_off_and_not_an_error(plan: PlanDocs) -> None:
    """18:475: *"Without a session DEDUP IS OFF, deliberately"*."""
    plan.require()
    assert plan.grep(r"Without a session\s*$|Without a session DEDUP IS OFF", documents=(SKETCH,))
    blocks = [_emission("c:d1#1"), _emission("c:d1#2")]
    result = partition(None, blocks)
    assert result.kept == tuple(blocks)
    assert result.withheld == ()
    assert result.chars_deduped == 0


def test_the_kind_is_the_nearest_legal_member_and_the_message_carries_the_real_cause(
    plan: PlanDocs,
) -> None:
    """10:2386: *"That `kind` is the nearest legal member, not the right one."*"""
    plan.require()
    assert plan.grep(r"nearest legal member, not the right one", documents=(INTERFACES,))
    assert LEDGER_RESET_KIND == "ledger_reset_by_compaction"
    assert "no session id: --stateless" in DEDUP_OFF_MESSAGE
    assert "stateful transport" in DEDUP_OFF_MESSAGE


def test_the_kind_is_a_member_of_the_closed_set(plan: PlanDocs) -> None:
    """15:988. The set is closed at twenty-seven and its sole home is 15 section 6.3."""
    plan.require()
    assert plan.grep(rf'"{LEDGER_RESET_KIND}"', documents=("15-observability.md",))


def test_a_ledger_with_no_key_is_refused_rather_than_built() -> None:
    """The no-session case is `None`, not an anonymous ledger that would key everything alike."""
    with pytest.raises(ValueError, match="dedup is off"):
        SessionLedger("")


# ---------------------------------------------------------------------------
# 3. `withhold()` -- three conjuncts, one fixture each
# ---------------------------------------------------------------------------


def test_the_baseline_withholds() -> None:
    """Fresh, sent before, byte-identical. Every fixture below moves exactly one of the three."""
    block = _emission("handbook:d7#412")
    assert withhold(_ledger(block), block, doc_fresh=True)


def test_a_block_never_sent_is_not_withheld() -> None:
    block = _emission("handbook:d7#412")
    assert not withhold(_ledger(), block, doc_fresh=True)


def test_a_block_whose_content_changed_is_re_sent(plan: PlanDocs) -> None:
    """18:480: `content_digest` proves *"the same content as we sent"*."""
    plan.require()
    assert plan.grep(r"proves .the same content as we sent.", documents=(CHARTER,))
    sent = _emission("handbook:d7#412", digest=DIGEST)
    now = _emission("handbook:d7#412", digest=OTHER)
    assert not withhold(_ledger(sent), now, doc_fresh=True)


def test_a_stale_document_is_re_sent_although_the_digest_matches(plan: PlanDocs) -> None:
    """18:482: *"A document edited since indexing is RE-SENT under the staleness banner"*."""
    plan.require()
    assert plan.grep(
        r"is RE-SENT under\s*$|RE-SENT under the staleness banner", documents=(SKETCH,)
    )
    block = _emission("handbook:d7#412")
    assert not withhold(_ledger(block), block, doc_fresh=False)


def test_a_different_generation_of_the_same_cite_is_not_the_same_block() -> None:
    """`gen` is in the lookup: a re-parsed document is a different emission."""
    sent = _emission("handbook:d7#412", gen=41)
    now = _emission("handbook:d7#412", gen=42)
    assert not withhold(_ledger(sent), now, doc_fresh=True)


def test_the_same_cite_in_a_different_corpus_is_not_the_same_block() -> None:
    """`corpus_id` is in the lookup, and `d7#412` is not globally unique."""
    sent = _emission("handbook:d7#412", corpus="handbook")
    now = _emission("contracts:d7#412", corpus="contracts")
    assert not withhold(_ledger(sent), now, doc_fresh=True)


def test_the_most_recent_emission_wins() -> None:
    """Two calls sent the same cite; the digest compared is the one the agent last saw."""
    ledger = _ledger(_emission("handbook:d7#412", digest=DIGEST))
    ledger.record([_emission("handbook:d7#412", digest=OTHER)])
    assert withhold(ledger, _emission("handbook:d7#412", digest=OTHER), doc_fresh=True)
    assert not withhold(ledger, _emission("handbook:d7#412", digest=DIGEST), doc_fresh=True)


# ---------------------------------------------------------------------------
# 4. Every bound forgets, and none of them refuses
# ---------------------------------------------------------------------------


def test_a_ninth_call_forgets_the_first() -> None:
    ledger = SessionLedger("s")
    for call in range(MAX_CALLS_RETAINED + 1):
        ledger.record([_emission(f"handbook:d1#{call}")])
    assert ledger.stats()["calls"] == MAX_CALLS_RETAINED
    assert ledger.get("handbook", DOC_A, 41, "handbook:d1#0") is None
    assert ledger.get("handbook", DOC_A, 41, "handbook:d1#1") is not None


def test_a_call_records_at_most_max_docs_per_call_documents() -> None:
    ledger = SessionLedger("s")
    kept = ledger.record(
        _emission(f"handbook:d{i}#1", doc_key=bytes([i])) for i in range(MAX_DOCS_PER_CALL + 5)
    )
    assert kept == MAX_DOCS_PER_CALL
    assert ledger.stats()["docs"] == MAX_DOCS_PER_CALL


def test_a_document_records_at_most_max_blocks_per_doc_blocks() -> None:
    ledger = SessionLedger("s")
    kept = ledger.record(_emission(f"handbook:d1#{i}") for i in range(MAX_BLOCKS_PER_DOC + 10))
    assert kept == MAX_BLOCKS_PER_DOC
    assert ledger.get("handbook", DOC_A, 41, f"handbook:d1#{MAX_BLOCKS_PER_DOC}") is None


def test_the_blocks_that_survive_a_bound_are_the_ones_that_ranked_highest() -> None:
    """The caller hands them in rank order, so the prefix is also what the agent still holds."""
    ledger = SessionLedger("s")
    ledger.record(_emission(f"handbook:d1#{i}") for i in range(MAX_BLOCKS_PER_DOC + 5))
    assert ledger.get("handbook", DOC_A, 41, "handbook:d1#0") is not None
    assert ledger.get("handbook", DOC_A, 41, f"handbook:d1#{MAX_BLOCKS_PER_DOC - 1}") is not None


def test_a_fifth_corpus_evicts_the_least_recently_recorded_one() -> None:
    ledger = SessionLedger("s")
    for index in range(MAX_CORPORA + 1):
        ledger.record([_emission(f"c{index}:d1#1", corpus=f"c{index}", doc_key=bytes([index]))])
    assert ledger.stats()["corpora"] == MAX_CORPORA
    assert ledger.get("c0", bytes([0]), 41, "c0:d1#1") is None
    assert ledger.get("c4", bytes([4]), 41, "c4:d1#1") is not None


def test_no_bound_raises() -> None:
    """A ledger that refused a ninth call would break the session rather than the saving."""
    ledger = SessionLedger("s")
    for call in range(MAX_CALLS_RETAINED * 3):
        ledger.record(
            _emission(f"c{call % 6}:d{i}#{j}", corpus=f"c{call % 6}", doc_key=bytes([i]))
            for i in range(MAX_DOCS_PER_CALL + 2)
            for j in range(3)
        )
    assert ledger.stats()["calls"] <= MAX_CALLS_RETAINED
    assert ledger.stats()["corpora"] <= MAX_CORPORA


def test_an_empty_call_is_not_recorded() -> None:
    """A call that emitted nothing is not a call the ledger has to forget later."""
    ledger = SessionLedger("s")
    assert ledger.record([]) == 0
    assert ledger.stats()["calls"] == 0


def test_clear_forgets_everything() -> None:
    """10:1947: *"not bookkeeping -- it is the correctness condition"* for the whole mechanism."""
    ledger = _ledger(_emission("handbook:d7#412"))
    ledger.clear()
    assert ledger.stats() == {"calls": 0, "corpora": 0, "docs": 0, "blocks": 0, "chars_sent": 0}
    assert not withhold(ledger, _emission("handbook:d7#412"), doc_fresh=True)


def test_stats_sum_what_was_sent() -> None:
    """18:788's `Session.stats()`: calls, docs, blocks, chars_sent."""
    ledger = _ledger(
        _emission("handbook:d1#1", chars=300),
        _emission("handbook:d1#2", chars=200),
        _emission("handbook:d2#1", doc_key=DOC_B, chars=100),
    )
    assert ledger.stats() == {
        "calls": 1,
        "corpora": 1,
        "docs": 2,
        "blocks": 3,
        "chars_sent": 600,
    }


# ---------------------------------------------------------------------------
# 5. `worth_withholding` -- two thresholds, and D278
# ---------------------------------------------------------------------------


def test_below_the_covered_floor_a_pointer_costs_more_than_it_saves(plan: PlanDocs) -> None:
    """18:487: *"a table cell is eight characters"*, and the pointer is ~140."""
    plan.require()
    assert plan.grep(r"a table cell is eight characters", documents=(SKETCH,))
    assert not worth_withholding(8)
    assert not worth_withholding(MIN_COVERED_CHARS - 1)
    assert worth_withholding(MIN_COVERED_CHARS)


def test_the_two_thresholds_agree_at_the_plans_own_figures() -> None:
    """D278's evidence: 400 - 140 = 260, above 200 and not far above it."""
    assert MIN_COVERED_CHARS - POINTER_CHARS == 260
    assert MIN_COVERED_CHARS - POINTER_CHARS >= MIN_DELTA_CHARS


def test_a_long_pointer_can_fail_the_delta_where_the_covered_floor_passes() -> None:
    """The half that makes `MIN_DELTA_CHARS` do work: a long URI and four long cites."""
    assert not worth_withholding(MIN_COVERED_CHARS, pointer_chars=300)
    assert worth_withholding(MIN_COVERED_CHARS + 100, pointer_chars=300)


@given(st.integers(min_value=0, max_value=20_000), st.integers(min_value=0, max_value=1_000))
def test_withholding_never_loses_characters(covered: int, pointer: int) -> None:
    """The post-condition: a pointer is emitted only where it is smaller than what it replaces."""
    if worth_withholding(covered, pointer):
        assert covered - pointer >= MIN_DELTA_CHARS > 0


# ---------------------------------------------------------------------------
# 6. `partition` -- all of a document or none of it
# ---------------------------------------------------------------------------


def _sent_pair() -> tuple[SessionLedger, list[Emission]]:
    blocks = [_emission("handbook:d1#1", chars=400), _emission("handbook:d1#2", chars=400)]
    return _ledger(*blocks), blocks


def test_a_withheld_document_leaves_the_evidence_and_arrives_as_a_row() -> None:
    ledger, blocks = _sent_pair()
    result = partition(ledger, blocks, fresh_docs=frozenset({DOC_A}))
    assert result.kept == ()
    assert result.documents_withheld == 1
    row = result.withheld[0]
    assert row.cites == ("handbook:d1#1", "handbook:d1#2")
    assert (row.blocks, row.covered_chars) == (2, 800)
    assert result.chars_deduped == 800


def test_a_stale_document_is_not_withheld_at_all() -> None:
    ledger, blocks = _sent_pair()
    result = partition(ledger, blocks, fresh_docs=frozenset())
    assert result.kept == tuple(blocks)
    assert result.withheld == ()


def test_a_document_that_does_not_clear_the_thresholds_comes_back_whole() -> None:
    """Not split across a pointer and the evidence: that row would say two things at once."""
    blocks = [_emission("handbook:d1#1", chars=100), _emission("handbook:d1#2", chars=100)]
    result = partition(_ledger(*blocks), blocks, fresh_docs=frozenset({DOC_A}))
    assert result.kept == tuple(blocks)
    assert result.withheld == ()
    assert result.chars_deduped == 0


def test_one_document_can_be_withheld_while_another_is_sent() -> None:
    sent = [_emission("handbook:d1#1", chars=900)]
    fresh = [_emission("handbook:d2#1", doc_key=DOC_B, chars=900)]
    result = partition(_ledger(*sent), [*sent, *fresh], fresh_docs=frozenset({DOC_A, DOC_B}))
    assert result.kept == tuple(fresh)
    assert [row.doc_key for row in result.withheld] == [DOC_A]


def test_the_kept_order_is_the_order_the_blocks_arrived_in() -> None:
    """The allocator reads rank order off this sequence, so re-ordering here re-ranks the Answer."""
    blocks = [_emission(f"handbook:d{i}#1", doc_key=bytes([i]), chars=100) for i in range(5)]
    result = partition(_ledger(), blocks, fresh_docs=frozenset())
    assert [block.cite for block in result.kept] == [block.cite for block in blocks]


def test_a_row_shows_at_most_four_cites_and_still_counts_them_all() -> None:
    """`MAX_SPANS_IN_POINTER` bounds what is printed; `blocks` is the number that were withheld."""
    blocks = [_emission(f"handbook:d1#{i}", chars=200) for i in range(9)]
    result = partition(_ledger(*blocks), blocks, fresh_docs=frozenset({DOC_A}))
    row = result.withheld[0]
    assert row.blocks == 9
    assert len(row.shown_cites) == MAX_SPANS_IN_POINTER


def test_an_emission_with_no_cite_is_refused() -> None:
    with pytest.raises(ValueError, match="no cite"):
        _emission("")


def test_a_negative_char_count_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        _emission("handbook:d1#1", chars=-1)


# ---------------------------------------------------------------------------
# 7. D276 -- the shape `withhold()` is typed to take cannot supply the key
# ---------------------------------------------------------------------------


def test_the_charter_types_withhold_over_a_rendered_block(plan: PlanDocs) -> None:
    """charter.md:6688, verbatim, so the premise of D276 is read and not remembered."""
    plan.require()
    assert plan.grep(
        r'def withhold\(prior: "SessionLedger", blk: "RenderedBlock"', documents=(CHARTER,)
    )


def test_a_rendered_block_carries_one_of_the_five_key_components(plan: PlanDocs) -> None:
    """D276. 18:588's twenty-six fields, parsed out of the sketch and matched against the key."""
    plan.require()
    text = plan.text(SKETCH)
    body = text[text.index("class RenderedBlock:") : text.index("The `@provisional` fields")]
    fields = {
        match.group(1) for line in body.splitlines() if (match := re.match(r"\s{4}(\w+):\s", line))
    }
    assert len(fields) == 26
    assert set(LEDGER_KEY_FIELDS) & fields == {"cite"}
    for absent in ("corpus_id", "doc_key", "gen", "content_digest"):
        assert absent not in fields
