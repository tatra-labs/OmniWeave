"""`pptx.reference@1`: every local reference resolves to what it needs. D791."""

from __future__ import annotations

from typing import Any

import pytest
from omniweave_target_pptx.rules.reference import NAMED, SPEC, USE_TARGETS

SLOT = "asset-slot:" + "ab" * 32
DEFS = (
    '<defs><linearGradient id="g"/><pattern id="p"/><filter id="f"/><marker id="m"/>'
    '<clipPath id="c"/><symbol id="s"/></defs>'
)


def test_the_spec_and_what_each_reference_names() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.reference@1",
        50,
        {"OW_TARGET_REFERENCE_UNRESOLVED", "OW_TARGET_IL_ASSET_URI"},
    )
    assert set(NAMED) == {"fill", "stroke", "filter", "marker-start", "marker-end", "clip-path"}
    assert "svg|symbol" in USE_TARGETS
    assert "svg|defs" not in USE_TARGETS


@pytest.mark.parametrize(
    "body",
    [
        '<rect fill="url(#g)" stroke="url(#g)" filter="url(#f)"/>',
        '<rect fill="url(#p)"/><path d="M0 0" marker-start="url(#m)" marker-end="url(#m)"/>',
        f'<image href="{SLOT}" clip-path="url(#c)"/>',
        '<use href="#s"/><use href="#r"/><rect id="r"/>',
        '<a href="#u03"><rect/></a><a href="https://example.org/q3"><rect/></a>',
        '<rect style="fill: url(#g); stroke: #000000"/>',
        '<rect fill="#FFFFFF" stroke="none"/>',
    ],
)
def test_references_that_resolve_say_nothing(slide: Any, body: str) -> None:
    assert slide(SPEC, DEFS + body) == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('<rect fill="url(#nope)"/>',
         "<rect> fill='url(#nope)': names no id in this slide; it needs <linearGradient> or "
         "<pattern> or <radialGradient>"),
        ('<rect stroke="url(#p)"/>',
         "<rect> stroke='url(#p)': names a <pattern>, and stroke takes <linearGradient> or "
         "<radialGradient>"),
        ('<rect filter="url(#m)"/>', "names a <marker>, and filter takes <filter>"),
        ('<rect filter="blur(2)"/>', "<rect> filter='blur(2)': write url(#id)"),
        ('<path d="M0 0" marker-end="url(#c)"/>', "names a <clipPath>, and marker-end takes"),
        ('<image href="https://example.org/a.png"/>',
         "a picture is asset-slot:<sha256 hex>; freeze the asset and write its slot"),
        ('<use href="s"/>', "<use> href='s': a <use> names a local id, #id"),
        ('<use href="#f"/>', "names a <filter>, and href takes"),
        ('<a href="http://example.org"><rect/></a>', "a link is #u<NN>, a slide, or https:"),
        ('<a href="#u3"><rect/></a>', "a link is #u<NN>"),
        ('<a href="#u09"><rect/></a>',
         "<a> href='#u09': names no slide in this deck; its units are u01, u02, u03"),
        ('<rect href="#g"/>', "href belongs to <use>, <image> or <a>"),
        ("<image/>", "a <image> names its picture as href=asset-slot:<sha256>"),
        ("<use/>", "a <use> names href=#id"),
    ],
)  # fmt: skip
def test_references_that_do_not_resolve_are_named(slide: Any, body: str, said: str) -> None:
    [found] = slide(SPEC, DEFS + body)
    assert said in found.msg


def test_codes_follow_what_is_wrong(slide: Any) -> None:
    found = slide(SPEC, DEFS + '<image href="a.png"/><rect fill="url(#x)"/><image/>')
    assert [f.code for f in found] == [
        "OW_TARGET_REFERENCE_UNRESOLVED",
        "OW_TARGET_IL_ASSET_URI",
        "OW_TARGET_IL_ASSET_URI",
    ]


def test_an_id_is_defined_once(slide: Any) -> None:
    [found] = slide(SPEC, '<rect id="a"/><g><circle id="a"/></g>')
    assert found.msg == "id='a' is defined twice in the slide; url(#id) and href need one"
    assert (found.construct, found.code) == ("geom.id", "OW_TARGET_REFERENCE_UNRESOLVED")
