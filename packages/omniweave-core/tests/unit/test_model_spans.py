"""The three coordinate systems cannot be confused, and the geometry frame normalises once.

Two kinds of assertion live here and they are kept apart on purpose.

**Transcription.** Field names, field ORDER, the five `OriginSpan` variants, the `view_id` shape,
the five `SERIALIZER_CAPS` formats and the three unit factors are read back out of
`_plan/03-document-model.md` and compared against the module. A renamed field or a reordered pair
is silent at runtime -- `OriginBytes('f', 2, 5, 'utf-8/strict')` type-checks whichever way round
`start` and `length` sit -- so the plan line is the oracle, not a comment.

**The defect class this cluster exists for.** `_notes/s10-fix-ledger.md` D3: `GraphSink.mention`
stored offsets from `normalize_k`'s OUTPUT space as offsets into `block.text`. Both are half-open
integer pairs; nothing in the plan could see it; every L3 span in every store would have been
silently wrong. So the tests below do not merely check that the three systems are DOCUMENTED as
distinct -- they check that a cross-system assignment RAISES: a foreign span in an offset field, a
bare eight-tuple where a `Quad` belongs, a `bytes` container handed to a `TextSpan`, a
`dataclasses.replace` that would move a span between systems, and a `RenderSpan` built from a
`TextSpan`'s two ints.

Randomness is a blake2b keystream, never `random`: the repo bans it outright ("Sampling is
blake2b. Determinism is a gate, not a habit.", 11-repo-layout.md section 8.1).

Specified in 03-document-model.md sections 2.3, 2.4, 7.1, 7.2, 7.4, 16.2 and 17 (P6, P8, P16);
07-store-and-retrieval.md section 8.2; 01-principles.md P-6.
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import re
from pathlib import Path
from typing import get_args, get_type_hints

import pytest
from omniweave_core.errors import ModelError
from omniweave_core.model import spans
from omniweave_core.model.enums import OsKind
from omniweave_core.model.spans import (
    SERIALIZER_CAPS,
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginNone,
    OriginPixels,
    OriginSpan,
    Quad,
    RenderSpan,
    SpanMap,
    TextSpan,
    _half_plane,
    _order_topleft_clockwise,
    _round_half_away,
)

DOC = "03-document-model.md"

#: A legal quad in the stored frame: 10 pt x 5 pt at the page origin, top-left then clockwise.
RECT = Quad(0, 0, 10_000, 0, 10_000, 5_000, 0, 5_000)

#: One well-formed instance of every variant, for the structural sweeps.
ORIGINS = (
    OriginBytes(part="file", start=2, length=5, codec="utf-8/strict"),
    OriginNodePath(part="word/document.xml", path=(0, 3, 1, 7)),
    OriginGlyphs(part="pdf:page=12/content=0", extractor="pdftext@0.6", start=15_221, length=812),
    OriginPixels(page=13, quad=RECT),
    OriginNone(),
)

SPANS = (TextSpan(2, 5), RenderSpan("md/1/7c3f", 2, 5))

#: Values that are NOT an offset. Every one of them is a plausible mistake: the first four are the
#: cross-system assignments, `True` is an `int` in Python, and the rest are near misses.
FOREIGN_OFFSETS = (
    TextSpan(0, 1),
    RenderSpan("md/1/7c3f", 0, 1),
    OriginNone(),
    RECT,
    (0, 1),
    True,
    1.0,
    "1",
    None,
)


# ---------------------------------------------------------------------------
# Plan transcription. The plan line is the oracle for every name and every order.
# ---------------------------------------------------------------------------


def _plan_fields(plan, class_name: str) -> tuple[str, ...]:
    """The `name: type` pairs 03 section 2.4 prints on one line for `class <name>:`."""
    hits = plan.grep(rf"^class {class_name}\s*:", documents=[DOC])
    assert len(hits) == 1, f"{class_name} has {len(hits)} single-line declarations in {DOC}"
    body = re.sub(rf"^class {class_name}\s*:", "", hits[0].text.split("#")[0])
    return tuple(re.findall(r"([a-z_][a-z_0-9]*)\s*:", body))


@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (OriginBytes, ("part", "start", "length", "codec")),
        (OriginNodePath, ("part", "path")),
        (OriginGlyphs, ("part", "extractor", "start", "length")),
        (OriginPixels, ("page", "quad")),
        (TextSpan, ("a", "b")),
        (RenderSpan, ("view_id", "a", "b")),
    ],
)
def test_every_field_name_and_its_order_is_the_plans(plan, cls, expected) -> None:
    """Order is load-bearing: `OriginBytes('f', 2, 5, 'utf-8/strict')` is accepted whichever way
    round `start` and `length` sit, and swapping them makes every re-verification read the wrong
    bytes. The literal here is the second reading; the plan line is the first."""
    plan.require()
    # `dataclasses.fields()`, not `__dataclass_fields__`: the latter also carries the `os_kind`
    # ClassVar pseudo-field, which is the variant TAG and not part of the plan's declaration.
    assert tuple(f.name for f in dataclasses.fields(cls)) == expected
    assert _plan_fields(plan, cls.__name__) == expected


def test_origin_none_carries_no_field_and_is_a_value_not_a_null(plan) -> None:
    plan.require()
    assert dataclasses.fields(OriginNone) == ()
    assert OriginNone() == OriginNone()
    assert OriginNone() is not None
    assert plan.grep(r"`OriginNone\(\)` is a \*\*value\*\*, not a null", documents=[DOC])


def test_03_220_rejects_the_four_tuple_origin_glyphs(plan) -> None:
    """The ruling: the glyphs branch re-verifies against a RETAINED PART, so the variant names the
    part, and the page is `block.page` -- storing it twice would be two names for one fact."""
    plan.require()
    ruling = plan.grep(
        r"`OriginGlyphs` is `\(part, extractor, start, length\)`, "
        r"not `\(page, extractor, start, length\)`",
        documents=[DOC],
    )
    assert len(ruling) == 1, "03:220's ruling did not reproduce"
    assert "page" not in {f.name for f in dataclasses.fields(OriginGlyphs)}


def test_06s_locus_example_still_prints_the_rejected_form(plan) -> None:
    """A KNOWN PLAN DEFECT, asserted so it cannot be forgotten: 06:2099 constructs
    `OriginGlyphs(page=13, ...)` and 06:2077-2081 selects `os_page`/`os_start`/`os_len`, three
    column names the charter's `block` DDL does not carry. 03:220 and charter.md:1040-1046 are
    the more normative sites and this module follows them. When 06 is amended this test flips to
    an assertion that the old spelling is gone."""
    plan.require()
    stale = plan.grep(r"OriginGlyphs\(page=", documents=["06-structure-extraction.md"])
    assert len(stale) == 1, "06's stale OriginGlyphs literal moved; recheck the defect report"
    columns = plan.text("_notes/charter.md")
    for absent in ("os_page", "os_start", "os_len"):
        assert f"  {absent} " not in columns


def test_the_union_is_exactly_the_plans_five_variants(plan) -> None:
    plan.require()
    assert get_args(OriginSpan) == (
        OriginBytes,
        OriginNodePath,
        OriginGlyphs,
        OriginPixels,
        OriginNone,
    )
    printed = plan.grep(r"^OriginSpan = ", documents=[DOC])
    assert len(printed) == 1
    for cls in get_args(OriginSpan):
        assert cls.__name__ in printed[0].text


def test_no_origin_variant_names_a_field_b_or_end() -> None:
    """`os_b` is a LENGTH, not an end offset, at every site: the column, the wire (`os.len`) and
    the value type (`OriginBytes.length`) -- one quantity, one spelling, three places (03:1447).
    A field called `b` or `end` on an origin variant is that convention breaking."""
    for variant in get_args(OriginSpan):
        names = {f.name for f in dataclasses.fields(variant)}
        assert not names & {"b", "end", "stop", "os_b"}, variant.__name__


def test_quad_is_the_plans_eight_int_namedtuple(plan) -> None:
    plan.require()
    assert plan.grep(r"^class Quad\(NamedTuple\):", documents=[DOC])
    assert Quad._fields == ("x0", "y0", "x1", "y1", "x2", "y2", "x3", "y3")
    for row in (r"^    x0:int; y0:int; x1:int; y1:int$", r"^    x2:int; y2:int; x3:int; y3:int$"):
        assert plan.grep(row, documents=[DOC]), row
    # `rect()` is a VIEW computed on demand, never a ninth..twelfth field (03:170).
    assert "rect" not in Quad._fields
    assert callable(Quad.rect)


def test_the_three_unit_factors_are_the_plans(plan) -> None:
    """03 section 7.1's table: pt scales x1000, emu x1000/12700, px x72000/dpi."""
    plan.require()
    table = plan.text(DOC)
    assert "1 pt = 12,700 EMU" in table
    assert "1000 / 12700" in table
    assert "72000 / dpi" in table
    one_pt = Quad.from_driver(
        [(1, 0), (1, 1), (0, 1), (0, 0)],
        origin="topleft",
        unit="pt",
        page_h=100.0,
        dpi=None,
        rotation=0,
    )
    assert one_pt.rect() == (0, 0, 1_000, 1_000)
    one_emu = Quad.from_driver(
        [(12_700, 0), (12_700, 12_700), (0, 12_700), (0, 0)],
        origin="topleft",
        unit="emu",
        page_h=9_144_000.0,
        dpi=None,
        rotation=0,
    )
    assert one_emu.rect() == (0, 0, 1_000, 1_000)
    one_inch = Quad.from_driver(
        [(96, 0), (96, 96), (0, 96), (0, 0)],
        origin="topleft",
        unit="px",
        page_h=1_000.0,
        dpi=96.0,
        rotation=0,
    )
    assert one_inch.rect() == (0, 0, 72_000, 72_000)


def test_serializer_caps_is_the_plans_five_formats(plan) -> None:
    plan.require()
    assert dict(SERIALIZER_CAPS) == {
        "md": True,
        "gfm": True,
        "html": True,
        "text": True,
        "otsl": True,
    }
    printed = plan.grep(r'SERIALIZER_CAPS: Mapping\[str, bool\] = \{"md": True', documents=[DOC])
    assert len(printed) == 1
    with pytest.raises(TypeError):
        SERIALIZER_CAPS["md"] = False  # type: ignore[index]


def test_the_view_id_shape_is_the_plans(plan) -> None:
    plan.require()
    assert plan.grep(
        r'`view_id = "<fmt>/<serializer_version>/<options_digest\[:4\]>"`', documents=[DOC]
    )
    assert plan.grep(r"`md/1/7c3f`", documents=[DOC])
    assert RenderSpan("md/1/7c3f", 0, 1).view_id == "md/1/7c3f"


# ---------------------------------------------------------------------------
# Unconfusability. A cross-system assignment must RAISE, not be documented.
# ---------------------------------------------------------------------------


def test_the_three_systems_share_no_base_but_object() -> None:
    systems = (TextSpan, RenderSpan, *get_args(OriginSpan))
    for left, right in itertools.combinations(systems, 2):
        shared = set(left.__mro__) & set(right.__mro__)
        assert shared == {object}, f"{left.__name__} and {right.__name__} share {shared}"


def test_no_span_is_a_tuple_but_quad_is() -> None:
    """`NewType` over a tuple would not have been enough: two tuples of the same arity compare
    equal and unpack interchangeably. `Quad` alone is the plan's `NamedTuple`, and it has eight
    fields, so it cannot be confused with a two-field span either (03:168 against 03:203)."""
    assert issubclass(Quad, tuple)
    assert Quad(*range(8)) == tuple(range(8))  # the store's decode path, and why spans are not.
    for cls in (TextSpan, RenderSpan, *get_args(OriginSpan)):
        assert not issubclass(cls, tuple), cls.__name__


def test_a_span_never_equals_a_bare_pair_or_the_other_system() -> None:
    assert TextSpan(2, 5) != (2, 5)
    assert TextSpan(2, 5) != RenderSpan("md/1/7c3f", 2, 5)
    assert RenderSpan("md/1/7c3f", 2, 5) != RenderSpan("gfm/1/7c3f", 2, 5)
    assert TextSpan(2, 5) == TextSpan(2, 5)


def test_a_render_span_cannot_be_built_from_a_text_spans_two_ints() -> None:
    """`view_id` is required and comes first, so the accidental `RenderSpan(a, b)` is a TypeError
    rather than a span in the wrong coordinate system."""
    with pytest.raises(TypeError):
        RenderSpan(2, 5)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="view_id must be a str"):
        RenderSpan(*dataclasses.astuple(TextSpan(2, 5)), 0)  # type: ignore[arg-type]


@pytest.mark.parametrize("foreign", FOREIGN_OFFSETS)
def test_a_foreign_value_in_an_offset_field_is_rejected(foreign) -> None:
    for build in (
        lambda v: TextSpan(v, 5),
        lambda v: TextSpan(0, v),
        lambda v: RenderSpan("md/1/7c3f", v, 5),
        lambda v: OriginBytes("file", v, 5, "utf-8/strict"),
        lambda v: OriginBytes("file", 0, v, "utf-8/strict"),
        lambda v: OriginGlyphs("file", "x@1", v, 5),
        lambda v: OriginPixels(v, RECT),
        lambda v: OriginNodePath("file", (v,)),
    ):
        with pytest.raises((TypeError, ValueError)):
            build(foreign)


@pytest.mark.parametrize(
    "not_a_quad",
    [tuple(range(8)), (0, 0, 10, 10), TextSpan(0, 1), OriginNone(), None, [0] * 8],
)
def test_origin_pixels_refuses_anything_but_a_quad(not_a_quad) -> None:
    """A tuple that merely holds eight ints has not been through `Quad.from_driver`, and a
    four-int rect is not the stored frame at all (03:1393)."""
    with pytest.raises(TypeError, match="must be a Quad"):
        OriginPixels(page=0, quad=not_a_quad)


@pytest.mark.parametrize("value", [*SPANS, *ORIGINS])
def test_every_value_type_is_frozen_and_slotted(value) -> None:
    """`@dataclass(frozen=True, slots=True)` for every value type (03:143). Slots are what stop a
    caller smuggling a second coordinate system in as an ad-hoc attribute."""
    declared = dataclasses.fields(value)
    if declared:
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(value, declared[0].name, 0)
    # An attribute that is not a field has nowhere to go, because `slots=True` left no `__dict__`.
    # CPython 3.12 reports that refusal from the frozen `__setattr__`'s own `super()` call, so the
    # class is TypeError rather than AttributeError; what matters is that it is refused.
    with pytest.raises((AttributeError, TypeError)):
        value.smuggled_offset = 1
    assert not hasattr(value, "__dict__")


def test_replace_cannot_move_a_span_between_systems() -> None:
    """`dataclasses.replace` is the one API that looks like it could retype a span in place."""
    with pytest.raises(TypeError):
        dataclasses.replace(TextSpan(2, 5), view_id="md/1/7c3f")
    with pytest.raises(TypeError):
        dataclasses.replace(RenderSpan("md/1/7c3f", 2, 5), length=5)
    assert dataclasses.replace(TextSpan(2, 5), b=6) == TextSpan(2, 6)


def test_the_two_slicing_conventions_do_not_coincide() -> None:
    """`(2, 5)` means three characters to a `TextSpan` and five bytes to an `OriginBytes`. 07:2502
    bans `part[os_a:os_b]` and `text[ts_a:ts_a+ts_b]` -- the two ways to get this wrong -- and a
    caller that never writes the slice by hand cannot write either."""
    text = "abcdefgh"
    part = b"abcdefgh"
    assert TextSpan(2, 5).slice_of(text) == "cde"
    assert OriginBytes("file", 2, 5, "utf-8/strict").slice_of(part) == b"cdefg"
    assert len(TextSpan(2, 5).slice_of(text)) != len(
        OriginBytes("file", 2, 5, "utf-8/strict").slice_of(part)
    )


def test_slice_of_refuses_the_other_systems_container() -> None:
    with pytest.raises(TypeError, match="never indexes the original container"):
        TextSpan(0, 1).slice_of(b"abc")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"never indexes block\.text"):
        OriginBytes("file", 0, 1, "utf-8/strict").slice_of("abc")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="serialized view"):
        RenderSpan("md/1/7c3f", 0, 1).slice_of(b"abc")  # type: ignore[arg-type]


def test_origin_glyphs_has_no_slice_of() -> None:
    """A glyph index is the EXTRACTOR's own space (03:1470): the run is recovered by
    re-extraction, never by slicing the part's bytes, so no slicing method may exist to invite
    it."""
    assert not hasattr(OriginGlyphs, "slice_of")
    assert hasattr(OriginBytes, "slice_of")


def test_isinstance_over_the_union_admits_the_five_and_nothing_else() -> None:
    for origin in ORIGINS:
        assert isinstance(origin, OriginSpan)
    for other in (*SPANS, RECT, (0, 1), "bytes", None):
        assert not isinstance(other, OriginSpan)


def test_the_os_kind_tag_of_each_variant_is_the_imported_enum_member() -> None:
    """The tag is `OsKind`, imported, never a string literal: `enum_val.ord` IS the stored value
    and two CHECK constraints resolve these members out of `enum_val` BY NAME (03:1438, 03:1443).
    Every member is claimed by exactly one variant, in the enum's declaration order."""
    assert tuple(origin.os_kind for origin in ORIGINS) == tuple(OsKind)
    assert OriginBytes.os_kind is OsKind.BYTES
    assert "kind" not in dir(OriginPixels)  # `Block.kind` is a DIFFERENT vocabulary (INV-21).


# ---------------------------------------------------------------------------
# Field validation, variant by variant.
# ---------------------------------------------------------------------------


def test_a_text_span_may_be_empty_but_never_inverted_or_negative() -> None:
    """`mention` carries `CHECK (ts_a <= ts_b)` (charter.md:5042) and P8 asserts
    `0 <= ts_a <= ts_b <= len(text)` (03:3002): equal endpoints are legal, and it is `ground()`
    that will never mint one, not the type."""
    assert TextSpan(3, 3).slice_of("abcdef") == ""
    with pytest.raises(ValueError, match="half-open"):
        TextSpan(5, 2)
    with pytest.raises(ValueError, match=">= 0"):
        TextSpan(-1, 2)


def test_slice_of_enforces_p8s_third_inequality() -> None:
    with pytest.raises(ValueError, match="outside a text"):
        TextSpan(0, 9).slice_of("abcdefgh")
    with pytest.raises(ValueError, match="outside a part"):
        OriginBytes("file", 4, 5, "utf-8/strict").slice_of(b"abcdefgh")


@pytest.mark.parametrize("codec", ["utf-8/strict", "cp1252/replace", "latin-1/ignore"])
def test_a_well_formed_codec_is_accepted_and_splits_the_way_p7_splits_it(codec) -> None:
    origin = OriginBytes("file", 0, 1, codec)
    assert origin.decode_args() == tuple(codec.split("/", 1))
    name, errors = origin.decode_args()
    assert "x".encode(name).decode(name, errors) == "x"


@pytest.mark.parametrize("codec", ["utf-8", "utf-8/", "/strict", "utf-8/strict/extra", "/", ""])
def test_a_codec_that_is_not_codec_slash_errors_is_rejected(codec) -> None:
    """The `bytes` branch's predicate READS `os_codec`: it decodes before it compares, so a
    malformed policy makes the branch unevaluable rather than merely undocumented (03:1440), and
    decode symmetry is an invariant (03:1466)."""
    with pytest.raises(ValueError, match=r"codec|empty"):
        OriginBytes("file", 0, 1, codec)


@pytest.mark.parametrize("cls", [OriginBytes, OriginGlyphs])
def test_a_length_of_zero_is_not_a_sentinel(cls) -> None:
    """07:2502: `os_b == 0` is a rejected value, not a sentinel -- an empty span is
    `os_kind = 'none'`, which is a variant of its own and needs no second spelling."""
    kwargs = {"part": "file", "start": 0, "length": 0}
    if cls is OriginGlyphs:
        kwargs["extractor"] = "pdftext@0.6"
    else:
        kwargs["codec"] = "utf-8/strict"
    with pytest.raises(ValueError, match="LENGTH"):
        cls(**kwargs)


def test_a_node_path_is_a_non_empty_tuple_of_child_indices() -> None:
    """PLAN SILENT on emptiness and reported: `()` renders as `os_path = ''`, and 03 section 7.2
    gives `os_path = NULL` for every other variant, so `''` would be a second spelling of "no
    path" in a column whose NULL-ness is a CHECK."""
    assert OriginNodePath("word/document.xml", (0,)).path == (0,)
    with pytest.raises(ValueError, match="at least one child index"):
        OriginNodePath("word/document.xml", ())
    with pytest.raises(TypeError, match="must be a tuple"):
        OriginNodePath("word/document.xml", [0, 3])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match=">= 0"):
        OriginNodePath("word/document.xml", (0, -1))


@pytest.mark.parametrize(
    "build",
    [
        lambda: OriginBytes("", 0, 1, "utf-8/strict"),
        lambda: OriginNodePath("", (0,)),
        lambda: OriginGlyphs("", "pdftext@0.6", 0, 1),
        lambda: OriginGlyphs("file", "", 0, 1),
    ],
)
def test_an_empty_part_or_extractor_is_rejected(build) -> None:
    """An address that names no part addresses nothing: INV-10's branches re-verify against the
    part whose `store_ref` they check, and `extractor` is an exact identity like `pdftext@0.6`
    because the glyph index space is the extractor's (03:1470)."""
    with pytest.raises(ValueError, match="must not be empty"):
        build()


def test_origin_pixels_page_is_zero_based_and_never_negative() -> None:
    assert OriginPixels(0, RECT).page == 0
    with pytest.raises(ValueError, match=">= 0"):
        OriginPixels(-1, RECT)


@pytest.mark.parametrize(
    "view_id",
    ["md", "md/1", "md/1/7c3", "md/1/7C3F", "md/1/7c3fa", "zz/1/7c3f", "md//7c3f", "md/x/7c3f"],
)
def test_a_malformed_view_id_is_rejected(view_id) -> None:
    """A view is hash-pinned (03:2891): its id names the format, the serializer version and the
    options digest, and a bare format string is not an identity."""
    with pytest.raises(ValueError, match=r"options_digest|not one of"):
        RenderSpan(view_id, 0, 1)


@pytest.mark.parametrize("fmt", sorted(SERIALIZER_CAPS))
def test_every_citable_format_yields_a_legal_view_id(fmt) -> None:
    assert RenderSpan(f"{fmt}/1/7c3f", 0, 1).view_id.startswith(fmt)


def test_require_view_makes_a_mismatched_lift_a_type_error() -> None:
    """03:2890 -- "lifting a `RenderSpan` through a `SpanMap` whose `view_id` differs is a **type
    error**, not a silent mis-lift". One implementation of that comparison, here, so no `SpanMap`
    invents its own."""
    span = RenderSpan("md/1/7c3f", 0, 1)
    assert span.require_view("md/1/7c3f") is None
    with pytest.raises(TypeError, match="type error, not a mis-lift"):
        span.require_view("md/1/aaaa")
    with pytest.raises(TypeError, match="type error, not a mis-lift"):
        span.require_view("gfm/1/7c3f")


# ---------------------------------------------------------------------------
# Quad.from_driver -- the one boundary where a frame is normalised.
# ---------------------------------------------------------------------------


def _quad(pts, **kw) -> Quad:
    base = {"origin": "topleft", "unit": "pt", "page_h": 1_000.0, "dpi": None, "rotation": 0}
    base.update(kw)
    return Quad.from_driver(pts, **base)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.5, 1), (1.5, 2), (2.5, 3), (-0.5, -1), (-1.5, -2), (-2.5, -3), (0.4, 0), (-0.4, 0)],
)
def test_rounding_is_half_away_from_zero_not_half_to_even(value, expected) -> None:
    """03:1396. Under `round()`'s banker's rounding 0.5 -> 0 and 2.5 -> 2, so two coordinates a
    millipoint apart would round in opposite directions and `layout_digest` would stop being a
    pure function of the driver's numbers."""
    assert _round_half_away(value) == expected
    if expected % 2 == 1:
        assert round(value) != expected  # the half-to-even answer really is different


def test_the_rounding_rule_reaches_from_driver() -> None:
    """0.0625 pt is exactly representable, so 62.5 mpt is an exact half: half-away gives 63 and
    banker's would give 62. The whole transform is therefore a pure integer function."""
    quad = _quad([(0.0625, 0.0625), (1, 0.0625), (1, 1), (0.0625, 1)])
    assert quad.x0 == 63
    assert quad.y0 == 63


def test_bottomleft_flips_in_the_drivers_own_unit_then_scales() -> None:
    """`y' = page_h - y`, then x1000 (03 section 7.1). PDF user space is the row this exists for."""
    quad = _quad(
        [(0, 841.89), (10, 841.89), (10, 836.89), (0, 836.89)],
        origin="bottomleft",
        page_h=841.89,
    )
    assert quad == Quad(0, 0, 10_000, 0, 10_000, 5_000, 0, 5_000)


def test_px_without_a_dpi_is_ow_quad_no_dpi() -> None:
    """03:1388 and 03:3211. `dpi` is REQUIRED for `unit="px"`; this is also what rejects the
    normalized-0..1 layout-model row, which arrives as px with `dpi=None` (03:1389)."""
    with pytest.raises(ModelError) as caught:
        _quad([(0, 0), (1, 0), (1, 1), (0, 1)], unit="px", dpi=None)
    assert caught.value.code() == "OW_QUAD_NO_DPI"
    assert caught.value.fix
    assert caught.value.is_fatal()


@pytest.mark.parametrize("unit", ["pt", "emu"])
def test_a_dpi_is_refused_where_it_means_nothing(unit) -> None:
    """Silently ignoring an argument is the failure mode 03 section 7.1 exists to prevent; its own
    example passes `dpi=None` with `pt` (03:1380)."""
    with pytest.raises(ValueError, match="meaningful only"):
        _quad([(0, 0), (1, 0), (1, 1), (0, 1)], unit=unit, dpi=72.0)


@pytest.mark.parametrize("dpi", [0.0, -72.0])
def test_a_non_positive_dpi_is_refused(dpi) -> None:
    with pytest.raises(ValueError, match="dpi must be > 0"):
        _quad([(0, 0), (1, 0), (1, 1), (0, 1)], unit="px", dpi=dpi)


@pytest.mark.parametrize("rotation", [0, 360, -360])
def test_an_unrotated_page_is_accepted(rotation) -> None:
    assert _quad([(0, 0), (1, 0), (1, 1), (0, 1)], rotation=rotation).rect() == (0, 0, 1000, 1000)


@pytest.mark.parametrize("rotation", [90, 180, 270, -90])
def test_a_rotated_page_is_refused_and_the_refusal_names_the_missing_page_width(rotation) -> None:
    """PLAN DEFECT, reported. 03:1385 wants "un-rotate by -rotation about the page centre"; the
    signature at 03:174-176 takes `page_h` and no page WIDTH, and a quarter turn about the centre
    of a `(w, h)` box needs both extents. Guessing which extent `page_h` is would bake an
    unverifiable frame into every stored quad, which is the defect class this module exists to
    prevent, so the refusal is loud. One added `page_w` parameter closes it."""
    with pytest.raises(ValueError, match="needs the page WIDTH"):
        _quad([(0, 0), (1, 0), (1, 1), (0, 1)], rotation=rotation)


@pytest.mark.parametrize("rotation", [45, 1, -13])
def test_a_rotation_that_is_not_a_quarter_turn_is_refused(rotation) -> None:
    with pytest.raises(ValueError, match="quarter turn"):
        _quad([(0, 0), (1, 0), (1, 1), (0, 1)], rotation=rotation)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"origin": "topright"}, "origin must be one of"),
        ({"unit": "mm"}, "unit must be one of"),
        ({"page_h": 0.0}, "page_h must be > 0"),
        ({"page_h": -1.0}, "page_h must be > 0"),
        ({"page_h": float("nan")}, "must be finite"),
    ],
)
def test_the_frame_arguments_are_closed_vocabularies(kwargs, match) -> None:
    with pytest.raises((ValueError, ModelError), match=match):
        _quad([(0, 0), (1, 0), (1, 1), (0, 1)], **kwargs)


@pytest.mark.parametrize(
    ("pts", "match"),
    [
        ([(0, 0), (1, 0), (1, 1)], "exactly 4 corners"),
        ([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)], "exactly 4 corners"),
        ("0011", "must be a sequence"),
        (42, "must be a sequence"),
        ([(0, 0), (1, 0), (1, 1), 7], r"must be an .x, y. pair"),
        ([(0, 0), (1, 0), (1, 1), (0, 1, 2)], r"must be an .x, y. pair"),
        ([(0, 0), (1, 0), (1, 1), (0, float("inf"))], "must be finite"),
        ([(0, 0), (1, 0), (1, 1), (0, "1")], "must be a real number"),
        ([(0, 0), (1, 0), (1, 1), (0, True)], "must be a real number"),
    ],
)
def test_a_polygon_that_is_not_four_finite_corners_is_refused(pts, match) -> None:
    """Four corners, not a rect and not an arbitrary polygon (03:1393): reducing a hexagon to
    four corners would be synthesizing geometry, which INV-9 forbids outright."""
    with pytest.raises((TypeError, ValueError), match=match):
        _quad(pts)


def test_a_coordinate_outside_i32_is_refused() -> None:
    """03:180-184: the largest representable page is ~2,147,483 pt. A 0..1 normalized layout model
    is rejected earlier, by the dpi rule; this catches a frame error four orders of magnitude
    out."""
    with pytest.raises(ValueError, match="outside i32"):
        _quad([(0, 0), (3e6, 0), (3e6, 1), (0, 1)], page_h=4e6)


def test_an_all_zero_quad_is_refused() -> None:
    """P6: "no quad is all-zero" (03:2990). INV-9's answer to "no geometry" is `quad IS NULL` plus
    a stated `Locus.reason`, never a zero rectangle."""
    with pytest.raises(ValueError, match="all-zero quad"):
        _quad([(0, 0), (0, 0), (0, 0), (0, 0)])


def test_corners_are_reordered_top_left_then_clockwise_whatever_the_driver_handed_us() -> None:
    """03:1398. A driver emitting counter-clockwise polygons must not produce quads that fail a
    containment test for no visible reason, so all 24 orderings of one rectangle's corners give
    one Quad."""
    corners = [(0, 0), (10, 0), (10, 5), (0, 5)]
    results = {_quad(list(permutation)) for permutation in itertools.permutations(corners)}
    assert results == {Quad(0, 0, 10_000, 0, 10_000, 5_000, 0, 5_000)}


def test_the_reordering_is_idempotent_and_a_permutation() -> None:
    corners = ((10, 5), (0, 0), (0, 5), (10, 0))
    ordered = _order_topleft_clockwise(corners)
    assert sorted(ordered) == sorted(corners)
    assert _order_topleft_clockwise(ordered) == ordered
    assert ordered == ((0, 0), (10, 0), (10, 5), (0, 5))


def test_the_half_plane_buckets_are_the_topleft_frames() -> None:
    """y grows DOWNWARD, so a visually clockwise walk is increasing `atan2(dy, dx)`: top-left is
    about -135 degrees and lands in bucket 0, bottom-left about +135 and lands in bucket 1."""
    assert _half_plane(-1, -1) == 0
    assert _half_plane(1, -1) == 0
    assert _half_plane(1, 1) == 1
    assert _half_plane(-1, 1) == 1
    assert _half_plane(0, 0) == 2


class _Blake2Stream:
    """A reproducible keystream. `random` is banned repo-wide; sampling is blake2b."""

    def __init__(self, seed: bytes) -> None:
        self._seed = seed
        self._counter = 0
        self._buf = b""
        self._pos = 0

    def byte(self) -> int:
        if self._pos >= len(self._buf):
            block = self._seed + self._counter.to_bytes(8, "big")
            self._buf = hashlib.blake2b(block, digest_size=64).digest()
            self._counter += 1
            self._pos = 0
        value = self._buf[self._pos]
        self._pos += 1
        return value

    def below(self, n: int) -> int:
        return self.byte() % n


FUZZ_CASES = 4_000


def test_fuzz_from_driver_is_deterministic_and_stays_inside_its_own_invariants() -> None:
    """The three properties a caller relies on, over 4,000 blake2b-drawn quadrilaterals: the
    result is byte-identical across calls (INV-24 territory -- `layout_digest` is keyed on it),
    every coordinate is a rounded transform of some input coordinate, and the stored corner
    sequence is its own fixpoint under the reordering."""
    stream = _Blake2Stream(b"omniweave.spans.quad")
    for _ in range(FUZZ_CASES):
        pts = [(stream.below(2_000) / 4, stream.below(2_000) / 4) for _ in range(4)]
        first = _quad(pts)
        assert _quad(pts) == first
        assert _quad(list(reversed(pts))) == first  # winding direction is not identity
        expected = {_round_half_away(value * 1_000) for point in pts for value in point}
        assert set(first) <= expected
        corners = tuple((first[i], first[i + 1]) for i in range(0, 8, 2))
        assert _order_topleft_clockwise(corners) == corners


def test_rect_is_the_bounding_box_of_the_four_corners() -> None:
    skewed = _quad([(1, 0), (10, 2), (9, 6), (0, 4)])
    assert skewed.rect() == (0, 0, 10_000, 6_000)
    assert RECT.rect() == (0, 0, 10_000, 5_000)


def test_the_bare_eight_int_form_is_the_stores_decode_path() -> None:
    """The `quad` column is "8 x i32 LE, or NULL" (charter.md:1039, 07:1027), so `Quad(*ints)` is
    how a stored blob becomes a value again; 06:2093-2097 prints exactly that. Enforcement of
    "nothing else calls it" is lexical (01:1191's grep) plus P6's patch test, because a
    `NamedTuple` cannot make `__new__` private and 03:168 prints `class Quad(NamedTuple)`."""
    decoded = Quad(0, 0, 10_000, 0, 10_000, 5_000, 0, 5_000)
    assert decoded == _quad([(0, 0), (10, 0), (10, 5), (0, 5)])
    assert len(decoded) == 8


# ---------------------------------------------------------------------------
# SpanMap -- where the view system and the block-text system meet.
# ---------------------------------------------------------------------------


class _Map:
    """A minimal conforming `SpanMap`: two intervals, the second synthetic."""

    view_id = "md/1/7c3f"

    def block_at(self, offset: int) -> tuple[int, TextSpan] | None:
        return (7, TextSpan(0, offset)) if offset < 3 else None

    def is_synthetic(self, offset: int) -> bool:
        return offset >= 3

    def offsets_of(self, b: int) -> tuple[int, int]:
        return (0, 3) if b == 7 else (0, 0)

    def to_text(self, s: RenderSpan) -> list[tuple[int, TextSpan]]:
        s.require_view(self.view_id)
        return [(7, TextSpan(s.a, min(s.b, 3)))]


def test_a_conforming_span_map_satisfies_the_protocol() -> None:
    assert isinstance(_Map(), SpanMap)


@pytest.mark.parametrize(
    "missing", ["block_at", "is_synthetic", "offsets_of", "to_text", "view_id"]
)
def test_a_span_map_missing_any_member_does_not_satisfy_the_protocol(missing) -> None:
    """`is_synthetic()` is in the list on purpose: 03:225 added it because section 16.5's law is
    "every offset lifts to exactly one block OR is marked synthetic", and a three-method Protocol
    could not express the second half, which left the law unassertable."""
    stub = type("Stub", (), {k: v for k, v in vars(_Map).items() if k != missing})
    assert not isinstance(stub(), SpanMap)


def test_the_protocol_speaks_render_span_in_and_text_span_out() -> None:
    """The two systems meet here and nowhere else, so the direction of every signature is the
    whole point: a view offset or a `RenderSpan` goes in, a `TextSpan` comes out."""
    hints = get_type_hints(SpanMap.block_at)
    assert hints["offset"] is int
    assert TextSpan in get_args(get_args(hints["return"])[0])
    to_text = get_type_hints(SpanMap.to_text)
    assert to_text["s"] is RenderSpan
    assert TextSpan in get_args(get_args(to_text["return"])[0])


def test_16_5s_projection_law_is_expressible_over_the_protocol(plan) -> None:
    """ "Every character of `P(S)` either lifts to exactly one `(BlockId, TextSpan)` through the
    `SpanMap`, or is marked synthetic in that map. There is no third case." (03:2967)."""
    plan.require()
    assert plan.grep(r"There is no third case", documents=[DOC])
    span_map = _Map()
    for offset in range(6):
        assert (span_map.block_at(offset) is not None) or span_map.is_synthetic(offset)
    assert span_map.to_text(RenderSpan("md/1/7c3f", 0, 2)) == [(7, TextSpan(0, 2))]
    with pytest.raises(TypeError, match="mis-lift"):
        span_map.to_text(RenderSpan("gfm/1/7c3f", 0, 2))


def test_the_module_declares_no_enum_and_so_cannot_re_home_a_vocabulary() -> None:
    """INV-21, counted as DEFINITION SITES: the fifteen closed vocabularies have one home,
    `omniweave_core.model.enums`, and this module imports `OsKind` from it rather than declaring
    a sixteenth spelling of the same five tags."""
    text = Path(spans.__file__).read_text(encoding="utf-8")
    assert "class OsKind" not in text
    assert "from omniweave_core.model.enums import OsKind" in text
    assert OriginBytes.os_kind is OsKind.BYTES
