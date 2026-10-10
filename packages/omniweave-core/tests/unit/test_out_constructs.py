"""`omniweave_core.out.constructs`: the ConstructTable and every way it refuses to load.

09-generation.md section 3.4 (the per-disposition key table and the four load-time assertions),
section 3.5 (`unknown_construct` is not configurable) and section 3.1 rule 5 (`forbidden_when` is
evaluated per unit, by the framework). The fixture is the reference target's ten-row table from
18-api-sketch.md section 6.2, with its `ignore` spelt in section 3.1's grammar (ruling 5).
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.out import html_carrier
from omniweave_core.out.constructs import ConstructTable, Disposition, RoundTrip

OWTEXT = """\
schema = "omniweave.out-constructs/1"
carrier = "html"
il = "owtext/1"
version = 1
unknown_construct = "forbidden"
ignore = ["html|head", "html|meta"]

[[construct]]
id = "attr.ow-cite"
selector = "@data-ow-cite"
disposition = "native"
round_trip = "exact"
canonical = "a space-separated list of cite tokens"
maps_to = "lower.cites:sidecar"
code = "OW_TARGET_CITE_MALFORMED"
since = "0.1.0"

[[construct]]
id = "attr.ow-el"
selector = "@data-ow-el"
disposition = "native"
round_trip = "exact"
canonical = "u<NN>e<NN>, minted once, unique per artefact"
maps_to = "lower.ids:passthrough"
code = "OW_TARGET_EL_DUPLICATE"
since = "0.1.0"

[[construct]]
id = "elem.ow-manual"
selector = "html|div[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason member as the attribute value"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
since = "0.1.0"

[[construct]]
id = "elem.section"
selector = "html|section"
disposition = "native"
round_trip = "exact"
canonical = "one <section data-ow-unit> per output unit"
maps_to = "lower.units:section"
code = "OW_TARGET_UNIT_MALFORMED"
since = "0.1.0"

[[construct]]
id = "elem.p"
selector = "html|p"
disposition = "native"
round_trip = "exact"
canonical = "block text, NFC-normalised, no nested block elements"
maps_to = "lower.text:paragraph"
code = "OW_TARGET_TEXT_INVALID"
since = "0.1.0"

[[construct]]
id = "attr.id"
selector = "@id"
disposition = "native"
forbidden_when = "html|style"
round_trip = "exact"
canonical = "unique within the unit, lower-case ASCII"
maps_to = "lower.ids:anchor"
code = "OW_TARGET_ID_WITH_STYLE"
since = "0.1.0"

[[construct]]
id = "attr.class"
selector = "@class"
disposition = "native"
round_trip = "exact"
canonical = "lower-case ASCII"
maps_to = "lower.text:classes"
code = "OW_TARGET_CLASS_INVALID"
since = "0.1.0"

[[construct]]
id = "attr.class.upper"
normalizes_to = "attr.class"
disposition = "normalize"
normalizer = "lower_ascii"
round_trip = "normalized"
code = "OW_TARGET_CLASS_NOT_LOWER"
severity = "warning"
canonical = "lower-case ASCII class names"
since = "0.1.0"

[[construct]]
id = "elem.script"
selector = "html|script"
disposition = "forbidden"
round_trip = "dropped"
code = "OW_TARGET_SCRIPT_FORBIDDEN"
msg = "executable content in an authored artefact; no text mapping exists"
since = "0.1.0"

[[construct]]
id = "style.text-shadow"
selector = "@style|text-shadow"
disposition = "bake"
bake = { renderer = "raster", dpi = 192, role = "bake" }
round_trip = "lossy"
code = "OW_TARGET_SHADOW_REQUIRES_BAKE"
since = "0.1.0"
"""

NORMALIZERS = {"lower_ascii": str.lower}


def _raw() -> dict[str, Any]:
    return tomllib.loads(OWTEXT)


def _load(raw: dict[str, Any]) -> ConstructTable:
    return ConstructTable.parse(raw, NORMALIZERS, source="constructs.toml")


def _row(raw: dict[str, Any], construct_id: str) -> dict[str, Any]:
    return next(r for r in raw["construct"] if r["id"] == construct_id)


def _refused(raw: dict[str, Any], match: str) -> TargetError:
    with pytest.raises(TargetError, match=match) as caught:
        _load(raw)
    return caught.value


def test_the_reference_table_loads() -> None:
    table = _load(_raw())
    assert (table.carrier, table.il, table.version) == ("html", "owtext/1", 1)
    assert len(table.rows) == 10
    assert table.ignore == ("html|head", "html|meta")
    upper = table.row("attr.class.upper")
    assert upper.disposition is Disposition.NORMALIZE
    assert upper.selector == "@class", "a normalize row inherits its native row's selector"
    shadow = table.row("style.text-shadow")
    assert shadow.bake is not None and (shadow.bake.renderer, shadow.bake.dpi) == ("raster", 192)
    assert shadow.round_trip is RoundTrip.LOSSY
    with pytest.raises(KeyError):
        table.row("elem.missing")


def test_the_digest_moves_with_a_value_and_not_with_layout(tmp_path: Path) -> None:
    path = tmp_path / "constructs.toml"
    path.write_text(OWTEXT, encoding="utf-8")
    first = ConstructTable.load(path, NORMALIZERS)
    path.write_text(
        "# a comment\n\n" + OWTEXT.replace("version = 1", "version   =   1"), encoding="utf-8"
    )
    assert ConstructTable.load(path, NORMALIZERS).digest() == first.digest()
    path.write_text(OWTEXT.replace("dpi = 192", "dpi = 193"), encoding="utf-8")
    assert ConstructTable.load(path, NORMALIZERS).digest() != first.digest()
    assert first.digest().startswith("sha256:") and len(first.digest()) == 71


def test_an_unreadable_table_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "constructs.toml"
    path.write_text("schema = ", encoding="utf-8")
    with pytest.raises(TargetError, match="does not load"):
        ConstructTable.load(path, NORMALIZERS)


@pytest.mark.parametrize(
    ("key", "value", "match"),
    [
        ("schema", "omniweave.out-constructs/2", "schema"),
        ("carrier", "pdf", "carrier"),
        ("unknown_construct", "warning", "not configurable"),
        ("version", 0, "positive integer"),
        ("version", True, "positive integer"),
        ("il", "", "IL id"),
        ("ignore", ["html:head"], "OW-T|invalid"),
        ("ignore", "html|head", "list of strings"),
        ("unknown_constructs", "forbidden", "unknown key"),
        ("construct", [], "no \\[\\[construct\\]\\] rows"),
    ],
)
def test_the_top_of_the_table_is_asserted(key: str, value: object, match: str) -> None:
    raw = _raw()
    raw[key] = value
    _refused(raw, match)


@pytest.mark.parametrize(
    ("row", "drop"),
    [
        ("attr.class", "canonical"),
        ("attr.class", "maps_to"),
        ("attr.class", "selector"),
        ("attr.class.upper", "normalizes_to"),
        ("attr.class.upper", "normalizer"),
        ("attr.class.upper", "canonical"),
        ("attr.class.upper", "severity"),
        ("style.text-shadow", "bake"),
        ("style.text-shadow", "selector"),
        ("elem.script", "msg"),
        ("elem.script", "since"),
        ("elem.script", "code"),
    ],
)
def test_each_required_key_is_required(row: str, drop: str) -> None:
    raw = _raw()
    del _row(raw, row)[drop]
    _refused(raw, "requires|is required")


@pytest.mark.parametrize(
    ("row", "key", "value"),
    [
        ("attr.class", "normalizer", "lower_ascii"),
        ("attr.class", "bake", {"renderer": "raster", "dpi": 1, "role": "bake"}),
        ("attr.class", "severity", "error"),
        ("attr.class.upper", "selector", "@class"),
        ("attr.class.upper", "maps_to", "lower.text:classes"),
        ("attr.class.upper", "forbidden_when", "html|style"),
        ("style.text-shadow", "canonical", "x"),
        ("style.text-shadow", "maps_to", "x"),
        ("elem.script", "canonical", "x"),
        ("elem.script", "severity", "warning"),
    ],
)
def test_each_forbidden_key_is_forbidden(row: str, key: str, value: object) -> None:
    raw = _raw()
    _row(raw, row)[key] = value
    _refused(raw, "may not carry")


@pytest.mark.parametrize(
    ("row", "key", "value", "match"),
    [
        ("attr.class.upper", "severity", "error", "never an error"),
        ("attr.class.upper", "normalizes_to", "attr.missing", "not a native row"),
        ("attr.class.upper", "normalizes_to", "elem.script", "not a native row"),
        ("attr.class.upper", "normalizer", "upper_hex", "not in normalizers.py"),
        ("style.text-shadow", "round_trip", "exact", "round_trip is one of"),
        ("elem.script", "round_trip", "normalized", "round_trip is one of"),
        ("elem.script", "disposition", "tolerated", "not a valid Disposition"),
        ("elem.script", "since", "0.1", "not a version"),
        ("elem.script", "code", "OW-T-401", "not a codes.toml symbol"),
        ("style.text-shadow", "bake", {"renderer": "raster", "dpi": 192}, "renderer, dpi, role"),
        ("elem.p", "visible", "no", "true or false"),
        ("elem.p", "forbiden_when", "html|style", "unknown key"),
    ],
)
def test_each_way_a_row_could_lie_is_refused(row: str, key: str, value: object, match: str) -> None:
    raw = _raw()
    _row(raw, row)[key] = value
    _refused(raw, match)


def test_a_normalize_chain_has_no_fixed_point_and_is_refused() -> None:
    raw = _raw()
    chained = copy.deepcopy(_row(raw, "attr.class.upper"))
    chained.update(id="attr.class.upper2", normalizes_to="attr.class.upper")
    raw["construct"].append(chained)
    _refused(raw, "not a native row")


@pytest.mark.parametrize(
    ("key", "value"), [("selector", "html|*"), ("forbidden_when", "svg|style")]
)
def test_an_unparseable_selector_names_the_row_and_the_key(key: str, value: str) -> None:
    raw = _raw()
    _row(raw, "attr.id")[key] = value
    error = _refused(raw, "invalid")
    assert error.code() == "OW_TARGET_SELECTOR_INVALID"
    assert f"construct 'attr.id': {key}" in str(error)
    assert "offset" in str(error)


def test_a_duplicate_id_is_refused() -> None:
    raw = _raw()
    raw["construct"].append(copy.deepcopy(_row(raw, "elem.p")))
    _refused(raw, "declared twice")


@pytest.mark.parametrize("construct_id", ["attr.ow-cite", "attr.ow-el", "elem.ow-manual"])
def test_the_mandatory_constructs_are_required(construct_id: str) -> None:
    raw = _raw()
    raw["construct"] = [r for r in raw["construct"] if r["id"] != construct_id]
    _refused(raw, "mandatory attribute")


def test_forbidden_when_is_evaluated_per_unit_by_the_framework() -> None:
    table = _load(_raw())
    plain = html_carrier("il/u01.html", '<section id="a"><p>x</p></section>', strict=True)
    styled = html_carrier(
        "il/u01.html", '<section id="a"><style>p{}</style><p>x</p></section>', strict=True
    )
    assert table.conditional(plain) == ()
    assert [row.id for row in table.conditional(styled)] == ["attr.id"]
