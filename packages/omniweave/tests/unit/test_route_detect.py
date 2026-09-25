"""05 section 2's detection ladder over real bytes: signatures, containers, probes and extensions.

Every container is built here from its format's own structure -- an OPC package with its
relationship and content types, an ODF and an EPUB with a stored `mimetype`, and compound files
written sector by sector -- because 05:597's claim is that *"every row is checkable against a file
with `xxd`"* and a fixture that was not a real file would check nothing.
"""

from __future__ import annotations

import json
import struct
import tomllib
import zipfile
from pathlib import Path

import pytest
from omniweave.route import detect
from omniweave.route.detect import (
    CORE_FORMATS,
    MEDIA_TYPES,
    detect_bytes,
    format_token_for,
    hint_for,
)
from omniweave_core.limits import MAX_IDENTITY_BYTES
from omniweave_ports.detect import StreamHint
from omniweave_ports.types import DriverError, FailureClass

REPO = Path(__file__).resolve().parents[4]
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"


def _write(path: Path, body: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _opc(
    path: Path,
    *,
    main: str = "word/document.xml",
    content_type: str | None = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    ),
    root: str = f'<w:document xmlns:w="{W}"><w:body/></w:document>',
    rels: str | None = None,
) -> Path:
    override = (
        ""
        if content_type is None
        else f'<Override PartName="/{main}" ContentType="{content_type}"/>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/'
            'content-types"><Default Extension="xml" ContentType="application/xml"/>'
            f"{override}</Types>",
        )
        archive.writestr(
            "_rels/.rels",
            rels
            or '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/'
            f'package/2006/relationships"><Relationship Id="rId1" Type="{REL}" '
            f'Target="{main}"/></Relationships>',
        )
        archive.writestr(main, f'<?xml version="1.0"?>{root}')
    return path


def _mimetyped(path: Path, mimetype: str) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(zipfile.ZipInfo("mimetype"), mimetype, compress_type=zipfile.ZIP_STORED)
        archive.writestr("content.xml", "<office:document-content/>")
    return path


def _cfb(path: Path, *streams: str) -> Path:
    """A version-3 compound file: header, one FAT sector, one directory sector, the root's
    children chained through their right-sibling ids. [MS-CFB] 2.2 and 2.6."""
    free, end, fat_sect, none = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
    header = bytearray(512)
    header[0:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    struct.pack_into("<HHHHH", header, 0x18, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<I", header, 0x2C, 1)  # one FAT sector
    struct.pack_into("<I", header, 0x30, 1)  # the directory starts at sector 1
    struct.pack_into("<III", header, 0x38, 4096, end, 0)
    struct.pack_into("<II", header, 0x44, end, 0)
    struct.pack_into("<109I", header, 0x4C, 0, *([free] * 108))
    fat = struct.pack("<128I", fat_sect, end, *([free] * 126))

    def entry(name: str, kind: int, *, right: int = none, child: int = none) -> bytes:
        raw = bytearray(128)
        encoded = (name + "\x00").encode("utf-16-le")
        raw[: len(encoded)] = encoded
        struct.pack_into("<HBB", raw, 0x40, len(encoded), kind, 1)
        struct.pack_into("<III", raw, 0x44, none, right, child)
        return bytes(raw)

    entries = [entry("Root Entry", 5, child=1 if streams else none)]
    for index, name in enumerate(streams[:3], start=1):
        entries.append(entry(name, 2, right=index + 1 if index < len(streams) else none))
    while len(entries) < 4:
        entries.append(bytes(128))
    return _write(path, bytes(header) + fat + b"".join(entries))


def _file(tmp_path: Path, name: str, body: bytes | str) -> detect.Detection:
    raw = body.encode("utf-8") if isinstance(body, str) else body
    return detect.detect(_write(tmp_path / name, raw))


# ---------------------------------------------------------------------------------------------
# the containers: 05 section 2.5
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("main", "content_type", "token"),
    [
        (
            "word/document.xml",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml",
            "docx",
        ),
        (
            "xl/workbook.xml",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
            "xlsx",
        ),
        (
            "ppt/presentation.xml",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
            "pptx",
        ),
        ("word/document.xml", "application/vnd.ms-word.document.macroEnabled.main+xml", "docx"),
    ],
)
def test_an_opc_package_is_its_main_part_s_content_type(
    tmp_path: Path, main: str, content_type: str, token: str
) -> None:
    found = detect.detect(_opc(tmp_path / "a.bin", main=main, content_type=content_type))
    assert (found.format, found.chosen and found.chosen.basis) == (token, "container_identity")
    assert found.media_type == MEDIA_TYPES[token]


def test_stale_content_types_fall_back_to_the_main_part_s_root_element(tmp_path: Path) -> None:
    """05:742: *"fall back to that part's mandated root element when the content types are stale or
    generic, which is what non-Microsoft producers ship"*."""
    found = detect.detect(_opc(tmp_path / "a.docx", main="word/main.xml", content_type=None))
    assert found.format == "docx"
    assert found.chosen is not None
    assert "root document" in found.chosen.detail


def test_a_docx_named_doc_is_a_docx_and_the_mismatch_is_recorded(tmp_path: Path) -> None:
    """05:706: the magic wins, always -- and 05:716-732's printed evidence, field for field."""
    found = detect.detect(_opc(tmp_path / "report.doc"))
    assert found.format == "docx"
    assert found.extension_mismatch is True
    evidence = json.loads(found.evidence_json())
    assert evidence["chosen"]["basis"] == "container_identity"
    assert evidence["hint"] == {"extension": ".doc", "media_type_hint": None}
    superseded = [one for one in evidence["rejected"] if one["format"] == "zip"]
    assert superseded == [
        {
            "format": "zip",
            "media_type": "application/zip",
            "confidence": 0.99,
            "basis": "magic",
            "detail": "PK 03 04",
            "consumed_bytes": 4,
            "superseded_by": "container_identity",
        }
    ]
    assert set(evidence) == {
        "v", "chosen", "rejected", "hint", "ambiguous", "extension_mismatch", "container",
        "providers",
    }  # fmt: skip


def test_a_container_identity_supersedes_its_own_magic_and_not_the_ranking(tmp_path: Path) -> None:
    """D570. Read literally, 05:576 ranks `magic` above `container_identity`, and every DOCX is
    `zip`; the identity is a reading OF the container the magic named, so it replaces that guess."""
    assert detect.detect(_opc(tmp_path / "a.docx")).format == "docx"


@pytest.mark.parametrize(
    ("mimetype", "token"),
    [
        ("application/vnd.oasis.opendocument.text", "odt"),
        ("application/vnd.oasis.opendocument.spreadsheet", "ods"),
        ("application/vnd.oasis.opendocument.presentation", "odp"),
        ("application/epub+zip", "epub"),
    ],
)
def test_odf_and_epub_are_their_mimetype_member(tmp_path: Path, mimetype: str, token: str) -> None:
    assert detect.detect(_mimetyped(tmp_path / "a.bin", mimetype)).format == token


def test_a_zip_with_no_identity_is_a_zip(tmp_path: Path) -> None:
    path = tmp_path / "a.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("notes.txt", "hello")
    found = detect.detect(path)
    assert (found.format, found.chosen and found.chosen.basis) == ("zip", "magic")


def test_an_identity_part_with_a_dtd_is_refused_before_it_is_parsed(tmp_path: Path) -> None:
    """05:748-754: billion-laughs would otherwise reach the HOST through detection."""
    rels = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><Relationships/>'
    with pytest.raises(DriverError) as refused:
        detect.detect(_opc(tmp_path / "a.docx", rels=rels))
    assert (refused.value.cls, refused.value.limit) == (
        FailureClass.RESOURCE_LIMIT,
        "MAX_IDENTITY_BYTES",
    )


def test_an_identity_part_over_the_bound_is_refused(tmp_path: Path) -> None:
    padding = " " * (MAX_IDENTITY_BYTES + 1)
    rels = f'<?xml version="1.0"?><Relationships>{padding}</Relationships>'
    with pytest.raises(DriverError):
        detect.detect(_opc(tmp_path / "a.docx", rels=rels))


@pytest.mark.parametrize(
    ("streams", "token"),
    [
        (("WordDocument", "1Table"), "doc"),
        (("PowerPoint Document",), "ppt"),
        (("Workbook",), "xls"),
        (("BOOK",), "xls"),
        (("__properties_version1.0", "__substg1.0_0037001F"), "msg"),
    ],
)
def test_a_compound_file_is_the_stream_its_root_storage_holds(
    tmp_path: Path, streams: tuple[str, ...], token: str
) -> None:
    """05:756-763, case-insensitively: *"producers ship `WORKBOOK` and `BOOK`"*."""
    found = detect.detect(_cfb(tmp_path / "a.bin", *streams))
    assert (found.format, found.chosen and found.chosen.basis) == (token, "container_identity")


def test_an_encrypted_package_is_unknown_and_says_so(tmp_path: Path) -> None:
    """05:760: *"the inner format is genuinely unknowable and guessing it produces a wrong
    `failure_class`"*."""
    found = detect.detect(_cfb(tmp_path / "a.docx", "EncryptedPackage", "EncryptionInfo"))
    assert (found.format, found.encrypted) == ("unknown", True)
    assert json.loads(found.evidence_json())["encrypted"] is True


def test_a_compound_file_with_no_known_stream_is_unknown_not_its_extension(tmp_path: Path) -> None:
    """A CFB is binary, and 05:623 gives binary with no signature `unknown` -- the `.doc` on its
    name is not evidence about bytes that say otherwise."""
    assert detect.detect(_cfb(tmp_path / "a.doc", "Something")).format == "unknown"


# ---------------------------------------------------------------------------------------------
# the signature table, the text probes, the extension and the two terminal non-formats
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("head", "token"),
    [
        (b"junk\n%PDF-1.7\n", "pdf"),
        (b"{\\rtf1\\ansi hello}", "rtf"),
        (b"\x1f\x8b\x08\x00", "gz"),
        (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8, "png"),
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "webp"),
        (b"GIF89a" + b"\x00" * 6, "gif"),
        (b"SQLite format 3\x00" + b"\x00" * 16, "sqlite"),
        (b"%!PS-Adobe-3.0\n", "ps"),
        (b"\x00" * 257 + b"ustar\x0000", "tar"),
        (b"BM" + b"\x00" * 12 + struct.pack("<I", 40) + b"\x00" * 8, "bmp"),
        (b"From alice@example.com Mon Jan  1 00:00:00 2026\nFrom: a\nTo: b\n\nhi\n", "mbox"),
        (b"Received: from x\nMessage-ID: <1@x>\nSubject: s\n\nbody\n", "eml"),
    ],
)
def test_each_signature_row_is_its_format(head: bytes, token: str) -> None:
    found = detect_bytes(head, StreamHint("a", None, None, len(head)))
    assert (found.format, found.chosen and found.chosen.basis) == (token, "magic")


def test_bm_alone_is_two_letters_of_prose_and_not_a_bitmap(tmp_path: Path) -> None:
    """05:612: *"`BM` alone is two ASCII letters and matches prose"*."""
    assert _file(tmp_path, "a.txt", "BM is the start of this sentence.\n").format == "txt"


@pytest.mark.parametrize(
    ("name", "body", "token"),
    [
        ("a.ipynb", '{"cells": [], "metadata": {}, "nbformat": 4}', "ipynb"),
        ("a.svg", '<svg xmlns="http://www.w3.org/2000/svg" width="1"/>', "svg"),
        ("a.x", '<?xml version="1.0"?><note><to>x</to></note>', "xml"),
        ("a.x", "<!-- <html> --><!doctype html><html><body>x</body></html>", "html"),
        ("a.x", '{"a": 1}\n{"b": 2}\n{"c": 3}\n', "jsonl"),
        ("a.x", '[{"a": 1}, {"b": 2}]', "json"),
        ("a.x", "id,name,qty\n1,apple,3\n2,pear,5\n3,fig,7\n", "csv"),
        ("a.x", "id\tname\tqty\n1\tapple\t3\n2\tpear\t5\n3\tfig\t7\n", "tsv"),
        ("a.md", "# Title\n\n- one\n- two\n", "md"),
        ("a.x", "Just a sentence of plain prose.\n", "txt"),
    ],
)
def test_each_content_probe_decides_a_signature_free_text(
    tmp_path: Path, name: str, body: str, token: str
) -> None:
    found = _file(tmp_path, name, body)
    assert (found.format, found.chosen and found.chosen.basis) == (token, "content_probe")


def test_markdown_is_extension_gated(tmp_path: Path) -> None:
    """05:693: *"content-probing Markdown makes `.xyz` Markdown"*."""
    assert _file(tmp_path, "a.xyz", "# Title\n\n- one\n").format == "txt"


def test_a_utf16_text_with_its_bom_is_text(tmp_path: Path) -> None:
    body = "﻿plain words in utf-16\n".encode("utf-16-le")
    assert _file(tmp_path, "a.x", body).format == "txt"


def test_binary_with_no_signature_is_unknown_whatever_it_is_called(tmp_path: Path) -> None:
    """05:623: the framework never runs a text decoder over a binary blob to see what happens."""
    found = _file(tmp_path, "a.txt", b"\x00\x01\x02\x03binary")
    assert (found.format, found.chosen) == ("unknown", None)


def test_non_utf8_text_with_no_controls_is_its_extension(tmp_path: Path) -> None:
    """Latin-1 prose is neither row 21's UTF-8 nor binary, so step 6 decides, weakly."""
    found = _file(tmp_path, "a.csv", "caf\xe9;na\xefve\n".encode("latin-1"))
    assert (found.format, found.weak) == ("csv", True)


def test_an_empty_file_is_empty(tmp_path: Path) -> None:
    assert _file(tmp_path, "a.pdf", b"").format == "empty"


def test_a_csv_that_is_also_valid_text_is_csv_and_txt_is_not_its_rival(tmp_path: Path) -> None:
    found = _file(tmp_path, "a.csv", "a,b\n1,2\n3,4\n5,6\n")
    assert found.format == "csv"
    assert [one.guess.format_token for one in found.rejected] == ["csv"], "the extension row"


def test_the_ranking_is_total_and_does_not_depend_on_input_order() -> None:
    guesses = [
        detect._guess("csv", "content_probe", "", 0, 0.70),
        detect._guess("txt", "content_probe", "", 0, 0.70),
        detect._guess("pdf", "extension", "", 0),
    ]
    hint = StreamHint("a", None, None, 1)
    one = detect._decide(guesses, (), hint, encrypted=False)
    two = detect._decide(list(reversed(guesses)), (), hint, encrypted=False)
    assert one.format == two.format == "csv"
    assert one.ambiguous is True, "05:700 case 2: two within 0.05, both above 0.60"


# ---------------------------------------------------------------------------------------------
# the vocabulary: core's forty-eight and the card's pairs
# ---------------------------------------------------------------------------------------------


def test_core_holds_the_forty_eight_tokens_05_prints() -> None:
    printed = (
        "pdf docx doc pptx ppt xlsx xls csv tsv rtf odt ods odp epub html xhtml xml md txt json "
        "jsonl ipynb svg eml msg mbox png jpeg webp tiff bmp gif mp4 matroska mp3 wav flac ogg ps "
        "sqlite zip tar gz sevenz rar xz empty unknown"
    )
    assert " ".join(CORE_FORMATS) == printed, "05:636-639, space-separated as printed"
    assert len(CORE_FORMATS) == 48


def test_the_office_card_s_pairs_agree_with_core_s_table() -> None:
    """05:666's single-valued lookup: two sources pairing one media type with two tokens is
    `OW-D-024`. The card and core must say the same thing about every media type both name."""
    card = REPO / "packages/omniweave-office/src/omniweave_office/driver.toml"
    pairs = tomllib.loads(card.read_text(encoding="utf-8"))["capability"]["parse"]["format_tokens"]
    for pair in pairs:
        assert format_token_for(pair["media_type"]) == pair["token"], pair


def test_every_extension_names_a_core_token() -> None:
    assert set(detect.EXTENSIONS.values()) <= set(CORE_FORMATS)
    assert hint_for(Path("A.DOCX")).extension == ".docx"


def test_the_shipped_policy_names_every_core_token_in_a_rule() -> None:
    """05:642: *"every one of them is named by a rule in section 4.4"* -- lint check 10
    (`OW-P-014`), which could not run until this module supplied the computed domain."""
    from omniweave.route.lint import format_coverage  # noqa: PLC0415
    from omniweave.route.policy import builtin_layer, compile_policy  # noqa: PLC0415

    policy = compile_policy([builtin_layer()])
    assert format_coverage(policy, detect.computed_domain()) == ()
