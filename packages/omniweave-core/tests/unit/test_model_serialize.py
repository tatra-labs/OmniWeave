"""The serialized view and its back-map agree, character for character, in all five formats.

Two assertions here are the work item and everything else supports them
(03-document-model.md section 16.1, section 16.5 rule 3, 16-roadmap.md:421 W2.8):

**Round-trip fidelity of the map.** For every block of a generated scope and every one of the five
formats, the concatenation of the `TextSpan`s the map hands back for that block reproduces the
block's `text` exactly -- nothing dropped, nothing duplicated, nothing reordered -- each interval's
view slice equals its text slice (or is a single source character rendered as a substitution), and
`block_at()` at every offset inside a block's interval returns that block.

**Totality.** For every offset of the output, exactly one of `block_at()` and `is_synthetic()`
answers: never neither, never both. That is section 16.5's rule 3 ("There is no third case",
03:2967-2969) and conformance property P31, and it is the assertion a hand-written serializer
silently fails on whitespace and separators -- which is why it is asserted over the WHOLE output
length rather than at sampled offsets.

Both are property tests over a generated scope, not one hand-written example. The generator is a
blake2b keystream, never `random`: this repo bans `random` outright ("Sampling is blake2b.
Determinism is a gate, not a habit.", 11-repo-layout.md section 8.1), and a projection whose test
fixtures were not reproducible could not assert projection-law rule 1 (two calls at one `gen` are
byte-identical, 03:2962).

**The deliberate absence.** W2.8's basis is "five formats, one `SpanMap` each. There is deliberately
no text-only serializer: if you have the text you have the map" (16-roadmap.md:421). An absence
cannot be tested by using it, so it is tested structurally: the module's public callables are
enumerated from its own AST and there must be exactly one, returning a two-element tuple.

Specified in 03-document-model.md sections 16.1, 16.2 and 16.5, section 17 P31, and section 5
(`layers`); 16-roadmap.md section 5 W2.8.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import itertools
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from omniweave_core.errors import PolicyRefusal, ResourceLimit, UsageError
from omniweave_core.limits import MAX_VIEW_BYTES
from omniweave_core.model.block import Block, BlockId, CellPos, Mark
from omniweave_core.model.enums import Kind, Layer, Method, Quote, TableKind, Trust
from omniweave_core.model.serialize import (
    FORMATS,
    SERIALIZER_VERSION,
    ArraySpanMap,
    TableFacts,
    ViewScope,
    serialize,
)
from omniweave_core.model.spans import (
    SERIALIZER_CAPS,
    OriginNone,
    RenderSpan,
    SpanMap,
    TextSpan,
)

#: The MODULE, not the function. `omniweave_core.model.serialize` names both -- the submodule and
#: the function the flat re-export surface binds over it (02:248) -- and attribute lookup gives the
#: function, which is what a consumer wants and what would silently make `monkeypatch.setattr`
#: below patch an attribute of a function object instead of a module global. `sys.modules` is the
#: unambiguous spelling, and `importlib.import_module` is banned outside `host/`.
mod = sys.modules["omniweave_core.model.serialize"]

DOC = "03-document-model.md"

#: How many generated scopes the two property tests run over. Each one is serialized in all five
#: formats and every offset of every output is checked, so this is 5 x 32 whole-output sweeps.
SCOPES = 32

BODY = frozenset({Layer.BODY})
BODY_AND_NOTE = frozenset({Layer.BODY, Layer.NOTE})


# ---------------------------------------------------------------------------
# The generator. blake2b, never `random`.
# ---------------------------------------------------------------------------


class Keystream:
    """A reproducible byte source keyed by one seed. The whole fixture corpus is a function of it,
    so a failure is re-runnable by its seed and a green run is not luck."""

    def __init__(self, seed: int) -> None:
        self._seed = seed.to_bytes(8, "big")
        self._counter = itertools.count()
        self._buf = b""

    def byte(self) -> int:
        if not self._buf:
            block = next(self._counter).to_bytes(8, "big")
            self._buf = hashlib.blake2b(self._seed + block, digest_size=32).digest()
        head, self._buf = self._buf[0], self._buf[1:]
        return head

    def below(self, n: int) -> int:
        return self.byte() % n

    def pick(self, options: tuple[object, ...]) -> object:
        return options[self.below(len(options))]

    def flip(self) -> bool:
        return self.byte() % 2 == 0


#: Words with characters that make the formats disagree: `&`, `<` and `>` force HTML escaping, `|`
#: forces a pipe-table escape, a newline forces the cell join, and a non-ASCII character makes the
#: byte budget and the character budget different numbers.
WORDS = ("alpha", "beta&gamma", "a<b>c", "pipe|split", "naiveé", "line\nbreak", "delta")
MARK_KINDS = ("bold", "italic", "code", "strike", "underline", "lang", "raw_style")


def _block(
    ident: int,
    kind: Kind,
    *,
    text: str | None = None,
    parent: int | None = None,
    ord_: int = 0,
    layer: Layer = Layer.BODY,
    marks: tuple[Mark, ...] = (),
) -> Block:
    """One `Block` with every host-minted field filled plausibly and nothing that varies per run."""
    return Block(
        id=BlockId(ident),
        addr=f"p0/{ident}",
        cite=f"d1#{ident}",
        doc_ord=1,
        gen=1,
        page=0,
        parent=None if parent is None else BlockId(parent),
        ord=ord_,
        kind=kind,
        raw_kind=None,
        layer=layer,
        label=None,
        text=text,
        content_digest=bytes(32),
        layout_digest=None,
        revision=1,
        quad=None,
        origin=OriginNone(),
        span=None,
        producer_id=1,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM,
        marks=marks,
    )


class ScopeBuilder:
    """Assembles one generated scope: blocks, the four satellites, and the ids to keep."""

    def __init__(self, ks: Keystream) -> None:
        self.ks = ks
        self.ids = itertools.count(1)
        self.blocks: list[Block] = []
        self.payloads: dict[BlockId, dict[str, object]] = {}
        self.tables: dict[BlockId, TableFacts] = {}
        self.cells: dict[BlockId, CellPos] = {}
        self.continues: dict[BlockId, BlockId] = {}
        self.paths: dict[BlockId, tuple[str, ...]] = {}

    def add(self, kind: Kind, **kw: object) -> Block:
        block = _block(next(self.ids), kind, **kw)  # type: ignore[arg-type]
        self.blocks.append(block)
        return block

    def sentence(self) -> str:
        return " ".join(str(self.ks.pick(WORDS)) for _ in range(1 + self.ks.below(3)))

    def marks_for(self, text: str) -> tuple[Mark, ...]:
        """Zero to three marks, deliberately allowed to overlap and to be zero-width.

        Overlap is the point: 03:2849-2851 promises a well-nested render from an arbitrarily
        overlapping mark set by splitting runs, and marker's one `formats` list per span cannot
        express it at all (03:368-370).
        """
        out: list[Mark] = []
        for _ in range(self.ks.below(4)):
            a = self.ks.below(len(text) + 1)
            b = min(len(text), a + self.ks.below(6))
            kind = str(self.ks.pick(MARK_KINDS))
            value: object | None = {"bcp47": "de-CH"} if kind == "lang" else None
            out.append(Mark(a, b, kind, value))
        if self.ks.flip() and text:
            out.append(Mark(1, 1, "anchor", {"name": "here", "akind": "heading"}))
        if self.ks.flip():
            out.append(Mark(0, len(text), "link", {"target": "https://x/y", "kind": "external"}))
        return tuple(out)

    def paragraph(self, parent: int, ord_: int) -> Block:
        text = self.sentence()
        return self.add(
            Kind.PARAGRAPH, text=text, parent=parent, ord_=ord_, marks=self.marks_for(text)
        )

    def heading(self, parent: int, ord_: int) -> Block:
        block = self.add(Kind.HEADING, text=self.sentence(), parent=parent, ord_=ord_)
        self.payloads[block.id] = {"level": 1 + self.ks.below(4)}
        self.paths[block.id] = ("Chapter", "Section")
        return block

    def listing(self, parent: int, ord_: int) -> Block:
        block = self.add(Kind.LIST, parent=parent, ord_=ord_)
        ordered = self.ks.flip()
        self.payloads[block.id] = {"ordered": ordered, "start": 1 + self.ks.below(3)}
        for i in range(1 + self.ks.below(3)):
            item = self.add(Kind.LIST_ITEM, text=self.sentence(), parent=int(block.id), ord_=i)
            if self.ks.flip():
                self.paragraph(int(item.id), 0)
        return block

    def quote(self, parent: int, ord_: int) -> Block:
        block = self.add(Kind.BLOCKQUOTE, parent=parent, ord_=ord_)
        for i in range(1 + self.ks.below(2)):
            self.paragraph(int(block.id), i)
        return block

    def code(self, parent: int, ord_: int) -> Block:
        block = self.add(Kind.CODE, text="def f():\n    return 1\n", parent=parent, ord_=ord_)
        self.payloads[block.id] = {"lang": "python", "fenced": True}
        return block

    def joined_pair(self, parent: int, ord_: int) -> Block:
        """Two paragraphs with an outbound `rel(continues)` -- step 4's JOIN (03:2836-2841)."""
        first = self.paragraph(parent, ord_)
        second = self.paragraph(parent, ord_ + 1)
        self.continues[first.id] = second.id
        return second

    def table(self, parent: int, ord_: int, *, kind: TableKind) -> Block:
        block = self.add(Kind.TABLE, parent=parent, ord_=ord_)
        rows, cols = 2 + self.ks.below(2), 2 + self.ks.below(2)
        header_rows = self.ks.below(2)
        self.tables[block.id] = TableFacts(kind=kind, header_rows=header_rows, header_cols=0)
        span_row = self.ks.below(rows)
        ordinal = 0
        for r in range(rows):
            c = 0
            while c < cols:
                wide = 2 if (r == span_row and c == 0 and cols > 2 and self.ks.flip()) else 1
                text = "" if self.ks.below(5) == 0 else self.sentence()
                cell = self.add(Kind.TABLE_CELL, text=text, parent=int(block.id), ord_=ordinal)
                self.cells[cell.id] = CellPos(r=r, c=c, row_span=1, col_span=wide)
                ordinal += 1
                c += wide
        return block

    def build(self) -> ViewScope:
        root = self.add(Kind.DOCUMENT)
        parent, ordinal = int(root.id), 0
        # Always present, because the work item names them: headings, paragraphs, a table, a
        # footnote and an empty block.
        self.heading(parent, ordinal)
        ordinal += 1
        self.paragraph(parent, ordinal)
        ordinal += 1
        self.add(Kind.PARAGRAPH, text="", parent=parent, ord_=ordinal)
        ordinal += 1
        self.table(parent, ordinal, kind=TableKind.DATA)
        ordinal += 1
        for maker in self._extras():
            maker(parent, ordinal)
            ordinal += 2
        note = self.add(
            Kind.FOOTNOTE, text=self.sentence(), parent=None, ord_=ordinal, layer=Layer.NOTE
        )
        self.paths[note.id] = ("Notes",)
        return ViewScope(
            blocks=tuple(self.blocks),
            kind="document",
            corpus_id="fixtures",
            gen=1,
            payloads=self.payloads,
            tables=self.tables,
            cells=self.cells,
            continues=self.continues,
            heading_paths=self.paths,
        )

    def _extras(self) -> tuple[object, ...]:
        pool = (
            self.listing,
            self.quote,
            self.code,
            self.joined_pair,
            self.heading,
            lambda p, o: self.table(p, o, kind=TableKind.LAYOUT),
        )
        return tuple(pool[self.ks.below(len(pool))] for _ in range(2 + self.ks.below(3)))


def fixture_scope(seed: int) -> ViewScope:
    return ScopeBuilder(Keystream(seed)).build()


TINY = fixture_scope(0)


# ---------------------------------------------------------------------------
# Reading the map back through nothing but its Protocol.
# ---------------------------------------------------------------------------


def owned_runs(view: str, smap: SpanMap) -> list[tuple[int, int, int, TextSpan]]:
    """Every maximal run of offsets that `block_at` answers identically, as `(a, b, block, span)`.

    Recovered by probing `block_at` at every offset rather than by reading the map's arrays: a test
    that walked `ArraySpanMap.starts` would assert the builder against itself, and the property
    being asserted is about the four Protocol methods any backend must satisfy.
    """
    runs: list[list[object]] = []
    previous: object = object()
    for i in range(len(view)):
        got = smap.block_at(i)
        if got != previous:
            runs.append([i, i + 1, got])
            previous = got
        else:
            runs[-1][1] = i + 1
    return [
        (int(a), int(b), int(got[0]), got[1])  # type: ignore[index]
        for a, b, got in runs
        if got is not None
    ]


def _substitutions() -> dict[str, frozenset[str]]:
    """Every one-character-to-many substitution any of the five formats may make.

    Read off the module's own `*_ESCAPE` tables rather than retyped, because the property below is
    "the view slice is the text slice with that format's substitutions applied", and a second copy
    of the tables would let the test agree with a typo. `&` is `&amp;` in HTML, a newline is a
    space in an `md` cell and `<br>` in a `gfm` one, a `|` inside a pipe cell is backslashed.
    """
    out: dict[str, set[str]] = {}
    for name, table in vars(mod).items():
        if not name.endswith("_ESCAPE") or not isinstance(table, Mapping):
            continue
        for char, sub in table.items():
            if isinstance(char, str) and isinstance(sub, str):
                out.setdefault(char, set()).add(sub)
    return {char: frozenset(subs) for char, subs in out.items()}


SUBSTITUTIONS = _substitutions()


def renders_as(source: str, rendered: str) -> bool:
    """Whether `rendered` is `source` with each character kept or replaced by a declared substitute.

    This is the exact statement the round-trip property needs and nothing weaker: a length
    comparison cannot tell a one-for-one substitution (a newline as a space) from a misaligned
    span, and an equality comparison cannot allow a legitimate `&amp;`. Backtracking, because a
    substitute may share a prefix with the character it replaces; one interval is short, so the
    search is trivial.
    """

    def walk(i: int, j: int) -> bool:
        if i == len(source):
            return j == len(rendered)
        char = source[i]
        if rendered.startswith(char, j) and walk(i + 1, j + 1):
            return True
        return any(
            rendered.startswith(sub, j) and walk(i + 1, j + len(sub))
            for sub in SUBSTITUTIONS.get(char, ())
        )

    return walk(0, 0)


# ---------------------------------------------------------------------------
# 1. Plan transcription: the signature, the formats, the view id.
# ---------------------------------------------------------------------------


def test_the_call_is_the_one_the_plans_diagram_fixes(plan) -> None:
    """03:32's diagram and 03:2809's `def` line must both be satisfied by the same function."""
    plan.require()
    assert plan.grep(
        r'serialize\(scope, "md"\|"gfm"\|"html"\|"text"\|"otsl"\) -> \(str, SpanMap\)',
        documents=[DOC],
    )
    signature = plan.grep(r"^def serialize\(scope: \"ViewScope\", fmt: Literal", documents=[DOC])
    assert len(signature) == 1, "03 section 16.1 declares serialize() exactly once"


def test_the_five_formats_are_serializer_caps_own_five() -> None:
    """A sixth format would have to be added to `SERIALIZER_CAPS` first, which is the table that
    decides citability (03:2865-2867). `FORMATS` is read off it rather than retyped."""
    assert FORMATS == ("md", "gfm", "html", "text", "otsl")
    assert set(FORMATS) == set(SERIALIZER_CAPS)


def test_the_view_id_is_the_plans_three_part_shape(plan) -> None:
    plan.require()
    assert plan.grep(
        r'`view_id = "<fmt>/<serializer_version>/<options_digest\[:4\]>"`', documents=[DOC]
    )
    for fmt in FORMATS:
        _, smap = serialize(TINY, fmt)
        assert re.fullmatch(rf"{fmt}/{SERIALIZER_VERSION}/[0-9a-f]{{4}}", smap.view_id)


def test_the_returned_map_satisfies_the_spanmap_protocol() -> None:
    """`SpanMap` is a `runtime_checkable` Protocol in `spans.py` and is not redeclared here: one
    name, one home (INV-21). This asserts the concrete map is an instance of the declared one."""
    _, smap = serialize(TINY, "md")
    assert isinstance(smap, ArraySpanMap)
    assert isinstance(smap, SpanMap)


# ---------------------------------------------------------------------------
# 2. The deliberate absence: no entry point returns only `str`.
# ---------------------------------------------------------------------------


def test_no_entry_point_returns_the_text_without_the_map() -> None:
    """W2.8's stated basis (16-roadmap.md:421) is an ABSENCE, so it is asserted structurally.

    Every public callable in the module is enumerated from the module's own AST -- there must be
    exactly one, `serialize`, and its return annotation must be a two-element tuple. A helper added
    later that returned a bare `str` would be a way to quote a serialized view without ever seeing
    which regions of it are synthetic, which is the one thing this design refuses.
    """
    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    public = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and not node.name.startswith("_")
    ]
    assert [node.name for node in public] == ["serialize"]
    returns = public[0].returns
    assert isinstance(returns, ast.Subscript), "serialize must be annotated as returning a tuple"
    assert ast.unparse(returns.value) == "tuple"
    assert len(returns.slice.elts) == 2  # type: ignore[attr-defined]
    assert ast.unparse(returns.slice.elts[0]) == "str"  # type: ignore[attr-defined]
    # And no method anywhere in the module hands back a rendered string on its own.
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.returns is not None:
            rendered = ast.unparse(node.returns)
            assert not (rendered == "str" and node.name.startswith(("to_", "render", "as_"))), (
                f"{node.name} returns a bare str; W2.8 forbids a text-only serializer"
            )


def test_no_model_class_grew_an_html_or_markdown_field() -> None:
    """02:248 and 03:2778: a projection is a function, never a field, and a serializer's output is
    never cached onto a model object. Asserted over this module's own classes, since it is the one
    that could most plausibly have done it."""
    banned = {"html", "markdown", "md"}
    for name in ("ViewScope", "TableFacts", "ArraySpanMap"):
        fields = set(getattr(mod, name).__dataclass_fields__)
        assert not (fields & banned), f"{name} carries a rendered-view field"


# ---------------------------------------------------------------------------
# 3. THE FIRST LOAD-BEARING PROPERTY -- round-trip fidelity of the map.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("seed", range(SCOPES))
def test_every_blocks_own_text_is_recoverable_through_the_map(seed, fmt) -> None:
    """The map's `TextSpan`s reproduce every rendered block's `text` exactly, and each interval's
    view slice is that text slice or a single character's substitution.

    Three failures this catches and nothing else does: a run-splitting walk that drops the last run
    of a marked block (the text no longer reassembles), an escaping path that keeps a
    length-preserving span across a multi-character substitution (the slices stop matching), and an
    emitter that attributes a separator to the block before it (the reassembly gains characters the
    block never said).
    """
    scope = fixture_scope(seed)
    view, smap = serialize(scope, fmt, layers=BODY_AND_NOTE)
    runs = owned_runs(view, smap)
    by_block: dict[int, list[tuple[int, int, TextSpan]]] = {}
    for a, b, owner, span in runs:
        by_block.setdefault(owner, []).append((a, b, span))
    for block in scope.blocks:
        if not block.text:
            continue
        mine = by_block.get(int(block.id), [])
        recovered = "".join(block.text[span.a : span.b] for _a, _b, span in mine)
        assert recovered == block.text, f"block {int(block.id)} did not reassemble in {fmt}"
        for a, b, span in mine:
            assert renders_as(block.text[span.a : span.b], view[a:b]), (
                f"interval [{a},{b}) of block {int(block.id)} renders "
                f"{block.text[span.a : span.b]!r} as {view[a:b]!r} in {fmt}"
            )
            if b - a != span.b - span.a:
                assert span.b - span.a == 1, (
                    f"interval [{a},{b}) of block {int(block.id)} claims "
                    f"{span.b - span.a} source characters in {b - a} view characters"
                )


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("seed", range(SCOPES))
def test_block_at_agrees_with_offsets_of_at_every_offset_inside_a_block(seed, fmt) -> None:
    """`offsets_of(b)` brackets every offset `block_at` attributes to `b`, and every offset inside
    one of `b`'s intervals answers `b` -- not a neighbour, and not `None`."""
    scope = fixture_scope(seed)
    view, smap = serialize(scope, fmt, layers=BODY_AND_NOTE)
    runs = owned_runs(view, smap)
    for a, b, owner, span in runs:
        first, end = smap.offsets_of(owner)
        assert first <= a < b <= end, f"offsets_of({owner}) does not bracket [{a},{b}) in {fmt}"
        for i in range(a, b):
            assert smap.block_at(i) == (owner, span)
    for block in scope.blocks:
        if block.layer in BODY_AND_NOTE and not block.tombstoned:
            first, end = smap.offsets_of(int(block.id))
            assert 0 <= first <= end <= len(view)


# ---------------------------------------------------------------------------
# 4. THE SECOND LOAD-BEARING PROPERTY -- every offset is owned or synthetic, never both.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
@pytest.mark.parametrize("seed", range(SCOPES))
def test_every_offset_of_the_output_is_owned_or_synthetic_and_never_both(seed, fmt) -> None:
    """Section 16.5 rule 3 and conformance property P31, over the WHOLE output length.

    "Every character of `P(S)` either lifts to exactly one `(BlockId, TextSpan)` through the
    `SpanMap`, or is marked synthetic in that map. There is no third case" (03:2967-2969). The
    conformance property the plan writes is the `or`; this asserts the exclusive `or`, because a
    map that answered both would let a caller take a quote off a heading marker and call it the
    heading's own words.
    """
    scope = fixture_scope(seed)
    view, smap = serialize(scope, fmt, layers=BODY_AND_NOTE)
    assert len(view) > 0
    for i in range(len(view)):
        owned = smap.block_at(i) is not None
        synthetic = smap.is_synthetic(i)
        assert owned != synthetic, (
            f"offset {i} of the {fmt} view is "
            f"{'both owned and synthetic' if owned else 'neither owned nor synthetic'}"
        )


@pytest.mark.parametrize("fmt", FORMATS)
def test_a_synthetic_region_is_text_no_block_ever_said(fmt) -> None:
    """The separators, markers and tags are synthetic, and there is at least one of them in every
    format that has any -- otherwise `is_synthetic` would be vacuously false and the totality
    property above would prove nothing."""
    view, smap = serialize(TINY, fmt)
    synthetic = "".join(view[i] for i in range(len(view)) if smap.is_synthetic(i))
    assert synthetic, f"{fmt} produced no synthetic region at all"


# ---------------------------------------------------------------------------
# 5. `layers`. 03:1014-1016.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_body_and_body_plus_note_are_different_views_and_both_are_total(fmt) -> None:
    """ "A caller who wants footnotes inline asks for `{BODY, NOTE}` and gets a `SpanMap` covering
    both" (03:1015). Different text, and the two properties above hold of each."""
    scope = fixture_scope(3)
    body, body_map = serialize(scope, fmt, layers=BODY)
    both, both_map = serialize(scope, fmt, layers=BODY_AND_NOTE)
    assert body != both
    assert len(both) > len(body)
    notes = [b for b in scope.blocks if b.layer is Layer.NOTE and b.text]
    assert notes, "the fixture must carry a note block for this to mean anything"
    for note in notes:
        assert note.text is not None
        with pytest.raises(KeyError):
            body_map.offsets_of(int(note.id))
        first, end = both_map.offsets_of(int(note.id))
        assert first < end
    for view, smap in ((body, body_map), (both, both_map)):
        for i in range(len(view)):
            assert (smap.block_at(i) is not None) != smap.is_synthetic(i)


def test_the_view_id_changes_with_the_layer_set() -> None:
    """`options_digest` is over "(layers sorted, contextualize, scope kind and its resolved block
    ids' digest, gen)" (03:2888), so two layer sets are two views and a `RenderSpan` into one
    cannot be lifted through the other."""
    _, body = serialize(TINY, "md", layers=BODY)
    _, both = serialize(TINY, "md", layers=BODY_AND_NOTE)
    assert body.view_id != both.view_id
    with pytest.raises(TypeError):
        both.to_text(RenderSpan(body.view_id, 0, 1))


def test_layers_must_be_a_non_empty_frozenset_of_layer() -> None:
    with pytest.raises(TypeError):
        serialize(TINY, "md", layers={Layer.BODY})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="at least one Layer"):
        serialize(TINY, "md", layers=frozenset())
    with pytest.raises(TypeError):
        serialize(TINY, "md", layers=frozenset({"body"}))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 6. The edges: out of range, and an empty scope.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_block_at_out_of_range_returns_none_and_does_not_raise(fmt) -> None:
    """03:225: `block_at()` returns `None` RATHER THAN RAISING. A projection is a read path, and an
    offset a caller computed from a stale view must not be able to crash a render."""
    view, smap = serialize(TINY, fmt)
    for offset in (-1, -1000, len(view), len(view) + 1, 10**9):
        assert smap.block_at(offset) is None
        assert smap.is_synthetic(offset) is False


def test_an_offset_that_is_not_an_int_is_a_type_error() -> None:
    """The one thing that does raise: a foreign coordinate. A `TextSpan` or a `RenderSpan` handed
    to `block_at` is the cross-system confusion `spans.py` exists to make impossible, and `True`
    is an `int` in Python."""
    _, smap = serialize(TINY, "md")
    for bad in (TextSpan(0, 1), RenderSpan(smap.view_id, 0, 1), 1.0, "1", None, True):
        with pytest.raises(TypeError):
            smap.block_at(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("fmt", FORMATS)
def test_an_empty_scope_serializes_to_the_empty_view_and_an_empty_map(fmt) -> None:
    """A page range with no body blocks is an empty page, not an exception."""
    view, smap = serialize(ViewScope(), fmt)
    assert view == ""
    assert smap.view_len == 0
    assert smap.n_intervals == 0
    assert smap.block_at(0) is None
    assert smap.is_synthetic(0) is False
    assert smap.to_text(RenderSpan(smap.view_id, 0, 0)) == []


def test_a_scope_whose_every_block_is_filtered_out_is_also_empty() -> None:
    """The layer filter can empty a non-empty scope, and that is not a different case."""
    scope = fixture_scope(1)
    view, smap = serialize(scope, "md", layers=frozenset({Layer.HIDDEN}))
    assert view == ""
    assert smap.n_intervals == 0


def test_a_tombstoned_block_is_not_in_any_view() -> None:
    """Step 1 restricts to `state = 0` (03:2827). Retirement is `state = 1` plus a
    `block_history` row, never a delete (03:313), so a tombstoned block is still in the scope."""
    live = _block(1, Kind.PARAGRAPH, text="visible")
    dead = _block(2, Kind.PARAGRAPH, text="retired")
    scope = ViewScope(blocks=(live, dataclasses.replace(dead, tombstoned=True)))
    view, smap = serialize(scope, "text")
    assert view == "visible"
    with pytest.raises(KeyError):
        smap.offsets_of(2)


# ---------------------------------------------------------------------------
# 7. Determinism. Projection law rule 1 and rule 4 (03:2962, :2970).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_two_calls_at_one_generation_are_byte_identical(fmt) -> None:
    scope = fixture_scope(7)
    first_view, first_map = serialize(scope, fmt, layers=BODY_AND_NOTE)
    second_view, second_map = serialize(scope, fmt, layers=BODY_AND_NOTE)
    assert first_view == second_view
    assert first_map == second_map


def test_the_order_the_scope_hands_children_over_does_not_change_the_view() -> None:
    """`ord` IS reading order (03:239), so a resolved sequence in a different row order is the same
    view. This is the assertion that would fail if the traversal depended on dict insertion order
    or on a set's iteration order rather than on `(ord, block_id)`."""
    scope = fixture_scope(11)
    present = {int(b.id) for b in scope.blocks}
    roots = tuple(b for b in scope.blocks if b.parent is None or int(b.parent) not in present)
    others = tuple(b for b in scope.blocks if b not in roots)
    reversed_scope = ViewScope(
        blocks=roots + tuple(reversed(others)),
        kind=scope.kind,
        corpus_id=scope.corpus_id,
        gen=scope.gen,
        payloads=scope.payloads,
        tables=scope.tables,
        cells=scope.cells,
        continues=scope.continues,
        heading_paths=scope.heading_paths,
    )
    for fmt in FORMATS:
        forward, _ = serialize(scope, fmt, layers=BODY_AND_NOTE)
        backward, _ = serialize(reversed_scope, fmt, layers=BODY_AND_NOTE)
        assert forward == backward, f"{fmt} depends on the row order, not on ord"


_CROSS_PROCESS = """
import hashlib, json
from omniweave_core.model.block import Block, BlockId, CellPos, Mark
from omniweave_core.model.enums import Kind, Layer, Method, Quote, TableKind, Trust
from omniweave_core.model.serialize import FORMATS, TableFacts, ViewScope, serialize
from omniweave_core.model.spans import OriginNone


def b(i, kind, text=None, parent=None, o=0, layer=Layer.BODY, marks=()):
    return Block(
        id=BlockId(i), addr="p0/%d" % i, cite="d1#%d" % i, doc_ord=1, gen=1, page=0,
        parent=None if parent is None else BlockId(parent), ord=o, kind=kind, raw_kind=None,
        layer=layer, label=None, text=text, content_digest=bytes(32), layout_digest=None,
        revision=1, quad=None, origin=OriginNone(), span=None, producer_id=1,
        method=Method.NATIVE, trust=Trust.EXTRACTED, quote=Quote.VERBATIM, marks=tuple(marks),
    )


blocks = (
    b(1, Kind.DOCUMENT),
    b(2, Kind.HEADING, "Head &<>", 1, 0),
    b(3, Kind.PARAGRAPH, "one two three", 1, 1, marks=(Mark(0, 3, "bold"), Mark(2, 7, "italic"))),
    b(4, Kind.PARAGRAPH, "", 1, 2),
    b(5, Kind.TABLE, None, 1, 3),
    b(6, Kind.TABLE_CELL, "h1", 5, 0),
    b(7, Kind.TABLE_CELL, "h2", 5, 1),
    b(8, Kind.TABLE_CELL, "v1", 5, 2),
    b(9, Kind.TABLE_CELL, "v2|x\\ny", 5, 3),
    b(10, Kind.FOOTNOTE, "note body", None, 0, layer=Layer.NOTE),
)
scope = ViewScope(
    blocks=blocks, kind="document", corpus_id="c", gen=1,
    payloads={BlockId(2): {"level": 3}},
    tables={BlockId(5): TableFacts(kind=TableKind.DATA, header_rows=1)},
    cells={
        BlockId(6): CellPos(0, 0), BlockId(7): CellPos(0, 1),
        BlockId(8): CellPos(1, 0), BlockId(9): CellPos(1, 1),
    },
    heading_paths={BlockId(2): ("A", "B")},
)
layers = frozenset({Layer.BODY, Layer.NOTE})
out = {}
for fmt in FORMATS:
    view, smap = serialize(scope, fmt, layers=layers, contextualize=True)
    out[fmt] = [
        hashlib.sha256(view.encode("utf-8")).hexdigest(),
        smap.view_id,
        smap.n_intervals,
    ]
print(json.dumps(out, sort_keys=True))
"""


def test_two_fresh_interpreters_produce_the_same_view_and_the_same_map(interpreter) -> None:
    """Rule 4: "`P` is a pure function of `(S, options, snapshot)` -- no clock, no RNG, no
    environment" (03:2970).

    Two spawns, because `PYTHONHASHSEED` differs between processes and that is the only witness
    for a `str`-keyed dict or a `frozenset` leaking its iteration order into the output -- which is
    exactly what `layers` would do if it were iterated rather than sorted, and what the children
    map would do if it were not ordered by `(ord, block_id)`. The trailing comment differs only so
    the `Interpreter` memo does not hand back one run twice.
    """
    first = json.loads(interpreter.run(_CROSS_PROCESS + "\n# run one\n").strip().splitlines()[-1])
    second = json.loads(interpreter.run(_CROSS_PROCESS + "\n# run two\n").strip().splitlines()[-1])
    assert first == second
    assert set(first) == set(FORMATS)
    assert len({row[0] for row in first.values()}) == len(FORMATS), "two formats rendered alike"


# ---------------------------------------------------------------------------
# 8. The traversal's five steps, one test each where the step is observable.
# ---------------------------------------------------------------------------


def test_a_block_renders_its_own_text_before_its_children() -> None:
    """Step 3b then 3c, "in this order and no other" (03:2830). This is where M-INV-4 earns its
    place: there is no de-duplication pass, so the model forbids the duplication instead
    (03:2844-2846)."""
    parent = _block(1, Kind.LIST_ITEM, text="item text")
    child = _block(2, Kind.PARAGRAPH, text="child prose", parent=1)
    view, _ = serialize(ViewScope(blocks=(parent, child)), "text")
    assert view.index("item text") < view.index("child prose")


def test_a_layout_table_is_unwrapped_by_the_serializer_but_not_by_otsl() -> None:
    """Step 2 (03:2828-2830): "The model never unwraps; only this step does." `otsl` is exempt
    because a table-only serialization has nothing else to say about a table (03:2881)."""
    scope = _layout_table_scope()
    for fmt in ("md", "gfm", "html", "text"):
        view, _ = serialize(scope, fmt)
        assert "|" not in view and "<table>" not in view, f"{fmt} rendered a layout table"
        assert "left" in view and "right" in view, f"{fmt} lost a layout cell"
    otsl, _ = serialize(scope, "otsl")
    assert "<nl>" in otsl and "<fcel>" in otsl


def _layout_table_scope() -> ViewScope:
    table = _block(1, Kind.TABLE)
    left = _block(2, Kind.TABLE_CELL, text="left", parent=1, ord_=0)
    right = _block(3, Kind.TABLE_CELL, text="right", parent=1, ord_=1)
    return ViewScope(
        blocks=(table, left, right),
        tables={table.id: TableFacts(kind=TableKind.LAYOUT)},
        cells={left.id: CellPos(0, 0), right.id: CellPos(0, 1)},
    )


def test_a_continues_seam_drops_the_separator_and_stays_two_intervals() -> None:
    """Step 4 (03:2836-2841): "no separator is emitted and no OPEN/CLOSE token is repeated: the two
    render as one paragraph. The SpanMap records two adjacent intervals, so a RenderSpan across the
    seam lifts to two blocks -- which is correct, because it is two blocks.\""""
    first = _block(1, Kind.PARAGRAPH, text="first half ", ord_=0)
    second = _block(2, Kind.PARAGRAPH, text="second half", ord_=1)
    joined = ViewScope(blocks=(first, second), continues={first.id: second.id})
    apart = ViewScope(blocks=(first, second))
    view, smap = serialize(joined, "md")
    assert view == "first half second half"
    assert serialize(apart, "md")[0] == "first half \n\nsecond half"
    seam = len("first half ")
    assert smap.block_at(seam - 1) == (1, TextSpan(0, seam))
    assert smap.block_at(seam) == (2, TextSpan(0, len("second half")))
    lifted = smap.to_text(RenderSpan(smap.view_id, seam - 2, seam + 2))
    assert [owner for owner, _span in lifted] == [1, 2]


def test_contextualize_prefixes_each_top_level_unit_and_the_prefix_is_synthetic() -> None:
    """Step 5 (03:2842). The heading path is text the block never said, so a quote taken across it
    is not that block's words -- which is the whole reason `is_synthetic` exists."""
    head = _block(1, Kind.HEADING, text="Body")
    scope = ViewScope(
        blocks=(head,),
        payloads={head.id: {"level": 2}},
        heading_paths={head.id: ("Chapter", "Section")},
    )
    plain, _ = serialize(scope, "text")
    with_path, smap = serialize(scope, "text", contextualize=True)
    assert plain == "Body"
    assert with_path == "Chapter > Section\nBody"
    for i in range(len("Chapter > Section\n")):
        assert smap.is_synthetic(i)
    assert smap.block_at(with_path.index("Body")) == (1, TextSpan(0, 4))
    assert serialize(scope, "text")[1].view_id != smap.view_id


# ---------------------------------------------------------------------------
# 9. Run-splitting. 03:2846-2852.
# ---------------------------------------------------------------------------


def test_an_overlapping_mark_set_renders_well_nested_and_drops_no_mark() -> None:
    """03:2849-2851: "An arbitrarily overlapping mark set therefore produces a well-nested render
    by splitting runs, and no mark is ever dropped."

    marker cannot express this at all -- one `formats: List[Literal[...]]` per span cannot say
    bold ending mid-italic (03:368-370) -- so the fixture is exactly that case.
    """
    block = _block(
        1,
        Kind.PARAGRAPH,
        text="bold both italic",
        marks=(Mark(0, 9, "bold"), Mark(5, 16, "italic")),
    )
    view, smap = serialize(ViewScope(blocks=(block,)), "html")
    assert view.count("<strong>") >= 1
    assert view.count("<em>") >= 1
    assert view.count("<strong>") == view.count("</strong>")
    assert view.count("<em>") == view.count("</em>")
    assert _tags_are_well_nested(view)
    owned = "".join(view[a:b] for a, b, _owner, _span in owned_runs(view, smap))
    assert owned == "bold both italic", "run-splitting lost or duplicated a character"


def _tags_are_well_nested(view: str) -> bool:
    stack: list[str] = []
    for match in re.finditer(r"</?([a-z]+)[^>]*>", view):
        name = match.group(1)
        if match.group(0).startswith("</"):
            if not stack or stack.pop() != name:
                return False
        else:
            stack.append(name)
    return not stack


def test_a_zero_width_mark_is_rendered_and_is_wholly_synthetic() -> None:
    """A zero-width mark (`a == b`) is legal and meaningful for `anchor` and `note_ref` (03:381),
    and it covers no character -- so every one of its own characters is synthetic."""
    block = _block(1, Kind.PARAGRAPH, text="see", marks=(Mark(3, 3, "note_ref", {"label": "7"}),))
    view, smap = serialize(ViewScope(blocks=(block,)), "md")
    assert view == "see[^7]"
    assert [i for i in range(len(view)) if smap.is_synthetic(i)] == [3, 4, 5, 6]


def test_a_mark_outside_the_text_is_skipped_rather_than_clamped() -> None:
    """P9 asserts every stored mark satisfies `0 <= a <= b <= len(text)`, so an out-of-range mark
    is a store the conformance suite already failed. Clamping it would render a token over
    characters the driver never marked, which is worse than ignoring it."""
    block = _block(1, Kind.PARAGRAPH, text="abc", marks=(Mark(2, 99, "bold"),))
    view, _ = serialize(ViewScope(blocks=(block,)), "md")
    assert view == "abc"


# ---------------------------------------------------------------------------
# 10. The five formats' stated differences. 03:2871-2882.
# ---------------------------------------------------------------------------


def test_the_block_separator_is_the_plans_per_format(plan) -> None:
    """03:2873-2880's separator column, read back out of the plan's own table.

    The table is located by its HEADER rather than by grepping each format name: `| `text` |` also
    opens a row of section 4.1's kind vocabulary and of section 8.4's method table, and a regex
    that swallowed those would read the wrong column of the wrong table. A section boundary is a
    claim too.
    """
    plan.require()
    row = {"md": "\n\n", "gfm": "\n\n", "html": "", "text": "\n\n", "otsl": "\n"}
    lines = plan.lines(DOC)
    headers = [
        i for i, line in enumerate(lines) if line.startswith("| `fmt` | for | block separator")
    ]
    assert len(headers) == 1, "03 section 16.1 prints the five-format table exactly once"
    printed = {}
    for line in lines[headers[0] + 2 : headers[0] + 2 + len(row)]:
        cells = [cell.strip() for cell in line.split("|")]
        printed[cells[1].replace("`", "")] = cells[3].replace("`", "")
    assert set(printed) == set(row)
    for fmt, sep in row.items():
        expected = {"\n\n": r"\n\n", "\n": r"\n", "": "none (block elements)"}[sep]
        assert printed[fmt] == expected
    assert row == mod._SEPARATOR


def test_gfm_emits_a_synthetic_delimiter_row_when_there_are_no_header_rows() -> None:
    """03:2876: "GFM strictly: synthetic delimiter row when `header_rows == 0`". Synthetic is the
    operative word -- the row is not any block's text, and the map must say so."""
    scope = _two_by_two(header_rows=0)
    view, smap = serialize(scope, "gfm")
    assert view.startswith("|  |  |\n| --- | --- |\n")
    for i in range(view.index("| a |")):
        assert smap.is_synthetic(i)


def test_gfm_joins_a_multi_line_cell_with_br_and_md_with_a_space() -> None:
    """The one difference 03:2876 states between `md` and `gfm`, and the substitution is one source
    character in one interval, so the map stays honest about the length."""
    scope = _two_by_two(header_rows=1, first_cell="one\ntwo")
    gfm, gfm_map = serialize(scope, "gfm")
    md, _ = serialize(scope, "md")
    assert "one<br>two" in gfm
    assert "one two" in md
    at = gfm.index("<br>")
    got = gfm_map.block_at(at)
    assert got is not None
    assert got[1] == TextSpan(3, 4)


def test_html_preserves_rowspan_and_colspan_where_gfm_flattens_them() -> None:
    """03:2877 against 03:2874: "`rowspan`/`colspan` preserved" against "spans flattened". A
    covered position renders as a blank cell in a pipe table, because GFM has no span syntax
    (03:2035)."""
    table = _block(1, Kind.TABLE)
    wide = _block(2, Kind.TABLE_CELL, text="wide", parent=1, ord_=0)
    below = _block(3, Kind.TABLE_CELL, text="below", parent=1, ord_=1)
    scope = ViewScope(
        blocks=(table, wide, below),
        tables={table.id: TableFacts(header_rows=1)},
        cells={wide.id: CellPos(0, 0, col_span=2), below.id: CellPos(1, 0)},
    )
    html, _ = serialize(scope, "html")
    assert 'colspan="2"' in html
    gfm, _ = serialize(scope, "gfm")
    assert "colspan" not in gfm
    assert "| wide |  |" in gfm


def test_html_escapes_the_three_characters_that_would_otherwise_be_markup() -> None:
    """One source character becomes five view characters, and the map records that as its own
    interval rather than folding it into a length-preserving neighbour -- the defect class of
    `_notes/s10-fix-ledger.md` D3, two integer pairs in different coordinate spaces."""
    block = _block(1, Kind.PARAGRAPH, text="a&b<c")
    view, smap = serialize(ViewScope(blocks=(block,)), "html")
    assert view == "<p>a&amp;b&lt;c</p>"
    at = view.index("&amp;")
    got = smap.block_at(at)
    assert got == (1, TextSpan(1, 2))
    assert smap.block_at(at + 4) == (1, TextSpan(1, 2))
    lifted = smap.to_text(RenderSpan(smap.view_id, at + 1, at + 2))
    assert lifted == [(1, TextSpan(1, 2))], "a partial substitution lifts to the whole character"


def test_text_joins_a_rows_cells_by_tab_and_its_rows_by_newline() -> None:
    """03:2878 reads "rows joined by tab, cells by newline", which is the two nouns in each other's
    slots -- so this asserts TSV, and `serialize.py`'s `text_table` docstring records the defect.
    A table whose rows were joined by tabs would put every cell of a 40-row table on one BM25
    line, which is the exact use the same row names ("BM25 fixtures, diffing, plain export")."""
    view, _ = serialize(_two_by_two(header_rows=1), "text")
    assert view == "a\tb\nc\td"


def test_otsl_names_which_way_a_covered_position_is_covered() -> None:
    """03:2879: `otsl` is the one row whose "lossy in" column reads "nothing about the table", so a
    covered position must say whether it was covered from the left, from above, or from both.

    The token vocabulary is docling's published OTSL (`_notes/mine-parse.md:322`), because the plan
    names OTSL and never defines its tokens -- reported as a plan silence.
    """
    table = _block(1, Kind.TABLE)
    wide = _block(2, Kind.TABLE_CELL, text="w", parent=1, ord_=0)
    tall = _block(3, Kind.TABLE_CELL, text="t", parent=1, ord_=1)
    plain = _block(4, Kind.TABLE_CELL, text="p", parent=1, ord_=2)
    scope = ViewScope(
        blocks=(table, wide, tall, plain),
        cells={
            wide.id: CellPos(0, 0, col_span=2),
            tall.id: CellPos(1, 0, row_span=1),
            plain.id: CellPos(1, 1),
        },
    )
    view, _ = serialize(scope, "otsl")
    assert view == "<fcel>w<lcel><nl><fcel>t<fcel>p<nl>"


def test_an_empty_cell_is_ecel_and_a_header_row_is_ched() -> None:
    scope = _two_by_two(header_rows=1, first_cell="")
    view, _ = serialize(scope, "otsl")
    assert view == "<ecel><ched>b<nl><fcel>c<fcel>d<nl>"


def _two_by_two(*, header_rows: int, first_cell: str = "a") -> ViewScope:
    table = _block(1, Kind.TABLE)
    texts = (first_cell, "b", "c", "d")
    cells = tuple(_block(2 + i, Kind.TABLE_CELL, text=texts[i], parent=1, ord_=i) for i in range(4))
    return ViewScope(
        blocks=(table, *cells),
        tables={table.id: TableFacts(header_rows=header_rows)},
        cells={
            cells[0].id: CellPos(0, 0),
            cells[1].id: CellPos(0, 1),
            cells[2].id: CellPos(1, 0),
            cells[3].id: CellPos(1, 1),
        },
    )


def test_md_writes_the_heading_level_from_the_payload_and_clamps_at_six() -> None:
    """`payload.level` is 1-based (03:819); markdown and HTML both have exactly six levels, and a
    `title` has no level at all, which is why it is a separate kind (03:818)."""
    for level, hashes in ((1, "# "), (3, "### "), (9, "###### ")):
        head = _block(1, Kind.HEADING, text="H")
        scope = ViewScope(blocks=(head,), payloads={head.id: {"level": level}})
        assert serialize(scope, "md")[0] == f"{hashes}H"
        assert serialize(scope, "html")[0] == f"<h{min(level, 6)}>H</h{min(level, 6)}>"
    title = _block(1, Kind.TITLE, text="T")
    assert serialize(ViewScope(blocks=(title,)), "md")[0] == "# T"


def test_a_blockquote_prefixes_every_line_and_the_prefix_is_synthetic() -> None:
    """03:2832 names it: "`> ` per line for blockquote"."""
    quote = _block(1, Kind.BLOCKQUOTE)
    inner = _block(2, Kind.PARAGRAPH, text="one\ntwo", parent=1)
    view, smap = serialize(ViewScope(blocks=(quote, inner)), "md")
    assert view == "> one\n> two"
    assert [i for i in range(len(view)) if smap.is_synthetic(i)] == [0, 1, 6, 7]


def test_a_code_block_is_fenced_with_its_payload_language() -> None:
    """03:2833 names "```python\\n" for code, and whitespace inside a code block is never
    normalised (03:824)."""
    code = _block(1, Kind.CODE, text="x = 1\n  y = 2")
    scope = ViewScope(blocks=(code,), payloads={code.id: {"lang": "python", "fenced": True}})
    view, smap = serialize(scope, "md")
    assert view == "```python\nx = 1\n  y = 2\n```"
    owned = "".join(view[a:b] for a, b, _owner, _span in owned_runs(view, smap))
    assert owned == "x = 1\n  y = 2"


# ---------------------------------------------------------------------------
# 11. Errors: the fmt argument, the caps table, and the two limits.
# ---------------------------------------------------------------------------


def test_a_format_that_is_not_one_of_the_five_is_a_usage_error() -> None:
    for bad in ("markdown", "MD", "csv", "", "pdf"):
        with pytest.raises(UsageError) as caught:
            serialize(TINY, bad)  # type: ignore[arg-type]
        assert caught.value.fix
    with pytest.raises(UsageError):
        serialize(TINY, None)  # type: ignore[arg-type]


def test_a_format_whose_caps_entry_is_false_may_never_be_cited_from(monkeypatch) -> None:
    """03:2865-2868 and 18:393: `OW_SPANMAP_UNAVAILABLE` names the SERIALIZER, not a driver,
    "because `serialize()` is core's own function over core's five formats and a parse driver never
    calls it. At release 1 there is no such format" -- so the branch is exercised by flipping the
    table, which is also the assertion that at release 1 nothing is flipped."""
    assert all(SERIALIZER_CAPS.values()), "at release 1 no format is uncitable (03:2866)"
    monkeypatch.setattr(mod, "SERIALIZER_CAPS", {**SERIALIZER_CAPS, "md": False})
    with pytest.raises(PolicyRefusal) as caught:
        serialize(TINY, "md")
    assert caught.value.code() == "OW_SPANMAP_UNAVAILABLE"
    assert caught.value.numeric() in ("OW-A-012", "")
    assert "serializer" in str(caught.value)


def test_max_view_bytes_is_checked_as_the_view_is_appended(monkeypatch) -> None:
    """03:2604-2607: "checked incrementally as the serializer appends rather than after the memory
    is spent", with `RESOURCE_LIMIT{MAX_VIEW_BYTES}` naming the knob."""
    assert mod.MAX_VIEW_BYTES == MAX_VIEW_BYTES
    monkeypatch.setattr(mod, "MAX_VIEW_BYTES", 16)
    with pytest.raises(ResourceLimit) as caught:
        serialize(fixture_scope(5), "md")
    assert caught.value.limit == "MAX_VIEW_BYTES"


def test_a_table_past_max_expansion_names_that_knob_instead(monkeypatch) -> None:
    """`MAX_EXPANSION` is "a table's charged span area, equal to `MAX_GRID_SLOTS` and asserted
    equal, so a table cannot build and then fail to store" (03:2620)."""
    monkeypatch.setattr(mod, "MAX_EXPANSION", 3)
    table = _block(1, Kind.TABLE)
    cell = _block(2, Kind.TABLE_CELL, text="x", parent=1)
    scope = ViewScope(blocks=(table, cell), cells={cell.id: CellPos(0, 0, 4, 4)})
    with pytest.raises(ResourceLimit) as caught:
        serialize(scope, "md")
    assert caught.value.limit == "MAX_EXPANSION"


def test_the_scope_type_and_its_invariants_are_enforced_at_construction() -> None:
    with pytest.raises(TypeError):
        serialize(object(), "md")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="RESOLVED tuple"):
        ViewScope(blocks=[_block(1, Kind.PARAGRAPH)])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="duplicate-free"):
        ViewScope(blocks=(_block(1, Kind.PARAGRAPH), _block(1, Kind.PARAGRAPH)))
    with pytest.raises(ValueError, match=r"ViewScope\.kind"):
        ViewScope(kind="page-range")
    for kind in mod.SCOPE_KINDS:
        assert ViewScope(kind=kind).kind == kind


def test_offsets_of_raises_for_a_block_the_view_never_rendered() -> None:
    """ "One dict read" (03:2860): a block that is not in the view is a caller bug, not a model
    condition with an `OW-*` code of its own."""
    _, smap = serialize(TINY, "md")
    with pytest.raises(KeyError):
        smap.offsets_of(10**9)


def test_a_visited_block_that_places_no_character_still_has_a_zero_length_span() -> None:
    """An empty `text`, a pure container and a `rule` all render nothing of their own, and
    `offsets_of` must still answer -- otherwise a caller has to distinguish "no such block" from
    "contributed nothing", which is a distinction the map should make for them."""
    root = _block(1, Kind.DOCUMENT)
    empty = _block(2, Kind.PARAGRAPH, text="", parent=1, ord_=0)
    rule = _block(3, Kind.RULE, parent=1, ord_=1)
    view, smap = serialize(ViewScope(blocks=(root, empty, rule)), "text")
    for ident in (1, 2, 3):
        first, end = smap.offsets_of(ident)
        assert first == end
        assert 0 <= first <= len(view)


# ---------------------------------------------------------------------------
# 12. `to_text` and the map's own arithmetic.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", FORMATS)
def test_to_text_lifts_every_owned_offset_of_a_whole_view_span(fmt) -> None:
    """A `RenderSpan` over the whole view lifts to exactly the owned intervals, in view order."""
    scope = fixture_scope(13)
    view, smap = serialize(scope, fmt, layers=BODY_AND_NOTE)
    lifted = smap.to_text(RenderSpan(smap.view_id, 0, len(view)))
    runs = owned_runs(view, smap)
    assert [owner for owner, _span in lifted] == [owner for _a, _b, owner, _span in runs]
    assert [span for _owner, span in lifted] == [span for _a, _b, _owner, span in runs]


def test_the_interval_count_is_what_the_plan_prices_at_24_bytes() -> None:
    """03:2861 prices the map at 24 B per interval, so the count is the quantity that matters and
    is exposed. A view with no marks and no children should not decompose per character."""
    block = _block(1, Kind.PARAGRAPH, text="a" * 500)
    _, smap = serialize(ViewScope(blocks=(block,)), "text")
    assert smap.n_intervals == 1


def test_a_render_span_from_another_view_cannot_be_lifted() -> None:
    """03:2890: a type error, not a silent mis-lift, and the comparison lives on `RenderSpan` so
    every `SpanMap` implementation raises it the same way."""
    _, md_map = serialize(TINY, "md")
    _, html_map = serialize(TINY, "html")
    with pytest.raises(TypeError, match="type error"):
        html_map.to_text(RenderSpan(md_map.view_id, 0, 1))


def test_the_maps_parallel_arrays_must_be_the_same_length() -> None:
    with pytest.raises(ValueError, match="parallel"):
        ArraySpanMap(
            view_id="md/1/0000",
            view_len=1,
            starts=(0,),
            owners=(None, None),
            text_spans=(None,),
            first_last={},
        )
    with pytest.raises(ValueError, match="view_id"):
        ArraySpanMap(
            view_id="md/1/zzzz",
            view_len=0,
            starts=(),
            owners=(),
            text_spans=(),
            first_last={},
        )
