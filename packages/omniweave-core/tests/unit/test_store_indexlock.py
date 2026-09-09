"""`omniweave.index.lock`: the format, and the merge driver's truth table.

The specification is 07-store-and-retrieval.md section 13.2 (:3099-3160), and the four properties
this file exists to hold are 00-vision.md:583's one line: *"sort-merge by `doc_key`, identical lines
union, a conflicting line for one `doc_key` is a real conflict a human resolves, and **a deleted
line stays deleted**"*.

`test_the_truth_table_over_ancestor_ours_and_theirs_is_complete` IS the specification. It enumerates
all 27 cells of `(ancestor, ours, theirs)` over `{absent, line A, line B}` for one `doc_key`, with
every expectation written out by hand rather than computed -- a table generated from the same rule
the code applies would be a test that cannot fail. The named cells the plan calls out have their own
tests as well, because a parametrised id is not a citation.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from omniweave_core.contract import SCHEMA
from omniweave_core.errors import StoreError
from omniweave_core.store import indexlock
from omniweave_core.store.indexlock import (
    CONFLICT_MARKER_LEN,
    DOC_STATUSES,
    FIELD_SEP,
    GITATTRIBUTES_LINE,
    HEADER_KEYS,
    LOCK_PATH,
    MERGE_DRIVER_NAME,
    LockFile,
    LockHeader,
    LockRow,
    git_config_argv,
    has_conflict_markers,
    merge_lock,
    read_lock,
    write_lock,
)

# The header from the printed fence at 07:3117, verbatim in its three token values.
HEADER = LockHeader(
    scorer=1,
    segmenter="derive.segment.spine@3:9c1e",
    space="bge-m3@a1b2c3/768/cosine/i8",
    schema=1,
)
HEADER_LINE = (
    "# schema=1 scorer=1 segmenter=derive.segment.spine@3:9c1e space=bge-m3@a1b2c3/768/cosine/i8"
)

DIGEST = bytes.fromhex("9c1e" * 8)
KEY = bytes.fromhex("11" * 16)


def row(key: bytes = KEY, gen: int = 1, uri: str = "/c/one.pdf") -> LockRow:
    """A well-formed row. Only `doc_key`, `gen` and `uri` ever vary in this file."""
    return LockRow(
        doc_key=key,
        gen=gen,
        status="ok",
        n_blocks=42,
        n_segments=3,
        content_digest=DIGEST,
        uri=uri,
    )


LINE_A = row(gen=1).render()
LINE_B = row(gen=2).render()
SIDES: dict[str, str | None] = {"absent": None, "A": LINE_A, "B": LINE_B}


def side(name: str) -> str:
    """One whole receipt holding the header and at most the one row `name` selects."""
    line = SIDES[name]
    body = "" if line is None else line + "\n"
    return HEADER_LINE + "\n" + body


CONFLICT = "conflict"

# The 27 cells, written out. Keys are (ancestor, ours, theirs); the value is the surviving line's
# name, `None` for "the row is gone from the result", or CONFLICT. Derivations that are NOT obvious
# carry a comment naming the plan row that decides them.
TRUTH_TABLE: dict[tuple[str, str, str], str | None] = {
    ("absent", "absent", "absent"): None,
    ("absent", "absent", "A"): "A",  # 07:3127 added; take it
    ("absent", "absent", "B"): "B",
    ("absent", "A", "absent"): "A",
    ("absent", "A", "A"): "A",  # 07:3126 identical line on both sides -> union
    ("absent", "A", "B"): CONFLICT,  # add/add of two different lines -> 07:3129
    ("absent", "B", "absent"): "B",
    ("absent", "B", "A"): CONFLICT,
    ("absent", "B", "B"): "B",
    ("A", "absent", "absent"): None,  # both deleted
    ("A", "absent", "A"): None,  # 07:3128 DELETED; IT STAYS DELETED -- the graphify cell
    ("A", "absent", "B"): CONFLICT,  # delete vs modify -> 07:3129, not :3128; see the module doc
    ("A", "A", "absent"): None,  # the mirror of the graphify cell
    ("A", "A", "A"): "A",
    ("A", "A", "B"): "B",  # ours untouched, theirs modified
    ("A", "B", "absent"): CONFLICT,  # modify vs delete
    ("A", "B", "A"): "B",  # ours modified, theirs untouched
    ("A", "B", "B"): "B",  # both modified the same way -> union
    ("B", "absent", "absent"): None,
    ("B", "absent", "A"): CONFLICT,
    ("B", "absent", "B"): None,  # the graphify cell again, with B as the base line
    ("B", "A", "absent"): CONFLICT,
    ("B", "A", "A"): "A",
    ("B", "A", "B"): "A",  # ours modified, theirs untouched
    ("B", "B", "absent"): None,
    ("B", "B", "A"): "A",  # ours untouched, theirs modified
    ("B", "B", "B"): "B",
}


# ---------------------------------------------------------------------------
# The format.
# ---------------------------------------------------------------------------


def test_the_header_line_is_the_one_the_plan_prints() -> None:
    assert HEADER.render() == HEADER_LINE


def test_the_header_keys_are_the_four_the_plan_prints_in_that_order() -> None:
    assert HEADER_KEYS == ("schema", "scorer", "segmenter", "space")
    rendered = HEADER.render().removeprefix("# ")
    assert [part.split("=", 1)[0] for part in rendered.split(" ")] == list(HEADER_KEYS)


def test_the_header_schema_defaults_to_the_contract_major_and_not_the_dotted_string() -> None:
    """07:3117 prints `schema=1`, so the header carries `SCHEMA` and never `SCHEMA_STRING`."""
    default = LockHeader(scorer=1, segmenter="s@1:a", space="m@b/8/cosine/i8")
    assert default.schema == SCHEMA
    assert f"schema={SCHEMA} " in default.render()
    assert "schema=1.0" not in default.render()


def test_a_row_renders_seven_two_space_separated_columns() -> None:
    rendered = row().render()
    assert rendered.split(FIELD_SEP) == [
        "11" * 16,
        "1",
        "ok",
        "42",
        "3",
        DIGEST.hex(),
        "/c/one.pdf",
    ]


def test_write_lock_and_read_lock_round_trip_exactly() -> None:
    rows = (row(bytes.fromhex("22" * 16)), row(bytes.fromhex("11" * 16), gen=7))
    text = write_lock(HEADER, rows)
    parsed = read_lock(text)
    assert parsed.header == HEADER
    assert set(parsed.rows) == set(rows)
    assert parsed.render() == text


def test_the_file_ends_in_exactly_one_newline_and_an_empty_corpus_is_the_header_alone() -> None:
    assert write_lock(HEADER, ()) == HEADER_LINE + "\n"
    text = write_lock(HEADER, (row(),))
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_rows_are_sorted_by_doc_key_bytes_whatever_order_the_caller_supplies() -> None:
    keys = [bytes([n]) * 16 for n in (0xFF, 0x00, 0x80, 0x01)]
    text = write_lock(HEADER, [row(key) for key in keys])
    assert [line.split(FIELD_SEP)[0] for line in text.splitlines()[1:]] == [
        key.hex() for key in sorted(keys)
    ]


def test_hex_order_is_the_same_total_order_as_byte_order() -> None:
    """The lemma the streaming merge rests on: `bytes.hex()` is monotone.

    `_row_key` compares column 1 as TEXT and never decodes it, which is only sound because the hex
    alphabet `0-9a-f` is ASCII-monotone. Asserted over every byte value and over every adjacent
    pair, so a hypothetical upper-case or base32 rendering would fail here first.
    """
    values = [bytes([n]) * 16 for n in range(256)]
    assert sorted(values) == sorted(values, key=lambda raw: raw.hex())
    assert [raw.hex() for raw in sorted(values)] == sorted(raw.hex() for raw in values)


def test_a_uri_holding_spaces_survives_the_round_trip() -> None:
    """`canonical_uri`'s `file` kind is a path form and percent-encodes nothing (identity.py:82)."""
    spaced = "/home/me/my annual report  final.pdf"
    text = write_lock(HEADER, (row(uri=spaced),))
    assert read_lock(text).rows[0].uri == spaced


@pytest.mark.parametrize("hostile", ["a\nb.pdf", "a\rb.pdf", "a\tb.pdf", "a\\nb.pdf", "\\\\"])
def test_a_uri_that_could_end_its_line_early_is_escaped_and_still_round_trips(
    hostile: str,
) -> None:
    """One line per document (02-architecture.md:1168) is what the escape protects."""
    text = write_lock(HEADER, (row(uri=hostile),))
    assert len(text.splitlines()) == 2
    assert read_lock(text).rows[0].uri == hostile


def test_read_lock_normalises_crlf_before_parsing() -> None:
    """11-repo-layout.md:490-493 rule 3: every `--check` normalises CRLF before comparing."""
    text = write_lock(HEADER, (row(),))
    assert read_lock(text.replace("\n", "\r\n")) == read_lock(text)


def _imported_modules() -> frozenset[str]:
    """Every top-level module name `indexlock` imports, read from its AST.

    Over the AST and not over the source text, because the docstring names `locale`, `Clock` and
    `sqlite3` in order to say that none of them is used -- a substring check would fail on the
    explanation rather than on the code.
    """
    tree = ast.parse(inspect.getsource(indexlock))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module.split(".")[0])
    return frozenset(names)


def test_no_clock_is_read_anywhere_in_the_module() -> None:
    """*"byte-stable, with no timestamps"* -- 01-principles.md:688, 02-architecture.md:489."""
    assert _imported_modules().isdisjoint({"time", "datetime", "calendar", "zoneinfo"})
    body = inspect.getsource(indexlock).split('"""', 2)[-1]
    for banned in ("monotonic(", "perf_counter(", "now(", "time("):
        assert banned not in body, banned


def test_the_module_reads_no_locale_and_imports_neither_sqlite3_nor_importlib() -> None:
    """The sort is `bytes.__lt__`, and the receipt is text: the TID251 licence goes unused."""
    assert _imported_modules().isdisjoint({"locale", "sqlite3", "importlib", "subprocess", "os"})
    assert _imported_modules() == {
        "__future__",
        "re",
        "collections",
        "dataclasses",
        "typing",
        "omniweave_core",
    }


@pytest.mark.parametrize("status", DOC_STATUSES)
def test_every_doc_status_the_model_allows_renders_and_parses(status: str) -> None:
    text = write_lock(HEADER, (row()._replace(status=status),))
    assert read_lock(text).rows[0].status == status


def test_a_status_outside_the_closed_vocabulary_is_refused() -> None:
    """`DocRecord.status` is a four-member `Literal` (03-document-model.md:408)."""
    with pytest.raises(StoreError, match="not one of"):
        write_lock(HEADER, (row()._replace(status="probably-ok"),))


def test_a_duplicate_doc_key_is_refused_rather_than_deduplicated() -> None:
    """`doc.doc_key` is `NOT NULL UNIQUE` (`0001_init.sql:150`)."""
    with pytest.raises(StoreError, match="two rows for doc_key"):
        write_lock(HEADER, (row(gen=1), row(gen=2)))


def test_an_unsorted_receipt_is_refused_by_read_lock() -> None:
    text = HEADER_LINE + "\n" + row(bytes.fromhex("22" * 16)).render() + "\n" + LINE_A + "\n"
    with pytest.raises(StoreError, match="not sorted by doc_key bytes"):
        read_lock(text)


@pytest.mark.parametrize(
    "broken",
    [
        "not a header at all",
        "# scorer=1 schema=1 segmenter=s@1:a space=m@b/8/cosine/i8",
        "# schema=1 scorer=1 segmenter=s@1:a",
        "# schema=1 scorer=1 segmenter=s@1:a space=m@b/8/cosine/i8 extra=1",
        "# schema=one scorer=1 segmenter=s@1:a space=m@b/8/cosine/i8",
        "# schema=1 scorer=1 segmenter= space=m@b/8/cosine/i8",
    ],
)
def test_a_header_that_is_missing_reordered_or_undecodable_is_refused(broken: str) -> None:
    with pytest.raises(StoreError):
        read_lock(broken + "\n")


@pytest.mark.parametrize(
    "broken",
    [
        "11" * 16 + FIELD_SEP + "1" + FIELD_SEP + "ok",
        "ZZ" * 16 + FIELD_SEP.join(("", "1", "ok", "1", "1", DIGEST.hex(), "/c/x")),
        ("ab" * 16).upper() + FIELD_SEP.join(("", "1", "ok", "1", "1", DIGEST.hex(), "/c/x")),
        FIELD_SEP.join(("11" * 16, "x", "ok", "1", "1", DIGEST.hex(), "/c/x")),
        FIELD_SEP.join(("11" * 16, "1", "ok", "1", "1", "9c1e", "/c/x")),
        FIELD_SEP.join(("11" * 16, "1", "ok", "1", "1", DIGEST.hex(), "")),
    ],
)
def test_a_malformed_row_is_refused_and_never_padded(broken: str) -> None:
    with pytest.raises(StoreError):
        read_lock(HEADER_LINE + "\n" + broken + "\n")


def test_an_upper_case_digest_is_refused_because_one_fact_has_one_spelling() -> None:
    upper = row().render().replace(DIGEST.hex(), DIGEST.hex().upper())
    with pytest.raises(StoreError, match="lower-case hex"):
        read_lock(HEADER_LINE + "\n" + upper + "\n")


def test_a_bool_is_not_a_count() -> None:
    """`True` is an `int` and would render as `1`, so a flag in a count column is refused."""
    with pytest.raises(StoreError, match="not a non-negative int"):
        write_lock(HEADER, (row()._replace(n_blocks=True),))


# ---------------------------------------------------------------------------
# Conflict markers, and the refusal the second half of W2.7 uses.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("marker", ["<" * 7, "=" * 7, ">" * 7])
def test_has_conflict_markers_finds_each_of_the_three_the_plan_names(marker: str) -> None:
    """07:3149-3151: `ow store verify --lock` refuses `<<<<<<<`, `=======` and `>>>>>>>`."""
    assert has_conflict_markers(HEADER_LINE + "\n" + marker + " x\n")


def test_a_clean_receipt_holds_no_marker() -> None:
    assert not has_conflict_markers(write_lock(HEADER, (row(),)))


def test_read_lock_refuses_a_file_holding_conflict_markers() -> None:
    conflicted = merge_lock(side("A"), side("absent"), side("B"))
    assert not conflicted.clean
    with pytest.raises(StoreError, match="conflict markers"):
        read_lock(conflicted.text)


# ---------------------------------------------------------------------------
# The truth table. This is the specification.
# ---------------------------------------------------------------------------


def test_the_truth_table_covers_every_cell() -> None:
    """27 cells: absent / A / B in each of the three positions, with nothing skipped."""
    assert len(TRUTH_TABLE) == 27
    assert set(TRUTH_TABLE) == {
        (base, ours, theirs) for base in SIDES for ours in SIDES for theirs in SIDES
    }


@pytest.mark.parametrize(("cell", "expected"), sorted(TRUTH_TABLE.items()))
def test_the_truth_table_over_ancestor_ours_and_theirs_is_complete(
    cell: tuple[str, str, str], expected: str | None
) -> None:
    base, ours, theirs = cell
    result = merge_lock(side(base), side(ours), side(theirs))
    body = [line for line in result.text.splitlines() if not line.startswith("#")]
    if expected is CONFLICT:
        assert not result.clean
        assert result.conflicts == (KEY.hex(),)
        assert any(line.startswith("<" * CONFLICT_MARKER_LEN) for line in body)
        assert any(line.startswith("=" * CONFLICT_MARKER_LEN) for line in body)
        assert any(line.startswith(">" * CONFLICT_MARKER_LEN) for line in body)
        return
    assert result.clean, result.text
    assert body == ([] if expected is None else [SIDES[expected]])


@pytest.mark.parametrize(("cell", "expected"), sorted(TRUTH_TABLE.items()))
def test_every_clean_cell_re_reads_through_read_lock_and_is_byte_stable(
    cell: tuple[str, str, str], expected: str | None
) -> None:
    result = merge_lock(side(cell[0]), side(cell[1]), side(cell[2]))
    if expected is CONFLICT:
        pytest.skip("a conflicted file is deliberately not a readable receipt (OW-S-061)")
    assert read_lock(result.text).render() == result.text


def test_the_merge_is_symmetric_up_to_which_side_a_conflict_names() -> None:
    """Swapping ours and theirs must not change WHETHER a cell is clean, only the marker order."""
    for base, ours, theirs in TRUTH_TABLE:
        forward = merge_lock(side(base), side(ours), side(theirs))
        mirrored = merge_lock(side(base), side(theirs), side(ours))
        assert forward.clean == mirrored.clean, (base, ours, theirs)


# ---------------------------------------------------------------------------
# The four named cells, each with its citation.
# ---------------------------------------------------------------------------


def test_a_line_added_identically_on_both_sides_unions_to_one_line() -> None:
    """*"identical lines union"* -- 00-vision.md:583; 07:3126."""
    result = merge_lock(side("absent"), side("A"), side("A"))
    assert result.clean
    assert result.text == HEADER_LINE + "\n" + LINE_A + "\n"


def test_a_line_deleted_on_our_side_and_untouched_on_theirs_stays_deleted() -> None:
    """**The cell a union driver gets wrong.**

    *"a deleted line stays deleted"* -- 00-vision.md:583, restated at 01-principles.md:688,
    02-architecture.md:1168 and 16-roadmap.md:420. The recorded counter-example is graphify's merge
    driver, `_nx.compose(G_cur, G_oth)` at `graphify/cli.py:2572`: *"a pure union that loads
    `_base_path` and never uses it. A node deleted on one branch and untouched on the other comes
    back"* (07:3105-3107). A union of ours and theirs here yields the line back; the three-way rule
    yields nothing, because `base == theirs` proves their side never touched it and ours removed it.
    """
    result = merge_lock(side("A"), side("absent"), side("A"))
    assert result.clean
    assert result.text == HEADER_LINE + "\n"
    assert LINE_A not in result.text
    # And the mirror: deleted on their side, untouched on ours.
    assert merge_lock(side("A"), side("A"), side("absent")).text == HEADER_LINE + "\n"


def test_a_line_modified_differently_on_both_sides_is_a_real_conflict() -> None:
    """*"a conflicting line for one `doc_key` is a real conflict a human resolves"* -- 07:3129.

    Both sides must appear inside the markers: a driver that dropped one half would be resolving,
    which is exactly what 11-repo-layout.md:504 forbids it from doing.
    """
    third = row(gen=3).render()
    result = merge_lock(side("A"), side("B"), HEADER_LINE + "\n" + third + "\n")
    assert not result.clean
    assert result.conflicts == (KEY.hex(),)
    assert LINE_B in result.text
    assert third in result.text
    assert has_conflict_markers(result.text)


def test_deleted_on_our_side_and_modified_on_theirs_is_a_conflict_not_a_silent_answer() -> None:
    """Neither a silent delete nor a silent resurrect, and the plan decides it twice.

    07:3128 read alone (*"present in base and absent from one side | deleted; it stays deleted"*)
    would drop the line their side had just rewritten. It does not mean that: :3106 states the
    defect it answers with the scope inside the sentence -- *"A node deleted on one branch **and
    untouched on the other** comes back"* -- so :3128 governs delete-versus-unchanged, and :3129,
    *"conflicting lines for one `doc_key`"*, catches this. A delete and a rewrite are two
    incompatible claims about one `doc_key`, and each silent reading discards evidence a human
    supplied: a silent delete throws away a re-parse, a silent resurrect throws away a removal.
    """
    result = merge_lock(side("A"), side("absent"), side("B"))
    assert not result.clean
    assert result.conflicts == (KEY.hex(),)
    assert LINE_B in result.text
    assert LINE_A not in result.text  # the base's line is not resurrected into the markers either
    assert merge_lock(side("A"), side("B"), side("absent")).clean is False


def test_a_differing_header_line_is_a_real_conflict() -> None:
    """07:3130: *"`schema`, `scorer` or `space` changed"*. Merging two scorers silently IS drift."""
    other = HEADER._replace(scorer=2)
    theirs = write_lock(other, (row(),))
    result = merge_lock(side("A"), side("A"), theirs)
    assert not result.clean
    assert result.header_conflict
    assert result.conflicts == ()
    assert HEADER_LINE in result.text
    assert other.render() in result.text
    assert has_conflict_markers(result.text)


def test_an_identical_header_passes_through_once() -> None:
    result = merge_lock(side("A"), side("A"), side("A"))
    assert result.text.splitlines().count(HEADER_LINE) == 1


def test_an_empty_side_claims_nothing_including_a_header() -> None:
    """Git hands an empty `%O` for a path added on both branches."""
    result = merge_lock("", side("A"), side("A"))
    assert result.clean
    assert result.text == HEADER_LINE + "\n" + LINE_A + "\n"


# ---------------------------------------------------------------------------
# Scale: no caps, and a byte-stable result.
# ---------------------------------------------------------------------------


def test_a_clean_merge_of_two_large_disjoint_corpora_is_sorted_and_byte_stable() -> None:
    """No caps. graphify's are 50 MB / 100k nodes, *"two to three orders below"* (07:3108)."""
    ours_rows = [row(n.to_bytes(16, "big"), uri=f"/c/o{n}.pdf") for n in range(0, 4000, 2)]
    theirs_rows = [row(n.to_bytes(16, "big"), uri=f"/c/t{n}.pdf") for n in range(1, 4000, 2)]
    result = merge_lock(
        write_lock(HEADER, ()), write_lock(HEADER, ours_rows), write_lock(HEADER, theirs_rows)
    )
    assert result.clean
    assert result.text == write_lock(HEADER, [*ours_rows, *theirs_rows])
    parsed = read_lock(result.text)
    assert len(parsed.rows) == 4000
    keys = [row_.doc_key for row_ in parsed.rows]
    assert keys == sorted(keys)
    # Byte-stable: the same corpus in the other argument order is the same bytes.
    mirrored = merge_lock(
        write_lock(HEADER, ()), write_lock(HEADER, theirs_rows), write_lock(HEADER, ours_rows)
    )
    assert mirrored.text == result.text


def test_the_merge_refuses_an_unsorted_input_rather_than_dropping_its_tail() -> None:
    """A sort-merge over an unsorted stream does not fail -- it silently loses rows. So: refuse."""
    high, low = bytes.fromhex("22" * 16), bytes.fromhex("11" * 16)
    unsorted = HEADER_LINE + "\n" + row(high).render() + "\n" + row(low).render() + "\n"
    with pytest.raises(StoreError, match="cannot read an unsorted receipt"):
        merge_lock(write_lock(HEADER, ()), unsorted, write_lock(HEADER, ()))


def test_a_longer_marker_length_still_contains_the_three_strings_verify_refuses_on() -> None:
    result = merge_lock(side("A"), side("absent"), side("B"), marker_len=32)
    assert not result.clean
    assert has_conflict_markers(result.text)
    assert "<" * 32 in result.text


# ---------------------------------------------------------------------------
# Registration -- for that path only.
# ---------------------------------------------------------------------------


def test_the_gitattributes_line_is_the_one_the_plan_prints() -> None:
    """07:3141, verbatim, `-diff` included."""
    assert GITATTRIBUTES_LINE == "omniweave.index.lock merge=owlock -diff"
    assert MERGE_DRIVER_NAME == "owlock"
    assert LOCK_PATH == "omniweave.index.lock"


def test_the_two_git_config_entries_are_the_ones_the_plan_prints() -> None:
    """07:3145-3146."""
    assert git_config_argv() == (
        ("git", "config", "merge.owlock.name", "omniweave index lock sort-merge"),
        ("git", "config", "merge.owlock.driver", "ow store merge-lock %O %A %B %L %P"),
    )


def test_no_registration_form_mentions_a_glob() -> None:
    """*"a merge driver is registered for that path only"* -- 07:3112-3113, 02-architecture.md:1168.

    The driver deletes lines. A `*` in either half would point it at every text file in the tree.
    """
    forms = [GITATTRIBUTES_LINE, *(" ".join(argv) for argv in git_config_argv())]
    for form in forms:
        assert "*" not in form.replace("%O %A %B %L %P", ""), form
        assert "?" not in form
        assert "[" not in form
    assert GITATTRIBUTES_LINE.split(" ")[0] == LOCK_PATH


def test_the_documented_scope_is_the_literal_filename_and_never_a_glob() -> None:
    """The docstring is part of the contract: `ow store git-install` reads it before it runs."""
    doc = indexlock.__doc__ or ""
    assert "for that path only" in doc
    assert "omniweave.index.lock" in doc
    assert "-diff" in doc
    assert "binary" in doc  # the docstring says why it is `-diff` and NOT `binary`


def test_a_lock_file_round_trips_through_its_own_render() -> None:
    parsed = read_lock(write_lock(HEADER, (row(),)))
    assert isinstance(parsed, LockFile)
    assert read_lock(parsed.render()) == parsed
