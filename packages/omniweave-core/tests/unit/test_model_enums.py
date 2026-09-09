"""The fifteen closed vocabularies are exactly the plan's, member for member and ordinal for
ordinal.

Almost every assertion here is transcription. 03-document-model.md section 2.1 prints eight of
the fifteen enums outright (`Kind`, `Layer`, `Trust`, `Quote`, `Method`, `PageKind`, `RelKind`,
`OsKind`); charter.md prints three more (`Lane` as `LANES`, `AnchorKind`, `Taint`); and the last
four -- `TableKind`, `AliasKind`, `ClaimStatus`, `TimePrecision` -- exist only as a SQL CHECK
list or a `Literal`, which is the gap 03:124 fills for `OsKind` and this module fills for them.
What transcription cannot catch is the thing that would be silent -- an ordinal that moved. Five
sibling clusters generate `enum_val` INSERTs, `block` CHECK constraints and the
`MAX_TRUST_BY_METHOD` triggers against these integers, and `enum_val.ord` IS THE STORED VALUE
and is APPEND-ONLY (03 section 2.1), so a member inserted in the middle of a vocabulary silently
retypes every historical row. The golden `VOCABULARIES` table below is therefore a literal, not
a derivation: a reorder must fail here before it can reach a migration.

Two assertions are not transcription and are named as such by 16-roadmap.md's W2.1 row:
`Quote.SYNTHETIC < Quote.VERBATIM`, and `quote_min == min(member quotes)` over a deliberately
mixed set. The second is written here in its enum half; its segment half belongs to whoever
builds `segment` and is named in this file so it is not lost.

Specified in 03-document-model.md sections 2.1, 4.1, 8.2, 8.3 and 13.1; 06-structure-extraction.md
sections 1.3, 1.4 and 3.8; charter.md's `enum_val` block (:939-951) and `0002_graph.sql`
(:4834-4849).
"""

from __future__ import annotations

import ast
import re
from enum import Enum
from pathlib import Path

import pytest
from omniweave_core.model import enums
from omniweave_core.model.enums import (
    ENUM_DOMAINS,
    GENERATION_BLOCKED,
    MAX_TRUST_BY_METHOD,
    AliasKind,
    AnchorKind,
    ClaimStatus,
    Kind,
    Lane,
    Layer,
    Method,
    OsKind,
    PageKind,
    Quote,
    RelKind,
    TableKind,
    Taint,
    TimePrecision,
    Trust,
    enum_val_rows,
)

CORE_SRC = Path(enums.__file__).resolve().parents[1]
"""`.../src/omniweave_core`. The INV-21 scan's root, found from the module rather than by
counting `parents[n]`, so moving the test tree cannot silently narrow the scan."""


# ---------------------------------------------------------------------------
# The golden: the fifteen domain names, and every member of every one, in order.
# ---------------------------------------------------------------------------

THE_FIFTEEN: tuple[str, ...] = (
    "kind",
    "layer",
    "trust",
    "method",
    "quote",
    "page_kind",
    "table_kind",
    "rel_kind",
    "origin_span_kind",
    "lane",
    "akind",
    "alias_kind",
    "claim_status",
    "taint",
    "precision",
)
"""03-document-model.md:2311-2312 and charter.md:942-943, verbatim and in their order.

A sixteenth cannot be added by accident: it has to be typed here, which is a decision somebody
makes rather than a consequence of adding a class to `enums.py`.
"""

VOCABULARIES: tuple[tuple[str, type[Enum], tuple[str, ...]], ...] = (
    (
        "kind",
        Kind,
        (
            "DOCUMENT",
            "SECTION",
            "TITLE",
            "HEADING",
            "PARAGRAPH",
            "LIST",
            "LIST_ITEM",
            "BLOCKQUOTE",
            "CODE",
            "TABLE",
            "TABLE_CELL",
            "FIGURE",
            "PICTURE",
            "CAPTION",
            "FORMULA",
            "RULE",
            "PAGE_HEADER",
            "PAGE_FOOTER",
            "FOOTNOTE",
            "ENDNOTE",
            "SPEAKER_NOTE",
            "COMMENT",
            "FORM",
            "FORM_FIELD",
            "CHECKBOX",
            "KEY_VALUE",
            "TOC",
            "TOC_ENTRY",
            "REFERENCE",
            "BIBLIOGRAPHY",
            "HANDWRITING",
            "CHEMICAL",
            "DIAGRAM",
            "CONTAINER",
            "UNKNOWN",
        ),
    ),
    ("layer", Layer, ("BODY", "FURNITURE", "NOTE", "ANNOTATION", "HIDDEN")),
    ("trust", Trust, ("AMBIGUOUS", "INFERRED", "EXTRACTED")),
    (
        "method",
        Method,
        (
            "NATIVE",
            "TEXT_LAYER",
            "NATIVE_XML",
            "OCR_PAGE",
            "OCR_BLOCK",
            "VLM_PAGE",
            "LLM",
            "HEURISTIC",
            "ROUNDTRIP",
            "USER",
        ),
    ),
    ("quote", Quote, ("SYNTHETIC", "RECONSTRUCTED", "REFLOWED", "NORMALIZED", "VERBATIM")),
    ("page_kind", PageKind, ("PAGE", "SLIDE", "SHEET", "FRAME", "STREAM")),
    ("table_kind", TableKind, ("DATA", "LAYOUT")),
    (
        "rel_kind",
        RelKind,
        (
            "CAPTION_OF",
            "NOTE_REF",
            "CONTINUES",
            "ANCHOR_REF",
            "HEADING_OF",
            "DERIVED_FROM",
            "SUPERSEDES",
        ),
    ),
    ("origin_span_kind", OsKind, ("BYTES", "NODEPATH", "GLYPHS", "PIXELS", "NONE")),
    (
        "lane",
        Lane,
        (
            "TEXT",
            "TABLE",
            "MATH",
            "FIELDS",
            "CAPTION",
            "ANCHOR",
            "XREF",
            "ENTITY",
            "CLAIM",
            "COMMUNITY",
            "SUMMARY",
        ),
    ),
    (
        "akind",
        AnchorKind,
        (
            "SECTION",
            "CLAUSE",
            "FIGURE",
            "TABLE",
            "EQUATION",
            "CITEKEY",
            "IDENTIFIER",
            "DEFINED_TERM",
            "FOOTNOTE",
            "EXHIBIT",
            "SLIDE",
            "SHEET",
            "GLOSSARY",
            "BOOKMARK",
        ),
    ),
    (
        "alias_kind",
        AliasKind,
        ("CANONICAL", "VARIANT", "ABBREV", "EXPANSION", "TRANSLIT", "LLM", "USER"),
    ),
    ("claim_status", ClaimStatus, ("ASSERTED", "DENIED", "SUSPECTED", "SUPERSEDED")),
    (
        "taint",
        Taint,
        (
            "NONE",
            "UNTRUSTED_SOURCE",
            "SENTINEL",
            "HIDDEN_TEXT",
            "OFFSCREEN",
            "SINGLE_WITNESS_XDOC",
        ),
    ),
    ("precision", TimePrecision, ("YEAR", "MONTH", "DAY", "DATETIME")),
)
"""Every domain, its enum, and every member NAME in DECLARATION ORDER.

Declaration order, never sorted. This is the append-only ledger in test form: a member may be
appended to one of these tuples and may never be moved, because the index is the stored value
for a `StrEnum` (03 section 2.1).
"""

INT_VALUED: tuple[str, ...] = ("trust", "quote", "taint")
"""The three domains whose `enum_val.ord` is the member's OWN INTEGER rather than its position.

`trust` and `quote` are the ordered `IntEnum`s the plan names (charter.md:948). `taint` is an
`IntFlag` and the plan is silent; `enums.Taint`'s docstring carries the choice and the reason.
"""

STR_VALUED: tuple[tuple[str, type[Enum], tuple[str, ...]], ...] = tuple(
    row for row in VOCABULARIES if row[0] not in INT_VALUED
)
"""The twelve whose ordinal is a POSITION. Split out so the dense-from-zero rule is a
parametrisation over the domains it holds for rather than a skip over the ones it does not."""


def _members(vocabulary: type[Enum]) -> tuple[Enum, ...]:
    return tuple(m for name, m in vocabulary.__members__.items() if m.name == name)


# ---------------------------------------------------------------------------
# The fifteen, and only the fifteen
# ---------------------------------------------------------------------------


def test_enum_domains_is_exactly_the_fifteen_in_order__03_document_model_md_2311() -> None:
    """The domain list is a literal here so a sixteenth is a decision, not a side effect."""
    assert tuple(ENUM_DOMAINS) == THE_FIFTEEN
    assert len(THE_FIFTEEN) == 15


def test_format_is_not_an_enum_val_domain__03_2311_charter_7948_adr_0012_197() -> None:
    """`format` is free text over a COMPUTED domain and cannot live in an append-only table.

    Core ships forty-eight format tokens and `unit.format`'s domain is that set UNION the
    enabled cards' `[capability.parse] format_tokens`, so it grows when a driver is enabled.
    `enum_val.ord` IS THE STORED VALUE and is APPEND-ONLY, so two installs with different cards
    would disagree about `enum_val` and an `.owdoc` would mean different things depending on
    what happened to be installed. 05-ingest-and-routing.md:633 and :2074 claim the opposite and
    are the defective sites (`_notes/build-defects.md` D10).
    """
    assert "format" not in ENUM_DOMAINS
    assert not any(domain == "format" for domain, _ord, _name in enum_val_rows())


def test_the_open_vocabularies_are_not_domains__charter_md_section_5_x2() -> None:
    """`relation`, `etype` and `claim_type` get their own TABLES, not `enum_val` rows.

    An enum generated from a Python enum cannot express "a driver may declare a new relation"
    (06-structure-extraction.md section 1.6).
    """
    for open_vocabulary in ("relation", "etype", "claim_type", "ref_kind"):
        assert open_vocabulary not in ENUM_DOMAINS


def test_every_domain_maps_to_a_distinct_enum() -> None:
    """`PRIMARY KEY (domain, ord)` cannot hold two vocabularies, so neither can this map."""
    classes = list(ENUM_DOMAINS.values())
    assert len(set(classes)) == len(classes)


def test_the_golden_table_covers_exactly_the_fifteen_domains() -> None:
    assert tuple(domain for domain, _cls, _names in VOCABULARIES) == THE_FIFTEEN
    assert {domain: cls for domain, cls, _names in VOCABULARIES} == dict(ENUM_DOMAINS)


# ---------------------------------------------------------------------------
# Members, in declaration order, never sorted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("domain", "vocabulary", "names"), VOCABULARIES, ids=THE_FIFTEEN)
def test_members_are_the_golden_names_in_declaration_order(
    domain: str, vocabulary: type[Enum], names: tuple[str, ...]
) -> None:
    assert tuple(m.name for m in _members(vocabulary)) == names, domain


@pytest.mark.parametrize(("domain", "vocabulary", "names"), VOCABULARIES, ids=THE_FIFTEEN)
def test_no_vocabulary_declares_an_alias(
    domain: str, vocabulary: type[Enum], names: tuple[str, ...]
) -> None:
    """An alias would put two names on one `ord`, and `enum_val` has room for exactly one."""
    assert tuple(vocabulary.__members__) == names, domain


@pytest.mark.parametrize(("domain", "vocabulary", "names"), VOCABULARIES, ids=THE_FIFTEEN)
def test_the_wire_value_is_the_lower_case_member_name(
    domain: str, vocabulary: type[Enum], names: tuple[str, ...]
) -> None:
    """03 section 2.1: every enum value is the lower-case member name on the wire, `IntEnum`
    included. For every `StrEnum` here that is also the member's own `.value`, and 03:1438
    resolves `origin_span_kind` members out of `enum_val` by exactly that spelling from inside a
    `block` CHECK constraint."""
    for member in _members(vocabulary):
        wire = member.name.lower()
        assert re.fullmatch(r"[a-z][a-z0-9_]*", wire), f"{domain}.{member.name}"
        if isinstance(member.value, str):
            assert member.value == wire, f"{domain}.{member.name}"
    assert names  # the parametrisation carries the golden; this guards an empty id list


def test_kind_is_thirty_four_members_plus_unknown__03_section_4_1() -> None:
    assert len(Kind) == 35
    assert Kind.UNKNOWN.value == "unknown"
    assert tuple(Kind)[-1] is Kind.UNKNOWN, "UNKNOWN is APPENDED, so it is last"


def test_blockquote_not_quote__03_823_charter_section_5_x17() -> None:
    """The tier enum owns the word `quote`; the block kind is `blockquote`."""
    assert Kind.BLOCKQUOTE.value == "blockquote"
    assert "QUOTE" not in Kind.__members__


def test_anchor_kind_is_one_vocabulary_and_spells_it_citekey__06_section_3_8() -> None:
    """`anchor.akind` and `ref_site.akind` join by EQUALITY in two views. The charter records
    what happened when they spelled the bibliography key differently: every `citekey` reference
    was permanently unresolved with nothing reporting it."""
    assert len(AnchorKind) == 14
    assert AnchorKind.CITEKEY.value == "citekey"
    assert "CITATION_KEY" not in AnchorKind.__members__


def test_alias_kind_is_disjoint_from_akind__charter_md_5019() -> None:
    """Two disjoint sets, therefore two columns and two domains: one domain name holds exactly
    one vocabulary."""
    akind = {m.value for m in AnchorKind}
    alias = {m.value for m in AliasKind}
    assert akind.isdisjoint(alias)


# ---------------------------------------------------------------------------
# The ordinals. This is the half that would fail silently.
# ---------------------------------------------------------------------------


def test_every_row_is_a_domain_ord_name_triple() -> None:
    rows = enum_val_rows()
    assert len(rows) == sum(len(names) for _domain, _cls, names in VOCABULARIES)
    for domain, stored, name in rows:
        assert domain in ENUM_DOMAINS
        assert isinstance(stored, int)
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name)


def test_domain_and_ord_are_unique__charter_md_941_primary_key_domain_ord() -> None:
    """`PRIMARY KEY (domain, ord)` -- the generated INSERTs must not need a conflict clause."""
    keys = [(domain, stored) for domain, stored, _name in enum_val_rows()]
    assert len(set(keys)) == len(keys)


def test_domain_and_name_are_unique_too() -> None:
    """A name resolved out of `enum_val` by `WHERE domain=? AND name=?` (03:1438) must resolve
    to one row, or the CHECK constraint compares against an arbitrary one of two."""
    keys = [(domain, name) for domain, _ord, name in enum_val_rows()]
    assert len(set(keys)) == len(keys)


@pytest.mark.parametrize(
    ("domain", "vocabulary", "names"),
    STR_VALUED,
    ids=[domain for domain, _cls, _names in STR_VALUED],
)
def test_str_enum_ordinals_are_dense_from_zero_in_declaration_order(
    domain: str, vocabulary: type[Enum], names: tuple[str, ...]
) -> None:
    """For a `StrEnum` the ordinal IS declaration order (03 section 2.1), which makes it dense
    from 0. The three `int`-valued domains are a separate parametrisation rather than a skip
    inside this one, because for them the ordinal is the member's own integer and `taint` is not
    dense at all -- a skipped case reads as "not checked yet"."""
    assert not issubclass(vocabulary, int), f"{domain} is a StrEnum, so its ordinal is a position"
    rows = [row for row in enum_val_rows() if row[0] == domain]
    assert [stored for _domain, stored, _name in rows] == list(range(len(names)))
    assert [name for _domain, _ord, name in rows] == [n.lower() for n in names]


def test_trust_ordinals_are_the_members_own_integers__charter_md_948() -> None:
    rows = {name: stored for domain, stored, name in enum_val_rows() if domain == "trust"}
    assert rows == {"ambiguous": 0, "inferred": 1, "extracted": 2}
    assert rows == {m.name.lower(): int(m) for m in Trust}


def test_quote_ordinals_are_the_members_own_integers__charter_md_948() -> None:
    rows = {name: stored for domain, stored, name in enum_val_rows() if domain == "quote"}
    assert rows == {
        "synthetic": 0,
        "reconstructed": 1,
        "reflowed": 2,
        "normalized": 3,
        "verbatim": 4,
    }
    assert rows == {m.name.lower(): int(m) for m in Quote}


def test_taint_ordinals_are_the_bits_not_the_positions__charter_md_5027() -> None:
    """`entity.taint` stores a BITMASK and `taint & TAINT_UNTRUSTED_SOURCE` is the shipped
    predicate, so `enum_val` has to carry the bit. Declaration order would register
    `hidden_text` at 2 while the stored bit is 4 -- the exact "every stored row means something
    else" hazard the append-only rule exists to prevent. The plan is silent on `IntFlag`;
    `enums.Taint`'s docstring carries the choice."""
    rows = {name: stored for domain, stored, name in enum_val_rows() if domain == "taint"}
    assert rows == {
        "none": 0,
        "untrusted_source": 1,
        "sentinel": 2,
        "hidden_text": 4,
        "offscreen": 8,
        "single_witness_xdoc": 16,
    }


def test_taint_none_is_carried_although_python_will_not_iterate_it() -> None:
    """A zero-valued `Flag` member is excluded from `iter()`, and `taint = 0` is the commonest
    stored value there is. `_declared()` walks `__members__` for exactly this reason."""
    assert Taint.NONE not in list(Taint)
    assert "none" in {name for domain, _ord, name in enum_val_rows() if domain == "taint"}


def test_taint_is_five_bits_plus_none__glossary_md_1066() -> None:
    assert len(list(Taint)) == 5
    assert [int(m) for m in Taint] == [1, 2, 4, 8, 16]
    assert int(Taint.NONE) == 0


def test_enum_val_rows_is_stable_and_ordered_by_domain() -> None:
    """A migration's generated INSERTs are byte-reproducible (INV-24), so the row order is part
    of the contract and not an accident of dict iteration."""
    assert enum_val_rows() == enum_val_rows()
    seen: list[str] = []
    for domain, _ord, _name in enum_val_rows():
        if domain not in seen:
            seen.append(domain)
    assert tuple(seen) == THE_FIFTEEN


# ---------------------------------------------------------------------------
# The two assertions that are not transcription. 16-roadmap.md W2.1.
# ---------------------------------------------------------------------------


def test_quote_synthetic_is_less_than_quote_verbatim__16_roadmap_md_w2_1() -> None:
    """Named by the roadmap as one of W2.1's two non-transcription tests, and it is the only
    thing that catches an inverted ladder. An `IntEnum` whose order is backwards silently
    inverts every comparison in the retrieval stack: `Filters.min_quote` would admit exactly the
    blocks it exists to exclude, and nothing else would notice."""
    assert Quote.SYNTHETIC < Quote.VERBATIM
    assert list(Quote) == sorted(Quote), "the ladder is declared weakest-first"


def test_min_over_a_mixed_set_of_quotes_is_the_weakest_member__03_128() -> None:
    """The enum half of `segment.quote_min == min(member quotes)`.

    The segment half needs a `segment` and belongs to whoever builds it; it is named here so it
    is not lost. Under a declaration-ordered `StrEnum` with `VERBATIM` first, `MIN()` returned
    the BEST tier present, so one verbatim block made a whole segment pass the byte-exactness
    gate for its reflowed and synthetic members.
    """
    mixed = (Quote.VERBATIM, Quote.SYNTHETIC, Quote.NORMALIZED, Quote.REFLOWED)
    assert min(mixed) is Quote.SYNTHETIC
    assert max(mixed) is Quote.VERBATIM
    assert min((Quote.VERBATIM,)) is Quote.VERBATIM


def test_min_over_a_mixed_set_of_trust_is_the_weakest_member__03_section_8_2() -> None:
    """`MIN()` over a set is the set's trust, which is why `AMBIGUOUS` is 0."""
    assert min((Trust.EXTRACTED, Trust.AMBIGUOUS, Trust.INFERRED)) is Trust.AMBIGUOUS
    assert Trust.AMBIGUOUS < Trust.INFERRED < Trust.EXTRACTED
    assert list(Trust) == sorted(Trust)


# ---------------------------------------------------------------------------
# MAX_TRUST_BY_METHOD -- one home, two renderings
# ---------------------------------------------------------------------------


def test_max_trust_by_method_is_total_over_method__inv_7() -> None:
    """A `Method` member with no ceiling is a hole in INV-7 that no generated trigger would
    show: the runner would clamp nothing and the driver's claim would stand."""
    assert set(MAX_TRUST_BY_METHOD) == set(Method)


def test_max_trust_by_method_is_the_plans_mapping__03_section_8_2() -> None:
    assert dict(MAX_TRUST_BY_METHOD) == {
        Method.NATIVE: Trust.EXTRACTED,
        Method.NATIVE_XML: Trust.EXTRACTED,
        Method.TEXT_LAYER: Trust.EXTRACTED,
        Method.HEURISTIC: Trust.EXTRACTED,
        Method.USER: Trust.EXTRACTED,
        Method.OCR_PAGE: Trust.INFERRED,
        Method.OCR_BLOCK: Trust.INFERRED,
        Method.VLM_PAGE: Trust.INFERRED,
        Method.LLM: Trust.INFERRED,
        Method.ROUNDTRIP: Trust.INFERRED,
    }


def test_no_method_ceiling_is_ambiguous__the_clamp_is_a_ceiling_never_a_floor() -> None:
    """`AMBIGUOUS` as a ceiling would make a whole method unable to say anything, which is a
    different mechanism from a clamp. Every ceiling is `INFERRED` or `EXTRACTED`."""
    assert set(MAX_TRUST_BY_METHOD.values()) == {Trust.INFERRED, Trust.EXTRACTED}


def test_heuristic_is_extracted_and_that_is_deliberate__03_1631() -> None:
    """The ceiling is keyed on what could be READ, not on how clever the reading was: a
    heuristic that splits a `w:tbl` into rows is reading the file, and the file said so. A
    coin-flip heuristic writes `AMBIGUOUS` itself; the clamp never raises it."""
    assert MAX_TRUST_BY_METHOD[Method.HEURISTIC] is Trust.EXTRACTED


def test_the_five_a_document_can_talk_back_on_are_capped_at_inferred() -> None:
    talkback = (Method.OCR_PAGE, Method.OCR_BLOCK, Method.VLM_PAGE, Method.LLM, Method.ROUNDTRIP)
    for method in talkback:
        assert MAX_TRUST_BY_METHOD[method] is Trust.INFERRED


def test_generation_blocked_is_the_three_bits__charter_md_5305() -> None:
    """`UNTRUSTED_SOURCE` and `SINGLE_WITNESS_XDOC` are deliberately absent: an ordinary
    third-party PDF taints everything derived from it, and blocking on that bit would block
    generation over the corpus the framework exists to read."""
    assert GENERATION_BLOCKED == Taint.SENTINEL | Taint.HIDDEN_TEXT | Taint.OFFSCREEN
    assert int(GENERATION_BLOCKED) == 2 | 4 | 8
    assert not GENERATION_BLOCKED & Taint.UNTRUSTED_SOURCE
    assert not GENERATION_BLOCKED & Taint.SINGLE_WITNESS_XDOC


# ---------------------------------------------------------------------------
# INV-21 -- one name, one type, one home
# ---------------------------------------------------------------------------


def _enum_class_defs() -> list[tuple[Path, ast.ClassDef]]:
    """Every `class X(<something Enum-shaped>)` under `omniweave_core`, read off the AST.

    AST rather than `import` + `__subclasses__`: a subclass check would only see the modules a
    test session happens to have imported, and `omniweave_core.model` is LAZY by design.
    """
    bases = {"Enum", "StrEnum", "IntEnum", "IntFlag", "Flag", "ReprEnum", "EnumType"}
    found: list[tuple[Path, ast.ClassDef]] = []
    for path in sorted(CORE_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(base, ast.Name) and base.id in bases for base in node.bases
            ):
                found.append((path, node))
    return found


def _member_names(node: ast.ClassDef) -> frozenset[str]:
    return frozenset(
        target.id
        for statement in node.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name) and target.id.isupper()
    )


def test_each_of_the_fifteen_is_declared_exactly_once_in_core__inv_21() -> None:
    """Counting DEFINITION SITES, not mentions. A second `class Layer` is the violation INV-21
    is written from: the charter shipped `Layer` naming both L2's Block layer and a cache layer
    inside one distribution, which made `from omniweave_core... import Layer` ambiguous."""
    declared = [node.name for _path, node in _enum_class_defs()]
    for _domain, vocabulary, _names in VOCABULARIES:
        assert declared.count(vocabulary.__name__) == 1, vocabulary.__name__


def test_no_two_enum_classes_in_core_declare_the_same_member_set__inv_21() -> None:
    """One vocabulary, one home. Two classes with the same member names are one vocabulary
    written twice, whatever they are called."""
    by_members: dict[frozenset[str], list[str]] = {}
    for path, node in _enum_class_defs():
        members = _member_names(node)
        if not members:
            continue
        by_members.setdefault(members, []).append(f"{path.name}:{node.name}")
    duplicated = {members: where for members, where in by_members.items() if len(where) > 1}
    assert duplicated == {}


def test_no_enum_class_name_is_used_twice_in_core__inv_21() -> None:
    seen: dict[str, list[str]] = {}
    for path, node in _enum_class_defs():
        seen.setdefault(node.name, []).append(path.as_posix())
    assert {name: where for name, where in seen.items() if len(where) > 1} == {}


def test_the_module_exports_the_fifteen_plus_four_and_nothing_else() -> None:
    """`__all__` is the fifteen vocabularies plus the four declarations that live beside them.

    A golden list rather than a set, so a reviewer diffs an addition on one line; the order is
    ruff RUF022's (constants, then classes, then functions), which is what keeps `ruff check`
    and this test from disagreeing about what "sorted" means.
    """
    assert enums.__all__ == [
        "ENUM_DOMAINS",
        "GENERATION_BLOCKED",
        "MAX_TRUST_BY_METHOD",
        "AliasKind",
        "AnchorKind",
        "ClaimStatus",
        "Kind",
        "Lane",
        "Layer",
        "Method",
        "OsKind",
        "PageKind",
        "Quote",
        "RelKind",
        "TableKind",
        "Taint",
        "TimePrecision",
        "Trust",
        "enum_val_rows",
    ]
    assert set(enums.__all__) == {vocabulary.__name__ for _d, vocabulary, _n in VOCABULARIES} | {
        "ENUM_DOMAINS",
        "GENERATION_BLOCKED",
        "MAX_TRUST_BY_METHOD",
        "enum_val_rows",
    }


# ---------------------------------------------------------------------------
# Parity with the plan documents themselves
# ---------------------------------------------------------------------------


def _plan_enum_fence(body: str) -> dict[str, tuple[tuple[str, str], ...]]:
    """Parse a plan `python` fence of one-line-per-class enum declarations.

    03 section 2.1 writes `class Layer(StrEnum):    BODY="body"; FURNITURE="furniture"` with
    members on the class line and continuations unindented under it, so the parser is
    line-oriented and carries the current class across lines. Comments are stripped first --
    03:104 writes `# renamed from QUOTE:` inside the `Kind` body.
    """
    member = re.compile(r'([A-Z][A-Z0-9_]*)\s*=\s*(?:"([a-z0-9_]+)"|(\d+))')
    out: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for raw in body.splitlines():
        line = raw.split("#", 1)[0]
        header = re.match(r"\s*class\s+(\w+)\(", line)
        if header is not None:
            current = header.group(1)
            out[current] = []
            line = line.split(":", 1)[1] if ":" in line else ""
        if current is None:
            continue
        for name, text_value, int_value in member.findall(line):
            out[current].append((name, text_value or int_value))
    return {name: tuple(pairs) for name, pairs in out.items()}


def test_the_eight_enums_03_prints_are_transcribed_exactly__03_section_2_1(plan) -> None:
    """The eight the plan prints outright. The other seven are fixed by a CHECK list or a DDL
    comment and are checked one by one below."""
    plan.require()
    fences = [
        body
        for body in plan.fences("03-document-model.md", "python")
        if "class Kind(StrEnum)" in body
    ]
    assert len(fences) == 1, "03 section 2.1's enum fence is the single home"
    printed = _plan_enum_fence(fences[0])
    expected = {
        "Kind": Kind,
        "Layer": Layer,
        "Trust": Trust,
        "Quote": Quote,
        "Method": Method,
        "PageKind": PageKind,
        "RelKind": RelKind,
        "OsKind": OsKind,
    }
    assert set(printed) == set(expected)
    for class_name, vocabulary in expected.items():
        ours = tuple((m.name, str(m.value)) for m in _members(vocabulary))
        assert printed[class_name] == ours, class_name


def test_the_fifteen_domain_names_are_the_plans__03_document_model_md_2311(plan) -> None:
    """Read off 03's own `enum_val` DDL comment rather than retyped, so the two cannot drift."""
    plan.require()
    lines = plan.lines("03-document-model.md")
    starts = [i for i, line in enumerate(lines) if "CLOSED domains only:" in line]
    assert len(starts) == 1
    head = lines[starts[0]].split("CLOSED domains only:", 1)[1]
    listing = f"{head} {lines[starts[0] + 1]}".replace("--", " ")
    names = tuple(part.strip(" .") for part in listing.split(",") if part.strip(" ."))
    assert names == THE_FIFTEEN


def test_max_trust_by_method_matches_the_plans_fence__03_section_8_2(plan) -> None:
    plan.require()
    fences = [
        body
        for body in plan.fences("03-document-model.md", "python")
        if "MAX_TRUST_BY_METHOD" in body
    ]
    assert len(fences) == 1, "03 section 8.2 is MAX_TRUST_BY_METHOD's single home in this doc"
    pairs = re.findall(r"Method\.([A-Z_]+)\s*:\s*([A-Z_]+)", fences[0])
    assert len(pairs) == len(Method)
    printed = {Method[name]: Trust[ceiling] for name, ceiling in pairs}
    assert printed == dict(MAX_TRUST_BY_METHOD)


def test_every_kind_member_has_a_row_in_the_vocabulary_table__03_section_4_1(plan) -> None:
    """Section 4.1's table says what each member OBLIGES; a member with no row is a member no
    driver knows how to populate."""
    plan.require()
    text = plan.text("03-document-model.md")
    for member in Kind:
        assert f"| `{member.value}` |" in text, member.value


def test_taint_matches_the_charters_declaration__charter_md_5302(plan) -> None:
    plan.require()
    lines = plan.lines("_notes/charter.md")
    starts = [i for i, line in enumerate(lines) if line.startswith("class Taint(IntFlag):")]
    assert len(starts) == 1
    body = "\n".join(lines[starts[0] : starts[0] + 4])
    # `1<<1` must not be read as the bare literal `1`, so the shift is part of one match and
    # optional rather than a second alternative the `\d+` branch would win first.
    printed = re.findall(r"([A-Z][A-Z0-9_]*)\s*=\s*(\d+)(?:\s*<<\s*(\d+))?", body)
    ours = [(m.name, int(m)) for m in _members(Taint)]
    rebuilt = [
        (name, int(base) << int(shift) if shift else int(base)) for name, base, shift in printed
    ]
    assert rebuilt == ours


def test_the_lane_members_are_the_charters_lanes__charter_md_2413(plan) -> None:
    """The plan contradicts itself about whether `lane` is closed; it does not contradict itself
    about the eleven members or their order. `enums.Lane`'s docstring carries the ruling."""
    plan.require()
    hits = plan.grep(r"^LANES: frozenset\[str\]", documents=("_notes/charter.md",))
    assert len(hits) == 1
    lines = plan.lines("_notes/charter.md")
    body = "\n".join(lines[hits[0].line - 1 : hits[0].line + 1])
    printed = tuple(re.findall(r'"([a-z_]+)"', body))
    assert printed == tuple(m.value for m in Lane)


def test_the_l3_check_lists_are_the_charters__charter_md_5017_5099(plan) -> None:
    """`alias_kind` and `claim.status` are fixed by their SQL CHECK lists, which is the only
    place either vocabulary is written down."""
    plan.require()
    lines = plan.lines("_notes/charter.md")
    alias = [i for i, line in enumerate(lines) if "alias_kind TEXT NOT NULL CHECK" in line]
    assert len(alias) == 1
    alias_body = "\n".join(lines[alias[0] : alias[0] + 2])
    assert tuple(re.findall(r"'([a-z_]+)'", alias_body)) == tuple(m.value for m in AliasKind)

    # Anchored on `CREATE TABLE claim (` rather than on the `status` column alone, because
    # `derive_run.status` (charter.md:4958) is a SECOND closed vocabulary spelled `status` --
    # ok|partial|empty|failed|quarantined -- and it is deliberately NOT an `enum_val` domain.
    # `claim_status` carries the table in its name for exactly that reason.
    heads = [i for i, line in enumerate(lines) if line.startswith("CREATE TABLE claim (")]
    assert len(heads) == 1
    status = next(
        i
        for i in range(heads[0], heads[0] + 40)
        if "status TEXT NOT NULL CHECK(status IN" in lines[i]
    )
    printed = tuple(re.findall(r"'([a-z_]+)'", lines[status]))
    assert printed == tuple(m.value for m in ClaimStatus)

    other = [
        i
        for i, line in enumerate(lines)
        if "status TEXT NOT NULL CHECK(status IN" in line and i != status
    ]
    assert other, "derive_run.status exists and is the reason this domain is not called `status`"
    for line_no in other:
        assert tuple(re.findall(r"'([a-z_]+)'", lines[line_no])) != printed


def test_time_precision_is_claims_t_precision__06_structure_extraction_md_458(plan) -> None:
    """The `precision` domain is `claim.t_precision`, not `Locus.precision`. `Locus`'s is
    "computed by the query, never stored as a column" (06:2106) and `enum_val.ord` is by
    definition a stored value."""
    plan.require()
    hits = plan.grep(r"t_precision: Literal", documents=("06-structure-extraction.md",))
    assert len(hits) == 1
    printed = tuple(re.findall(r'"([a-z]+)"', hits[0].text))
    assert printed == tuple(m.value for m in TimePrecision)


def test_anchor_kind_matches_the_charters_fourteen__charter_md_4839(plan) -> None:
    plan.require()
    lines = plan.lines("_notes/charter.md")
    starts = [i for i, line in enumerate(lines) if "class AnchorKind(StrEnum):" in line]
    assert len(starts) == 1
    body = "\n".join(lines[starts[0] : starts[0] + 6])
    printed = tuple(name for name, _v in re.findall(r'([A-Z][A-Z_]*)="([a-z_]+)"', body))
    assert printed == tuple(m.name for m in AnchorKind)


def test_table_kind_is_the_two_tags_table_meta_kind_names__03_section_10_1(plan) -> None:
    """`table_meta.kind` is `data|layout` and `Grid.kind` is `Literal["data","layout"]`; no
    document declares the enum, which is the same gap 03:124 fills for `OsKind`."""
    plan.require()
    text = plan.text("03-document-model.md")
    assert "-- data|layout" in text
    assert 'kind: Literal["data","layout"]' in text
    assert tuple(m.value for m in TableKind) == ("data", "layout")
