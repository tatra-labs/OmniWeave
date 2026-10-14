"""`omniweave_core.out.opc`: the one ZIP writer, the part digest, and section 5.3's package checks.

09-generation.md section 5.3 (the four hard preconditions), section 6 (`part` is the portable floor,
`byte` recorded) and section 14.4 (built in memory, returned as bytes); charter OUT13 and OUT15. The
package is a minimal pptx-shaped OPC: content types, the root relationships, one presentation part
and one slide.
"""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.out.opc import (
    CANONICAL_DATE,
    check_package,
    check_unit_count,
    part_digest,
    write_opc,
)

TYPES = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    b'<Default Extension="rels" ContentType="application/relationships+xml"/>'
    b'<Default Extension="xml" ContentType="application/xml"/>'
    b'<Override PartName="/ppt/presentation.xml" ContentType="application/x-presentation"/>'
    b"</Types>"
)
ROOT_RELS = (
    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    b'<Relationship Id="rId1" Type="t" Target="ppt/presentation.xml"/>'
    b'<Relationship Id="rId2" Type="t" Target="https://example.invalid/x" TargetMode="External"/>'
    b"</Relationships>"
)
PRES_RELS = (
    b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    b'<Relationship Id="rId1" Type="t" Target="slides/slide1.xml"/>'
    b"</Relationships>"
)
MEMBERS = {
    "ppt/slides/slide1.xml": b"<sld/>",
    "ppt/_rels/presentation.xml.rels": PRES_RELS,
    "_rels/.rels": ROOT_RELS,
    "ppt/presentation.xml": b"<presentation/>",
    "[Content_Types].xml": TYPES,
}


def test_the_package_is_written_in_canonical_order_with_every_field_pinned() -> None:
    data = write_opc(MEMBERS)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        assert [i.filename for i in infos] == [
            "[Content_Types].xml",
            "_rels/.rels",
            "ppt/_rels/presentation.xml.rels",
            "ppt/presentation.xml",
            "ppt/slides/slide1.xml",
        ]
        assert {
            (i.date_time, i.create_system, i.external_attr, i.compress_type) for i in infos
        } == {(CANONICAL_DATE, 3, 0o644 << 16, zipfile.ZIP_DEFLATED)}
        assert {i.filename: zf.read(i) for i in infos} == MEMBERS


def test_the_bytes_do_not_depend_on_the_callers_order() -> None:
    reversed_members = dict(reversed(list(MEMBERS.items())))
    assert write_opc(reversed_members) == write_opc(MEMBERS)


def test_part_digest_is_over_parts_and_not_the_container() -> None:
    fast, small = write_opc(MEMBERS, compresslevel=1), write_opc(MEMBERS, compresslevel=9)
    assert check_package(fast) == check_package(small) == MEMBERS
    assert (
        part_digest(check_package(fast))
        == part_digest(check_package(small))
        == part_digest(MEMBERS)
    )
    changed = {**MEMBERS, "ppt/slides/slide1.xml": b"<sld x='1'/>"}
    assert part_digest(changed) != part_digest(MEMBERS)
    framed = b"".join(
        name.encode() + b"\x00" + hashlib.sha256(MEMBERS[name]).hexdigest().encode() + b"\n"
        for name in sorted(MEMBERS)
    )
    assert part_digest(MEMBERS) == "sha256:" + hashlib.sha256(framed).hexdigest()


@pytest.mark.parametrize(
    ("members", "match"),
    [
        ({k: v for k, v in MEMBERS.items() if k != "[Content_Types].xml"}, "needs"),
        ({k: v for k, v in MEMBERS.items() if k != "_rels/.rels"}, "needs"),
        ({**MEMBERS, "/ppt/abs.xml": b""}, "not an OPC part name"),
        ({**MEMBERS, "ppt/../escape.xml": b""}, "not an OPC part name"),
        ({**MEMBERS, "ppt\\back.xml": b""}, "not an OPC part name"),
        ({**MEMBERS, "ppt//double.xml": b""}, "not an OPC part name"),
        ({**MEMBERS, "PPT/Presentation.xml": b""}, "one name to OPC"),
    ],
)
def test_a_package_that_is_not_opc_is_refused(members: dict[str, bytes], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        write_opc(members)


# ---------------------------------------------------------------------------
# check_package (09 section 5.3)
# ---------------------------------------------------------------------------


def _refused(data: bytes) -> TargetError:
    with pytest.raises(TargetError) as caught:
        check_package(data)
    return caught.value


def test_a_member_that_does_not_decompress_is_named() -> None:
    data = bytearray(write_opc({**MEMBERS, "ppt/media/big.bin": bytes(range(256)) * 64}))
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as zf:
        info = zf.getinfo("ppt/media/big.bin")
    start = info.header_offset + 30 + len(info.filename) + len(info.extra)
    for offset in range(start + 4, start + 24):
        data[offset] ^= 0xFF
    error = _refused(bytes(data))
    assert error.code() == "OW_TARGET_PACKAGE_CORRUPT"
    assert "ppt/media/big.bin" in str(error)
    assert _refused(b"not a zip").code() == "OW_TARGET_PACKAGE_CORRUPT"


def test_a_dangling_relationship_is_named_and_an_external_one_is_not_checked() -> None:
    error = _refused(write_opc({k: v for k, v in MEMBERS.items() if k != "ppt/slides/slide1.xml"}))
    assert error.code() == "OW_TARGET_DANGLING_REL"
    assert "ppt/_rels/presentation.xml.rels points at slides/slide1.xml" in str(error)
    absolute = PRES_RELS.replace(b'Target="slides/slide1.xml"', b'Target="/ppt/slides/slide1.xml"')
    assert check_package(write_opc({**MEMBERS, "ppt/_rels/presentation.xml.rels": absolute}))


def test_a_part_with_no_content_type_is_a_gap() -> None:
    error = _refused(write_opc({**MEMBERS, "ppt/media/image1.png": b"\x89PNG"}))
    assert error.code() == "OW_TARGET_CONTENT_TYPE_GAP"
    assert "ppt/media/image1.png" in str(error)
    typed = TYPES.replace(
        b"</Types>", b'<Default Extension="PNG" ContentType="image/png"/></Types>'
    )
    assert check_package(
        write_opc({**MEMBERS, "[Content_Types].xml": typed, "ppt/media/image1.png": b"\x89PNG"})
    )


def test_a_rels_part_is_extension_rels_and_a_dotless_part_has_none() -> None:
    """OPC's extension follows the last dot of the last segment: `.rels` is `rels`."""
    assert check_package(write_opc(MEMBERS))["_rels/.rels"] == ROOT_RELS
    error = _refused(write_opc({**MEMBERS, "ppt/media/noext": b""}))
    assert error.code() == "OW_TARGET_CONTENT_TYPE_GAP"
    assert "covers ." in str(error)
    override = TYPES.replace(
        b"</Types>", b'<Override PartName="/ppt/media/noext" ContentType="x/y"/></Types>'
    )
    members = {**MEMBERS, "[Content_Types].xml": override, "ppt/media/noext": b""}
    assert check_package(write_opc(members)) == members


def test_a_relationships_part_that_is_not_xml_or_holds_a_doctype_is_corrupt() -> None:
    doctyped = b"<!DOCTYPE r>" + ROOT_RELS
    entity = b'<!DOCTYPE r [<!ENTITY a "b">]>' + ROOT_RELS
    for rels in (b"<Relationships", doctyped, entity):
        error = _refused(write_opc({**MEMBERS, "_rels/.rels": rels}))
        assert error.code() == "OW_TARGET_PACKAGE_CORRUPT"
        assert "_rels/.rels" in str(error)


def test_the_unit_count_prints_both_numbers() -> None:
    check_unit_count(12, 12)
    with pytest.raises(TargetError, match="holds 11 units and the plan commissioned 12") as caught:
        check_unit_count(11, 12)
    assert caught.value.code() == "OW_TARGET_UNIT_COUNT_MISMATCH"
