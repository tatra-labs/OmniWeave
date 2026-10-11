"""`omniweave_core.out.carrier`: the two stdlib carriers, the selector grammar and the splice.

09-generation.md section 3.1 (the carriers, `visible_text`, the four printed types, the selector
grammar and its eight rules), section 8.3 pt 3 (the transactional splice, OUT17) and section 14.3
(hostile input). Every IL a target author writes is parsed here, so the refusals are tested as
hard as the happy path: a DOCTYPE, a billion-laughs payload, a processing instruction, a bogus
comment and each ceiling.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from typing import Any

import pytest
from omniweave_core.errors import ResourceLimit, TargetError
from omniweave_core.limits import MAX_IL_DEPTH
from omniweave_core.out.carrier import (
    CarrierParseError,
    ParseError,
    Selector,
    Splice,
    parse_selector,
    style_declarations,
    tree,
)
from omniweave_core.out.carrier.html import HtmlDoc, html_carrier
from omniweave_core.out.carrier.tree import Node
from omniweave_core.out.carrier.xml import SvgDoc, svg_carrier

SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
    'viewBox="0 0 1280 720" data-ow-el="u01/e1">\n'
    '  <text x="10" y="20" data-ow-el="u01/e2" style="fill: #FFF; font-size:24px">\n'
    "    Revenue   grew\n"
    '    <tspan x="10" dy="1.2em">by 41.2 %</tspan>\n'
    "    <title>not visible</title>\n"
    "  </text>\n"
    '  <rect width="10" height="10" fill="#3a7bd5"/>\n'
    '  <use xlink:href="#a" data-ow-el="u01/e3"/>\n'
    "</svg>\n"
)

HTML = (
    '<section data-ow-unit="u01" data-ow-el="u01/e1">\n'
    '  <h2 id="t" data-ow-el="u01/e2">Q3   results</h2>\n'
    '  <p class="Lead" data-ow-el="u01/e3">Revenue <b>grew</b><br>by 41.2&nbsp;%</p>\n'
    "  <template><p>never shown</p></template>\n"
    '  <img src="asset-slot:00" alt="">\n'
    "</section>\n"
)


def _svg(text: str = SVG, *, strict: bool = True) -> SvgDoc:
    return svg_carrier("il/u01.svg", text, strict=strict)


def _html(text: str = HTML, *, strict: bool = True) -> HtmlDoc:
    return html_carrier("il/u01.html", text, strict=strict)


def _refused(build: object, text: str) -> ParseError:
    with pytest.raises(CarrierParseError) as caught:
        build("il/u01.x", text, strict=False)  # type: ignore[operator]
    return caught.value.error


# ---------------------------------------------------------------------------
# The tree a rule reads
# ---------------------------------------------------------------------------


def test_the_svg_tree_spells_tags_and_attributes_as_selectors_do() -> None:
    doc = _svg()
    root = doc.root()
    assert root.tag == "svg|svg"
    assert root.el == "u01/e1"
    assert [c.tag for c in root.children()] == ["svg|text", "svg|rect", "svg|use"]
    use = next(n for n in doc.nodes() if n.tag == "svg|use")
    assert use.attr("xlink:href") == "#a"
    assert use.attr("absent") is None
    assert doc.root().attr("viewBox") == "0 0 1280 720", "case is significant"


def test_positions_are_one_based_characters_and_bytes_land_on_the_tag() -> None:
    text = 'é<svg xmlns="http://www.w3.org/2000/svg">\n  <g>\n    <rect/></g></svg>'
    with pytest.raises(CarrierParseError):
        _svg(text)  # text before the root
    text = (
        '<svg xmlns="http://www.w3.org/2000/svg"><!-- é -->\n'
        '  <g>\n    <rect title="a>b" /></g></svg>'
    )
    doc = _svg(text)
    data = text.encode("utf-8")
    g, rect = (n for n in doc.nodes() if n.tag in {"svg|g", "svg|rect"})
    assert (g.at, rect.at) == ("il/u01.svg:2:3", "il/u01.svg:3:5")
    assert isinstance(rect, Node)
    assert data[rect.start : rect.end] == b'<rect title="a>b" />', "a quoted > ends no tag"
    assert rect.self_closing
    assert isinstance(g, Node)
    assert data[g.start : g.end] == b'<g>\n    <rect title="a>b" /></g>'
    assert data[g.start : g.start_end] == b"<g>"


def test_the_html_tree_lower_cases_and_closes_voids() -> None:
    doc = _html()
    section = doc.root()
    assert section.tag == "html|section"
    assert [c.tag for c in section.children()] == ["html|h2", "html|p", "html|template", "html|img"]
    img = next(n for n in doc.nodes() if n.tag == "html|img")
    assert isinstance(img, Node)
    data = HTML.encode("utf-8")
    assert data[img.start : img.end] == b'<img src="asset-slot:00" alt="">'
    assert img.attr("alt") == ""
    p = next(n for n in doc.nodes() if n.tag == "html|p")
    assert isinstance(p, Node)
    assert data[p.start : p.end].endswith(b"</p>")
    assert p.at == "il/u01.html:3:3"


def test_text_content_is_raw_and_visible_text_is_the_carriers_rule() -> None:
    doc = _svg()
    text = next(n for n in doc.nodes() if n.tag == "svg|text")
    assert "Revenue   grew" in text.text_content()
    assert "not visible" in text.text_content()
    assert doc.visible_text(text) == "Revenue grew\nby 41.2 %"
    assert doc.visible_text(doc.root()) == "Revenue grew\nby 41.2 %", (
        "ruling 10: each <text> under it"
    )
    html = _html()
    p = next(n for n in html.nodes() if n.tag == "html|p")
    assert html.visible_text(p) == "Revenue grew\nby 41.2\xa0%"
    assert html.visible_text(html.root()) == "Q3 results\nRevenue grew\nby 41.2\xa0%"


def test_svg_visible_text_honours_xml_space_preserve() -> None:
    text = (
        '<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve">'
        '<text x="0">  two  spaces<tspan dy="1em">next</tspan></text></svg>'
    )
    doc = _svg(text)
    node = next(n for n in doc.nodes() if n.tag == "svg|text")
    assert doc.visible_text(node) == "  two  spaces\nnext", "the <text>'s own x is no break"


def test_html_visible_text_takes_the_declared_sets() -> None:
    doc = html_carrier("il/u01.html", HTML, strict=True, blocks=(), invisible=("b",))
    p = next(n for n in doc.nodes() if n.tag == "html|p")
    assert doc.visible_text(p) == "Revenue\nby 41.2\xa0%"
    assert "never shown" in doc.visible_text(doc.root()), "no set, no silence"


# ---------------------------------------------------------------------------
# Refusals in both modes (09 section 3.1 item 4, section 14.3), rulings 8 and 12
# ---------------------------------------------------------------------------

_LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]><svg>&lol2;</svg>'
)


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ('<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>', "DOCTYPE"),
        (_LAUGHS, "DOCTYPE"),
        (
            '<?xml-stylesheet href="a.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
            "xml-stylesheet",
        ),
        ('<svg xmlns="http://www.w3.org/2000/svg"><?php echo 1 ?></svg>', "php"),
    ],
)
def test_the_svg_carrier_refuses_before_it_expands(text: str, why: str) -> None:
    error = _refused(svg_carrier, text)
    assert why in error.msg and "refused" in error.msg
    assert error.at.startswith("il/u01.x:1:")


def test_an_undeclared_entity_is_an_error_not_an_expansion() -> None:
    text = '<svg xmlns="http://www.w3.org/2000/svg">&lol;</svg>'
    with pytest.raises(CarrierParseError) as caught:
        _svg(text)
    assert caught.value.error.msg == "undefined entity"
    assert _svg(text, strict=False).root().text_content() == "", "recorded, and nothing expanded"
    doc = svg_carrier(
        "il/u01.svg", '<svg xmlns="http://www.w3.org/2000/svg">&lt;&#65;</svg>', strict=True
    )
    assert doc.root().text_content() == "<A"


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("<!DOCTYPE html><section></section>", "<!DOCTYPE"),
        ("<section><?php echo 1 ?></section>", "processing instruction"),
        ("<section><! bogus ></section>", "bogus comment"),
        ("<section></ 1></section>", "bogus comment"),
        ("<section><![CDATA[x]]></section>", "CDATA"),
    ],
)
def test_the_html_carrier_refuses_in_both_modes(text: str, why: str) -> None:
    error = _refused(html_carrier, text)
    assert why in error.msg


def test_an_html_comment_is_not_a_bogus_one() -> None:
    doc = _html("<section><!-- OWC1:v1 note --><p>a</p></section>")
    assert [c.tag for c in doc.root().children()] == ["html|p"]


def test_the_ceilings_are_resource_limits_naming_their_knob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deep = "<g>" * MAX_IL_DEPTH + "</g>" * MAX_IL_DEPTH
    with pytest.raises(ResourceLimit) as caught:
        _svg(f'<svg xmlns="http://www.w3.org/2000/svg">{deep}</svg>')
    assert caught.value.limit == "MAX_IL_DEPTH"
    with pytest.raises(ResourceLimit) as caught:
        _html("<div>" * (MAX_IL_DEPTH + 1))
    assert caught.value.limit == "MAX_IL_DEPTH"
    monkeypatch.setattr(tree, "MAX_IL_NODES", 3)
    with pytest.raises(ResourceLimit) as caught:
        _svg('<svg xmlns="http://www.w3.org/2000/svg"><g/><g/><g/></svg>')
    assert caught.value.limit == "MAX_IL_NODES"
    monkeypatch.setattr(tree, "MAX_IL_FILE_BYTES", 10)
    with pytest.raises(ResourceLimit) as caught:
        _html("<section>eleven bytes</section>")
    assert caught.value.limit == "MAX_IL_FILE_BYTES"


# ---------------------------------------------------------------------------
# Strict and recovering (ruling 4, 9, 11)
# ---------------------------------------------------------------------------


def test_the_svg_recovering_read_keeps_the_tree_to_the_first_error() -> None:
    text = '<svg xmlns="http://www.w3.org/2000/svg">\n<text>a</text>\n<g><rect></g></svg>'
    with pytest.raises(CarrierParseError) as caught:
        _svg(text)
    assert caught.value.error == ParseError("il/u01.svg:3:12", "mismatched tag")
    doc = _svg(text, strict=False)
    assert doc.problems == (caught.value.error,)
    assert [n.tag for n in doc.nodes()] == ["svg|svg", "svg|text", "svg|g", "svg|rect"]


@pytest.mark.parametrize(
    ("text", "msg"),
    [
        ("<section><p>a</section>", "</section> closes <p> early"),
        ("<section></p></section>", "</p> closes no open element"),
        ("<section><p>a</p>", "<section> is never closed"),
        ("<section></section><section></section>", "<section> is a second root element"),
        ("<section></section>tail", "text outside the root element"),
        ('<section id="a" id="b"></section>', "attribute 'id' is repeated on <section>"),
        ("<section><br></br></section>", "</br> closes a void element"),
        ("<section><div/></section>", "<div/> does not close a non-void element in HTML"),
    ],
)
def test_the_strict_html_parse_refuses_what_the_recovering_one_records(text: str, msg: str) -> None:
    with pytest.raises(CarrierParseError) as caught:
        _html(text)
    assert caught.value.error.msg == msg
    recovered = _html(text, strict=False)
    assert msg in [p.msg for p in recovered.problems]
    assert recovered.root().tag == "html|section"


def test_a_document_without_a_root_is_refused_in_both_modes() -> None:
    for build, text in ((svg_carrier, "<!-- nothing -->"), (html_carrier, "just text")):
        with pytest.raises(CarrierParseError):
            build("il/u01.x", text, strict=False)  # type: ignore[operator]


# ---------------------------------------------------------------------------
# The selector grammar (09 section 3.1's eight rules), ruling 5
# ---------------------------------------------------------------------------


def test_the_three_forms_each_yield_elements() -> None:
    doc = _svg()
    assert [n.tag for n in doc.select("svg|text")] == ["svg|text"]
    assert [n.tag for n in doc.select("@data-ow-el")] == ["svg|svg", "svg|text", "svg|use"]
    assert [n.tag for n in doc.select("@style|font-size")] == ["svg|text"]
    assert doc.select("@style|stroke") == ()
    assert [n.tag for n in doc.select("svg|svg[viewBox]")] == ["svg|svg"]
    assert doc.select("svg|rect[viewBox]") == ()
    html = _html()
    assert [n.tag for n in html.select("html|section[data-ow-unit]")] == ["html|section"]
    assert not html.select("html|style"), "ruling 1: an empty select is false"


@pytest.mark.parametrize(
    "selector",
    [
        "html|p",
        "svg|text p",
        "svg|text > tspan",
        "svg|*",
        ".class",
        "#id",
        "@fill|x",
        "svg|text:first",
        "@fill[x]",
        "svg|text[a=b]",
        "",
    ],
)
def test_an_unparseable_selector_is_a_usage_error_and_never_an_empty_match(selector: str) -> None:
    with pytest.raises(TargetError) as caught:
        _svg().select(selector)
    assert caught.value.code() == "OW_TARGET_SELECTOR_INVALID"
    assert "offset" in str(caught.value)


def test_a_foreign_namespace_matches_no_selector() -> None:
    text = (
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="urn:x">'
        "<x:text>hidden</x:text><link/></svg>"
    )
    doc = _svg(text)
    assert [n.tag for n in doc.nodes()] == ["svg|svg", "{urn:x}text", "svg|link"]
    assert doc.select("svg|text") == ()
    assert [n.tag for n in doc.select("svg|link")] == ["svg|link"], (
        "an unprefixed element is the carrier's"
    )


def test_parse_selector_shapes() -> None:
    assert parse_selector("svg|foreignObject", "svg") == Selector(
        "element", tag="svg|foreignObject"
    )
    assert parse_selector("html|div[data-ow-manual]", "html") == Selector(
        "element", tag="html|div", name="data-ow-manual"
    )
    assert parse_selector("@style|Mix-Blend-Mode", "svg") == Selector(
        "subproperty", name="style", prop="mix-blend-mode"
    )
    assert parse_selector("@xlink:href", "svg") == Selector("attribute", name="xlink:href")


def test_style_declarations_split_outside_quotes_and_parentheses() -> None:
    assert style_declarations('fill: url(a;b); FONT-family: "x;y", sans; ; nocolon') == (
        ("fill", "url(a;b)"),
        ("font-family", '"x;y", sans'),
    )


# ---------------------------------------------------------------------------
# The splice (OUT17), ruling 6
# ---------------------------------------------------------------------------


def test_a_splice_applies_back_to_front_in_one_byte_space() -> None:
    text = '<svg xmlns="http://www.w3.org/2000/svg"><text>é</text><rect/></svg>'
    doc = _svg(text)
    data = text.encode("utf-8")
    rect = next(n for n in doc.nodes() if n.tag == "svg|rect")
    assert isinstance(rect, Node)
    at = data.index("é".encode())
    out = doc.splice([Splice(at, at + 2, "üü"), Splice(rect.start, rect.end, '<rect width="1"/>')])
    assert out == '<svg xmlns="http://www.w3.org/2000/svg"><text>üü</text><rect width="1"/></svg>'
    assert doc.source() == text, "the document is untouched"


def test_a_splice_that_breaks_the_file_returns_the_error_and_writes_nothing() -> None:
    doc = _html()
    out = doc.splice([Splice(0, 0, "<div>")])
    assert isinstance(out, ParseError)
    assert "never closed" in out.msg or "second root" in out.msg


def test_overlapping_splices_and_split_characters_are_refused() -> None:
    doc = _svg('<svg xmlns="http://www.w3.org/2000/svg"><text>é</text></svg>')
    with pytest.raises(ValueError, match="overlap"):
        doc.splice([Splice(0, 5, "a"), Splice(4, 6, "b")])
    with pytest.raises(ValueError, match="overlap"):
        doc.splice([Splice(3, 3, "a"), Splice(3, 3, "b")])
    at = doc.source().encode("utf-8").index("é".encode())
    with pytest.raises(ValueError, match="boundary"):
        doc.splice([Splice(at + 1, at + 1, "x")])
    with pytest.raises(ValueError, match="boundary"):
        doc.splice([Splice(0, 10_000, "x")])
    with pytest.raises(ValueError, match="byte range"):
        Splice(5, 4, "")


def test_a_recovered_document_is_never_written_even_by_a_splice_that_would_repair_it() -> None:
    text = "<section><p>a</section>"
    doc = _html(text, strict=False)
    at = text.index("</section>")
    repaired = text[:at] + "</p>" + text[at:]
    _html(repaired)  # the repair would parse strictly
    assert doc.splice([Splice(at, at, "</p>")]) == doc.problems[0]


def _draws(seed: int) -> Iterator[int]:
    """A blake2b counter stream: the repo samples by hash, never by `random` (TID251)."""
    counter = 0
    while True:
        counter += 1
        digest = hashlib.blake2b(f"{seed}:{counter}".encode(), digest_size=8).digest()
        yield int.from_bytes(digest, "big")


def test_a_random_batch_leaves_the_file_parseable_or_unchanged() -> None:
    """09 section 8.3 pt 3's fuzz, at a size the unit tier can afford."""
    draws = _draws(733)
    doc = _svg()
    data = SVG.encode("utf-8")
    pieces = ["", "<g>", "</g>", "<rect/>", "x", '"', "<!-- c -->", "&amp;", "<", "é", "<g></g>"]
    outcomes = {"written": 0, "refused": 0}
    for _ in range(1_000):
        first = next(draws) % (len(data) // 2)
        second = len(data) // 2 + next(draws) % (len(data) // 2)
        cuts = (first, first + next(draws) % 4, second, min(second + next(draws) % 4, len(data)))
        if any(c < len(data) and data[c] & 0xC0 == 0x80 for c in cuts):
            continue
        batch = [
            Splice(cuts[0], cuts[1], pieces[next(draws) % len(pieces)]),
            Splice(cuts[2], cuts[3], pieces[next(draws) % len(pieces)]),
        ]
        out = doc.splice(batch)
        if isinstance(out, str):
            svg_carrier("il/u01.svg", out, strict=True)
            outcomes["written"] += 1
        else:
            outcomes["refused"] += 1
        assert doc.source() == SVG
    assert min(outcomes.values()) >= 50, outcomes  # both branches, measured at 75 and 925


@pytest.mark.parametrize(
    ("parse", "text", "tag"),
    [
        (
            lambda t: html_carrier("il/u01.html", t, strict=True),
            '<p b="2" a="1">x <em>y</em> z</p>',
            "html|em",
        ),
        (
            lambda t: svg_carrier("il/u01.svg", t, strict=True),
            '<svg xmlns="http://www.w3.org/2000/svg" b="2" a="1">x <g>y</g> z</svg>',
            "svg|g",
        ),
    ],
)
def test_a_node_lists_its_attributes_and_its_contents_in_order(
    parse: Any, text: str, tag: str
) -> None:
    """D781's `attrs()` and D782's `contents()`, on both carriers: source order, and the text
    between elements kept where it stands."""
    root = parse(text).root()
    assert [k for k in root.attrs() if k in {"a", "b"}] == ["b", "a"]
    before, element, after = root.contents()
    assert (before, after) == ("x ", " z")
    assert not isinstance(element, str)
    assert (element.tag, element.text_content()) == (tag, "y")
