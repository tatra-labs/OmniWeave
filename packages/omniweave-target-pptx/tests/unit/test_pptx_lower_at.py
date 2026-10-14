"""`compile.pptx.native`'s address map: where each `data-ow-el` landed in the deck. D803.

The provenance part's `at` names, for each address, its unit, its shape's `p:cNvPr` id, and for a
`<tspan>` its paragraph and the run range its text took, since a run has no name to carry one.
`parse.pptx.native` reads it. The last test holds each located run range to R2's text clause:
read back from the package, it is the element's own `visible_text()`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from lowerkit import (  # type: ignore[import-not-found]  # tests/lowerkit.py
    A,
    P,
    lowered,
)
from omniweave_core.out.carrier.tree import collapse
from omniweave_target_pptx.driver import PROVENANCE, PptxCompiler

ROOT = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u{n}/e1">'


def unit(n: int, body: str) -> str:
    return ROOT.format(n=f"{n:02d}") + body + "</svg>"


def at(out: Any) -> dict[str, dict[str, Any]]:
    return json.loads(out.members[PROVENANCE])["at"]


def test_every_kind_of_address_lands_where_its_reader_looks(tmp_path: Path) -> None:
    out = lowered(
        tmp_path,
        unit(
            1,
            '<rect data-ow-el="u01/e2" width="1" height="1"/>'
            '<g data-ow-el="u01/e3"><text data-ow-el="u01/e4" y="9">a'
            '<tspan data-ow-el="u01/e5" font-weight="bold">b</tspan>'
            '<tspan data-ow-el="u01/e6" x="0" dy="9">c</tspan></text></g>'
            '<a data-ow-el="u01/e7" href="#u02"><circle data-ow-el="u01/e8" r="1"/></a>',
        ),
        unit(2, '<rect data-ow-el="u02/e2" width="1" height="1"/>'),
    )
    assert at(out) == {
        "u01/e1": {"unit": "u01"},
        "u01/e2": {"unit": "u01", "shape": 2},
        "u01/e3": {"unit": "u01", "shape": 3},
        "u01/e4": {"unit": "u01", "shape": 4},
        "u01/e5": {"unit": "u01", "shape": 4, "line": 0, "runs": [1, 2]},
        "u01/e6": {"unit": "u01", "shape": 4, "line": 1, "runs": [0, 1]},
        "u01/e7": {"unit": "u01", "shape": 5},
        "u01/e8": {"unit": "u01", "shape": 6},
        "u02/e1": {"unit": "u02"},
        "u02/e2": {"unit": "u02", "shape": 2},
    }


def test_a_tspan_takes_its_descendants_runs_and_an_empty_one_none(tmp_path: Path) -> None:
    out = lowered(
        tmp_path,
        unit(
            1,
            '<text data-ow-el="u01/e2" y="9">a<tspan data-ow-el="u01/e3">b'
            '<tspan data-ow-el="u01/e4">c</tspan>d</tspan>e'
            '<tspan data-ow-el="u01/e5"/>'
            '<tspan data-ow-el="u01/e7">f<tspan data-ow-el="u01/e8">g</tspan></tspan>'
            '<tspan data-ow-el="u01/e6" x="0" dy="9"/></text>',
        ),
    )
    found = at(out)
    # runs on line 0: a b c d e f g; a descendant's run ends its ancestor's range (e7)
    runs = [found[f"u01/e{n}"].get("runs") for n in (3, 4, 5, 7, 8, 6)]
    assert runs == [[1, 4], [2, 3], [0, 0], [5, 7], [6, 7], [0, 0]]
    assert [found[f"u01/e{n}"].get("line") for n in (3, 4, 5, 7, 8, 6)] == [0, 0, 0, 0, 0, 1]


def test_a_clone_lands_nowhere_and_its_use_where_it_stands(tmp_path: Path) -> None:
    out = lowered(
        tmp_path,
        unit(
            1,
            '<defs><text id="t" data-ow-el="u01/e2" y="9">a<tspan data-ow-el="u01/e3">b</tspan>'
            '</text></defs><use data-ow-el="u01/e4" href="#t"/>',
        ),
    )
    assert at(out) == {"u01/e1": {"unit": "u01"}, "u01/e4": {"unit": "u01", "shape": 2}}


@pytest.mark.parametrize(
    "body",
    [
        '<text data-ow-el="u01/e2" y="9">Revenue\n  <tspan data-ow-el="u01/e3">rose</tspan> 12%'
        '<tspan data-ow-el="u01/e4" x="0" dy="9">in <tspan data-ow-el="u01/e5">Q3</tspan></tspan>'
        "</text>",
        '<text data-ow-el="u01/e2" y="9"><tspan data-ow-el="u01/e3" x="0" dy="9"> a  b </tspan>'
        '<tspan data-ow-el="u01/e4" x="0" dy="9">c</tspan>d</text>',
        '<text data-ow-el="u01/e2" y="9" xml:space="preserve"> a '
        '<tspan data-ow-el="u01/e3"> b </tspan></text>',
    ],
)
def test_each_located_text_reads_back_as_its_visible_text(tmp_path: Path, body: str) -> None:
    """R2's text clause, through `at`: a text box's paragraphs joined a line each, ends trimmed
    of empty lines, and a `<tspan>`'s runs joined, collapsed unless preserved."""
    out = lowered(tmp_path, unit(1, body))
    doc = PptxCompiler().carrier("il/u01.svg", unit(1, body))
    preserved = 'xml:space="preserve"' in body
    tree = out.tree()
    shapes = {int(c.get("id")): c for c in tree.iter(f"{P}cNvPr")}
    seen = 0
    for node in _addressed(doc.root()):
        place = at(out)[node.el]
        if "shape" not in place:
            continue
        box = shapes[place["shape"]].getparent().getparent()
        paragraphs = box.findall(f"{P}txBody/{A}p")
        if "line" in place:
            runs = paragraphs[place["line"]].findall(f"{A}r")[slice(*place["runs"])]
            text = "".join(r.find(f"{A}t").text or "" for r in runs)
            found = text if preserved else collapse(text)
        else:
            found = "\n".join(
                "".join(t.text or "" for t in p.iter(f"{A}t")) for p in paragraphs
            ).strip("\n")
        assert found == doc.visible_text(node), node.el
        seen += 1
    assert seen >= 2


def _addressed(root: Any) -> list[Any]:
    out, stack = [], [root]
    while stack:
        node = stack.pop()
        if node.el:
            out.append(node)
        stack.extend(reversed(list(node.children())))
    return out


def test_the_part_body_holds_at_only_where_a_target_passes_it() -> None:
    """docx writes none (its bookmarks carry its addresses); a deck always writes one."""
    from omniweave_core.out.provenance import body  # noqa: PLC0415 -- the framework's own

    plain = json.loads(body([], {}, corpus="a", slug="s", artifact_gen=1))
    placed = json.loads(body([], {}, corpus="a", slug="s", artifact_gen=1, at={"e": {"unit": "u"}}))
    assert ("at" in plain, placed["at"]) == (False, {"e": {"unit": "u"}})
