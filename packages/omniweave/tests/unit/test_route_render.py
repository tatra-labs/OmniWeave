"""`omniweave.route.render` -- the pixel floor, the area ceiling, and the DPI between.

05:911-914 works three renders through by hand so *"a reviewer can check a render"*, which is an
invitation this file accepts. Two of the three come out as printed and all three come out snapped,
because neither declared floor is a multiple of the `patch_snap = 28` the same section declares
(D225).

The other measurement here is the memory one. Every per-page budget in the plan is stated as
**10.7 MB** -- the `render` cache's 20 GiB (08:1273), the CPU render semaphore (02:661), the
supervisor's sizing (16:542) -- and 03:2154 derives it from A4 at 192 DPI. No profile in the
shipped policy produces 192 DPI on A4; the glyph profile produces 167.4, and the number that falls
out is 8.2 MB. D224.
"""

from __future__ import annotations

import pytest
from omniweave.route import policy as rp
from omniweave.route import render as rr
from omniweave_core.errors import RouteError

US_LETTER = (612.0, 792.0)
"""05:911's own page: *"US Letter is 612 x 792 pt"*."""

A4 = (595.276, 841.89)
"""03:2154's: *"A4 is 8.27 x 11.69 in"*, which is 595.28 x 841.89 pt."""

A5 = (419.528, 595.276)
"""05:913: *"A5 is 420 x 595 pt"*."""

A3 = (841.89, 1190.55)
"""05:919 prices an A3 glyph render at 2.71 Mpx, which is the unsnapped area."""


@pytest.fixture(scope="module")
def shipped() -> dict[str, rr.Profile]:
    policy = rp.compile_policy([rp.builtin_layer()], registry=None)
    return dict(rr.profiles(policy))


# --------------------------------------------------------------------------------------------
# 1. The profiles, as the shipped policy declares them.
# --------------------------------------------------------------------------------------------


def test_the_shipped_policy_declares_exactly_the_two_profiles(
    shipped: dict[str, rr.Profile],
) -> None:
    """05:907: *"The two profiles are `[render.structure]` (692 px floor) and `[render.glyph]`
    (1384 px floor)"*, and 05:49's own comment on the second: *"2 x the structure floor"*."""
    assert sorted(shipped) == ["glyph", "structure"]
    assert shipped["structure"].short_edge_min_px == 692
    assert shipped["glyph"].short_edge_min_px == 1384
    assert shipped["glyph"].short_edge_min_px == 2 * shipped["structure"].short_edge_min_px
    assert all(one.area_max_px == 6_291_456 for one in shipped.values())
    assert all(one.patch_snap == 28 for one in shipped.values())


def test_binarize_true_is_refused_rather_than_carried() -> None:
    """05:916: *"`binarize = false`, always"*. A field that may hold one value is a fact, and a
    fact that can be set is a bug waiting for an operator."""
    with pytest.raises(RouteError, match="destroys the antialiasing"):
        rr.Profile(name="glyph", short_edge_min_px=1384, area_max_px=6_291_456, binarize=True)


def test_an_unknown_profile_name_is_refused_at_construction() -> None:
    with pytest.raises(RouteError, match="is not a render profile"):
        rr.Profile(name="thumbnail", short_edge_min_px=64, area_max_px=4096)


def test_the_more_expensive_profile_wins_and_it_is_not_alphabetical() -> None:
    """05:908: *"where two matching rules ask for different profiles the more expensive one wins
    (`glyph` > `structure`), so accumulation is deterministic"*.

    Alphabetically `glyph` LOSES to `structure`, so a caller comparing strings would silently take
    the cheaper render on every page where two rules disagree. That is the whole reason this is a
    function."""
    assert rr.more_expensive("structure", "glyph") == "glyph"
    assert rr.more_expensive("glyph", "structure") == "glyph"
    assert max("structure", "glyph") == "structure"  # the bug this function exists to prevent
    with pytest.raises(RouteError, match="is not a render profile"):
        rr.more_expensive("glyph", "thumbnail")


# --------------------------------------------------------------------------------------------
# 2. Section 3.4's own worked arithmetic.
# --------------------------------------------------------------------------------------------


def test_us_letter_at_the_structure_profile_is_floored_at_96_dpi(
    shipped: dict[str, rr.Profile],
) -> None:
    """05:912: *"the structure profile gives `max((692/612)x72, 96) = max(81.4, 96) = 96` DPI ->
    816 x 1056 px"*. The DPI is the plan's; the pixels are the plan's snapped to 28."""
    raster = rr.plan_raster(US_LETTER, shipped["structure"])
    assert raster.dpi == pytest.approx(96.0)
    assert (raster.width_px, raster.height_px) == (840, 1064)
    assert raster.snapped
    assert not raster.capped


def test_us_letter_at_the_glyph_profile_is_the_plans_dpi(shipped: dict[str, rr.Profile]) -> None:
    """05:913: *"the glyph profile gives `max((1384/612)x72, 96) = 162.8` DPI -> 1384 x 1791 px"*,
    and 05:919 prices that render at 2.48 Mpx."""
    raster = rr.plan_raster(US_LETTER, shipped["glyph"])
    assert raster.dpi == pytest.approx(162.82, abs=0.01)
    assert (raster.width_px, raster.height_px) == (1400, 1792)
    assert raster.area_px / 1e6 == pytest.approx(2.51, abs=0.01)


def test_a5_is_scaled_up_to_the_floor_which_is_the_whole_design(
    shipped: dict[str, rr.Profile],
) -> None:
    """05:914: *"A5 is 420 x 595 pt, so structure gives `(692/420)x72 = 118.6` DPI -> exactly 692
    px on the short edge, scaled **up**"*.

    This is the property 05:906 says marker and docling lose: *"marker and docling are DPI-only, so
    the same A5 scan silently gets a tiny image."* At a flat 96 DPI an A5 short edge is 559 px,
    which is 133 px below the floor the profile exists to guarantee."""
    raster = rr.plan_raster(A5, shipped["structure"])
    assert raster.dpi > rr.MIN_DPI
    assert raster.dpi == pytest.approx(118.7, abs=0.2)
    assert raster.short_edge_px >= shipped["structure"].short_edge_min_px
    flat = round(A5[0] / rr.PT_PER_INCH * rr.MIN_DPI)
    assert flat == 559
    assert raster.short_edge_px - flat == 141


def test_the_four_printed_numbers_are_none_of_them_multiples_of_the_patch_snap() -> None:
    """D225. 05:911-914 prints 816, 1056, 1384 and 1791 as the arithmetic *"so a reviewer can
    check a render"*, and 05:917 declares `patch_snap = 28` *"so the encoder does not pad"*.

    No printed number is a multiple of 28 -- and neither floor is either, so the snap is never a
    no-op and the printed rasters can never be delivered. That is not a rounding quibble: it is
    the section's own worked example failing its own declaration."""
    for printed in (816, 1056, 1384, 1791, 692):
        assert printed % 28 != 0, f"{printed} is a multiple of 28 after all"


def test_the_area_ceiling_wins_and_the_short_edge_records_what_was_delivered(
    shipped: dict[str, rr.Profile],
) -> None:
    """05:920: *"when the two conflict the ceiling wins and `render.short_edge_px` records what was
    actually delivered"*.

    05:919 says a US Letter glyph render is 2.48 Mpx and an A3 one 2.71 Mpx, *"both under it"* --
    so the ceiling binds on neither, and a page has to be far off square to reach it. A 8.5 x 34 in
    banner does: the floor wants 1400 px on the short edge, the ceiling allows 6.29 Mpx, and the
    short edge comes back at 1260 -- BELOW the floor, which is the whole reason the field is a
    measurement rather than a restatement of the profile."""
    assert not rr.plan_raster(US_LETTER, shipped["glyph"]).capped
    assert not rr.plan_raster(A3, shipped["glyph"]).capped
    banner = rr.plan_raster((612.0, 2448.0), shipped["glyph"])
    assert banner.capped
    assert banner.area_px <= shipped["glyph"].area_max_px
    assert banner.short_edge_px < shipped["glyph"].short_edge_min_px


# --------------------------------------------------------------------------------------------
# 3. The memory constant every budget in the plan is stated in.
# --------------------------------------------------------------------------------------------


def test_a4_at_192_dpi_is_the_plans_10_7_mb_and_no_profile_renders_it(
    shipped: dict[str, rr.Profile],
) -> None:
    """D224, both halves in one test.

    03:2154's arithmetic reproduces: A4 at 192 DPI is 1,588 x 2,245 px = 3,565,060 px, and at
    3 B/px that is 10.7 MB. And the glyph profile -- the expensive one, the one a `PAGE` call
    uses -- renders A4 at 167.4 DPI for 8.2 MB. The constant is 31% above what the profile that
    exists delivers.
    """
    assert 1588 * 2245 == 3_565_060  # 03:2154's own product, from its own two dimensions
    assert pytest.approx(10.7, abs=0.05) == 3_565_060 * 3 / 1e6
    assert round(A4[1] / rr.PT_PER_INCH * 192) == 2245

    raster = rr.plan_raster(A4, shipped["glyph"])
    assert raster.dpi == pytest.approx(167.4, abs=0.1)
    assert raster.dpi < 192
    assert raster.decoded_bytes / 1e6 == pytest.approx(8.2, abs=0.1)


def test_the_real_per_page_ceiling_is_the_area_cap_and_it_is_above_10_7_mb(
    shipped: dict[str, rr.Profile],
) -> None:
    """The other half of D224, and the direction that matters for a semaphore.

    A budget sized on 10.7 MB is conservative for a typical page and **under**-sized for the worst
    one: `area_max_px x 3` is 18.9 MB, 76% above the constant, and a page reaches it whenever the
    aspect ratio is extreme enough that the short-edge floor and the area ceiling collide."""
    ceiling = shipped["glyph"].area_max_px * 3
    assert ceiling / 1e6 == pytest.approx(18.9, abs=0.05)
    assert ceiling > 10_700_000
    banner = rr.plan_raster((612.0, 2448.0), shipped["glyph"])
    assert banner.decoded_bytes == pytest.approx(ceiling, rel=0.01)


def test_a_page_with_no_size_has_no_raster() -> None:
    profile = rr.Profile(name="glyph", short_edge_min_px=1384, area_max_px=6_291_456)
    with pytest.raises(RouteError, match="a page size is positive"):
        rr.plan_raster((0.0, 792.0), profile)


def test_a_short_edge_past_the_signals_domain_is_refused() -> None:
    """`render.short_edge_px`'s declared domain is `[0, 65536]` (05:2160). A profile that produced
    more would produce a value no rule could read, so it is a refusal and not a clamp."""
    profile = rr.Profile(name="glyph", short_edge_min_px=70_000, area_max_px=10**12)
    with pytest.raises(RouteError, match="declared domain"):
        rr.plan_raster(US_LETTER, profile)
