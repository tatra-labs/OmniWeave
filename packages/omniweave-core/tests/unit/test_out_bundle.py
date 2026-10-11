"""`omniweave_core.out.job.ILBundle`: the roster on disk, both digests, one parse a unit.

09-generation.md section 3.2 (`il.toml` and the three rosters), section 3.7 (`ILBundle`'s fields and
its four decisions), section 11.3 (`il_digest_rt`, derived from the table) and section 14.3 (the
read boundary). The fixture is a two-unit `owtext/1` bundle over the html carrier.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from omniweave_core.errors import ResourceLimit, TargetError
from omniweave_core.out import job
from omniweave_core.out.carrier import CarrierDoc, CarrierParseError
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.job import UNPARSED_HEX, UNREADABLE, ILBundle, elided, read_il_files
from omniweave_core.out.report import il_digest

TABLE = """\
schema = "omniweave.out-constructs/1"
carrier = "html"
il = "owtext/1"
version = 1
unknown_construct = "forbidden"

[[construct]]
id = "attr.ow-cite"
selector = "@data-ow-cite"
disposition = "native"
round_trip = "exact"
canonical = "cite tokens"
maps_to = "lower.cites:sidecar"
code = "OW_TARGET_CITE_MALFORMED"
since = "0.1.0"

[[construct]]
id = "attr.ow-el"
selector = "@data-ow-el"
disposition = "native"
round_trip = "exact"
canonical = "u<NN>e<NN>"
maps_to = "lower.ids:passthrough"
code = "OW_TARGET_EL_DUPLICATE"
since = "0.1.0"

[[construct]]
id = "elem.ow-manual"
selector = "html|div[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
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
id = "attr.title"
selector = "@title"
disposition = "native"
round_trip = "lossy"
canonical = "a tooltip, which the target does not carry"
maps_to = "lower.text:none"
code = "OW_TARGET_TEXT_INVALID"
since = "0.1.0"

[[construct]]
id = "elem.script"
selector = "html|script"
disposition = "forbidden"
round_trip = "dropped"
code = "OW_TARGET_SCRIPT_FORBIDDEN"
msg = "executable content"
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
CONSTRUCTS = ConstructTable.parse(
    tomllib.loads(TABLE), {"lower_ascii": str.lower}, source="constructs.toml"
)
DIGEST = "sha256:" + "7" * 64
IL_TOML = f"""schema = "omniweave.out-il/1"
il = "owtext/1"
constructs_digest = "{DIGEST}"

[[unit]]
id = "u01"
ord = 1
file = "u01.html"
anchor = "cover"

[[unit]]
id = "u02"
ord = 2
file = "u02.html"
"""
U1 = (
    '<section data-ow-el="u01/e1">'
    '<p data-ow-el="u01/e2" class="lead" style="color: red">a</p></section>'
)
U2 = '<section data-ow-el="u02/e1"><p>b</p></section>'


def _carrier(path: str, text: str) -> CarrierDoc:
    return html_carrier(path, text, strict=False)


def _bundle(tmp_path: Path, **files: str) -> Path:
    il = tmp_path / "il"
    il.mkdir(parents=True, exist_ok=True)
    contents = {"il.toml": IL_TOML, "u01.html": U1, "u02.html": U2, **files}
    for name, text in contents.items():
        if text is not None:
            (il / name).write_text(text, encoding="utf-8", newline="")
    return il


def _load(il: Path) -> ILBundle:
    return ILBundle.load(il, carrier=_carrier, constructs=CONSTRUCTS)


def test_a_bundle_loads_its_roster_digests_nsigs_and_addresses(tmp_path: Path) -> None:
    il = _bundle(tmp_path)
    bundle = _load(il)
    assert (bundle.schema, bundle.il, bundle.constructs_digest, bundle.origin) == (
        "omniweave.out-il/1",
        "owtext/1",
        DIGEST,
        None,
    )
    assert [(u.id, u.ord, u.il_path, u.anchor) for u in bundle.units] == [
        ("u01", 1, "il/u01.html", "cover"),
        ("u02", 2, "il/u02.html", ""),
    ]
    assert bundle.units[0].nsig == html_carrier("il/u01.html", U1, strict=True).root().nsig
    assert [f.name for f in bundle.files] == ["il.toml", "u01.html", "u02.html"]
    assert bundle.il_digest == il_digest(read_il_files(il))
    assert bundle.els == {"u01": frozenset({"u01/e1", "u01/e2"}), "u02": frozenset({"u02/e1"})}
    assert bundle.root == str(il.resolve())
    assert bundle.text("il/u02.html") == U2
    assert bundle.data("il/u02.html") == U2.encode()
    assert bundle.template_nsigs == frozenset()


def test_adding_a_roster_row_moves_il_digest_before_the_file_exists(tmp_path: Path) -> None:
    """09 section 3.2: il.toml is in the digest."""
    il = _bundle(tmp_path)
    before = _load(il).il_digest
    (il / "il.toml").write_text(
        IL_TOML.replace('anchor = "cover"', 'anchor = "title"'), encoding="utf-8"
    )
    assert _load(il).il_digest != before


# ---------------------------------------------------------------------------
# il_digest_rt (09 section 11.3), ruling 14
# ---------------------------------------------------------------------------


def test_the_exclusion_set_is_derived_from_the_table() -> None:
    assert elided(CONSTRUCTS) == ("@title", "html|script", "@style|text-shadow")


def test_il_digest_rt_ignores_a_lossy_payload_and_sees_an_exact_one(tmp_path: Path) -> None:
    base = _load(_bundle(tmp_path / "a"))
    shadowed = U1.replace('style="color: red"', 'style="color: red; text-shadow: 1px 1px"')
    scripted = U1.replace("</section>", "<script>x</script></section>")
    titled = U1.replace('class="lead"', 'class="lead" title="a tip"')
    for variant in (shadowed, scripted, titled):
        other = _load(_bundle(tmp_path / f"v{len(variant)}", **{"u01.html": variant}))
        assert other.il_digest != base.il_digest, "different bytes"
        assert other.il_digest_rt == base.il_digest_rt, "a lossy or dropped payload is elided"
    exact = _load(
        _bundle(tmp_path / "e", **{"u01.html": U1.replace('class="lead"', 'class="note"')})
    )
    assert exact.il_digest_rt != base.il_digest_rt, (
        "R5: a semantic mutation of an exact row moves it"
    )
    colour = _load(_bundle(tmp_path / "c", **{"u01.html": U1.replace("color: red", "color: blue")}))
    assert colour.il_digest_rt != base.il_digest_rt, "only the elided declaration leaves the style"


def test_a_normalize_row_elides_nothing() -> None:
    """Ruling 14: `attr.class.upper` shares `@class` with the exact native row."""
    assert "@class" not in elided(CONSTRUCTS)


# ---------------------------------------------------------------------------
# The three rosters (09 section 3.2), rulings 12-13
# ---------------------------------------------------------------------------


def test_a_projected_bundle_says_so(tmp_path: Path) -> None:
    toml = IL_TOML.replace("[[unit]]", 'origin = "project"\n\n[[unit]]', 1)
    assert _load(_bundle(tmp_path, **{"il.toml": toml})).origin == "project"


def test_an_orphan_file_alone_is_a_mismatch(tmp_path: Path) -> None:
    il = _bundle(tmp_path, **{"u09.html": "<section></section>"})
    with pytest.raises(TargetError, match=r"files with no unit \['u09\.html'\]"):
        _load(il)


def test_a_file_with_no_row_and_a_row_with_no_file_are_both_named(tmp_path: Path) -> None:
    il = _bundle(tmp_path, **{"u09.html": "<section></section>"})
    (il / "u02.html").unlink()
    with pytest.raises(TargetError) as caught:
        _load(il)
    assert caught.value.code() == "OW_TARGET_ROSTER_MISMATCH"
    assert "units with no file ['u02']" in str(caught.value)
    assert "files with no unit ['u09.html']" in str(caught.value)


def test_template_nsig_and_dot_files_are_not_units(tmp_path: Path) -> None:
    il = _bundle(tmp_path, **{"template.nsig": "0000abcd\n9f3a1c04\n", ".stamp.lock": "pid"})
    assert _load(il).template_nsigs == frozenset({"0000abcd", "9f3a1c04"})
    (il / "template.nsig").write_text("not-hex\n", encoding="utf-8")
    with pytest.raises(TargetError, match="8 hex"):
        _load(il)


@pytest.mark.parametrize(
    ("toml", "match"),
    [
        (IL_TOML.replace("omniweave.out-il/1", "omniweave.out-il/2"), "schema"),
        (IL_TOML.replace('il = "owtext/1"\n', ""), "required"),
        (
            IL_TOML.replace(f'constructs_digest = "{DIGEST}"', 'constructs_digest = "71c4"'),
            "required",
        ),
        (IL_TOML.replace("[[unit]]", 'origin = "projected"\n\n[[unit]]', 1), "origin"),
        (IL_TOML.replace("ord = 2", "ord = 3"), "1..2"),
        (IL_TOML.replace('id = "u02"', 'id = "u01"'), "repeats"),
        (IL_TOML.replace('file = "u02.html"', 'file = "il/u02.html"'), "basename"),
        (IL_TOML.replace('file = "u02.html"', 'file = "il.toml"'), "basename"),
        (IL_TOML.replace('id = "u02"', 'id = "slide2"'), "does not match"),
        (IL_TOML.replace('anchor = "cover"', 'anchor = "cover"\nnote = "x"'), "a \\[\\[unit\\]\\]"),
        (IL_TOML.replace("[[unit]]", "pages = 2\n\n[[unit]]", 1), "unknown key"),
        ("schema = ", "does not load"),
    ],
)
def test_an_il_toml_that_lies_is_refused(tmp_path: Path, toml: str, match: str) -> None:
    il = _bundle(tmp_path, **{"il.toml": toml})
    with pytest.raises(TargetError, match=match) as caught:
        _load(il)
    assert caught.value.code() == "OW_TARGET_IL_TOML_INVALID"


def test_no_il_toml_is_refused(tmp_path: Path) -> None:
    il = _bundle(tmp_path)
    (il / "il.toml").unlink()
    with pytest.raises(TargetError, match="does not load"):
        _load(il)


# ---------------------------------------------------------------------------
# A unit that will not parse, and the read boundary (rulings 15-16)
# ---------------------------------------------------------------------------


def test_a_unit_the_carrier_refuses_loads_without_an_nsig(tmp_path: Path) -> None:
    il = _bundle(tmp_path, **{"u02.html": "<!DOCTYPE html><section></section>"})
    bundle = _load(il)
    assert bundle.units[1].nsig is None
    assert "u02" not in bundle.els
    assert bundle.units[0].nsig is not None, "one refused unit does not hide the other"
    with pytest.raises(CarrierParseError):
        _carrier("il/u02.html", bundle.text("il/u02.html"))
    recovered = _load(_bundle(tmp_path / "r", **{"u02.html": "<section><p>b</section>"}))
    assert recovered.units[1].nsig is None, "a recovering read with problems is no parse"
    assert UNPARSED_HEX == "0" * 64
    other = _load(_bundle(tmp_path / "o", **{"u02.html": "<!DOCTYPE x><section>z</section>"}))
    assert other.il_digest != bundle.il_digest
    assert other.il_digest_rt == bundle.il_digest_rt, "ruling 15: a refused unit is 64 zeros"


def test_undecodable_bytes_are_order_zeros_and_a_large_file_is_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    il = _bundle(tmp_path)
    (il / "u02.html").write_bytes(b"<section>\xff</section>")
    bundle = _load(il)
    assert bundle.units[1].nsig is None
    with pytest.raises(CarrierParseError, match="not UTF-8"):
        bundle.text("il/u02.html")
    monkeypatch.setattr(job, "MAX_IL_FILE_BYTES", 10)
    with pytest.raises(ResourceLimit) as caught:
        bundle.data("il/u01.html")
    assert caught.value.limit == "MAX_IL_FILE_BYTES"


def test_an_unreadable_unit_stays_in_both_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    il = _bundle(tmp_path)
    clean = _load(il).il_digest
    real_open = Path.open

    def refuse(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "u02.html":
            raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", refuse)
    bundle = _load(il)
    assert [f.sha256 for f in bundle.files if f.name == "u02.html"] == [UNREADABLE]
    assert bundle.units[1].nsig is None
    assert bundle.il_digest != clean, "the unreadable file contributes the literal, never drops out"
