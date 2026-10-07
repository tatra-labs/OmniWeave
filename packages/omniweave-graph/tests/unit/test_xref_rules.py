"""`derive.xref.pattern`'s pattern set and detector: 06-structure-extraction.md section 3.4, D669.

The three properties 06:1052-1056 asks CI to hold over `patterns.toml` are the first tests here:
every `yes` matches whole, every `no` matches nowhere, and no two patterns claim one token over the
union of all fixtures.
"""

from __future__ import annotations

import re
from itertools import combinations

import pytest
from omniweave_core.model.enums import AnchorKind
from omniweave_graph.view import Member
from omniweave_graph.xref import rules
from omniweave_graph.xref.rules import MAX_REF_SITES_PER_BLOCK, Pattern, find, patterns

ALL = patterns()
FIXTURES = [text for p in ALL for text in (*p.yes, *p.no)]


def refs(*texts: str, kind: str = "paragraph") -> list[tuple[str, str, str]]:
    members = [Member(cite=f"d1#{i}", kind=kind, text=t) for i, t in enumerate(texts)]
    found = find(members)
    for r in found.refs:
        text = members[int(r.cite.split("#")[1])].text or ""
        assert text[r.span[0] : r.span[1]] == r.surface
    return [(r.akind, r.name, r.surface) for r in found.refs]


# -- the set ---------------------------------------------------------------------------------------


def test_the_set_is_the_plans_four_split_and_extended_as_d669_rules() -> None:
    assert [(p.name, p.akind, p.scope) for p in ALL] == [
        ("section_ref", "section", "document"),
        ("exhibit_ref", "exhibit", "document"),
        ("figure_ref", "figure", "document"),
        ("table_ref", "table", "document"),
        ("equation_ref", "equation", "document"),
        ("identifier", "identifier", "corpus"),
    ]


@pytest.mark.parametrize(
    ("pattern", "text"), [(p, y) for p in ALL for y in p.yes], ids=lambda v: getattr(v, "name", v)
)
def test_every_yes_matches_whole(pattern: Pattern, text: str) -> None:
    match = pattern.expression.search(text)
    assert match is not None
    assert match.span() == (0, len(text)), match


@pytest.mark.parametrize(
    ("pattern", "text"), [(p, n) for p in ALL for n in p.no], ids=lambda v: getattr(v, "name", v)
)
def test_every_no_matches_nowhere(pattern: Pattern, text: str) -> None:
    assert pattern.expression.search(text) is None


@pytest.mark.parametrize("text", FIXTURES)
def test_no_two_patterns_claim_one_token_over_every_fixture(text: str) -> None:
    spans = [(p.name, m.span()) for p in ALL for m in p.expression.finditer(text)]
    for (a, (a0, a1)), (b, (b0, b1)) in combinations(spans, 2):
        assert a == b or a1 <= b0 or b1 <= a0, (text, a, b)


def test_the_akind_vocabulary_is_anchor_kinds() -> None:
    assert {member.value for member in AnchorKind} == rules._AKINDS


def test_a_set_that_breaks_its_own_rules_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Files:
        def __init__(self, body: str) -> None:
            self.body = body

        def joinpath(self, _name: str) -> _Files:
            return self

        def read_text(self, encoding: str) -> str:
            del encoding
            return self.body

    bad = {
        "akind": '[[pattern]]\nname="x"\nakind="chapter"\nscope="document"\nre="(a)"\n'
        'yes=["a","a","a"]\nno=["b","b","b"]\n',
        "group": '[[pattern]]\nname="x"\nakind="section"\nscope="document"\nre="a"\n'
        'yes=["a","a","a"]\nno=["b","b","b"]\n',
        "fixtures": '[[pattern]]\nname="x"\nakind="section"\nscope="document"\nre="(a)"\n'
        'yes=["a"]\nno=["b","b","b"]\n',
    }
    for why, body in bad.items():
        monkeypatch.setattr(rules, "files", lambda _pkg, body=body: _Files(body))
        rules.patterns.cache_clear()
        try:
            with pytest.raises(ValueError, match="pattern x"):
                rules.patterns()
        finally:
            rules.patterns.cache_clear()
        assert why


# -- the detector ----------------------------------------------------------------------------------


def test_the_name_is_the_first_group_and_the_occurrence_the_whole_match() -> None:
    assert refs("See Section 4.2(b) and Exhibit C, per Table 3 and GL-4471.") == [
        ("section", "4.2(b)", "Section 4.2(b)"),
        ("exhibit", "C", "Exhibit C"),
        ("table", "3", "Table 3"),
        ("identifier", "GL-4471", "GL-4471"),
    ]


def test_a_word_inside_another_word_is_not_a_reference() -> None:
    assert refs("The config 3 and suitable 4 ways, configured twice.") == []


def test_overlapping_matches_keep_the_earlier_then_the_longer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def make(name: str, expression: str) -> Pattern:
        return Pattern(name, "section", "document", re.compile(expression), (), ())

    monkeypatch.setattr(
        rules, "patterns", lambda: (make("short", r"(Sec) 4"), make("long", r"(Sec 4\.2)"))
    )
    assert refs("Sec 4.2 then Sec 4") == [
        ("section", "Sec 4.2", "Sec 4.2"),
        ("section", "Sec", "Sec 4"),
    ]


def test_at_most_thirty_two_occurrences_per_block_and_the_rest_are_disclosed() -> None:
    text = " ".join(f"Section {n}" for n in range(40))
    found = find([Member(cite="d1#1", kind="paragraph", text=text)])
    assert [r.name for r in found.refs] == [str(n) for n in range(MAX_REF_SITES_PER_BLOCK)]
    [notice] = found.notices
    assert (notice.code, notice.cite) == ("OW_REFSITE_TRUNCATED", "d1#1")
    assert notice.detail == {"limit": "MAX_REF_SITES_PER_BLOCK", "value": 32, "found": 40}


@pytest.mark.parametrize(
    "kind", ["code", "formula", "toc", "toc_entry", "page_header", "page_footer"]
)
def test_a_kind_without_prose_is_not_read(kind: str) -> None:
    assert refs("See Section 4.", kind=kind) == []


def test_a_label_opening_a_heading_or_caption_defines_rather_than_refers() -> None:
    """D670: `derive.anchor.native` defines `Schedule 2` from this heading: no occurrence."""
    assert refs("Schedule 2 - Fees", kind="heading") == []
    assert refs("  Figure 3: Revenue", kind="caption") == []
    assert refs("Schedule 2 - Fees, see Section 4", kind="title") == [("section", "4", "Section 4")]
    assert refs("Schedule 2 - Fees", kind="paragraph") == [("exhibit", "2", "Schedule 2")]


@pytest.mark.parametrize("kind", ["heading", "paragraph", "list_item", "table_cell", "footnote"])
def test_a_text_bearing_kind_is_read(kind: str) -> None:
    assert refs("See Section 4.", kind=kind) == [("section", "4", "Section 4")]


def test_a_pathological_block_costs_linear_time() -> None:
    import time  # noqa: PLC0415

    text = "Section " * 50_000 + "§§ " * 50_000 + "AB-" * 50_000
    started = time.perf_counter()
    find([Member(cite="d1#1", kind="paragraph", text=text)])
    assert time.perf_counter() - started < 2.0


# -- one vocabulary, two consumers (D674) ----------------------------------------------------------


def test_the_query_lifter_restates_this_pattern_set_expression_for_expression() -> None:
    """06:1095-1097: query-side sanitisation lifts *"the same token shapes"* -- *"one vocabulary,
    two consumers"*. Core may not import this package, so `REF_SHAPES` restates the set; this holds
    the restatement equal, in order. `citekey` is the one query-only shape after it."""
    from omniweave_core.retrieve.channels import REF_SHAPES  # noqa: PLC0415 -- this test's own

    assert [(shape.pattern, shape.flags, akind) for shape, akind in REF_SHAPES[: len(ALL)]] == [
        (p.expression.pattern, p.expression.flags, p.akind) for p in ALL
    ]
    assert [akind for _, akind in REF_SHAPES[len(ALL) :]] == ["citekey"]


@pytest.mark.parametrize("text", [text for p in ALL for text in p.yes])
def test_a_query_naming_a_reference_lifts_the_key_its_ref_site_carries(text: str) -> None:
    """The keys, not only the expressions: what `ow query` lifts from a `yes` fixture is exactly
    the `(name_norm, akind)` the sink writes for the same words in a document."""
    from omniweave_core.ident import normalize_key  # noqa: PLC0415 -- this test's own
    from omniweave_core.retrieve.channels import sanitize  # noqa: PLC0415

    written = [(normalize_key(name), akind) for akind, name, _surface in refs(text)]
    assert list(sanitize(text).refs) == written
