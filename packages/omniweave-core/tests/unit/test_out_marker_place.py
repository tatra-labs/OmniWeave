"""`omniweave_core.out.marker.place` and `CarrierDoc.place_marker`: where a note goes, and when not.

09-generation.md section 8.2's placement paragraph and resolution table; charter OUT18 and OUT19. A
placed marker must scan, must resolve against the `nsig` it recorded, and must come out again by a
whole-line removal. Those three are asserted for both insertion forms, on both carriers.
"""

from __future__ import annotations

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.limits import MAX_MARKERS_PER_UNIT
from omniweave_core.out.carrier import CarrierDoc, ParseError
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.carrier.xml import svg_carrier
from omniweave_core.out.marker import (
    MarkerEdit,
    Payload,
    apply_reverse,
    encode_payload,
    place,
    resolve,
    scan,
)

NS = 'xmlns="http://www.w3.org/2000/svg"'
TS = "2026-09-03T11:04:00Z"
NOTE = Payload(note="make this the FY26 figure", sev="must", by="human")


def _svg(body: str, *, strict: bool = True) -> CarrierDoc:
    return svg_carrier(
        "il/u01.svg", f'<svg {NS} data-ow-el="u01/e1">\n{body}</svg>\n', strict=strict
    )


def _placed(doc: CarrierDoc, el: str, payload: Payload = NOTE) -> tuple[CarrierDoc, str]:
    out = place(doc, el, payload, TS)
    assert not isinstance(out, ParseError)
    text, _ = out
    return svg_carrier("il/u01.svg", text, strict=True) if "<svg" in text else html_carrier(
        "il/u01.html", text, strict=True
    ), text


def _anchor_nsig(doc: CarrierDoc, el: str) -> str:
    return next(n for n in doc.select("@data-ow-el") if n.el == el).nsig


@pytest.mark.parametrize(
    ("body", "line", "prefix"),
    [
        ('  <text data-ow-el="u01/e2" x="1">\n    41.2\n  </text>\n', 3, "    "),
        ('  <text data-ow-el="u01/e2" x="1">41.2</text>\n', 3, "\n"),
    ],
)
def test_a_placed_marker_scans_resolves_and_comes_out_again(
    body: str, line: int, prefix: str
) -> None:
    doc = _svg(body)
    before = _anchor_nsig(doc, "u01/e2")
    where = doc.place_marker(next(n for n in doc.select("@data-ow-el") if n.el == "u01/e2"))
    assert (where.line, where.prefix, where.hoisted, where.container_el) == (
        line,
        prefix,
        False,
        None,
    )
    marked, text = _placed(doc, "u01/e2")
    (marker,) = scan(marked)
    assert marker.line == line, "the marker sits on its own line"
    assert text.splitlines()[line - 1].strip().startswith("<!-- OWC1:v1 el=u01/e2")
    assert marker.nsig == before == _anchor_nsig(marked, "u01/e2"), "placing it moved no nsig"
    assert resolve(marked, marker).code is None
    cleared = apply_reverse(marked, [MarkerEdit(marker)])
    assert isinstance(cleared, str)
    if prefix != "\n":
        assert cleared == doc.source(), "a whole-line removal restores the file byte for byte"
    cleared_doc = svg_carrier("il/u01.svg", cleared, strict=True)
    assert _anchor_nsig(cleared_doc, "u01/e2") == before


def test_a_self_closing_anchor_hoists_to_its_container() -> None:
    doc = _svg('  <g data-ow-el="u01/e5">\n    <rect data-ow-el="u01/e3"/>\n  </g>\n')
    marked, _ = _placed(doc, "u01/e3")
    (marker,) = scan(marked)
    rect = next(n for n in doc.select("@data-ow-el") if n.el == "u01/e3")
    where = doc.place_marker(rect)
    assert (where.hoisted, where.container_el, where.el) == (True, "u01/e5", "u01/e3")
    assert marker.el == "u01/e3"
    assert resolve(marked, marker).code is None


def test_html_places_the_same_way() -> None:
    doc = html_carrier(
        "il/u01.html",
        '<section data-ow-el="u01/e1">\n  <p data-ow-el="u01/e2">a</p>\n</section>\n',
        strict=True,
    )
    marked, _ = _placed(doc, "u01/e2")
    (marker,) = scan(marked)
    assert resolve(marked, marker).code is None
    assert marker.nsig == _anchor_nsig(doc, "u01/e2")


def test_a_text_target_is_never_guessed() -> None:
    doc = _svg('  <text data-ow-el="u01/e2">a<tspan>b</tspan>c</text>\n')
    with pytest.raises(TargetError) as caught:
        place(doc, "u01/e2", NOTE, TS)
    assert caught.value.code() == "OW_TARGET_MARKER_AMBIGUOUS"
    picked = Payload(note=NOTE.note, sev="must", by="human", prev="c")
    assert not isinstance(place(doc, "u01/e2", picked, TS), ParseError)
    for prev in ("x", ""):
        with pytest.raises(TargetError, match="picks"):
            place(doc, "u01/e2", Payload(note=NOTE.note, sev="must", by="human", prev=prev), TS)
    single = _svg('  <text data-ow-el="u01/e2">a<tspan>b</tspan></text>\n')
    assert not isinstance(place(single, "u01/e2", NOTE, TS), ParseError), "one run is unambiguous"


@pytest.mark.parametrize(
    ("body", "el", "code"),
    [
        ('  <rect data-ow-el="u01/e2"/>\n', "u01/e9", "OW_TARGET_MARKER_ORPHAN"),
        (
            '  <rect data-ow-el="u01/e2"/>\n  <rect data-ow-el="u01/e2"/>\n',
            "u01/e2",
            "OW_TARGET_EL_DUPLICATE",
        ),
    ],
)
def test_a_placement_with_no_single_anchor_is_refused(body: str, el: str, code: str) -> None:
    with pytest.raises(TargetError) as caught:
        place(_svg(body), el, NOTE, TS)
    assert caught.value.code() == code


def test_the_257th_note_is_refused() -> None:
    lines = "".join(
        f"  <!-- OWC1:v1 el=u01/e2 nsig=00000000 id=k-{n:08x} ts={TS} "
        f"p={encode_payload(NOTE)} -->\n"
        for n in range(MAX_MARKERS_PER_UNIT)
    )
    with pytest.raises(TargetError) as caught:
        place(_svg(lines + '  <rect data-ow-el="u01/e2"/>\n'), "u01/e2", NOTE, TS)
    assert caught.value.code() == "OW_TARGET_MARKER_BUDGET"


def test_a_recovered_document_takes_no_marker() -> None:
    doc = html_carrier(
        "il/u01.html",
        '<section data-ow-el="u01/e1"><p data-ow-el="u01/e2">a</section>',
        strict=False,
    )
    assert place(doc, "u01/e2", NOTE, TS) == doc.problems[0]


def test_whitespace_is_not_content_for_nsig() -> None:
    """D746's amendment: runs collapse and ends strip, so a marker's own line moves nothing."""
    tight = _svg('  <text data-ow-el="u01/e2">a b</text>\n')
    loose = _svg('  <text data-ow-el="u01/e2">\n    a   b\n  </text>\n')
    other = _svg('  <text data-ow-el="u01/e2">a c</text>\n')
    pick = [
        next(n for n in d.select("@data-ow-el") if n.el == "u01/e2") for d in (tight, loose, other)
    ]
    assert pick[0].nsig == pick[1].nsig != pick[2].nsig
