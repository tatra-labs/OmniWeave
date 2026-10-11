"""`omniweave_core.out.roundtrip`: r1 ... r7 as predicates, each failure kind on its own.

09-generation.md section 11.1's seven laws and section 11.4's applicability rule. Each predicate
is fed the facts its law is stated over, once where it holds and once per way it can fail.
"""

from __future__ import annotations

import unicodedata

import pytest
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.out.roundtrip import (
    LAWS,
    ILElement,
    ReadBlock,
    RoundBlock,
    applicable,
    r1,
    r2,
    r3,
    r4a,
    r4b,
    r5,
    r6,
    r7,
)

P, N, C, R, B = (
    UnitOutcome.PASSTHROUGH,
    UnitOutcome.NATIVE,
    UnitOutcome.CLONED_PASSTHROUGH,
    UnitOutcome.REBUILT,
    UnitOutcome.PATCHED,
)


# ---------------------------------------------------------------------------
# R1
# ---------------------------------------------------------------------------


def test_r1_holds_at_every_declared_class() -> None:
    built = {"part": "sha256:a", "byte": "sha256:b", "render": "sha256:x"}
    rebuilt = {"part": "sha256:a", "byte": "sha256:b", "render": "sha256:y"}
    assert r1({"part", "byte"}, built, rebuilt).passed


def test_r1_names_a_different_and_an_unmeasured_class() -> None:
    result = r1({"part", "byte", "frame"}, {"part": "a", "byte": "b"}, {"part": "a", "byte": "c"})
    assert [(f.kind, f.subject) for f in result.failures] == [
        ("differs", "byte"),
        ("unmeasured", "frame"),
    ]


# ---------------------------------------------------------------------------
# R2
# ---------------------------------------------------------------------------

KIND_MAP = {"elem.text": "paragraph", "elem.title": "title"}
ELEMENTS = (
    ILElement("u01/e1", "elem.title", "Q3", frozenset()),
    ILElement("u01/e2", "elem.text", "Café revenue rose", frozenset({"d7#1"})),
)


def test_r2_holds_when_each_element_has_exactly_its_block() -> None:
    blocks = (
        ReadBlock("u01/e1", "title", "Q3"),
        ReadBlock(
            "u01/e2",
            "paragraph",
            unicodedata.normalize("NFD", "Café revenue rose"),
            frozenset({"d7#1"}),
        ),
        ReadBlock(None, "paragraph", "furniture"),
    )
    assert r2(ELEMENTS, blocks, KIND_MAP).passed


@pytest.mark.parametrize(
    ("blocks", "kinds"),
    [
        (
            (ReadBlock("u01/e2", "paragraph", "Café revenue rose", frozenset({"d7#1"})),),
            {"missing"},
        ),
        (
            (
                ReadBlock("u01/e1", "title", "Q3"),
                ReadBlock("u01/e1", "title", "Q3"),
                ReadBlock("u01/e2", "paragraph", "Café revenue rose", frozenset({"d7#1"})),
            ),
            {"duplicated"},
        ),
        (
            (
                ReadBlock("u01/e1", "paragraph", "Q3"),
                ReadBlock("u01/e2", "paragraph", "Café revenue rose", frozenset({"d7#1"})),
            ),
            {"kind"},
        ),
        (
            (
                ReadBlock("u01/e1", "title", "Q4"),
                ReadBlock("u01/e2", "paragraph", "Café revenue rose", frozenset({"d7#1"})),
            ),
            {"text"},
        ),
        (
            (
                ReadBlock("u01/e1", "title", "Q3"),
                ReadBlock("u01/e2", "paragraph", "Café revenue rose", frozenset()),
            ),
            {"cites"},
        ),
    ],
)
def test_r2_keeps_each_failure_distinct(blocks: tuple[ReadBlock, ...], kinds: set[str]) -> None:
    assert r2(ELEMENTS, blocks, KIND_MAP).kinds() == kinds


def test_r2_an_unmapped_construct_is_a_kind_failure() -> None:
    element = ILElement("u01/e9", "elem.mystery", "x")
    result = r2((element,), (ReadBlock("u01/e9", "paragraph", "x"),), KIND_MAP)
    assert result.kinds() == {"kind"}


def test_r2_a_none_text_is_compared_as_empty() -> None:
    element = ILElement("u01/e1", "elem.title", "")
    assert r2((element,), (ReadBlock("u01/e1", "title", None),), KIND_MAP).passed


# ---------------------------------------------------------------------------
# R3
# ---------------------------------------------------------------------------


def _round(*rows: tuple[int, int, str, str]) -> list[RoundBlock]:
    return [RoundBlock(*row) for row in rows]


def test_r3_compares_body_digests_in_page_ord_order() -> None:
    d1 = _round((0, 1, "body", "b"), (0, 0, "body", "a"), (0, 2, "note", "n"))
    d2 = _round((0, 0, "body", "a"), (0, 1, "body", "b"), (1, 0, "furniture", "f"))
    assert r3(d1, d2).passed


@pytest.mark.parametrize(
    "d2",
    [
        _round((0, 0, "body", "b"), (0, 1, "body", "a")),
        _round((0, 0, "body", "a")),
        _round((0, 0, "body", "a"), (0, 1, "body", "b"), (0, 2, "body", "c")),
        _round((0, 0, "body", "a"), (0, 1, "body", "z")),
    ],
)
def test_r3_order_count_and_content_all_matter(d2: list[RoundBlock]) -> None:
    d1 = _round((0, 0, "body", "a"), (0, 1, "body", "b"))
    result = r3(d1, d2)
    assert result.kinds() == {"not-fixed"}


def test_r3_names_where_the_rounds_first_differ() -> None:
    result = r3(_round((0, 0, "body", "a"), (0, 1, "body", "b")), _round((0, 0, "body", "a")))
    assert result.failures[0].subject == "body[1]"


# ---------------------------------------------------------------------------
# R4
# ---------------------------------------------------------------------------


def test_r4a_zero_edits_copy_every_unit_byte_for_byte() -> None:
    assert r4a({"u01": P, "u02": C}, {"u01": ("x", "x"), "u02": ("y", "y")}).passed


@pytest.mark.parametrize(
    ("outcomes", "copied", "kind"),
    [
        ({"u01": N}, {"u01": ("x", "x")}, "not-copied"),
        ({"u01": P}, {}, "unasserted"),
        ({"u01": C}, {"u01": ("x", "y")}, "bytes-moved"),
    ],
)
def test_r4a_names_each_way_a_copy_fails(
    outcomes: dict[str, UnitOutcome], copied: dict[str, tuple[str, str]], kind: str
) -> None:
    assert r4a(outcomes, copied).kinds() == {kind}


def test_r4b_a_unit_the_edit_never_touches_is_never_rebuilt() -> None:
    deps = {
        "u01": frozenset({"u01/e1"}),
        "u02": frozenset({"u02/e1", "defs/grad3"}),
        "u03": frozenset({"u03/e1"}),
    }
    ok = r4b({"u01": R, "u02": B, "u03": P}, deps, frozenset({"u01/e1"}))
    assert ok.passed
    bad = r4b({"u01": R, "u02": R, "u03": N}, deps, frozenset({"u01/e1"}))
    assert [(f.kind, f.subject) for f in bad.failures] == [
        ("not-local", "u02"),
        ("not-local", "u03"),
    ]


def test_r4b_a_definition_dependency_counts_as_touched() -> None:
    """09: a unit referencing a changed `<defs>` entry is changed though its bytes are not."""
    deps = {"u02": frozenset({"u02/e1", "defs/grad3"})}
    assert r4b({"u02": R}, deps, frozenset({"defs/grad3"})).passed


# ---------------------------------------------------------------------------
# R5
# ---------------------------------------------------------------------------

R5_OK = {
    "declared_loss": frozenset({"anim.curve"}),
    "observed_loss": frozenset({"anim.curve"}),
    "loss_shown": frozenset({"anim.curve"}),
    "exact": frozenset({"elem.text"}),
    "exercised": frozenset({"elem.text"}),
    "moved": frozenset({"elem.text"}),
}


def test_r5_holds_when_every_clause_does() -> None:
    assert r5(**R5_OK).passed


@pytest.mark.parametrize(
    ("change", "kind"),
    [
        ({"observed_loss": frozenset({"anim.curve", "marks.kern"})}, "undeclared-loss"),
        ({"loss_shown": frozenset()}, "loss-never-shown"),
        ({"exercised": frozenset()}, "exact-unexercised"),
        ({"moved": frozenset()}, "exact-invisible"),
    ],
)
def test_r5_names_each_clause(change: dict[str, frozenset[str]], kind: str) -> None:
    assert r5(**{**R5_OK, **change}).kinds() == {kind}


def test_r5_a_wildcard_loss_is_not_green() -> None:
    """09: without the third clause, `loses = ["*"]` is a green report."""
    result = r5(**{**R5_OK, "exact": frozenset({"elem.text", "elem.title"})})
    assert result.kinds() == {"exact-unexercised", "exact-invisible"}


# ---------------------------------------------------------------------------
# R6
# ---------------------------------------------------------------------------


def test_r6_holds_when_every_unrepresented_part_is_ledgered() -> None:
    parts = {"u03 (source slide 5)": ["ppt/media/media1.mp4"]}
    assert r6(parts, frozenset({"ppt/media/media1.mp4"})).passed
    assert r6({}, frozenset()).passed


def test_r6_refuses_naming_the_paths_and_both_exits() -> None:
    parts = {
        "u03 (source slide 5)": ["ppt/media/media1.mp4", "ppt/embeddings/oleObject1.bin"],
        "u04 (source slide 6)": ["ppt/media/kept.png"],
    }
    result = r6(parts, frozenset({"ppt/media/kept.png"}))
    assert [f.subject for f in result.failures] == ["u03 (source slide 5)"]
    assert result.failures[0].msg == (
        "round-trip export would drop source video, audio, or opaque payload relationships:\n"
        "  unit u03 (source slide 5): ppt/embeddings/oleObject1.bin, ppt/media/media1.mp4\n"
        "Keep each listed source unit unedited, or remove the opaque relationship from the source\n"
        "artefact before importing."
    )


# ---------------------------------------------------------------------------
# R7
# ---------------------------------------------------------------------------


def test_r7_every_unit_exactly_once() -> None:
    assert r7(["u01", "u02"], {"u01": N, "u02": P}).passed


@pytest.mark.parametrize(
    ("units", "outcomes", "kinds"),
    [
        (["u01", "u02"], {"u01": N}, {"unclassified"}),
        (["u01"], {"u01": N, "u09": N}, {"stray"}),
        (["u01", "u01"], {"u01": N}, {"repeated"}),
    ],
)
def test_r7_names_each_way_a_count_fails(
    units: list[str], outcomes: dict[str, UnitOutcome], kinds: set[str]
) -> None:
    assert r7(units, outcomes).kinds() == kinds


# ---------------------------------------------------------------------------
# Applicability
# ---------------------------------------------------------------------------


def test_an_undeclared_law_is_visibly_not_applicable() -> None:
    claim = applicable(["r1"], "structure")
    assert claim.applies == ("r1",)
    assert claim.not_applicable == tuple(law for law in LAWS if law != "r1")
    assert applicable(LAWS, "passthrough").not_applicable == ()


@pytest.mark.parametrize(
    ("laws", "fidelity", "said"),
    [
        (["r4"], "structure", "r4 is not meaningful at fidelity 'structure'"),
        (["r4"], "patched", "r4 is not meaningful"),
        (["r2"], "none", "r2 is not meaningful"),
        (["r3"], "none", "r3 is not meaningful"),
        (["r8"], "none", "laws \\['r8'\\]"),
        (["r1"], "lossless", "fidelity 'lossless'"),
    ],
)
def test_a_law_the_tier_forbids_is_a_card_error(laws: list[str], fidelity: str, said: str) -> None:
    with pytest.raises(ValueError, match=said):
        applicable(laws, fidelity)


def test_fidelity_none_still_owes_the_laws_that_need_no_reader() -> None:
    claim = applicable(["r1", "r5", "r6", "r7"], "none")
    assert claim.applies == ("r1", "r5", "r6", "r7")
