"""`omniweave.route.agree` -- the distance, the two absences, and the row the scoreboard reads.

The writer's half runs against a real store for `test_route_ledger.py`'s reason: the claim worth
checking is not that an `INSERT` executes but that the row reaches `route_scoreboard` as
`escalation_divergence = 1.0 - agreement`, and the only thing that knows whether it does is the
view.

Two tests here exist to pin defects rather than behaviour and say so in their names:
`test_markdown_emphasis_counts_as_disagreement` is D230, and it will change the day `strip_md` has
a home this distribution may import. `test_a_full_page_character_distance_costs_more_than_the_call`
is D229 with a number attached.
"""

from __future__ import annotations

import hashlib
import string
import time
from typing import TYPE_CHECKING

import pytest
from omniweave.route import agree as rag
from omniweave.route import ledger as rlg
from omniweave_core.errors import RouteError
from omniweave_core.store.sqlite import connect

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

SLICE = "pdf/workiva/true/en"
"""Section 10.3's slice, as in `test_route_ledger.py` -- the same document produced part 177."""

CAPTION = "Figure 12. Consolidated statements of operations for the years ended December 31."
"""Part 177's 84-character caption (05:3160): the page is one photograph and this is all the text
layer holds. The plan reads 0.94 agreement on it and calls it the known false positive."""

_DECISION = (
    "INSERT INTO route_decision (decision_id, content_sha256, unit_part, lane, rung, "
    "policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class, "
    "rule_id, rule_origin, slice_key, evidence_digest, est_spend, est_micros, reserved_micros, "
    "admission, pinned, generation, decided_at) "
    "VALUES (?, ?, '', 'text', 3, 'p', 'b', 'h', 'r', 'parse.page.olmocr', 'local_compute', "
    "'decode.part-text-unusable', 'o', ?, 'e', '{}', 854, 2732, 'admitted', ?, 1, 0)"
)
"""One escalated decision. `content_sha256` is a parameter because the eight identity columns
carry a `UNIQUE` (05:2846), so a second decision in these tests has to differ in one of them --
which is also the constraint that makes a `decision_id` deterministic and D233 worth filing."""

_EVIDENCE = (
    "INSERT OR IGNORE INTO route_evidence (evidence_digest, payload, swept_at, first_seen_at) "
    "VALUES ('e', X'00', NULL, 0)"
)


@pytest.fixture
def db(tmp_path: Path, migrations: Path) -> Iterator[rlg.Connection]:
    """A store with every committed migration applied and one escalated decision in it."""
    conn = connect(tmp_path / "index.owstore")
    for path in sorted(migrations.glob("[0-9]*.sql")):
        conn.executescript(path.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(_EVIDENCE)
    conn.execute(_DECISION, ("d001", "c1", SLICE, 0))
    conn.execute("INSERT INTO route_threshold (k, v) VALUES ('audit.min_audit_n', 30)")
    conn.execute("INSERT INTO route_threshold (k, v) VALUES ('audit.regress_at', 0.08)")
    conn.execute("INSERT INTO route_threshold (k, v) VALUES ('audit.release_at', 0.048)")
    yield conn
    conn.close()


def _page(chars: int, *, seed: int) -> str:
    """Roughly `chars` characters of filler, derived from a keyed blake2b stream.

    Not `random`: `TID251` bans the module across this tree, giving as its reason that sampling is
    blake2b and determinism is a gate rather than a habit -- and a fixture that seeds a global
    generator is exactly the habit. Two runs of this file compare the same two pages, anywhere.
    """
    data = bytearray()
    counter = 0
    while len(data) < chars:
        data += hashlib.blake2b(f"{seed}:{counter}".encode(), digest_size=64).digest()
        counter += 1
    words: list[str] = []
    index = 0
    while index < chars:
        length = 2 + data[index] % 8
        letters = data[index + 1 : index + 1 + length]
        if len(letters) < length:
            break
        words.append("".join(string.ascii_lowercase[byte % 26] for byte in letters))
        index += length + 1
    return " ".join(words)


# ---------------------------------------------------------------------------
# tokens() -- the fold, and the one it does not perform
# ---------------------------------------------------------------------------


def test_the_join_the_caller_used_cannot_change_the_tokens() -> None:
    """`fold_common` collapses whitespace, so a part's blocks may be joined any way at all."""
    blocks = ("First line.", "Second line.", "Third.")
    assert rag.tokens("\n".join(blocks)) == rag.tokens(" ".join(blocks))
    assert rag.tokens("\n\n".join(blocks)) == rag.tokens("  ".join(blocks))


def test_the_fold_does_not_casefold() -> None:
    """Not `normalize_k`: a VLM that restored a capital the text layer lost read the page better,
    and a casefolding comparison would score that as agreement."""
    assert rag.tokens("Paris") != rag.tokens("paris")


def test_the_fold_maps_the_quote_families_and_the_dashes() -> None:
    """`quotes=True`, which is `normalize_eval`'s setting: a curly apostrophe in one reading and a
    straight one in the other is a font, not a disagreement."""
    curly = "it" + chr(0x2019) + "s well" + chr(0x2014) + "known"
    assert rag.tokens(curly) == rag.tokens("it's well-known")


def test_an_empty_reading_is_no_tokens_and_not_one_empty_token() -> None:
    assert rag.tokens("") == ()
    assert rag.tokens("   \n  ") == ()


# ---------------------------------------------------------------------------
# distance() -- exact, generic, and trimmed
# ---------------------------------------------------------------------------


def test_the_textbook_pair() -> None:
    """`kitten` to `sitting` is 3, which is the value every Levenshtein implementation agrees on."""
    assert rag.distance("kitten", "sitting") == 3


def test_identical_sequences_are_zero_and_an_empty_one_is_the_others_length() -> None:
    assert rag.distance("abc", "abc") == 0
    assert rag.distance("", "abcd") == 4
    assert rag.distance(("a", "b"), ()) == 2


def test_the_distance_is_symmetric() -> None:
    first, second = rag.tokens(_page(600, seed=1)), rag.tokens(_page(600, seed=2))
    assert rag.distance(first, second) == rag.distance(second, first)


def test_trimming_a_shared_prefix_and_suffix_does_not_change_the_answer() -> None:
    """The trim is an optimisation with an exactness claim, so the claim is tested."""
    core_left, core_right = "the audited statements", "the unaudited statements"
    prefix, suffix = "shared opening text " * 4, " shared closing text" * 4
    bare = rag.distance(rag.tokens(core_left), rag.tokens(core_right))
    padded = rag.distance(
        rag.tokens(prefix + core_left + suffix), rag.tokens(prefix + core_right + suffix)
    )
    assert bare == padded


# ---------------------------------------------------------------------------
# agreement() -- the value, and the two ways there is none
# ---------------------------------------------------------------------------


def test_two_identical_readings_agree_completely() -> None:
    reading = rag.agreement(CAPTION, CAPTION)
    assert reading.value == 1.0
    assert reading.edits == 0


def test_the_value_stays_inside_the_registered_domain() -> None:
    """05:2175 registers `[0.0, 1.0]` closed on both ends, and `Agreement` refuses anything else."""
    for seed in range(8):
        reading = rag.agreement(_page(300, seed=seed), _page(300, seed=seed + 100))
        assert reading.value is not None
        assert 0.0 <= reading.value <= 1.0


def test_the_signal_separates_the_two_slices_it_exists_to_find() -> None:
    """05:2251: *"slices where escalation changed nothing"* and *"slices where escalation changed
    everything"* are the two answers the label has to distinguish."""
    unchanged = rag.agreement(CAPTION, CAPTION.replace("December", "Decemher"))
    changed = rag.agreement(CAPTION, _page(400, seed=9))
    assert unchanged.value is not None
    assert changed.value is not None
    assert unchanged.value > 0.9
    assert changed.value < 0.1


def test_an_empty_decode_reading_is_not_computed_and_names_decode() -> None:
    """12:1105 -- on the 12 scanned exhibits DECODE produced nothing. 0.0 would be a label."""
    reading = rag.agreement("", "the model read a whole page here")
    assert reading.value is None
    assert not reading.computed
    assert "DECODE" in reading.reason


def test_an_empty_page_reading_names_page_instead() -> None:
    reading = rag.agreement(CAPTION, "")
    assert reading.value is None
    assert "PAGE" in reading.reason


def test_two_empty_readings_are_still_not_computed() -> None:
    assert rag.agreement("", "").value is None


def test_a_comparison_above_the_cell_budget_is_refused_rather_than_guessed() -> None:
    """A quadratic with no ceiling is an unbounded pause inside a settle phase."""
    left = _page(60_000, seed=3)
    right = _page(60_000, seed=4)
    reading = rag.agreement(left, right)
    assert reading.value is None
    assert "MAX_CELLS" in reading.reason
    assert reading.decode_words > 1_000


def test_the_budget_measures_the_trimmed_work_and_not_the_input_length() -> None:
    """Two identical 10,000-word readings trim to nothing, so the cheapest comparison there is
    must not be the one the guard refuses."""
    long_page = _page(60_000, seed=3)
    reading = rag.agreement(long_page, long_page)
    assert reading.value == 1.0
    assert reading.decode_words > rag.MAX_CELLS**0.5


# ---------------------------------------------------------------------------
# The record itself
# ---------------------------------------------------------------------------


def test_an_uncomputed_agreement_may_not_be_silent() -> None:
    with pytest.raises(RouteError):
        rag.Agreement(None, 0, 0, 0)


def test_a_value_outside_the_domain_is_refused_at_construction() -> None:
    with pytest.raises(RouteError) as caught:
        rag.Agreement(1.5, 0, 1, 1)
    assert "[0.0, 1.0]" in str(caught.value)


def test_the_detail_carries_the_truth_kind_and_the_unit() -> None:
    detail = rag.agreement(CAPTION, CAPTION).detail
    assert '"truth_kind":"agreement"' in detail
    assert '"unit":"word"' in detail
    assert detail.index('"decode_words"') < detail.index('"edits"')


def test_the_render_says_agreement_not_accuracy() -> None:
    assert "not accuracy" in rag.agreement(CAPTION, CAPTION).render()


# ---------------------------------------------------------------------------
# record() -- one row, once
# ---------------------------------------------------------------------------


def test_the_row_carries_the_source_the_metric_and_no_column_that_is_another_sources(
    db: rlg.Connection,
) -> None:
    entry = rag.record(
        db, decision_id="d001", decode_text=CAPTION, page_text=CAPTION, created_at=1_700_000
    )
    assert entry.written
    rows = db.execute(
        "SELECT source, metric, agreement, polarity, ref_driver, created_at FROM route_quality"
    ).fetchall()
    assert len(rows) == 1
    assert tuple(rows[0]) == ("agree", "norm_edit_agreement", 1.0, None, None, 1_700_000)


def test_a_second_call_writes_nothing_and_says_why(db: rlg.Connection) -> None:
    """A `decision_id` is a digest over the decision's identity, so the second row would be the
    same measurement counted twice -- and the view weights `escalation_divergence` by row."""
    first = rag.record(db, decision_id="d001", decode_text=CAPTION, page_text=CAPTION, created_at=1)
    second = rag.record(
        db, decision_id="d001", decode_text=CAPTION, page_text=CAPTION, created_at=2
    )
    assert first.written
    assert not second.written
    assert "counted twice" in second.reason
    assert db.execute("SELECT COUNT(*) FROM route_quality").fetchall()[0][0] == 1


def test_a_not_computed_reading_writes_no_row_at_all(db: rlg.Connection) -> None:
    entry = rag.record(db, decision_id="d001", decode_text="", page_text=CAPTION, created_at=1)
    assert not entry.written
    assert "DECODE" in entry.reason
    assert db.execute("SELECT COUNT(*) FROM route_quality").fetchall()[0][0] == 0


def test_the_row_reaches_the_scoreboard_as_one_minus_the_agreement(db: rlg.Connection) -> None:
    """05:2838's own column, and 05:2862's own arithmetic -- asserted through the view rather
    than restated in Python."""
    rag.record(
        db,
        decision_id="d001",
        decode_text=CAPTION,
        page_text=CAPTION.replace("December", "Decemher"),
        created_at=1,
    )
    rollups = rlg.scoreboard(db)
    assert len(rollups) == 1
    reading = rag.agreement(CAPTION, CAPTION.replace("December", "Decemher"))
    assert reading.value is not None
    assert rollups[0].escalation_divergence == pytest.approx(1.0 - reading.value)
    assert rollups[0].divergence is None
    assert rollups[0].state == "UNKNOWN"


def test_a_pinned_decisions_agreement_never_reaches_the_scoreboard(db: rlg.Connection) -> None:
    """05:2937 is the view's own `WHERE`: *"a pinned decision may not justify a demotion"*."""
    db.execute(_DECISION, ("d002", "c2", SLICE, 1))
    rag.record(
        db, decision_id="d002", decode_text=CAPTION, page_text="quite different", created_at=1
    )
    assert all(rollup.escalation_divergence is None for rollup in rlg.scoreboard(db))


# ---------------------------------------------------------------------------
# The two defects, pinned
# ---------------------------------------------------------------------------


def test_markdown_emphasis_counts_as_disagreement() -> None:
    """D230. `strip_md` is `omniweave_conform`'s and `tools/layers.toml` forbids the import, so a
    `**bold**` run in the VLM reading disagrees with a text layer that has no asterisks."""
    plain = "the audited consolidated statements"
    emphasised = "the **audited** consolidated statements"
    reading = rag.agreement(plain, emphasised)
    assert reading.value is not None
    assert reading.value < 1.0
    assert reading.edits == 1


def test_a_full_page_character_distance_costs_more_than_the_call_it_measures() -> None:
    """D229. 05:2175 budgets 1.2 ms; the character-level distance upstream takes with a compiled
    wheel is measured in seconds here, and the olmOCR call it is grading is 2,400 ms (05:2451)."""
    left = _page(4_000, seed=5)
    right = left[:2_000] + _page(2_000, seed=6)
    started = time.perf_counter()
    rag.distance(left, right)
    characters_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    rag.distance(rag.tokens(left), rag.tokens(right))
    words_ms = (time.perf_counter() - started) * 1000
    assert words_ms < characters_ms
    assert characters_ms > 100.0


# ---------------------------------------------------------------------------
# The legend
# ---------------------------------------------------------------------------


def test_the_legend_states_the_heading_three_documents_ask_for() -> None:
    """01:946, 12:1101 and 13:1459 all print *"Agreement (not accuracy)"*."""
    legend = "\n".join(rag.scoreboard_legend())
    assert "NOT ACCURACY" in legend
    assert "agreement" in legend
    assert "only audit may demote" in legend
