"""`derive.entity.gazetteer`'s rules: the token automaton, the lexicon artefact. **D683.**"""

from __future__ import annotations

import json

import pytest
from omniweave_graph.gazetteer.rules import (
    LEXICON_FORMAT,
    Automaton,
    Target,
    decode_lexicon,
    find,
    tokens,
)

NAMES = ("acme", "acme_holdings", "acme_holdings_ltd", "holdings_ltd", "beta_corp", "ltd")


def hits(text: str, names: tuple[str, ...] = NAMES) -> list[tuple[str, str]]:
    return [(h.name, h.surface) for h in find(text, Automaton(names))]


def test_a_name_meets_its_surface_across_case_and_punctuation() -> None:
    """Ruling 1: `name_norm`'s fold, one word at a time."""
    assert hits("Acme Holdings, Ltd. shall pay BETA corp.") == [
        ("acme_holdings_ltd", "Acme Holdings, Ltd"),
        ("beta_corp", "BETA corp"),
    ]


def test_a_match_starts_and_ends_on_a_word_boundary() -> None:
    assert hits("macme acmes beta_corporation") == []


def test_the_span_is_in_block_text_and_two_hits_are_two_spans() -> None:
    """Ruling 2: a quote would ground both at the first."""
    text = "Beta Corp sued Beta Corp."
    assert [(h.a, h.b) for h in find(text, Automaton(NAMES))] == [(0, 9), (15, 24)]


def test_the_longest_match_wins_leftmost_first_and_never_overlaps() -> None:
    """Ruling 3."""
    assert hits("Ltd Acme Holdings Ltd Holdings Ltd") == [
        ("ltd", "Ltd"),
        ("acme_holdings_ltd", "Acme Holdings Ltd"),
        ("holdings_ltd", "Holdings Ltd"),
    ]
    assert hits("Acme Holdings") == [("acme_holdings", "Acme Holdings")]


def test_a_suffix_name_is_found_through_the_output_links() -> None:
    """`holdings_ltd` ends inside a path that began with `acme`: the failure links must reach it."""
    assert hits("Acme Holdings Ltdx Holdings Ltd", ("acme_holdings_ltd_x", "holdings_ltd")) == [
        ("holdings_ltd", "Holdings Ltd"),
    ]
    assert hits("acme holdings ltd", ("acme_holdings_ltd_x", "holdings_ltd")) == [
        ("holdings_ltd", "holdings ltd"),
    ]


def test_a_word_folds_like_normalize_key() -> None:
    assert [t.key for t in tokens("Straße ﬁnal ÉCOLE")] == ["strasse", "final", "école"]


def test_a_name_cannot_match_half_a_word() -> None:
    """`½` folds to `1_2`: one word, two pieces, and a name `1` is not in it."""
    assert [(t.key, t.a, t.b) for t in tokens("½")] == [("1", 0, 1), ("2", 0, 1)]
    assert hits("½", ("1",)) == []
    assert hits("½", ("2",)) == [], "nor the back half"
    assert hits("1 2", ("1",)) == [("1", "1")]


def test_an_empty_automaton_finds_nothing() -> None:
    assert find("Acme", Automaton([])) == ()
    assert Automaton([]).nodes == 1


def lexicon(*names: tuple[str, list[dict[str, str]]], count: int | None = None) -> bytes:
    head = {
        "t": "lexicon",
        "format": LEXICON_FORMAT,
        "names": len(names) if count is None else count,
    }
    lines = [head] + [{"t": "name", "name": n, "entities": e} for n, e in names]
    return "".join(json.dumps(line) + "\n" for line in lines).encode()


ACME = {"etype": "org", "key": "acme_holdings_ltd", "title": "Acme Holdings Ltd."}


def test_the_artefact_decodes_to_names_and_their_entities() -> None:
    found = decode_lexicon(lexicon(("acme_holdings_ltd", [ACME])))
    assert dict(found.names) == {
        "acme_holdings_ltd": (Target("org", "acme_holdings_ltd", "Acme Holdings Ltd."),)
    }
    assert dict(decode_lexicon(lexicon()).names) == {}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b"", "not even a header"),
        (b'{"t":"name"}\n', "not a lexicon header"),
        (b'{"t":"lexicon","format":"owgraph-lexicon/0","names":0}\n', "names format"),
        (lexicon(("acme", [])), "names no entity"),
        (lexicon(("acme", [{"etype": "org", "key": "acme"}])), "etype, key and title"),
        (lexicon(("acme", [ACME]), count=2), "counts 2 names and 1 follow"),
        (lexicon() + b"[1]\n", "line 2 is not a name frame"),
    ],
)
def test_a_malformed_artefact_is_refused_by_line(raw: bytes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        decode_lexicon(raw)
