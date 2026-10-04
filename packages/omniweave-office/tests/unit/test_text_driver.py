"""`TextParser` (`parse.text.builtin`) against its fixtures: a case per format, and the refusals.

The conform kit runs the twelve suites over this driver (`tools/ow_conform.py --card
.../text/driver.toml --fixtures packages/omniweave-office/fixtures/text`) and is the authority on
the Port contract. What is here is what the kit cannot ask, because it does not know the formats:
that each reader keeps the structure its format states -- heading levels, list nesting, table
spans, code languages -- and drops what is not content.

Specified in 04-driver-system.md section 10.1; D646.
"""

from __future__ import annotations

import dataclasses
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import Fixture, run_parse
from omniweave_office.text import readers
from omniweave_office.text.driver import (
    LATIN1_DIAG,
    MEDIA_TYPES,
    PART,
    TextParser,
    decode,
)
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.detect import StreamHint

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "text"
CARD = Path(readers.__file__).resolve().parent / "driver.toml"
REPO = Path(__file__).resolve().parents[4]


def run(name: str, tmp_path: Path) -> Any:
    return run_parse(TextParser(), Fixture.of(FIXTURES / name), tmp_path)


def shape(name: str, tmp_path: Path) -> list[tuple[int | None, str, Any, str]]:
    """Each block as `(parent index, kind, payload or cell, text)`, in emission order."""
    index: dict[str, int] = {}
    out = []
    for record in run(name, tmp_path).fragment.records:
        if record.get("t") != "block":
            continue
        index[record["tmp"]] = len(index)
        detail = record.get("cell") or record.get("payload")
        out.append((index.get(record["parent"]), record["kind"], detail, record["text"]))
    return out


def hint(name: str) -> StreamHint:
    return StreamHint(
        filename=name, extension=Path(name).suffix, declared_media_type=None, byte_len=None
    )


# ---------------------------------------------------------------------------
# the card, and the list it shares with routing
# ---------------------------------------------------------------------------


def test_the_card_serves_exactly_the_ten_tokens_decode_text_native_routes() -> None:
    """`ow route lint` check 11 holds the card's token set equal to the rule's list; this is the
    same equality read from the two files, so neither can move alone."""
    card = tomllib.loads(CARD.read_text(encoding="utf-8"))
    policy = REPO / "packages/omniweave/src/omniweave/route/policies/00-builtin-route.toml"
    rule = next(
        one
        for one in tomllib.loads(policy.read_text(encoding="utf-8"))["rule"]
        if one["id"] == "decode.text-native"
    )
    tokens = set(rule["when"]["unit.format"]["in"])
    assert set(MEDIA_TYPES.values()) == tokens
    assert set(card["capability"]["formats"]) == set(MEDIA_TYPES)
    pairs = {(p["media_type"], p["token"]) for p in card["capability"]["parse"]["format_tokens"]}
    assert pairs == set(MEDIA_TYPES.items())
    assert card["driver"]["entrypoint"] == "omniweave_office.text.driver:TextParser"
    assert rule["then"] == {"driver": card["driver"]["id"], "terminal": True}


def test_probe_names_defusedxml_rather_than_saying_ok() -> None:
    verdict = TextParser.probe(env=None)  # type: ignore[arg-type]
    assert verdict.status is ProbeStatus.OK
    assert verdict.detail.startswith("defusedxml ")


@pytest.mark.parametrize(
    ("name", "token"),
    [
        ("guide.md", "md"),
        ("notes.txt", "txt"),
        ("page.html", "html"),
        ("page.xhtml", "xhtml"),
        ("catalog.xml", "xml"),
        ("data.json", "json"),
        ("events.jsonl", "jsonl"),
        ("analysis.ipynb", "ipynb"),
        ("rows.tsv", "tsv"),
        ("logo.svg", "svg"),
    ],
)
def test_sniff_names_each_format(name: str, token: str) -> None:
    (guess,) = TextParser().sniff((FIXTURES / name).read_bytes(), hint(name))
    assert (guess.format_token, guess.media_type) == (
        token,
        next(media for media, one in MEDIA_TYPES.items() if one == token),
    )


def test_sniff_says_not_mine_for_binary_bytes() -> None:
    assert TextParser().sniff((FIXTURES / "not_a_document.bin").read_bytes(), hint("x.txt")) == ()


# ---------------------------------------------------------------------------
# each format's structure
# ---------------------------------------------------------------------------


def test_markdown_keeps_headings_lists_quotes_code_tables_and_rules(tmp_path: Path) -> None:
    blocks = shape("guide.md", tmp_path)
    kinds = [kind for _parent, kind, _detail, _text in blocks]
    assert blocks[0] == (None, "code", {"lang": "yaml"}, "title: Onboarding guide\nowner: platform")
    assert blocks[1] == (None, "heading", {"level": 1}, "Onboarding guide")
    assert blocks[2][3] == "Welcome to the **platform** team. Read this first."
    assert (None, "heading", {"level": 2}, "Setup") in blocks
    assert (None, "heading", {"level": 3}, "Escalation") in blocks
    ordered = blocks[4]
    assert ordered[:3] == (
        None,
        "list",
        {
            "ordered": True,
            "start": 1,
            "marker_style": "decimal",
            "nesting_level": 0,
        },
    )
    assert (7, "paragraph", None, "Clone the repository: it lives on the internal host.") in blocks
    nested = [b for b in blocks if b[1] == "list" and b[2]["nesting_level"] == 1]
    assert len(nested) == 1 and blocks[nested[0][0]][1] == "list_item"
    assert (
        21,
        "paragraph",
        None,
        "The on-call rota starts in your second week. Ask your buddy for the pager.",
    ) in blocks
    assert (None, "code", {"lang": "python"}, 'def hello() -> str:\n    return "hi"') in blocks
    assert kinds.count("table_cell") == 9 and "rule" in kinds


def test_html_keeps_structure_and_spans_and_drops_what_is_not_content(tmp_path: Path) -> None:
    blocks = shape("page.html", tmp_path)
    texts = [text for *_rest, text in blocks]
    assert blocks[0] == (None, "heading", {"level": 1}, "Service status")
    assert "All systems are operating normally & on schedule." in texts
    assert not any(
        "console.log" in text or "color: red" in text or text == "Status page" for text in texts
    )
    by_index = dict(enumerate(blocks))
    cells = [
        (detail["r"], detail["c"], detail["row_span"], detail["col_span"], by_index[i + 1][3])
        for i, (_parent, kind, detail, _text) in enumerate(blocks)
        if kind == "table_cell"
    ]
    assert cells == [
        (0, 0, 1, 1, "Region"),
        (0, 1, 1, 2, "Latency"),
        (1, 0, 2, 1, "Europe"),
        (1, 1, 1, 1, "p50"),
        (1, 2, 1, 1, "12 ms"),
        (2, 1, 1, 1, "p99"),  # column 0 is Europe's, spanned down from row 1
        (2, 2, 1, 1, "80 ms"),
    ]
    assert (None, "code", None, "curl https://status.example/api") in blocks
    assert any(kind == "blockquote" for _p, kind, _d, _t in blocks)


def test_xhtml_reads_a_self_closing_break_and_an_ordered_start(tmp_path: Path) -> None:
    blocks = shape("page.xhtml", tmp_path)
    assert (
        None,
        "paragraph",
        None,
        "Economy class for flights under six hours. Business class above.",
    ) in blocks
    assert (
        None,
        "list",
        {
            "ordered": True,
            "start": 3,
            "marker_style": "decimal",
            "nesting_level": 0,
        },
        "",
    ) in blocks


@pytest.mark.parametrize(
    ("name", "texts"),
    [
        (
            "notes.txt",
            [
                "Meeting notes, 2026-03-02.",
                "The launch moves to April 14 because the audit is not finished.\n"
                "Finance signs off on the budget next week.",
                "Action: Dana writes the release notes.",
            ],
        ),
        ("catalog.xml", ["The Pragmatic Programmer", "1999", "Refactoring", "2018"]),
        ("logo.svg", ["Acme logo", "The Acme wordmark on a blue bar", "Acme Corp"]),
        (
            "data.json",
            [
                "service: billing",
                "owners[0]: Ana",
                "owners[1]: Bo",
                "limits.rps: 1200",
                "limits.burst: true",
                "region: null",
            ],
        ),
        (
            "events.jsonl",
            [
                "at: 2026-03-01T09:00:00Z; event: deploy; service: search",
                "at: 2026-03-01T09:05:00Z; event: rollback; service: search",
            ],
        ),
    ],
)
def test_the_flat_formats_read_one_paragraph_per_unit_of_content(
    name: str, texts: list[str], tmp_path: Path
) -> None:
    blocks = shape(name, tmp_path)
    assert [(kind, text) for _p, kind, _d, text in blocks] == [("paragraph", t) for t in texts]


def test_a_notebook_reads_markdown_code_and_output(tmp_path: Path) -> None:
    assert shape("analysis.ipynb", tmp_path) == [
        (None, "heading", {"level": 1}, "Churn analysis"),
        (None, "paragraph", None, "Monthly churn by plan."),
        (None, "code", {"lang": "python"}, "rate = 42 / 1000\nprint(rate)"),
        (None, "code", None, "0.042"),
    ]


def test_tsv_is_one_table_whose_first_row_is_its_header(tmp_path: Path) -> None:
    blocks = shape("rows.tsv", tmp_path)
    assert blocks[0] == (None, "table", {"header_rows": 1, "header_cols": 0, "kind": "data"}, "")
    assert [text for _p, kind, _d, text in blocks if kind == "paragraph"][:3] == [
        "name",
        "team",
        "start",
    ]


# ---------------------------------------------------------------------------
# the fragment, the encoding and the refusals
# ---------------------------------------------------------------------------


def test_the_routed_media_type_decides_the_reader_and_not_the_extension(tmp_path: Path) -> None:
    """Routing decided the format before `INVOKE` (05 section 4.4), and `UnitRef.media_type`
    carries it: a `.json` file routed as plain text is read as text, its braces and all."""
    fixture = dataclasses.replace(Fixture.of(FIXTURES / "data.json"), media_type="text/plain")
    records = run_parse(TextParser(), fixture, tmp_path).fragment.records
    assert records[0]["format"] == "txt"
    (block,) = [r for r in records if r["t"] == "block"]
    assert block["text"].startswith('{\n  "service": "billing"')


def test_the_fragment_is_one_stream_page_and_an_unretained_part(tmp_path: Path) -> None:
    records = run("guide.md", tmp_path).fragment.records
    assert [r["t"] for r in records[:3]] == ["doc", "part", "page"]
    assert records[1] | {"sha256": ""} == {
        "t": "part",
        "path": PART,
        "sha256": "",
        "byte_len": len((FIXTURES / "guide.md").read_bytes()),
        "retain": False,
    }
    assert records[2]["page_kind"] == "stream"
    assert records[-1]["status"] == "ok"
    assert {r["os"]["k"] for r in records if r["t"] == "block"} == {"none"}
    achieved = records[0]["achieved"]
    assert (achieved["sections"], achieved["tables"]) == ("outline_from_source", "cells")


def test_bytes_that_are_not_utf8_read_as_latin1_with_a_warning(tmp_path: Path) -> None:
    records = run("latin1.txt", tmp_path).fragment.records
    assert [r["text"] for r in records if r["t"] == "block"] == ["Café au lait, crème brûlée."]
    (diag,) = [r for r in records if r["t"] == "diag"]
    assert (diag["code"], diag["severity"], diag["fatal"]) == (LATIN1_DIAG, "warning", False)


@pytest.mark.parametrize(
    ("raw", "text", "codec"),
    [
        (b"\xef\xbb\xbfplain", "plain", "utf-8-sig"),
        ("café".encode("utf-16"), "café", "utf-16"),
        ("café".encode(), "café", "utf-8"),
        (b"caf\xe9", "café", "latin-1"),
    ],
)
def test_decode_reads_a_byte_order_mark_then_utf8_then_latin1(
    raw: bytes, text: str, codec: str
) -> None:
    assert decode(raw) == (text, codec)


@pytest.mark.parametrize(
    ("name", "cls", "words"),
    [
        ("entities.xml", FailureClass.CORRUPT_INPUT, "DTDForbidden"),
        ("broken.json", FailureClass.CORRUPT_INPUT, "not JSON"),
        ("not_a_document.bin", FailureClass.UNSUPPORTED_FORMAT, "none of the ten"),
    ],
)
def test_each_refusal_is_typed_and_says_why(
    name: str, cls: FailureClass, words: str, tmp_path: Path
) -> None:
    with pytest.raises(DriverError) as caught:
        run(name, tmp_path)
    assert caught.value.cls is cls
    assert words in str(caught.value)


def test_a_jsonl_line_that_is_not_json_is_named_by_its_number() -> None:
    with pytest.raises(readers.ReadError, match="line 2 is not JSON"):
        readers.jsonl('{"a": 1}\n{oops\n', readers.Blocks())


def test_an_empty_file_is_ok_with_no_block_and_not_valid_nonempty(tmp_path: Path) -> None:
    """The host turns an `ok` with no block into `EMPTY_RESULT` before caching, as for every
    driver; this driver's half is to answer `is_valid_nonempty()` honestly."""
    source = tmp_path / "empty.md"
    source.write_bytes(b"\n\n")
    run_ = run_parse(TextParser(), Fixture.of(source), tmp_path / "kit")
    assert run_.blocks == ()
    (fragment,) = run_.result.produced
    assert TextParser().is_valid_nonempty(fragment) is False


def test_control_characters_are_removed_and_text_is_nfc() -> None:
    out = readers.Blocks()
    readers.plain("café\x00 bell\x07", out)
    assert out.records[0]["text"] == "café bell"


def test_the_fragment_is_json_lines_with_no_ascii_escaping(tmp_path: Path) -> None:
    body = run("latin1.txt", tmp_path).body
    assert "Café".encode() in body
    assert all(json.loads(line) for line in body.decode().splitlines())
