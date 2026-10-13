"""`compile.pptx.native`'s citations and manual regions: the provenance part, and a marked
placeholder. D802.

Each deck is lowered through `lowered()` (tests/lowerkit.py), whose `cites` pins a cite's
generation in the Plan and whose `draft` makes a draft, and read back from the package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from lowerkit import (  # type: ignore[import-not-found]  # tests/lowerkit.py
    A,
    P,
    box,
    lowered,
    outline,
    slide,
    u,
)
from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_core.errors import TargetError
from omniweave_core.out.opc import write_opc
from omniweave_core.out.plan import UnitOutcome
from omniweave_target_pptx.driver import PROVENANCE, PptxCompiler

CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def part(out: Any) -> Any:
    return json.loads(out.members[PROVENANCE])


# ---------------------------------------------------------------------------------------------
# the provenance part
# ---------------------------------------------------------------------------------------------


def test_the_part_is_written_even_with_nothing_cited(tmp_path: Path) -> None:
    out = lowered(tmp_path, slide('<rect width="1" height="1"/>'))
    assert part(out) == {
        "schema": "omniweave.out-provenance/1",
        "corpus": "acme",
        "slug": "deck",
        "artifact_gen": 1,
        "cites": [],
        "els": {},
    }
    root = etree.fromstring(out.members["_rels/.rels"])
    assert [
        r.get("Target") for r in root if r.get("Type") == "urn:omniweave:relationship:provenance"
    ] == [PROVENANCE]
    types = etree.fromstring(out.members["[Content_Types].xml"])
    assert [
        o.get("ContentType")
        for o in types.iter(f"{CT}Override")
        if o.get("PartName") == f"/{PROVENANCE}"
    ] == ["application/json"]


def test_the_part_maps_every_address_to_its_construct(tmp_path: Path) -> None:
    out = lowered(
        tmp_path,
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u01/e1">'
        '<rect data-ow-el="u01/e2" width="1" height="1"/><text data-ow-el="u01/e3" y="9">a</text>'
        '<g data-ow-el="u01/e4"><circle data-ow-el="u01/e5" r="1"/></g></svg>',
    )
    assert part(out)["els"] == {
        "u01/e1": "ow.unit",
        "u01/e2": "shape.rect",
        "u01/e3": "text.text",
        "u01/e4": "shape.g",
        "u01/e5": "shape.circle",
    }


def test_each_cite_is_a_row_with_its_pinned_generation(tmp_path: Path) -> None:
    out = lowered(
        tmp_path,
        slide(
            '<text data-ow-el="u01/e2" y="9" data-ow-cite="acme:d7#1 d7#2" '
            'data-ow-cite-kind="paraphrase" data-ow-cite-span="0:3">a</text>'
            '<rect data-ow-el="u01/e3" width="1" height="1" data-ow-cite="d9#4" '
            'data-ow-cite-kind="quote" data-ow-cite-span="2:5"/>'
        ),
        cites={"d7#1": 3, "d7#2": 4, "d9#4": 1},
    )
    assert part(out)["cites"] == [
        {"el": "u01/e2", "cite": "d7#1", "doc_gen": 3, "kind": "paraphrase", "span": None},
        {"el": "u01/e2", "cite": "d7#2", "doc_gen": 4, "kind": "paraphrase", "span": None},
        {"el": "u01/e3", "cite": "d9#4", "doc_gen": 1, "kind": "quote", "span": [2, 5]},
    ]
    checks = {c.name: (c.value, c.detail) for c in out.receipt().checks}
    assert checks["citations_channel"] == ("passed", "embedded: 3 cite row(s)")


def test_a_cite_draws_nothing(tmp_path: Path) -> None:
    plain = lowered(tmp_path / "a", slide('<rect data-ow-el="u01/e2" width="1" height="1"/>'))
    cited = lowered(
        tmp_path / "b",
        slide('<rect data-ow-el="u01/e2" width="1" height="1" data-ow-cite="d7#1"/>'),
        cites={"d7#1": 1},
    )
    assert outline(plain.first()) == outline(cited.first())


@pytest.mark.parametrize(
    ("body", "code", "said"),
    [
        ('<rect width="1" height="1" data-ow-cite="d7#1"/>',
         "OW_TARGET_IL_MALFORMED", "carries no data-ow-el"),
        ('<rect data-ow-el="u01/e2" width="1" height="1" data-ow-cite="d7#9"/>',
         "OW_TARGET_CITE_UNRESOLVED", "d7#9"),
        (
            '<rect data-ow-el="u01/e2" width="1" height="1" data-ow-cite="d7#1" '
            'data-ow-cite-kind="rumour"/>',
            "OW_TARGET_IL_MALFORMED",
            "is not one of",
        ),
        (
            '<rect data-ow-el="u01/e2" width="1" height="1" data-ow-cite="d7#1" '
            'data-ow-cite-span="5:2"/>',
            "OW_TARGET_IL_MALFORMED",
            "is not a:b with a < b",
        ),
    ],
)  # fmt: skip
def test_a_cite_the_part_cannot_state_is_refused(
    tmp_path: Path, body: str, code: str, said: str
) -> None:
    with pytest.raises(TargetError, match=said) as caught:
        lowered(tmp_path, slide(body), cites={"d7#1": 1})
    assert caught.value.code() == code


def test_a_package_without_its_provenance_part_is_a_failed_row(tmp_path: Path) -> None:
    out = lowered(tmp_path, slide('<rect width="1" height="1"/>'))
    members = {n: d for n, d in out.members.items() if n != PROVENANCE}
    rels = etree.fromstring(members["_rels/.rels"])
    for r in [r for r in rels if r.get("Target") == PROVENANCE]:
        rels.remove(r)
    members["_rels/.rels"] = etree.tostring(rels)
    out.path.write_bytes(write_opc(members))
    [row] = [
        c
        for c in PptxCompiler().postflight(str(out.path), out.plan).checks
        if c.name == "citations_channel"
    ]
    assert (row.value, row.detail) == ("failed", f"no {PROVENANCE} in the package")


# ---------------------------------------------------------------------------------------------
# manual regions
# ---------------------------------------------------------------------------------------------


def test_a_manual_region_is_its_content_its_reason_and_an_outline(tmp_path: Path) -> None:
    out = lowered(
        tmp_path,
        slide(
            '<g data-ow-el="u01/e2" data-ow-manual="unverifiable_data">'
            '<rect x="10" y="10" width="20" height="20"/></g>'
        ),
        draft=True,
    )
    [made] = out.shapes()
    named = made.find(f"{P}nvGrpSpPr/{P}cNvPr")
    assert (named.get("name"), named.get("descr")) == ("u01/e2", "ow:manual unverifiable_data")
    rect, mark = made.findall(f"{P}sp")
    assert box(rect) == box(mark) == (u(10), u(10), u(20), u(20))
    assert outline(mark) == [
        "sp",
        "nvSpPr",
        "cNvPr descr=ow:manual unverifiable_data id=4 name=ow:manual 4",
        "cNvSpPr",
        "nvPr",
        "spPr",
        "xfrm",
        f"off x={u(10)} y={u(10)}",
        f"ext cx={u(20)} cy={u(20)}",
        "prstGeom prst=rect",
        "avLst",
        "noFill",
        f"ln w={u(2)}",
        "solidFill",
        "srgbClr val=C00000",
        "prstDash val=dash",
    ]
    receipt = out.receipt()
    assert dict(receipt.units) == {"u01": UnitOutcome.MANUAL_REQUIRED}
    assert receipt.delivery == "draft"


def test_an_empty_manual_region_is_its_outline_alone(tmp_path: Path) -> None:
    out = lowered(tmp_path, slide('<g data-ow-manual="unverifiable_data"/>'), draft=True)
    [made] = out.shapes()
    [mark] = made.findall(f"{P}sp")
    assert box(mark) == (0, 0, 0, 0)
    assert mark.find(f"{P}nvSpPr/{P}cNvPr").get("descr") == "ow:manual unverifiable_data"
    assert not list(made.iter(f"{A}t"))
