"""The three non-interchangeable coordinate systems, and the one geometry frame.

Implements 03-document-model.md section 2.3 (`Quad` -- one stored frame, one constructor) and
section 2.4 (the three coordinate systems), with their normative expansions in section 7.1 (the
driver-frame transform table), section 7.2 (`OriginSpan`'s five variants and the seven columns
they fill), section 7.4 (`TextSpan` is not a byte range) and section 16.2 (`view_id`). The
addressing convention the two span systems disagree about **on purpose** is
07-store-and-retrieval.md section 8.2 (:2496-2504), and the principle all four types obey is
01-principles.md P-6 ("put the constraint in the type; normalise once, at the boundary").

**Three systems, three types, and no implicit conversion, ever** (03:227, 01:955-966).

| system                 | type here                   | units                             |
|------------------------|-----------------------------|-----------------------------------|
| block text             | `TextSpan(a, b)`            | characters of ONE block's text    |
| the original container | `OriginSpan`, 5 variants    | bytes, child indices, glyphs, px  |
| a serialized view      | `RenderSpan(view_id, a, b)` | characters of one view            |

`Quad` is not one of the three: it is the geometry FRAME (03 section 2.3 is its own section,
beside section 2.4's three), and its discipline is different -- one stored frame, normalised
once, at the boundary, inside `Quad.from_driver`.

**Why this file is written defensively.** `_notes/s10-fix-ledger.md` D3 ("blocking 2, part 2") is
the defect this cluster exists to prevent: `GraphSink.mention` produced `ts_a`/`ts_b` from
`normalize_k`'s OUTPUT space and stored them as offsets into `block.text`. Both are half-open
integer pairs, so no CHECK, no invariant and no property test in the plan could see it, and every
L3 span in every store would have been silently wrong and unrepairable without re-parsing the
corpus. The plan's fix is that `ground()` (06-structure-extraction.md section 1.7) is the SOLE
producer of a `ts_a`/`ts_b` and that `normalize_k` carries a back-map (`omniweave_core.ident`, on
disk). This module's contribution is the other half:

1. Each system is a DISTINCT NOMINAL type. None of the three spans is a tuple subclass, so none
   is structurally interchangeable with another or with a bare `(a, b)`; `Quad` alone is a tuple,
   and it has eight fields, so it cannot be confused with a two-field span either.
2. The asymmetric slicing convention lives ON THE TYPES as `slice_of()`, one method name and two
   different meanings: `TextSpan` is half-open `[a, b)` in characters of a `str`, `OriginBytes`
   is `(offset, LENGTH)` in `bytes`. 07:2502's semgrep rule rejects `part[os_a:os_b]` and
   `text[ts_a:ts_a+ts_b]` -- the two ways to get this wrong -- and a caller that never writes the
   slice by hand cannot write either of them. `TextSpan.slice_of` refuses `bytes` and
   `OriginBytes.slice_of` refuses `str`, so the containers cannot be swapped either.
3. Every field is validated at construction, so a foreign span, a `bool`, a `float` or a
   `Quad`-shaped bare tuple raises at the boundary rather than becoming a stored row.

`OriginGlyphs` deliberately has NO `slice_of`: a glyph index is the extractor's own space and is
recovered by re-extraction, never by slicing bytes (03:1425, 03:1470-1476).

Stdlib only, like everything under `omniweave_core.model` (03 section 2). This module is inside
one of the nine LAZY subpackages (11-repo-layout.md section 1.3), so nothing eager may import it:
G17 asserts a bare `import omniweave_core` loads none of them.

Tier T-SCHEMA: 02-architecture.md section 2 row 24.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import cmp_to_key
from types import MappingProxyType
from typing import ClassVar, Final, Literal, NamedTuple, Protocol, runtime_checkable

from omniweave_core.errors import ModelError
from omniweave_core.model.enums import OsKind

__all__ = [
    "SERIALIZER_CAPS",
    "OriginBytes",
    "OriginGlyphs",
    "OriginNodePath",
    "OriginNone",
    "OriginPixels",
    "OriginSpan",
    "Quad",
    "RenderSpan",
    "SpanMap",
    "TextSpan",
]


# ---------------------------------------------------------------------------
# 0. The shared field guards.
#
# Every offset in this module is a plain `int`. `bool` is excluded deliberately: `True` is an
# `int` in Python, and `TextSpan(a=True, b=3)` is a bug that would otherwise store `1`. A foreign
# span, a `float` and a NumPy integer all fail the same check, which is the cross-system
# rejection stated in the module docstring.
# ---------------------------------------------------------------------------


def _as_int(value: object, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{what} must be an int, not {type(value).__name__} ({value!r})"
        raise TypeError(msg)
    return value


def _check_nonneg(value: object, what: str) -> None:
    if _as_int(value, what) < 0:
        msg = f"{what} must be >= 0, not {value!r}"
        raise ValueError(msg)


def _as_nonempty_str(value: object, what: str) -> str:
    if not isinstance(value, str):
        msg = f"{what} must be a str, not {type(value).__name__} ({value!r})"
        raise TypeError(msg)
    if not value:
        msg = f"{what} must not be empty"
        raise ValueError(msg)
    return value


# ---------------------------------------------------------------------------
# 1. Geometry -- 03 section 2.3 and section 7.1.
# ---------------------------------------------------------------------------

#: 1 pt = 1000 millipoints. The stored unit (03:168).
_MPT_PER_PT: Final = 1000

#: 1 inch = 72 pt = 72,000 mpt. The `unit="px"` row of 03 section 7.1's table: `x 72000 / dpi`.
_MPT_PER_INCH: Final = 72_000

#: 1 pt = 12,700 EMU. The OOXML DrawingML row: `x 1000 / 12700` (03:1387).
_EMU_PER_PT: Final = 12_700

#: Four corners, not a rect (03:1393). A polygon with any other vertex count would have to be
#: REDUCED to four, and reducing it is synthesizing geometry -- INV-9 forbids that outright.
_CORNERS: Final = 4

#: i32, never float (03:168). The range is not a practical constraint: an A4 page is
#: 595,280 x 841,890 mpt, four orders of magnitude below the ceiling (03:180-184).
_I32_MIN: Final = -(2**31)
_I32_MAX: Final = 2**31 - 1

_ORIGINS: Final = ("topleft", "bottomleft")
_UNITS: Final = ("pt", "px", "emu")

#: 03:1385 accepts a display rotation. Only `0` is COMPUTABLE from the printed signature -- see
#: `_reject_rotation`.
_QUARTER_TURNS: Final = (0, 90, 180, 270)
_FULL_TURN: Final = 360


def _round_half_away(value: float) -> int:
    """Round-half-away-from-zero on the millipoint (03:1396).

    NOT `round()`, which is half-to-even: under banker's rounding 62.5 mpt stores as 62 while
    63.5 mpt stores as 64, so two coordinates a millipoint apart round in opposite directions and
    `layout_digest` stops being a pure function of the driver's numbers. `math.floor`/`math.ceil`
    on an IEEE double is exact integer arithmetic on every platform, which is the whole point of
    fixed point here: a float bbox makes `layout_digest` libm- and platform-dependent (03:178).
    """
    if value >= 0:
        return math.floor(value + 0.5)
    return math.ceil(value - 0.5)


def _as_coord(value: object, what: str) -> float:
    """A driver coordinate: a finite real. `bool` and `complex` are not coordinates."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        msg = f"{what} must be a real number, not {type(value).__name__} ({value!r})"
        raise TypeError(msg)
    if not math.isfinite(value):
        msg = f"{what} must be finite, not {value!r}"
        raise ValueError(msg)
    return float(value)


def _driver_points(pts: object) -> tuple[tuple[float, float], ...]:
    """Exactly four finite `(x, y)` pairs, in the driver's own frame and unit."""
    if isinstance(pts, (str, bytes)) or not isinstance(pts, Iterable):
        msg = f"pts must be a sequence of four (x, y) pairs, not {type(pts).__name__}"
        raise TypeError(msg)
    items = tuple(pts)
    if len(items) != _CORNERS:
        msg = (
            f"pts must hold exactly {_CORNERS} corners, not {len(items)}: a Quad is four corners "
            "(03:1393) and reducing another polygon to four would synthesize geometry (INV-9)"
        )
        raise ValueError(msg)
    out: list[tuple[float, float]] = []
    for index, item in enumerate(items):
        try:
            x, y = item
        except (TypeError, ValueError) as exc:
            msg = f"pts[{index}] must be an (x, y) pair, not {item!r}"
            raise TypeError(msg) from exc
        out.append((_as_coord(x, f"pts[{index}].x"), _as_coord(y, f"pts[{index}].y")))
    return tuple(out)


def _reject_stray_dpi(unit: str, dpi: float | None) -> None:
    """A `dpi` means nothing for `pt` or `emu`, and silently ignoring an argument is the failure
    mode 03 section 7.1 exists to prevent (its own example passes `dpi=None` with `pt`,
    03:1380)."""
    if dpi is not None:
        msg = f'dpi is meaningful only for unit="px"; unit="{unit}" was given dpi={dpi!r}'
        raise ValueError(msg)


def _mpt_scale(unit: str, dpi: float | None) -> tuple[int, float]:
    """The `(numerator, denominator)` of 03 section 7.1's table for `unit`.

    Two factors rather than one pre-multiplied float: `value * 1000 / 12700` keeps the division as
    exact as a double allows and reproduces everywhere, while `value * 0.07874015748031496` bakes
    in a rounding the table does not state.
    """
    if unit == "pt":
        _reject_stray_dpi(unit, dpi)
        return _MPT_PER_PT, 1.0
    if unit == "emu":
        _reject_stray_dpi(unit, dpi)
        return _MPT_PER_PT, float(_EMU_PER_PT)
    # unit == "px". `dpi` is REQUIRED and its absence is OW_QUAD_NO_DPI (03:1388, 03:3211). This
    # is also what rejects the "normalized 0..1 layout model" row of the same table (03:1389):
    # it arrives as px with `dpi=None`, and normalizing against the real page size first is the
    # driver's job, not ours.
    if dpi is None:
        raise ModelError(
            'Quad.from_driver(unit="px") needs a dpi: a raster coordinate has no length '
            "without one",
            symbol="OW_QUAD_NO_DPI",
            fix="pass dpi=<the render dpi> to Quad.from_driver, or convert to pt in the driver",
        )
    resolution = _as_coord(dpi, "dpi")
    if resolution <= 0:
        msg = f"dpi must be > 0, not {dpi!r}"
        raise ValueError(msg)
    return _MPT_PER_INCH, resolution


def _reject_rotation(rotation: object) -> None:
    """PLAN DEFECT. `from_driver`'s printed signature cannot un-rotate.

    03:1385 says the `/Rotate 90` case is "flip, then un-rotate by -rotation about the page
    centre", but the signature at 03:174-176 takes `page_h` and no page WIDTH. Un-rotating a
    quarter turn about the centre of a `(w, h)` box needs both extents: only ONE of the two
    90-degree turns is recoverable from a single extent, and WHICH one depends on whether
    `page_h` is the unrotated height (03:1391, "`page.w_mpt`/`h_mpt` are the unrotated page box")
    or the display height a rotation-aware reader returns. Guessing between the two readings
    would bake an unverifiable coordinate frame into every stored quad -- exactly the class of
    error this module exists to prevent -- so a non-zero rotation is REFUSED rather than
    approximated. Reported to the owner; one added `page_w` parameter closes it.
    """
    turn = _as_int(rotation, "rotation") % _FULL_TURN
    if turn not in _QUARTER_TURNS:
        msg = f"rotation must be a quarter turn, not {rotation!r}"
        raise ValueError(msg)
    if turn != 0:
        msg = (
            f"rotation={rotation!r} is not implementable from this signature: un-rotating about "
            "the page centre needs the page WIDTH and Quad.from_driver takes only page_h "
            "(03:1385 against 03:174-176 -- reported as a plan defect). Hand coordinates in the "
            "unrotated page frame and record the display rotation on `page.rotation`."
        )
        raise ValueError(msg)


def _as_page_extent(page_h: object) -> float:
    height = _as_coord(page_h, "page_h")
    if height <= 0:
        msg = f"page_h must be > 0, not {page_h!r}"
        raise ValueError(msg)
    return height


def _check_corners(corners: Sequence[tuple[int, int]]) -> None:
    for index, corner in enumerate(corners):
        for name, value in (("x", corner[0]), ("y", corner[1])):
            if not _I32_MIN <= value <= _I32_MAX:
                msg = (
                    f"corner {index}.{name} = {value} mpt is outside i32; the largest "
                    "representable page is ~2,147,483 pt (03:180-184)"
                )
                raise ValueError(msg)
    # P6: "no quad is all-zero" (03:2990). An all-zero quad is the shape a fallback to the page
    # box or a zero-initialised struct produces, and INV-9's answer to "no geometry" is
    # `quad IS NULL` plus a stated `Locus.reason`, never a zero rectangle.
    if all(value == 0 for corner in corners for value in corner):
        msg = "an all-zero quad is not geometry: pass no quad and state a reason (INV-9, P6)"
        raise ValueError(msg)


def _half_plane(dx: int, dy: int) -> int:
    """Which side of the branch cut a centroid-relative corner falls on.

    The frame is topleft, so y grows DOWNWARD and a visually clockwise walk is increasing
    `atan2(dy, dx)` over `(-pi, pi]`: top-left is about -135 degrees, top-right -45, bottom-right
    +45, bottom-left +135. Bucket 0 is `(-pi, 0]`, bucket 1 is `(0, pi]`, and bucket 2 is the zero
    vector -- a corner sitting exactly on the centroid, which only a degenerate quad produces.
    """
    if dy < 0 or (dy == 0 and dx > 0):
        return 0
    if dy > 0 or (dy == 0 and dx < 0):
        return 1
    return 2


def _order_topleft_clockwise(corners: Sequence[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    """Re-order four corners to top-left-then-clockwise in the stored frame (03:1398).

    `from_driver` re-orders whatever the driver handed it, so a driver emitting counter-clockwise
    polygons does not produce quads that fail a containment test for no visible reason. The
    comparator is INTEGER arithmetic -- a cross product against a centroid scaled by the corner
    count, so no division and no `atan2`. A libm call in the ORDERING would put a
    platform-dependent permutation into `layout_digest`, which is a float bbox's defect one step
    removed.
    """
    total_x = sum(x for x, _ in corners)
    total_y = sum(y for _, y in corners)
    count = len(corners)

    def offset(corner: tuple[int, int]) -> tuple[int, int]:
        return count * corner[0] - total_x, count * corner[1] - total_y

    def compare(left: tuple[int, int], right: tuple[int, int]) -> int:
        u, v = offset(left), offset(right)
        bucket_u, bucket_v = _half_plane(*u), _half_plane(*v)
        if bucket_u != bucket_v:
            return -1 if bucket_u < bucket_v else 1
        cross = u[0] * v[1] - u[1] * v[0]
        if cross > 0:  # `u` is the earlier angle inside a half-plane that spans less than pi.
            return -1
        if cross < 0:
            return 1
        # Collinear with the centroid, or the same point twice: a degenerate quad, where the
        # walk order is genuinely ambiguous. Break the tie on the corner itself so the order is
        # TOTAL and the stored quad is a function of the corner SET, never of the order the
        # driver happened to emit -- otherwise a driver reordering its own output would move
        # `layout_digest` and invalidate every cache keyed on it.
        if left != right:
            return -1 if left < right else 1
        return 0

    return tuple(sorted(corners, key=cmp_to_key(compare)))


class Quad(NamedTuple):
    """Four corners in 1/1000 pt, topleft origin, unrotated page. i32, never float (03:168).

    Eight ints and not a rect, because a rotated text box, a skewed scan and a curved-baseline
    OCR line all have a real quadrilateral and an axis-aligned rect silently over-claims
    (03:1393). `rect()` is a computed VIEW for consumers that only need a bounding box, never a
    field.

    **`from_driver` is the only DRIVER-frame constructor** (03:178, INV-9, conformance P6 at
    03:2990, which asserts it by patching `from_driver` to raise). The bare eight-int form that
    `NamedTuple` gives is the STORE's decode path and nothing else: the `quad` column is
    "8 x i32 LE, or NULL" (charter.md:1039, 07:1027), so `Quad(*ints)` is how a stored blob
    becomes a value again -- 06:2093-2097 spells exactly that out at the one site that prints a
    `Quad(...)` literal. Enforcement of "nothing else calls it" is lexical, by 01:1191's grep for
    `Quad(` outside `Quad.from_driver`; a `NamedTuple` cannot make `__new__` private, and the plan
    prints `class Quad(NamedTuple)` at two sites (03:168, 06:2093), so the type is the plan's and
    the grep is the gate. That semgrep rule is not yet in `tools/semgrep/omniweave.yaml`;
    reported.
    """

    x0: int
    y0: int
    x1: int
    y1: int
    x2: int
    y2: int
    x3: int
    y3: int

    def rect(self) -> tuple[int, int, int, int]:
        """The axis-aligned bounding box `(x_min, y_min, x_max, y_max)`, computed on demand."""
        xs = (self.x0, self.x1, self.x2, self.x3)
        ys = (self.y0, self.y1, self.y2, self.y3)
        return min(xs), min(ys), max(xs), max(ys)

    @classmethod
    def from_driver(
        cls,
        pts: Sequence[tuple[float, float]],
        *,
        origin: Literal["topleft", "bottomleft"],
        unit: Literal["pt", "px", "emu"],
        page_h: float,
        dpi: float | None,
        rotation: int,
    ) -> Quad:
        """Normalise a driver's own frame to the stored one, exactly once, at the boundary.

        03 section 7.1's table, row by row: `bottomleft` flips `y' = page_h - y` IN THE DRIVER'S
        UNIT and then scales; `pt` scales by 1000; `emu` by `1000 / 12700`; `px` by
        `72000 / dpi`, and a missing `dpi` is `OW_QUAD_NO_DPI`. Rounding is half-away-from-zero
        per coordinate AFTER the affine transform, so the whole operation is a pure integer
        function of the inputs and reproduces on every platform.

        Every keyword is required and none carries a default (03:174-176). `page.quad_origin`
        records what the driver handed us, not what is stored, so an audit can re-derive this
        transform (03:1400).
        """
        if origin not in _ORIGINS:
            msg = f"origin must be one of {_ORIGINS}, not {origin!r}"
            raise ValueError(msg)
        if unit not in _UNITS:
            msg = f"unit must be one of {_UNITS}, not {unit!r}"
            raise ValueError(msg)
        height = _as_page_extent(page_h)
        numerator, denominator = _mpt_scale(unit, dpi)
        _reject_rotation(rotation)
        points = _driver_points(pts)
        if origin == "bottomleft":
            points = tuple((x, height - y) for x, y in points)
        corners = tuple(
            (
                _round_half_away(x * numerator / denominator),
                _round_half_away(y * numerator / denominator),
            )
            for x, y in points
        )
        _check_corners(corners)
        return cls(*(value for corner in _order_topleft_clockwise(corners) for value in corner))


# ---------------------------------------------------------------------------
# 2. System one -- `OriginSpan`, the address in the original container.
#    03 section 2.4 and section 7.2.
#
# `os_b` is a LENGTH, not an end offset, at every site: the column, the wire (`os.len`) and the
# value type (`OriginBytes.length`) -- one quantity, one spelling, three places (03:1447). That is
# why no variant here has a field named `b` or `end`, and why `slice_of` is `part[a : a + len]`.
#
# The variant tag is exposed as `os_kind`, matching the column and the wire key, and it is the
# `OsKind` member imported from `omniweave_core.model.enums` rather than a string literal: the
# `origin_span_kind` `enum_val` ordinals ARE the stored values (03 section 2.1), and two CHECK
# constraints resolve those members out of `enum_val` BY NAME (03:1438, 03:1443). It is NOT
# spelled `kind`, because `Block.kind` is a different closed vocabulary and one attribute name
# holding two vocabularies is the INV-21 failure the charter's `Layer` collision is written from.
# ---------------------------------------------------------------------------

#: The `<codec>/<errors>` decode policy is two parts, exactly. Conformance P7 splits it as
#: `os_codec.split("/", 1)` (03:2999) and decode symmetry is an invariant (03:1466): both sides of
#: a verification decode with the same codec AND the same error policy.
_CODEC_PARTS: Final = 2


def _check_codec(value: object, what: str) -> None:
    parts = _as_nonempty_str(value, what).split("/")
    if len(parts) != _CODEC_PARTS or not all(parts):
        msg = (
            f"{what} must be '<codec>/<errors>' such as 'utf-8/strict' or 'cp1252/replace' "
            f"(03:1466), not {value!r}"
        )
        raise ValueError(msg)


def _check_length(value: object, what: str) -> None:
    """An `os_b` is a length: `>= 0` by 03's CHECK, and never `0` by 07:2502.

    PLAN CONTRADICTS ITSELF and the stricter reading is implemented, because it satisfies both.
    03:1444 prints `CHECK (os_b IS NULL OR os_b >= 0)` -- the DDL literal, and 03 section 7.2 is
    the declared home of the column mapping. 07:2502 says "`os_b == 0` is a CHECK-rejected value
    rather than a sentinel -- an empty span is `os_kind = 'none'`", which is a statement about the
    MODEL: an empty origin span has a variant of its own and does not need a second spelling. A
    value type that rejects `0` can never produce a row violating `>= 0`, so both loci are
    honoured; the DDL literal stays 03's and is not this module's to write.
    """
    if _as_int(value, what) < 1:
        msg = f"{what} is a LENGTH and must be >= 1; an empty span is OriginNone() (07:2502)"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class OriginBytes:
    """Flat text: `.txt`, `.md`, `.csv`, an `.html` source, a JSON blob (03:1415).

    Re-verified by `nfc(part_bytes[os_a : os_a + os_b].decode(*os_codec.split("/", 1)))
    == block.text` -- decode under the recorded policy, then NFC and nothing else. The `bytes`
    branch is the one whose predicate READS `os_codec`, which is why a NULL codec makes it
    unevaluable rather than merely undocumented and why `codec` carries no default here (03:1440).
    """

    part: str
    start: int
    length: int
    codec: str

    os_kind: ClassVar[OsKind] = OsKind.BYTES

    def __post_init__(self) -> None:
        _as_nonempty_str(self.part, "OriginBytes.part")
        _check_nonneg(self.start, "OriginBytes.start")
        _check_length(self.length, "OriginBytes.length")
        _check_codec(self.codec, "OriginBytes.codec")

    def decode_args(self) -> tuple[str, str]:
        """`(codec, errors)` -- P7's `os_codec.split("/", 1)`, split in ONE place."""
        codec, errors = self.codec.split("/", 1)
        return codec, errors

    def slice_of(self, part_bytes: bytes) -> bytes:
        """`part_bytes[start : start + length]` -- OFFSET AND LENGTH, never a range.

        Refuses a `str`: a `bytes` origin addresses the container's bytes, and slicing
        `block.text` with it is the coordinate-system confusion this module exists to stop.
        """
        if not isinstance(part_bytes, (bytes, bytearray, memoryview)):
            msg = (
                "OriginBytes.slice_of takes the part's BYTES, not "
                f"{type(part_bytes).__name__}: an OriginSpan never indexes block.text (03:1525)"
            )
            raise TypeError(msg)
        end = self.start + self.length
        if end > len(part_bytes):
            msg = f"[{self.start}, {end}) is outside a part of {len(part_bytes)} bytes"
            raise ValueError(msg)
        return bytes(part_bytes[self.start : end])


@dataclass(frozen=True, slots=True)
class OriginNodePath:
    """OOXML, ODF, any XML container: a child-index path, stored as `os_path = '0.3.1.7'`.

    A byte offset into `word/document.xml` is destroyed by any attribute reordering on
    re-serialization; a child-index path is stable under edits to other subtrees, which is
    ppt-master's verified answer (`SourceRefRecord.source_path: tuple[int, ...]`). A byte range is
    right for flat text and wrong for containers (03:1455-1462). Re-verified by
    `nfc(node_text(part, os_path)) == block.text`.
    """

    part: str
    path: tuple[int, ...]

    os_kind: ClassVar[OsKind] = OsKind.NODEPATH

    def __post_init__(self) -> None:
        _as_nonempty_str(self.part, "OriginNodePath.part")
        # A tuple, not a list: every value type here is frozen, and a mutable path on the
        # framework's provenance chain is a bug waiting for its first author (03:250).
        if not isinstance(self.path, tuple):
            msg = f"OriginNodePath.path must be a tuple, not {type(self.path).__name__}"
            raise TypeError(msg)
        # PLAN SILENT on emptiness; chosen and reported. `()` renders as `os_path = ''`, and 03
        # section 7.2's column mapping gives `os_path = NULL` for every non-nodepath variant, so
        # `''` would be a second spelling of "no path" in a column whose NULL-ness is a CHECK.
        if not self.path:
            msg = "OriginNodePath.path must name at least one child index"
            raise ValueError(msg)
        for index, step in enumerate(self.path):
            _check_nonneg(step, f"OriginNodePath.path[{index}]")


@dataclass(frozen=True, slots=True)
class OriginGlyphs:
    """A PDF text layer: a glyph run in ONE extractor's own index space (03:1470).

    **`(part, extractor, start, length)`, NOT `(page, extractor, start, length)`** -- 03:220 is
    the ruling and this type honours it. INV-10's glyphs branch re-verifies by re-extracting the
    run from a RETAINED part, so the variant must name the part whose `store_ref` the invariant
    checks; the page is `block.page`, and storing it twice would be two names for one fact. The
    charter's own DDL comment already gives the part spelling for this case:
    `os_part = 'pdf:page=12/content=0'`.

    `extractor` is an exact identity such as `pdftext@0.6`, because the glyph index space is the
    EXTRACTOR's, not the PDF's. There is deliberately no `slice_of`: the run is recovered by
    re-extraction under the recorded extractor, never by slicing bytes.

    Two sites still print the rejected four-tuple -- `OriginGlyphs(page=13, ...)` at 06:2099, and
    `os_page`/`os_start`/`os_len` in the SQL at 06:2077-2081, three column names the charter's
    `block` DDL does not carry (charter.md:1040-1046). Both are defective; reported.
    """

    part: str
    extractor: str
    start: int
    length: int

    os_kind: ClassVar[OsKind] = OsKind.GLYPHS

    def __post_init__(self) -> None:
        _as_nonempty_str(self.part, "OriginGlyphs.part")
        _as_nonempty_str(self.extractor, "OriginGlyphs.extractor")
        _check_nonneg(self.start, "OriginGlyphs.start")
        _check_length(self.length, "OriginGlyphs.length")


@dataclass(frozen=True, slots=True)
class OriginPixels:
    """OCR / VLM: the polygon IS the address, and nothing re-verifies it (03:1423).

    `pixels` can never reach `Quote.VERBATIM`: there is no character source to re-read. Neither
    field has an `os_*` column of its own -- 03 section 7.2's mapping row for `pixels` is NULL
    across all six payload columns, with `quad IS NOT NULL` as its additional CHECK -- so this
    variant round-trips through `block.page` and `block.quad`, which is the same
    two-names-for-one-fact argument 03:220 makes for `OriginGlyphs`.
    """

    page: int
    quad: Quad

    os_kind: ClassVar[OsKind] = OsKind.PIXELS

    def __post_init__(self) -> None:
        # 0-based, and the ORIGINAL source page, never a batch index (03:283).
        _check_nonneg(self.page, "OriginPixels.page")
        # A bare eight-tuple is refused: `Quad` is the type that carries the frame, and a tuple
        # that merely holds eight ints has not been through `from_driver`.
        if not isinstance(self.quad, Quad):
            msg = (
                f"OriginPixels.quad must be a Quad, not {type(self.quad).__name__}: the stored "
                "frame is Quad.from_driver's output (03:1376)"
            )
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class OriginNone:
    """Derived, synthetic, or a driver that carries no address.

    `OriginNone()` is a **value**, not a null (03:1464): `os_kind` is `NOT NULL` on the table, the
    union is nullable only as a whole, and a driver that leaves it unset gets `none` plus a
    recorded degradation in `achieved.origin_span`.
    """

    os_kind: ClassVar[OsKind] = OsKind.NONE


#: The tagged union (03:200). A `types.UnionType`, so `isinstance(x, OriginSpan)` is a real
#: runtime membership test over exactly the five variants and nothing else.
OriginSpan = OriginBytes | OriginNodePath | OriginGlyphs | OriginPixels | OriginNone


# ---------------------------------------------------------------------------
# 3. System two -- `TextSpan`, a character range in ONE block's own text.
#    03 section 2.4 and section 7.4.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextSpan:
    """Half-open `[a, b)` in characters of **this block's own `block.text`** (07:2496).

    Its units are Python characters after NFC, and it answers "which part of this paragraph". It
    is what docling's `charspan` actually is (`readingorder_model.py:418-421`), and it is NOT
    convertible to an `OriginSpan` by arithmetic: that direction is a QUERY (`locate()`), which
    re-decodes the part, descends the node's runs or re-extracts the glyph run, and reports a
    `precision` saying which (03:1537).

    The columns are `ts_a`/`ts_b`, not `a`/`b`, because the terminology lock reserves that pair
    (07:497); the FIELDS are `a`/`b` exactly as 03:203 prints them.

    **`a == b` is legal.** `mention` carries `CHECK (ts_a <= ts_b)` (charter.md:5042) and
    conformance P8 asserts `0 <= ts_a <= ts_b <= len(text)` (03:3002), so an empty range is a
    representable value here and it is `ground()` alone that will never mint one.
    """

    a: int
    b: int

    def __post_init__(self) -> None:
        _check_nonneg(self.a, "TextSpan.a")
        _as_int(self.b, "TextSpan.b")
        if self.b < self.a:
            msg = f"TextSpan is half-open [a, b) and needs a <= b, not ({self.a}, {self.b})"
            raise ValueError(msg)

    def slice_of(self, text: str) -> str:
        """`text[a:b]` -- a half-open RANGE, never an offset and a length.

        Refuses `bytes`: a `TextSpan` indexes the string omniweave reconstructed, and slicing a
        part's bytes with it is the confusion 07:2502's semgrep rule bans. This method is also the
        only place P8's third inequality (`ts_b <= len(text)`) can be checked, since the type alone
        cannot see the text.
        """
        if not isinstance(text, str):
            msg = (
                f"TextSpan.slice_of takes block.text, not {type(text).__name__}: a TextSpan "
                "never indexes the original container (03:1525)"
            )
            raise TypeError(msg)
        if self.b > len(text):
            msg = f"[{self.a}, {self.b}) is outside a text of {len(text)} characters (P8)"
            raise ValueError(msg)
        return text[self.a : self.b]


# ---------------------------------------------------------------------------
# 4. System three -- `RenderSpan`, a character range in one serialized view.
#    03 section 2.4, section 16.1 and section 16.2.
# ---------------------------------------------------------------------------

#: 03:214. Every serializer returns its `SpanMap`; there is no text-only serializer, because if
#: you have the text you have the map. A format whose entry is `False` may never be cited from,
#: and at release 1 there is no such format (03:2866). Read-only: a tenant flipping a cap at
#: runtime would make citability a mutable global.
SERIALIZER_CAPS: Final[Mapping[str, bool]] = MappingProxyType(
    {"md": True, "gfm": True, "html": True, "text": True, "otsl": True}
)

#: `view_id = "<fmt>/<serializer_version>/<options_digest[:4]>"`, e.g. `md/1/7c3f` (03:2887).
#: `options_digest` is `sha256_canonical`, so its prefix is lower-case hex; four characters,
#: because four is what the plan slices.
_VIEW_DIGEST_CHARS: Final = 4
_VIEW_ID_RE: Final = re.compile(r"^(?P<fmt>[a-z0-9]+)/(?P<version>[0-9]+)/(?P<digest>[0-9a-f]{4})$")


def _check_view_id(value: object, what: str) -> None:
    match = _VIEW_ID_RE.match(_as_nonempty_str(value, what))
    if match is None:
        msg = (
            f"{what} must be '<fmt>/<serializer_version>/<options_digest[:4]>' such as "
            f"'md/1/7c3f' (03:2887), not {value!r}"
        )
        raise ValueError(msg)
    fmt = match.group("fmt")
    if fmt not in SERIALIZER_CAPS:
        msg = f"{what} names format {fmt!r}, which is not one of {sorted(SERIALIZER_CAPS)}"
        raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class RenderSpan:
    """A half-open character range in ONE serialized view, carrying that view's identity.

    A view is a hash-pinned projection: when it is materialised its sha256 and byte length go into
    `manifest.views[]`, so a span into it is pinned to bytes that can be checked (03:2891). The
    `view_id` is not decoration -- it is what makes 03:2890's rule enforceable, and
    `require_view` is that rule.

    A `RenderSpan` cannot be built from a `TextSpan`'s two ints: `view_id` is required and comes
    first, so the accidental `RenderSpan(a, b)` is a `TypeError` rather than a span in the wrong
    coordinate system.
    """

    view_id: str
    a: int
    b: int

    def __post_init__(self) -> None:
        _check_view_id(self.view_id, "RenderSpan.view_id")
        _check_nonneg(self.a, "RenderSpan.a")
        _as_int(self.b, "RenderSpan.b")
        if self.b < self.a:
            msg = f"RenderSpan is half-open [a, b) and needs a <= b, not ({self.a}, {self.b})"
            raise ValueError(msg)

    def require_view(self, view_id: str) -> None:
        """03:2890: lifting a `RenderSpan` through a `SpanMap` whose `view_id` differs is a
        **type error**, not a silent mis-lift. This is that check, in one place, so every
        `SpanMap` implementation raises the same way instead of each inventing a comparison.
        """
        if view_id != self.view_id:
            msg = (
                f"this RenderSpan addresses view {self.view_id!r}; lifting it through a SpanMap "
                f"for {view_id!r} is a type error, not a mis-lift (03:2890)"
            )
            raise TypeError(msg)

    def slice_of(self, view_text: str) -> str:
        """`view_text[a:b]` in the view this span names.

        The view string is NOT `block.text`; both are `str`, so the guard against confusing them
        is the nominal type plus `require_view`, never the argument type.
        """
        if not isinstance(view_text, str):
            msg = f"RenderSpan.slice_of takes the serialized view, not {type(view_text).__name__}"
            raise TypeError(msg)
        if self.b > len(view_text):
            msg = f"[{self.a}, {self.b}) is outside a view of {len(view_text)} characters"
            raise ValueError(msg)
        return view_text[self.a : self.b]


@runtime_checkable
class SpanMap(Protocol):
    """Emitted BY the serializer that produced the view (03:207-212).

    **It gains `is_synthetic()`, and `block_at()` returns `None` rather than raising** (03:225).
    Section 16.5's projection law is "every character of `P(S)` either lifts to exactly one
    `(BlockId, TextSpan)` through the `SpanMap`, or is marked synthetic in that map -- there is no
    third case", and the conformance property is
    `for every offset i: map.block_at(i) is not None or map.is_synthetic(i)`. A three-method
    Protocol could not express the second half, so the law was unassertable.

    Note the direction of every signature: a view offset or a `RenderSpan` goes IN, and a
    `TextSpan` comes OUT. The two systems meet here and nowhere else, which is why this Protocol
    lives beside them.

    The block identifier is annotated `int` because `BlockId = NewType("BlockId", int)`
    (03 section 2.2) is not on disk yet and is not this cluster's to declare; 03:209-212 spells
    these returns `tuple[BlockId, TextSpan]`, and this Protocol must be tightened when the
    identity types land. Reported.
    """

    view_id: str

    def block_at(self, offset: int) -> tuple[int, TextSpan] | None:
        """The block owning `offset`, or `None` when the offset is synthetic."""
        ...

    def is_synthetic(self, offset: int) -> bool:
        """Whether `offset` belongs to text no Block owns (a heading path, a delimiter row)."""
        ...

    def offsets_of(self, b: int) -> tuple[int, int]:
        """The view's first and last offset for one block."""
        ...

    def to_text(self, s: RenderSpan) -> list[tuple[int, TextSpan]]:
        """Clip a `RenderSpan` to the intervals it overlaps, in `block.text` coordinates."""
        ...
