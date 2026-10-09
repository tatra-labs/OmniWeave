"""The fuzzy stages' arithmetic: entropy, shingles, MinHash bands, Jaro-Winkler, guards. D685."""

from __future__ import annotations

import pytest
from omniweave.graph import fuzzy


def test_the_constants_are_graphifys_and_the_charters() -> None:
    """06:1793-1795, transcribed; 32 bands of 4 rows over 128 permutations."""
    assert (fuzzy.ENTROPY_MIN, fuzzy.LSH_THRESHOLD, fuzzy.MERGE_THRESHOLD, fuzzy.NUM_PERM) == (
        2.5,
        0.7,
        92.0,
        128,
    )
    assert (fuzzy.BANDS, fuzzy.ROWS, fuzzy.SHINGLE_K, fuzzy.COHESION_SPLIT_DELTA) == (
        32,
        4,
        3,
        10.0,
    )


def test_entropy_is_bits_per_character_and_gates_short_labels() -> None:
    """N1's observation: under six distinct characters a label never reaches 2.5."""
    assert fuzzy.entropy("") == 0.0
    assert fuzzy.entropy("aaaa") == 0.0
    assert fuzzy.entropy("acme") == pytest.approx(2.0)
    assert fuzzy.entropy("abcdef") == pytest.approx(2.585, abs=1e-3)
    assert fuzzy.entropy("acme_holdings_ltd") > fuzzy.ENTROPY_MIN


def test_shingles_strip_every_separator() -> None:
    """06:1796: `graph extractor` and `graphextractor` share their shingles."""
    assert fuzzy.shingles("graph extractor") == fuzzy.shingles("graphextractor")
    assert fuzzy.shingles("ab") == frozenset({"ab"})
    assert fuzzy.shingles(" _ ") == frozenset()


def test_a_signature_is_deterministic_and_its_bands_are_thirty_two() -> None:
    sig = fuzzy.signature(fuzzy.shingles("acme holdings ltd"))
    assert sig == fuzzy.signature(fuzzy.shingles("acmeholdings ltd"))
    assert len(sig) == fuzzy.NUM_PERM
    assert len(fuzzy.bands(sig)) == fuzzy.BANDS
    assert fuzzy.signature([]) == ()
    assert fuzzy.bands(()) == ()


def test_the_bands_catch_a_pair_a_seventy_percent_jaccard_cut_would_drop() -> None:
    """Ruling 1, measured: Jaccard 0.58, and the bands still meet."""
    a, b = fuzzy.shingles("acme holdings ltd"), fuzzy.shingles("acme holdings limited")
    assert len(a & b) / len(a | b) == pytest.approx(0.579, abs=1e-3)
    left, right = fuzzy.bands(fuzzy.signature(a)), fuzzy.bands(fuzzy.signature(b))
    assert any(x == y for x, y in zip(left, right, strict=True))


@pytest.mark.parametrize(
    ("s", "t", "jaro", "winkler"),
    [
        ("martha", "marhta", 0.9444, 0.9611),
        ("dwayne", "duane", 0.8222, 0.84),
        ("dixon", "dicksonx", 0.7667, 0.8133),
        ("same", "same", 1.0, 1.0),
        ("abc", "", 0.0, 0.0),
        ("abc", "xyz", 0.0, 0.0),
    ],
)
def test_jaro_and_jaro_winkler_are_the_textbook_values(
    s: str, t: str, jaro: float, winkler: float
) -> None:
    assert fuzzy.jaro(s, t) == pytest.approx(jaro, abs=1e-4)
    assert fuzzy.jaro_winkler(s, t) == pytest.approx(winkler, abs=1e-4)


def test_the_winkler_bonus_counts_four_characters_of_prefix_at_most() -> None:
    """Six shared leading characters earn the bonus of four: 0.9048 + 4 * 0.1 * 0.0952."""
    assert fuzzy.jaro_winkler("abcdefg", "abcdefh") == pytest.approx(0.9429, abs=1e-4)


def test_a_long_label_across_documents_is_scored_with_plain_jaro() -> None:
    """06:1720: Winkler's prefix bonus over-fires across files on long labels."""
    a, b = "acme holdings ltd", "acme holdings limited"
    assert fuzzy.verify(a, b, cross_document=True) == pytest.approx(100 * fuzzy.jaro(a, b))
    assert fuzzy.verify(a, b, cross_document=False) == pytest.approx(100 * fuzzy.jaro_winkler(a, b))
    assert fuzzy.verify("martha", "marhta", cross_document=True) == pytest.approx(96.11, abs=0.01)


def test_label_reads_the_keys_separators_as_spaces() -> None:
    assert fuzzy.label("acme_holdings_ltd") == "acme holdings ltd"


@pytest.mark.parametrize(
    ("left", "right", "guard"),
    [
        ("auth", "auth service", "prefix_containment"),
        ("acme holdings", "acme holdings ltd", "prefix_containment"),
        ("schedule 4", "schedule 5", "numeric_tokens_differ"),
        ("annex 2", "annex", "prefix_containment"),
        ("buyer indemnity", "indemnity buyer", "content_token_swap"),
        ("model x", "model s", "variant_suffix"),
        ("jon smith", "john smith", "short_label_substitution"),
        ("acme corp", "acme co", "prefix_containment"),
        ("version 10 release", "version 12 release", "numeric_tokens_differ"),
        ("jon smyth", "jon smith", None),
        ("acme holdings ltd", "acme holdings limited", None),
        ("international business machines", "internatinal business machines", None),
    ],
)
def test_each_guard_blocks_its_class_and_passes_the_rest(
    left: str, right: str, guard: str | None
) -> None:
    """06:1825-1829, and ruling 4's precise forms: the first guard that blocks is reported."""
    assert fuzzy.blocked_by(left, right) == guard


def test_the_variant_and_short_guards_stand_down_on_long_labels() -> None:
    assert not fuzzy._variant_suffix("international model x", "international model s")
    assert not fuzzy._short_label_substitution("international bank", "internationl bank")
    assert fuzzy._short_label_substitution("abcd", "abce") is False, "one substitution merges"
    assert fuzzy._short_label_substitution("abcd", "abdc") is True, "two do not"
