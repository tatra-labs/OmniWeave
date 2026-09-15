"""The render profiles: a pixel floor on the short edge, an area ceiling, and the DPI between.

05:900-921 is the whole specification, and its first sentence is the design: *"A VLM sees pixels,
not points, so a profile is a **pixel floor on the short edge plus a pixel-area ceiling**, and the
DPI is derived per page."* lift is the only repo in the collection that gets this right
(`settings.py:11-12`, `input.py:27-50`); marker and docling are DPI-only, *"so the same A5 scan
silently gets a tiny image."*

## Why this is the router's and not a driver's

Three reasons, and each is a line rather than a preference. The profile tables are `[render.*]` in
the policy, so `RoutePolicy.render` already carries them. `then.render` selects one, and 05:908 says
that where two matching rules ask for different profiles *"the more expensive one wins (`glyph` >
`structure`), so accumulation is deterministic"* -- which is rule accumulation, not rasterising.
And the output is an evidence key: `render.short_edge_px` is a registered `SignalSpec` (05:2160,
provider `pdfium`) and it is what `parse.page.olmocr`'s `[cost.model] scaling` reads
(`{ key = "render.short_edge_px", exponent = 2.0, reference = 1384 }`, 05:2453). So the plan is the
router's; the pixels are pdfium's.

## The order of operations, which is the whole of it

1. `dpi = max((short_edge_min_px / min_page_dim_pt) x 72, MIN_DPI)` -- 05:905's
   `scale_dpi = max((692 / min_page_dim) * 72, 96)`, transcribed. An A5 scan is scaled **up** to
   the floor, which is the behaviour the DPI-only repos lose.
2. Snap to `patch_snap` -- 05:917, *"so the encoder does not pad"*.
3. Apply `area_max_px` by scaling down **after** the floor is met. 05:920: *"when the two conflict
   the ceiling wins and `render.short_edge_px` records what was actually delivered"*.

Step 2 is where the plan runs out, and D225 records it: the section's own four worked numbers --
816, 1056, 1384, 1791 -- are none of them multiples of 28, nor are the two floors it declares. This
module snaps and says which way and why; `Raster.snapped` records whether it moved.

## `binarize` is not a knob, and this module refuses one

05:916: *"`binarize = false`, always: Ollama-OCR renders at a bare 72 DPI and then Otsu-binarises,
which destroys the antialiasing every VLM in the collection was trained on."* 13:1472 says the same
from the quality side and adds that a binarising degradation *"would measure a pipeline"* nobody
ships. So `Profile.__post_init__` refuses `binarize = true` rather than carrying it: a field that
may hold one value is a fact, and a fact that can be set is a bug waiting for an operator.

Specified in 05-ingest-and-routing.md section 3.4; the profile tables are 05:1305-1318's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import RouteError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave.route.policy import RoutePolicy

__all__ = [
    "MIN_DPI",
    "PROFILES",
    "PT_PER_INCH",
    "Profile",
    "Raster",
    "more_expensive",
    "plan_raster",
    "profiles",
]

PROFILES: Final[tuple[str, str]] = ("structure", "glyph")
"""The two, in ascending cost. 05:907: *"The two profiles are `[render.structure]` (692 px floor)
and `[render.glyph]` (1384 px floor)"*, and 05:908 orders them `glyph` > `structure`. The order is
the tuple's, so `more_expensive()` is an index comparison rather than a second table."""

PT_PER_INCH: Final[int] = 72
"""A PDF point is 1/72 inch. The `x 72` in 05:905's formula, named rather than inline."""

MIN_DPI: Final[int] = 96
"""lift's `IMAGE_DPI = 96` (`lift/lift/settings.py:11`), the floor under the derived DPI. It binds
on pages already large in points: US Letter at the structure profile wants 81.4 DPI and gets 96,
which 05:912 works through. Below it a raster is small in absolute pixels however big the page."""

_MAX_SHORT_EDGE: Final[int] = 65_536
"""`render.short_edge_px`'s declared domain is `[0, 65536]` (05:2160), so a plan that produced more
would produce a value no rule could read. It is a refusal rather than a clamp: a page that wants
more pixels than the signal can carry is a page whose profile is wrong."""


@dataclass(frozen=True, slots=True)
class Profile:
    """One `[render.*]` table. Four keys, and one of them may hold exactly one value.

    `binarize` is typed `bool` and refused when true, rather than being dropped from the record:
    the card, the policy file and the `MeasuredOn` `sampling` key all carry it (13:919 makes the
    render profile digest -- *"DPI 150, RGB8, `binarize = false`, a named resampling filter, alpha
    flattened onto white"* -- a `MeasuredOn` field), so it has to round-trip. What it may not do is
    vary.
    """

    name: str
    short_edge_min_px: int
    area_max_px: int
    patch_snap: int = 1
    binarize: bool = False

    def __post_init__(self) -> None:
        if self.name not in PROFILES:
            raise RouteError(
                f"{self.name!r} is not a render profile; the two are {', '.join(PROFILES)}",
                fix="uv run ow route lint --strict",
            )
        if self.binarize:
            raise RouteError(
                f"[render.{self.name}] binarize = true destroys the antialiasing every VLM in the "
                "collection was trained on (05:916); it is false always and is not a knob",
                fix="uv run ow route lint --strict",
            )
        for field_name in ("short_edge_min_px", "area_max_px", "patch_snap"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or value < 1:
                raise RouteError(
                    f"[render.{self.name}] {field_name} = {value!r} is not a positive integer",
                    fix="uv run ow route lint --strict",
                )

    @property
    def rank(self) -> int:
        """Position in `PROFILES`. Higher is more expensive."""
        return PROFILES.index(self.name)


@dataclass(frozen=True, slots=True)
class Raster:
    """What a render of one page at one profile delivers. `short_edge_px` is the evidence key.

    `dpi` is derived and per page, which is the point of the whole design; it is carried because
    `cache_index` layer `render` is keyed on `(doc_ord, gen, page, dpi, renderer, renderer_version,
    colorspace)` (07:934), so a raster that did not know its own DPI could not be cached.

    `capped` and `snapped` are the two ways the delivered raster differs from the naive one, and
    both are recorded rather than inferred: a reviewer checking 05:911-914's worked arithmetic
    against a real render needs to know which of the three steps moved the number.
    """

    profile: str
    width_px: int
    height_px: int
    dpi: float
    capped: bool = False
    snapped: bool = False

    @property
    def short_edge_px(self) -> int:
        """05:921's *"the number a rule and the cost estimator may read"*. `SignalSpec` 05:2160."""
        return min(self.width_px, self.height_px)

    @property
    def area_px(self) -> int:
        return self.width_px * self.height_px

    @property
    def decoded_bytes(self) -> int:
        """RGB8, three bytes a pixel. 03:2154's arithmetic, applied to what is actually delivered.

        Carried because every memory budget in the plan is stated per decoded page -- the `render`
        cache's 20 GiB (08:1273), the CPU render semaphore (02:661), the supervisor's own reasoning
        (16:542) -- and all of them quote **10.7 MB**, which is A4 at 192 DPI and not a raster any
        profile here produces. D224.
        """
        return self.area_px * 3

    def render(self) -> str:
        notes = "".join(("+snapped" if self.snapped else "", "+capped" if self.capped else ""))
        return (
            f"{self.profile:<9} {self.width_px} x {self.height_px} px at {self.dpi:.1f} DPI  "
            f"short_edge_px={self.short_edge_px}  {self.area_px / 1e6:.2f} Mpx  "
            f"{self.decoded_bytes / 1e6:.1f} MB{notes}"
        )


def profiles(policy: RoutePolicy) -> Mapping[str, Profile]:
    """`[render.structure]` and `[render.glyph]` off a compiled policy, as records.

    Every declared profile, not only the two: an unknown name raises in `Profile.__post_init__`,
    which is where an operator who invented `[render.thumbnail]` should hear about it rather than
    at the render step with a page already in memory.
    """
    found: dict[str, Profile] = {}
    for name, table in policy.render.items():
        found[name] = Profile(
            name=name,
            short_edge_min_px=_int(table, "short_edge_min_px", name),
            area_max_px=_int(table, "area_max_px", name),
            patch_snap=_int(table, "patch_snap", name, default=1),
            binarize=bool(table.get("binarize", False)),
        )
    return found


def _int(table: Mapping[str, object], key: str, profile: str, *, default: int | None = None) -> int:
    value = table.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouteError(
            f"[render.{profile}] {key} = {value!r} is not an integer",
            fix="uv run ow route lint --strict",
        )
    return value


def more_expensive(first: str, second: str) -> str:
    """05:908's accumulation -- *"the more expensive one wins (`glyph` > `structure`)"*.

    A function and not a `max()` at the call site, because the ordering is `PROFILES`' and a
    caller comparing strings would get alphabetical -- under which `glyph` loses to `structure`,
    silently, on every page where two rules disagree.
    """
    ranks = [PROFILES.index(one) for one in (first, second) if one in PROFILES]
    if len(ranks) != 2:  # noqa: PLR2004 -- both names, or the caller named something else
        unknown = [one for one in (first, second) if one not in PROFILES]
        raise RouteError(
            f"{unknown!r} is not a render profile; the two are {', '.join(PROFILES)}",
            fix="uv run ow route lint --strict",
        )
    return PROFILES[max(ranks)]


def plan_raster(page_pt: tuple[float, float], profile: Profile) -> Raster:
    """One page's size in points, one profile -> the raster the render step delivers.

    The three steps of the module docstring, in order, and the order is load-bearing: the area
    ceiling is applied, per 05:918, *"after the short-edge floor is met"*, so a page that cannot
    have both gets the ceiling -- 05:920, *"when the two conflict the ceiling wins"* -- and
    `short_edge_px` then reports less than `short_edge_min_px`, which is why that field is a
    measurement rather than a restatement of the profile.

    Snapping runs between them, and it snaps **up**. Up rather than down because step 1's whole
    purpose is a floor: `692` snapped down to `672` would be a page below the floor delivered by
    the code whose job is to reach it. The cost is at most `patch_snap - 1` pixels an edge, and the
    ceiling -- which is applied afterwards and wins -- bounds what that can grow into.

    **The snapped box is a canvas, not a scale.** The page is rendered at `dpi` and the remainder
    is the white the profile already flattens alpha onto (13:919), so the aspect ratio is the
    page's and `dpi` stays the derived value -- which matters because `dpi` is in `cache_index`
    layer `render`'s key (07:934) and a DPI perturbed by a rounding would miss every cached page.
    Distorting to fit instead would change the geometry a `Quad` is recorded in, for 28 pixels.
    """
    width_pt, height_pt = float(page_pt[0]), float(page_pt[1])
    if width_pt <= 0 or height_pt <= 0:
        raise RouteError(
            f"a page of {width_pt} x {height_pt} pt has no raster; a page size is positive",
            fix="uv run ow route lint --strict",
        )
    dpi = max(profile.short_edge_min_px / min(width_pt, height_pt) * PT_PER_INCH, float(MIN_DPI))
    width = round(width_pt / PT_PER_INCH * dpi)
    height = round(height_pt / PT_PER_INCH * dpi)
    snapped = False
    if profile.patch_snap > 1:
        width, height = _snap_up(width, profile.patch_snap), _snap_up(height, profile.patch_snap)
        snapped = (width, height) != (
            round(width_pt / PT_PER_INCH * dpi),
            round(height_pt / PT_PER_INCH * dpi),
        )
    capped = False
    if width * height > profile.area_max_px:
        scale = math.sqrt(profile.area_max_px / (width * height))
        width, height = max(1, int(width * scale)), max(1, int(height * scale))
        dpi *= scale
        capped = True
    if min(width, height) > _MAX_SHORT_EDGE:
        raise RouteError(
            f"[render.{profile.name}] on a {width_pt:g} x {height_pt:g} pt page delivers a short "
            f"edge of {min(width, height)} px, above render.short_edge_px's declared domain "
            f"[0, {_MAX_SHORT_EDGE}] (05:2160)",
            fix="uv run ow route lint --strict",
        )
    return Raster(
        profile=profile.name,
        width_px=width,
        height_px=height,
        dpi=dpi,
        capped=capped,
        snapped=snapped,
    )


def _snap_up(value: int, snap: int) -> int:
    """The next multiple of `snap` at or above `value`. `patch_snap = 28` (05:917)."""
    return -(-value // snap) * snap
