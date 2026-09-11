"""14-security.md:498's parity test, and the boundary that refuses to guess.

The row asks for exactly one assertion: *"a parity test asserts that every `MAX_*` in
`omniweave_core.limits` that names a vector anydoc also bounds has a value greater than or equal to
anydoc's, so the Python-side ceiling can never be the tighter one silently. If anydoc raises a
constant in a patch release, the parity test fails and the bump is a reviewed event."*

It lives here rather than in `omniweave_office` because it imports `omniweave_core`, which
`tools/layers.toml` forbids that package (`omniweave_office = ["omniweave_ports"]`). Test code may
import anything; library code may not, and the rule is what keeps a driver distribution from
growing a dependency on core through the back door of a check.

**Three copies are joined, not two.** `omniweave_office.limits.CEILINGS` is the driver's table, the
vendored `src/package/limits.rs` is the source a reviewer reads, and the installed wheel is what
actually runs. A table that agreed with the vendored source while the wheel had moved on would pass
a two-way check and mean nothing.

Specified in 14-security.md section 2.10; 05-ingest-and-routing.md section 2's limits table.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from omniweave_core import limits as core_limits
from omniweave_office.limits import CEILINGS, NAMES, UNKNOWN_LIMIT, classify

REPO = Path(__file__).resolve().parents[4]
VENDORED = REPO / "vendor" / "anydoc" / "src" / "package" / "limits.rs"
CRATE = REPO / "vendor" / "anydoc" / "src"

_CONST = re.compile(r"^pub const (MAX_[A-Z_]+):\s*\w+\s*=\s*([^;]+);", re.MULTILINE)
_RAISED = re.compile(r'limit:\s*"([a-z_]+)"')


def _rust_int(expression: str) -> int:
    total = 1
    for factor in expression.strip().replace("_", "").split("*"):
        total *= int(factor.strip())
    return total


def _vendored() -> dict[str, int]:
    source = VENDORED.read_text(encoding="utf-8")
    return {match.group(1): _rust_int(match.group(2)) for match in _CONST.finditer(source)}


def test_the_taxonomy_is_eleven_constants_and_not_twelve() -> None:
    """The plan says "twelve" in five places; the pinned source has eleven.

    `_plan/_notes/build-defects.md` D123 records the recount. This test is the reason the number
    in `limits.py` can be trusted: it is re-derived from the vendored source on every run, so a
    twelfth constant upstream is a failure here rather than a silent omission everywhere.

    The same discipline 03 section 18 Q10 applies to anydoc's `Block` variant count, which the
    charter calls nine and then lists eight: state the verified number, record the divergence, do
    not propagate it.
    """
    constants = _vendored()
    assert len(constants) == 11
    assert set(constants) == {name.upper() for name in CEILINGS}


def test_every_ceiling_matches_the_vendored_source() -> None:
    """The driver's table is a copy of `limits.rs`, and this is the test that it is a copy."""
    constants = _vendored()
    for name, ceiling in CEILINGS.items():
        assert constants[name.upper()] == ceiling.value, name


def test_the_names_that_can_reach_python_are_exactly_the_eleven() -> None:
    """Every `ConvertError::ResourceLimit { limit: "..." }` in the crate has a row here.

    The constants and the raisable names are two different sets in principle -- a constant could
    exist and never be raised, or a name raised with no constant behind it -- and the parity claim
    needs both. They are in bijection at 0.2.4, and this test is what would notice if they stopped
    being.
    """
    raised = set()
    for path in sorted(CRATE.rglob("*.rs")):
        raised.update(_RAISED.findall(path.read_text(encoding="utf-8", errors="replace")))
    assert raised == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_the_python_side_ceiling_is_never_the_tighter_one(name: str) -> None:
    """14-security.md:498, one assertion per vector: `core >= anydoc`.

    A Python-side ceiling BELOW the Rust one would be the tighter limit while every message, every
    `codes.toml` row and every operator's mental model says the Rust constant is what fires. The
    one row where the two differ in kind is `max_asset_total_bytes`: anydoc's is 128 MiB and
    core's is 512 MiB, because core's is derived rather than copied (05:212) -- the charter's
    per-asset `MAX_ASSET_BYTES` is 256 MiB, so a whole-document budget below it would make a
    single legal maximum-size asset unrepresentable.
    """
    ceiling = CEILINGS[name]
    ours = getattr(core_limits, ceiling.core)
    assert ours >= ceiling.value, (
        f"{ceiling.core} = {ours} is below anydoc's {name.upper()} = {ceiling.value}; "
        f"the Python-side ceiling must never silently be the tighter one"
    )


def test_classify_passes_a_known_name_through_and_never_invents_one() -> None:
    """The boundary's two answers are different SHAPES of string, on purpose."""
    assert classify("max_xml_depth") == "max_xml_depth"
    assert classify("max_records") == "max_records"
    assert classify("max_something_new") == UNKNOWN_LIMIT
    assert classify(None) == UNKNOWN_LIMIT
    assert classify("") == UNKNOWN_LIMIT
    assert UNKNOWN_LIMIT.isupper()
    assert all(name.islower() for name in NAMES)


def test_names_is_derived_from_the_map_rather_than_re_listed() -> None:
    """INV-21 over two lines of the same module: one home for one fact."""
    assert tuple(CEILINGS) == NAMES
    assert len(set(NAMES)) == len(NAMES)
