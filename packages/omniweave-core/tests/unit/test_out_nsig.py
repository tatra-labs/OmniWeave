"""`nsig`: the canonical subtree digest, its six normalizations and the definition dependency.

09-generation.md section 8.2. `nsig` is 8 hex over the canonicalized subtree. It is a change
detector, so every normalization is tested both ways: the change it forgives does not move `nsig`,
and a real change does. The shared-definition clause is tested where 09 says people forget it: a
subtree whose own bytes are identical but whose `<defs>` entry moved has changed.
"""

from __future__ import annotations

import pytest
from omniweave_core.out.carrier.tree import Node
from omniweave_core.out.carrier.xml import svg_carrier
from omniweave_core.out.report import (
    canonical_subtree,
    changed_definitions,
    definitions,
    nsig,
    referenced_ids,
    unchanged,
)

NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
SLOT = "a" * 64


def _el(body: str, el: str = "u01/e2") -> Node:
    doc = svg_carrier("il/u01.svg", f"<svg {NS}>{body}</svg>", strict=True)
    node = next(n for n in doc.nodes() if n.attr("data-ow-el") == el)
    assert isinstance(node, Node)
    return node


def _root(body: str) -> Node:
    root = svg_carrier("il/u01.svg", f"<svg {NS}>{body}</svg>", strict=True).root()
    assert isinstance(root, Node)
    return root


def test_nsig_is_eight_hex_and_memoized_on_the_node() -> None:
    node = _el('<rect data-ow-el="u01/e2" width="1"/>')
    value = nsig(node)
    assert len(value) == 8 and int(value, 16) >= 0
    assert node.nsig == value
    assert node.nsig is node.nsig, "computed once"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # 6: the address itself is ignored
        ('<rect data-ow-el="u01/e2" width="1"/>', '<rect width="1" data-ow-el="u01/e2"/>'),
        # attribute order and indentation are not content
        (
            '<g data-ow-el="u01/e2"><rect a="1" b="2"/></g>',
            '<g data-ow-el="u01/e2">\n  <rect b="2" a="1"/>\n</g>',
        ),
        # 5: an attribute-free one-child <g> is its child
        (
            '<g data-ow-el="u01/e2"><g><g><rect width="1"/></g></g></g>',
            '<g data-ow-el="u01/e2"><rect width="1"/></g>',
        ),
        # 4: a filter on a one-visual-child, otherwise bare, group lowers to the child
        (
            '<g data-ow-el="u01/e2"><g filter="url(#f)"><title>t</title><rect width="1"/></g></g>',
            '<g data-ow-el="u01/e2"><g><title>t</title><rect filter="url(#f)" width="1"/></g></g>',
        ),
    ],
)
def test_each_normalization_forgives_its_change(before: str, after: str) -> None:
    assert nsig(_el(before)) == nsig(_el(after))


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('<rect data-ow-el="u01/e2" width="1"/>', '<rect data-ow-el="u01/e2" width="2"/>'),
        ('<text data-ow-el="u01/e2">41.2</text>', '<text data-ow-el="u01/e2">41.3</text>'),
        (
            '<g data-ow-el="u01/e2"><rect/><circle/></g>',
            '<g data-ow-el="u01/e2"><circle/><rect/></g>',
        ),
        # a group WITH an attribute is not collapsed
        (
            '<g data-ow-el="u01/e2"><g opacity="0.5"><rect/></g></g>',
            '<g data-ow-el="u01/e2"><rect/></g>',
        ),
        # a filter on a two-child group is NOT lowered
        (
            '<g data-ow-el="u01/e2"><g filter="url(#f)"><rect/><circle/></g></g>',
            '<g data-ow-el="u01/e2"><g><rect filter="url(#f)"/><circle filter="url(#f)"/></g></g>',
        ),
        # a filter is not lowered onto a child that has its own
        (
            '<g data-ow-el="u01/e2"><g filter="url(#f)"><rect filter="url(#g)"/></g></g>',
            '<g data-ow-el="u01/e2"><g><rect filter="url(#f)"/></g></g>',
        ),
        # nor onto a construct no filter target names
        (
            '<g data-ow-el="u01/e2"><g filter="url(#f)"><ellipse/></g></g>',
            '<g data-ow-el="u01/e2"><g><ellipse filter="url(#f)"/></g></g>',
        ),
        # tail text is content
        (
            '<text data-ow-el="u01/e2">a<tspan>b</tspan>c</text>',
            '<text data-ow-el="u01/e2">a<tspan>b</tspan>d</text>',
        ),
    ],
)
def test_a_real_change_moves_nsig(before: str, after: str) -> None:
    assert nsig(_el(before)) != nsig(_el(after))


def test_no_address_is_content_the_measured_ones_or_a_childs() -> None:
    """Normalization 6 over every `data-ow-el` in the subtree, not only the measured element's."""
    one = _el('<g data-ow-el="u01/e2"><rect data-ow-el="u01/e3"/></g>')
    other = _el('<g data-ow-el="u01/e7"><rect data-ow-el="u01/e9"/></g>', el="u01/e7")
    assert nsig(one) == nsig(other)


def test_a_filtered_group_with_another_attribute_keeps_its_filter() -> None:
    kept = _el('<g data-ow-el="u01/e2"><g filter="url(#f)" opacity="0.5"><rect/></g></g>')
    lowered = _el('<g data-ow-el="u01/e2"><g opacity="0.5"><rect filter="url(#f)"/></g></g>')
    assert nsig(kept) != nsig(lowered)


def test_a_bare_group_collapses_at_any_depth() -> None:
    deep = _el('<g data-ow-el="u01/e2"><g opacity="1"><g><rect/></g></g></g>')
    flat = _el('<g data-ow-el="u01/e2"><g opacity="1"><rect/></g></g>')
    assert nsig(deep) == nsig(flat)


def test_the_root_of_the_subtree_is_never_collapsed() -> None:
    """ppt-master collapses below the measured element, never the element itself."""
    assert nsig(_el('<g data-ow-el="u01/e2"><rect/></g>')) != nsig(
        _el('<rect data-ow-el="u01/e2"/>')
    )


def test_a_clone_prefix_is_stripped_from_ids_and_references() -> None:
    cloned = _el(
        '<g data-ow-el="u01/e2"><linearGradient id="c3_grad"/>'
        '<rect fill="url(#c3_grad)"/><use xlink:href="#c3_grad"/></g>'
    )
    plain = _el(
        '<g data-ow-el="u01/e2"><linearGradient id="grad"/><rect fill="url(#grad)"/>'
        '<use xlink:href="#grad"/></g>'
    )
    assert nsig(cloned) != nsig(plain)
    assert nsig(cloned, clone_prefix="c3_") == nsig(plain)
    assert b"c3_" not in canonical_subtree(cloned, clone_prefix="c3_")


def test_an_edited_asset_is_folded_in() -> None:
    node = _el(f'<image data-ow-el="u01/e2" href="asset-slot:{SLOT}"/>')
    edited = nsig(node, edited={SLOT: "b" * 64})
    assert edited != nsig(node)
    assert f":edited:{'b' * 64}".encode() in canonical_subtree(node, edited={SLOT: "b" * 64})
    assert nsig(node, edited={"c" * 64: "b" * 64}) == nsig(node), (
        "another slot's edit is not this one"
    )


def test_referenced_ids_reads_urls_hrefs_and_style_text() -> None:
    node = _el(
        '<g data-ow-el="u01/e2" clip-path="url(#clip)"><rect fill="url( \'#grad\' )"/>'
        '<use href="#sym"/><use xlink:href="#icon"/><use href="https://x"/>'
        "<style>.a{fill:url(#css)}</style></g>"
    )
    assert referenced_ids(node) == frozenset({"clip", "grad", "sym", "icon", "css"})


def test_a_changed_definition_changes_a_subtree_whose_bytes_did_not() -> None:
    body = '<rect data-ow-el="u01/e2" fill="url(#grad)"/><rect data-ow-el="u01/e3" fill="red"/>'
    before = _root(
        '<defs><linearGradient id="grad"><stop offset="0"/></linearGradient>'
        f'<g id="keep"/></defs>{body}'
    )
    after = _root(
        '<defs><linearGradient id="grad"><stop offset="1"/></linearGradient>'
        f'<g id="keep"/></defs>{body}'
    )
    changed = changed_definitions(definitions(before), definitions(after))
    assert changed == frozenset({"grad"})
    users = {n.attr("data-ow-el"): n for n in _walk(after) if n.attr("data-ow-el")}
    assert nsig(users["u01/e2"]) == nsig(
        next(n for n in _walk(before) if n.attr("data-ow-el") == "u01/e2")
    )
    assert not unchanged(users["u01/e2"], nsig(users["u01/e2"]), changed), "its own bytes are equal"
    assert unchanged(users["u01/e3"], nsig(users["u01/e3"]), changed)


def test_definitions_are_the_direct_defs_children_with_ids() -> None:
    root = _root(
        '<defs><g id="a"/><g/><g id="b"><g id="nested"/></g></defs>'
        '<g><defs><g id="deep"/></defs></g>'
    )
    assert set(definitions(root)) == {"a", "b"}
    assert definitions(_root("<rect/>")) == {}
    assert changed_definitions({"a": "1", "b": "2"}, {"a": "1", "c": "3"}) == frozenset({"b", "c"})


def _walk(root: Node) -> list[Node]:
    out: list[Node] = []
    stack = [root]
    while stack:
        node = stack.pop()
        out.append(node)
        stack.extend(node.children())
    return out
