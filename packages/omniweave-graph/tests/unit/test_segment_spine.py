"""`derive.segment.spine`'s rules, one test each, and the invariants every output must hold.

06-structure-extraction.md section 3.2 is the specification; the readings the plan left open are
`spine.py`'s module docstring, D662.
"""

from __future__ import annotations

import hashlib
from typing import TypeVar

import pytest
from omniweave_core import limits
from omniweave_graph.segment import spine
from omniweave_graph.segment.spine import Block, Grid, Params, Spine, segment
from omniweave_graph.tokens import TOKENIZER_ID, count_tokens

T = TypeVar("T")


def prose(
    cite: str, tokens: int, *, sec: str = "/", layer: str = "body", kind: str = "paragraph"
) -> Block:
    return Block(cite=cite, kind=kind, layer=layer, sec=sec, text="x" * (4 * tokens))


def table(cite: str, rows: int, cols: int, *, header: int = 1, tokens: int = 1) -> list[Block]:
    """A `table` block and its cells in row-major order, each cell `tokens` tokens."""
    out = [Block(cite=cite, kind="table", grid=Grid(rows, cols, header))]
    out += [
        Block(
            cite=f"{cite}.{r}.{c}", kind="table_cell", text="y" * (4 * tokens), table=cite, r=r, c=c
        )
        for r in range(rows)
        for c in range(cols)
    ]
    return out


def cites(result: Spine) -> list[tuple[str, ...]]:
    return [s.blocks for s in result.segments]


# ---------------------------------------------------------------------------
# the numbers
# ---------------------------------------------------------------------------


def test_the_ceilings_equal_the_hosts() -> None:
    """The package may not import `omniweave_core.limits`; this holds the copies equal."""
    assert spine.MAX_SEGMENT_TOKENS == limits.MAX_SEGMENT_TOKENS
    assert spine.MAX_SEGMENT_BLOCKS == limits.MAX_SEGMENT_BLOCKS


def test_the_count_is_utf8_bytes_over_four_rounded_up() -> None:
    assert TOKENIZER_ID == "ow.bytes4/1"
    assert count_tokens("") == 0
    assert count_tokens("abcd") == 1
    assert count_tokens("abcde") == 2
    assert count_tokens("é") == 1  # two bytes
    assert count_tokens("中文") == 2  # six bytes


def test_params_refuse_a_value_above_its_ceiling_or_a_target_above_the_max() -> None:
    with pytest.raises(ValueError, match="max_blocks = 513"):
        Params(max_blocks=513)
    with pytest.raises(ValueError, match="target_tokens must not exceed"):
        Params(max_tokens=1000)
    with pytest.raises(ValueError, match="positive integer"):
        Params(table_tokens=0)
    assert Params(target_tokens=300, max_tokens=600, table_tokens=200).max_tokens == 600


# ---------------------------------------------------------------------------
# the five emit rules
# ---------------------------------------------------------------------------


def test_a_segment_is_emitted_once_it_reaches_the_target() -> None:
    result = segment([prose(f"b{i}", 400) for i in range(7)], {})
    assert cites(result) == [("b0", "b1", "b2"), ("b3", "b4", "b5"), ("b6",)]
    assert [s.n_tokens for s in result.segments] == [1200, 1200, 400]


def test_a_block_that_would_cross_the_max_starts_the_next_segment() -> None:
    result = segment([prose("a", 1000), prose("b", 1100), prose("c", 10)], {})
    assert cites(result) == [("a",), ("b", "c")]
    assert all(s.n_tokens <= spine.MAX_SEGMENT_TOKENS for s in result.segments)


def test_a_segment_holds_at_most_511_blocks() -> None:
    result = segment([prose(f"b{i}", 1) for i in range(600)], {})
    assert [len(s.blocks) for s in result.segments] == [511, 89]


def test_a_heading_change_ends_the_segment_and_names_its_path() -> None:
    sections = {"/0001": "Part II", "/0001/0002": "7. Risk Factors"}
    blocks = [
        prose("h1", 2, sec="/0001", kind="heading"),
        prose("p1", 5, sec="/0001"),
        prose("h2", 3, sec="/0001/0002", kind="heading"),
        prose("p2", 5, sec="/0001/0002"),
        prose("p3", 5, sec="/0001"),
    ]
    result = segment(blocks, sections)
    assert cites(result) == [("h1", "p1"), ("h2", "p2"), ("p3",)]
    assert [s.heading_path for s in result.segments] == [
        ("Part II",),
        ("Part II", "7. Risk Factors"),
        ("Part II",),
    ]


def test_a_table_starts_a_segment_and_text_after_it_starts_another() -> None:
    blocks = [prose("p1", 5), *table("t", 3, 2), prose("p2", 5)]
    result = segment(blocks, {})
    assert cites(result)[0] == ("p1",)
    assert cites(result)[-1] == ("p2",)
    assert [s.atom for s in result.segments] == [None, "table", None]


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------


def test_a_table_is_packed_in_whole_rows_with_the_header_charged_to_every_segment() -> None:
    """10 tokens of header; rows of 100 tokens; the 400 ceiling holds 3 rows beside the header."""
    blocks = table("t", 9, 1, header=1, tokens=10)
    blocks = [blocks[0], blocks[1]] + [
        b if b.r == 0 else Block(**{**_fields(b), "text": "z" * 400}) for b in blocks[2:]
    ]
    result = segment(blocks, {})
    assert cites(result) == [
        ("t.0.0", "t.1.0", "t.2.0", "t.3.0"),
        ("t.4.0", "t.5.0", "t.6.0"),
        ("t.7.0", "t.8.0"),
    ]
    assert [s.n_tokens for s in result.segments] == [310, 300, 200]
    assert {s.atom for s in result.segments} == {"table"}


def test_every_cell_is_a_member_once_and_the_table_block_is_none() -> None:
    result = segment(table("t", 50, 6, header=2, tokens=3), {})
    members = [c for s in result.segments for c in s.blocks]
    assert len(members) == len(set(members)) == 300
    assert "t" not in members


def test_a_table_too_long_for_32_segments_at_400_grows_its_segments_instead() -> None:
    """999 rows of ten 3-token cells is 30,000 tokens: 84 Segments at 400, 34 at the grown
    ceil(30,000 / 32) = 938, and 20 at 2,048, where the block cap binds first. No Diag."""
    result = segment(table("t", 1000, 10, header=1, tokens=3), {})
    assert len(result.segments) == 20
    assert not result.notices
    assert all(s.synopsis_of is None for s in result.segments)
    assert all(30 + s.n_tokens <= spine.MAX_SEGMENT_TOKENS for s in result.segments)
    assert sum(len(s.blocks) for s in result.segments) == 10_000


def test_the_first_growth_is_to_ceil_tokens_over_32_not_straight_to_the_max() -> None:
    """13,000 one-token rows: 33 Segments of 400 at the table ceiling, 32 of 407 at
    ceil(13,000 / 32) -- and 26 of 511 had it jumped to the max, which is not what was asked."""
    result = segment(table("t", 13_000, 1, header=0), {})
    assert len(result.segments) == 32
    assert max(s.n_tokens for s in result.segments) == 407
    assert not result.notices


def test_a_table_that_overflows_at_the_grown_ceiling_is_packed_again_at_the_max() -> None:
    """33 rows of 390 tokens and a 1-token header: ceil(12,871 / 32) = 403 holds one row a
    Segment, 33 > 32, so the table is packed again at 2,048, which holds five."""
    blocks = table("t", 34, 1, header=1, tokens=1)
    blocks = [blocks[0], blocks[1]] + [
        Block(**{**_fields(b), "text": "z" * 1560}) for b in blocks[2:]
    ]
    result = segment(blocks, {})
    assert not result.notices
    assert [len(s.blocks) for s in result.segments] == [6, 5, 5, 5, 5, 5, 3]


def test_a_table_the_block_cap_holds_above_32_keeps_every_row_and_says_so() -> None:
    """20,000 one-token cells -- at the cell ceiling, not past it -- need 40 Segments of 51 rows
    at the 511-block cap: every cell stays a member, and the overflow is a Diag, not a synopsis."""
    result = segment(table("t", 2000, 10, header=1), {})
    assert len(result.segments) == 40
    assert all(s.synopsis_of is None for s in result.segments)
    assert sum(len(s.blocks) for s in result.segments) == 20_000
    assert [(n.code, n.cite, n.detail) for n in result.notices] == [
        ("OW_RESOURCE_LIMIT", "t", {"limit": "TABLE_MAX_SEGMENTS", "segments": 40})
    ]


def test_a_repacked_table_keeps_the_second_packings_notices_only() -> None:
    """30 rows of 600 cells: each row is cut at 511 in both packings, so a row's split notice must
    appear once, not once per packing."""
    result = segment(table("t", 30, 600, header=0), {})
    split = [n for n in result.notices if n.detail["limit"] == "MAX_SEGMENT_BLOCKS"]
    assert len(split) == 30
    assert [n.detail["limit"] for n in result.notices[-1:]] == ["TABLE_MAX_SEGMENTS"]


def test_a_row_wider_than_a_segment_is_split_and_disclosed() -> None:
    result = segment(table("t", 2, 600, header=0), {})
    assert [len(s.blocks) for s in result.segments] == [511, 89, 511, 89]
    limits_named = [n.detail["limit"] for n in result.notices]
    assert limits_named == ["MAX_SEGMENT_BLOCKS", "MAX_SEGMENT_BLOCKS"]


def test_a_table_past_the_cell_ceiling_is_one_synopsis_segment() -> None:
    result = segment(table("t", 2001, 10, header=1), {})
    assert len(result.segments) == 1
    synopsis = result.segments[0]
    assert synopsis.synopsis_of == "t"
    assert synopsis.atom == "table"
    assert synopsis.blocks[:10] == tuple(f"t.0.{c}" for c in range(10))
    assert len(synopsis.blocks) == 10 * 9
    [notice] = result.notices
    assert notice.code == "OW_TABLE_SYNOPSIS_ONLY"
    assert notice.detail["limit"] == "TABLE_SYNOPSIS_CELLS"
    assert notice.detail["cells"] == 20_010
    assert notice.detail["sampled_rows"] == [1 + i * 2000 // 8 for i in range(8)]


def test_a_synopsis_stops_sampling_before_the_max() -> None:
    """Rows of 250 tokens: the header and seven sampled rows are 2,000 tokens, an eighth would be
    2,250, so the synopsis carries seven and says which."""
    result = segment(table("t", 2001, 10, header=1, tokens=25), {})
    [synopsis] = result.segments
    assert synopsis.n_tokens == 2000
    assert result.notices[0].detail["sampled_rows"] == [1 + i * 2000 // 8 for i in range(7)]


# ---------------------------------------------------------------------------
# refusals, layers, containers
# ---------------------------------------------------------------------------


def test_a_block_above_the_max_is_its_own_segment_with_a_resource_limit_diag() -> None:
    result = segment([prose("a", 10), prose("big", 3000), prose("b", 10)], {})
    assert cites(result) == [("a",), ("big",), ("b",)]
    [notice] = result.notices
    assert (notice.code, notice.cite, notice.detail["limit"]) == (
        "OW_RESOURCE_LIMIT",
        "big",
        "MAX_SEGMENT_TOKENS",
    )


def test_layers_are_segmented_apart_and_body_is_numbered_first() -> None:
    blocks = [
        prose("hdr1", 2, layer="furniture"),
        prose("p1", 5),
        prose("fn1", 5, layer="note"),
        prose("p2", 5),
        prose("hdr2", 2, layer="furniture"),
    ]
    result = segment(blocks, {})
    assert cites(result) == [("p1", "p2"), ("hdr1", "hdr2"), ("fn1",)]
    assert [s.layer for s in result.segments] == ["body", "furniture", "note"]


def test_a_container_is_no_segments_member() -> None:
    blocks = [
        Block(cite="list", kind="list"),
        prose("li1", 3, kind="list_item"),
        Block(cite="pic", kind="picture"),
    ]
    assert cites(segment(blocks, {})) == [("li1",)]


def test_a_cell_outside_its_tables_run_is_segmented_as_prose() -> None:
    stray = Block(cite="c9", kind="table_cell", text="abcd", table="gone", r=0, c=0)
    result = segment([prose("p", 3), stray], {})
    assert cites(result) == [("p", "c9")]


# ---------------------------------------------------------------------------
# the invariants, over generated documents
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(40))
def test_every_output_is_zero_overlap_ordered_and_bounded(seed: int) -> None:
    rng = _Draw(seed)
    blocks: list[Block] = []
    secs = ["/", "/0001", "/0001/0001", "/0002"]
    n = 0
    while len(blocks) < 400:
        n += 1
        if rng.below(100) < 8:
            blocks += table(
                f"t{n}",
                1 + rng.below(40),
                1 + rng.below(8),
                header=rng.below(3),
                tokens=1 + rng.below(30),
            )
        else:
            layer = rng.choice(["body"] * 6 + ["furniture", "note"])
            blocks.append(
                prose(
                    f"b{n}",
                    rng.choice([0, 3, 40, 300, 900, 2500]),
                    sec=rng.choice(secs),
                    layer=layer,
                )
            )
    result = segment(blocks, {"/0001": "One", "/0002": "Two"})
    members = [c for s in result.segments for c in s.blocks]
    assert len(members) == len(set(members)), "a block is in two Segments"
    text_blocks = [b.cite for b in blocks if b.text is not None]
    synopses = {s.synopsis_of for s in result.segments if s.synopsis_of}
    assert set(members) <= set(text_blocks)
    missing = set(text_blocks) - set(members)
    assert all(b.table in synopses for b in blocks if b.cite in missing), "a block lost"
    order = {b.cite: i for i, b in enumerate(blocks)}
    for s in result.segments:
        assert len(s.blocks) <= spine.MAX_SEGMENT_BLOCKS - 1
        assert [order[c] for c in s.blocks] == sorted(order[c] for c in s.blocks)
        if s.n_tokens > spine.MAX_SEGMENT_TOKENS:
            assert any(n.cite in s.blocks and n.code == "OW_RESOURCE_LIMIT" for n in result.notices)
    assert segment(blocks, {"/0001": "One", "/0002": "Two"}) == result, "not deterministic"


class _Draw:
    """Draws keyed by blake2b over `(seed, n)`: `random` is banned in this workspace."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.n = 0

    def below(self, bound: int) -> int:
        self.n += 1
        digest = hashlib.blake2b(f"{self.seed}:{self.n}".encode(), digest_size=8).digest()
        return int.from_bytes(digest, "big") % bound

    def choice(self, options: list[T]) -> T:
        return options[self.below(len(options))]


def _fields(block: Block) -> dict[str, object]:
    return {name: getattr(block, name) for name in Block.__slots__}
