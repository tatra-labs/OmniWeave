"""`omniweave_core.out.marker`: the `OWC1` grammar, the scan, the two-factor anchor, the apply.

09-generation.md section 8 and section 14.3; charter OUT16 to OUT19. The payload's two properties
(`decode(encode(x)) == x` and no `--`) are tested over generated payloads, and a marker is proved a
legal XML comment by parsing the file that holds it.
"""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest
from omniweave_core.errors import ResourceLimit, TargetError
from omniweave_core.limits import MAX_MARKERS_PER_UNIT
from omniweave_core.out.carrier import ParseError, Splice
from omniweave_core.out.carrier.xml import SvgDoc, svg_carrier
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.job import ILBundle
from omniweave_core.out.marker import (
    MARKER_RE,
    Marker,
    MarkerEdit,
    Payload,
    apply_reverse,
    assert_clean,
    decode_payload,
    encode_payload,
    format_marker,
    marker_id,
    over_budget,
    resolve,
    scan,
    scan_text,
)
from omniweave_core.out.plan import OutUnit
from omniweave_core.out.rules import run_pack

NS = 'xmlns="http://www.w3.org/2000/svg"'
TS = "2026-09-03T11:04:00Z"
NOTE = Payload(
    note="this number should be the FY26 figure, not FY25", sev="must", by="human", prev="41.2"
)


def _draws(seed: int) -> Iterator[int]:
    counter = 0
    while True:
        counter += 1
        yield int.from_bytes(
            hashlib.blake2b(f"{seed}:{counter}".encode(), digest_size=8).digest(), "big"
        )


def _svg(body: str) -> SvgDoc:
    return svg_carrier("il/u01.svg", f"<svg {NS}>\n{body}</svg>\n", strict=True)


TEXT = '  <text data-ow-el="u01/e2" x="1">\n    41.2\n  </text>\n  <rect data-ow-el="u01/e3"/>\n'


def _marked(payload: Payload = NOTE, el: str = "u01/e2", *, nsig: str | None = None) -> SvgDoc:
    """`TEXT` with one marker as the text element's first child, on its own line."""
    probe = _svg(TEXT.replace("    41.2", "    <!-- x -->\n    41.2"))
    node = next(n for n in probe.nodes() if n.el == el) if nsig is None else None
    line = format_marker(probe, el, nsig or (node.nsig if node else "00000000"), TS, payload)
    return _svg(TEXT.replace("    41.2", f"    {line}\n    41.2"))


# ---------------------------------------------------------------------------
# The payload (ruling 1-2)
# ---------------------------------------------------------------------------


def test_the_payload_round_trips_and_never_holds_a_double_hyphen() -> None:
    draws = _draws(745)
    alphabet = ["-", ">", '"', "\n", "<", "é", "--", "-->", "a", " ", "☃", "\x00", "=", "+", "/"]
    for _ in range(2_000):
        note = "".join(alphabet[next(draws) % len(alphabet)] for _ in range(next(draws) % 60))
        payload = Payload(note=note, sev="should", by="agent", hint=note[:5] or None)
        encoded = encode_payload(payload)
        assert "--" not in encoded
        assert decode_payload(encoded) == payload
        assert MARKER_RE.fullmatch(
            f"OWC1:v1 el=u01/e1 nsig=00000000 id=k-00000000 ts={TS} p={encoded}"
        )


def test_the_reader_strips_every_space_before_it_counts_the_padding() -> None:
    """Ruling 1: a space is the writer's, and padding is counted without it."""
    for note in ("", "a", "ab", "abc"):
        payload = Payload(note=note, sev="must", by="human")
        encoded = encode_payload(payload)
        assert decode_payload(" " + encoded) == payload
        assert decode_payload(encoded[:4] + "  " + encoded[4:]) == payload


def test_a_payload_of_hyphens_is_spaced_and_still_decodes() -> None:
    payload = Payload(note="Ͼ" * 3, sev="ask", by="human")  # base64url holds "--", found by search
    encoded = encode_payload(payload)
    assert "- -" in encoded
    assert decode_payload(encoded) == payload


def test_a_payload_past_the_ceiling_is_refused() -> None:
    with pytest.raises(ResourceLimit) as caught:
        encode_payload(Payload(note="x" * 4_100, sev="must", by="human"))
    assert caught.value.limit == "MAX_MARKER_PAYLOAD_BYTES"


@pytest.mark.parametrize(
    "text",
    [
        "!!!",
        encode_payload(NOTE)[:-3] + "@@@",
        "e30",  # {}
        "eyJub3RlIjoiYSIsInNldiI6Im11c3QifQ",  # {"note":"a","sev":"must"}: no `by`
        "eyJub3RlIjoiYSIsInNldiI6InNvb24iLCJieSI6Imh1bWFuIn0",  # sev "soon"
        "eyJieSI6InJvYm90Iiwibm90ZSI6ImEiLCJzZXYiOiJtdXN0In0",  # by "robot"
        "eyJub3RlIjoxLCJzZXYiOiJtdXN0IiwiYnkiOiJodW1hbiJ9",  # note 1
        "eyJub3RlIjoiYSIsInNldiI6Im11c3QiLCJieSI6Imh1bWFuIiwiZXRhIjoiMSJ9",  # an `eta` key
    ],
)
def test_anything_else_is_not_a_payload(text: str) -> None:
    with pytest.raises(ValueError):
        decode_payload(text)


def test_the_id_is_minted_from_the_markers_content() -> None:
    first = marker_id("u01/e2", "9f3a1c04", TS, NOTE)
    assert first == marker_id("u01/e2", "9f3a1c04", TS, NOTE)
    assert first.startswith("k-") and len(first) == 10
    other = Payload(note=NOTE.note + ".", sev="must", by="human", prev="41.2")
    assert marker_id("u01/e2", "9f3a1c04", TS, other) != first


def test_a_marker_is_a_legal_xml_comment_and_refuses_a_bad_address() -> None:
    doc = _marked()
    assert len(scan(doc)) == 1, "the file holding it parsed strictly"
    with pytest.raises(ValueError, match="grammar"):
        format_marker(doc, "u1/e2", "00000000", TS, NOTE)


# ---------------------------------------------------------------------------
# scan (ruling 3)
# ---------------------------------------------------------------------------


def test_scan_reports_each_marker_its_line_and_its_whole_line_bytes() -> None:
    doc = _marked()
    (marker,) = scan(doc)
    assert (marker.el, marker.ts, marker.state, marker.payload) == ("u01/e2", TS, "pending", NOTE)
    assert marker.line == 3
    data = doc.source().encode("utf-8")
    assert data[marker.start : marker.end].startswith(b"    <!-- OWC1:v1 el=u01/e2 ")
    assert data[marker.start : marker.end].endswith(b"-->\n")
    assert marker.as_json() == {"el": "u01/e2", "id": marker.id, "state": "pending"}


def test_scan_is_tolerant_and_never_throws() -> None:
    corrupt = f"<!-- OWC1:v1 el=u01/e2 nsig=00000000 id=k-00000000 ts={TS} p=bm90IGpzb24 -->"
    text = (
        "<svg><text>broken, mid-keystroke\n"
        f"{corrupt}\n"
        f"OWC1:v1 el=u01/e3 nsig=00000000 id=k-00000001 ts={TS} p=e30 no delimiters\n"
        f"text OWC1:v1 el=u01/e5 nsig=00000000 id=k-00000003 ts={TS} p=e30 -->, never opened\n"
        f"<!-- OWC1:v1 el=u01/e4 nsig=00000000 id=k-00000002 ts={TS} p=e30 and never closed\n"
    )
    (marker,) = scan_text(text)
    assert (marker.el, marker.state, marker.payload, marker.line) == ("u01/e2", "corrupt", None, 2)


# ---------------------------------------------------------------------------
# resolve (ruling 5)
# ---------------------------------------------------------------------------


def test_resolution_follows_09s_table() -> None:
    (marker,) = scan(_marked())
    assert resolve(_marked(), marker).code is None
    stale = _marked(nsig="00000000")
    assert resolve(stale, scan(stale)[0]).code == "OW_TARGET_MARKER_STALE"
    orphan = _marked(el="u01/e9", nsig="00000000")
    assert resolve(orphan, scan(orphan)[0]).code == "OW_TARGET_MARKER_ORPHAN"
    twice = _svg(TEXT + '  <rect data-ow-el="u01/e2"/>\n')
    assert resolve(twice, marker).code == "OW_TARGET_EL_DUPLICATE"


# ---------------------------------------------------------------------------
# apply_reverse (ruling 6)
# ---------------------------------------------------------------------------


def test_an_edit_and_its_markers_line_land_in_one_batch() -> None:
    doc = _marked()
    (marker,) = scan(doc)
    data = doc.source().encode("utf-8")
    at = data.index(b"41.2")
    out = apply_reverse(doc, [MarkerEdit(marker, (Splice(at, at + 4, "48.9"),))])
    assert isinstance(out, str)
    assert "OWC1" not in out and "48.9" in out
    assert out == doc.source().replace(doc.source().splitlines(keepends=True)[2], "").replace(
        "41.2", "48.9"
    )
    svg_carrier("il/u01.svg", out, strict=True)


def test_a_skipped_marker_stays_because_presence_is_the_state() -> None:
    doc = _marked()
    out = apply_reverse(doc, [])
    assert out == doc.source()
    assert len(scan_text(out if isinstance(out, str) else "")) == 1


def test_an_unresolved_or_unscanned_marker_is_refused_before_anything_is_applied() -> None:
    stale = _marked(nsig="00000000")
    with pytest.raises(TargetError) as caught:
        apply_reverse(stale, [MarkerEdit(scan(stale)[0])])
    assert caught.value.code() == "OW_TARGET_MARKER_STALE"
    (marker,) = scan(_marked())
    ghost = Marker(
        marker.el, marker.nsig, "k-ffffffff", marker.ts, marker.payload, "pending", 3, 0, 1
    )
    with pytest.raises(ValueError, match="not in this document"):
        apply_reverse(_marked(), [MarkerEdit(ghost)])


def test_a_breaking_edit_returns_the_error_and_the_file_is_unchanged() -> None:
    doc = _marked()
    (marker,) = scan(doc)
    at = doc.source().encode("utf-8").index(b"</text>")
    out = apply_reverse(doc, [MarkerEdit(marker, (Splice(at, at + 7, ""),))])
    assert isinstance(out, ParseError)
    assert len(scan(doc)) == 1


# ---------------------------------------------------------------------------
# assert_clean and the budget (ruling 7)
# ---------------------------------------------------------------------------

TABLE = """\
schema = "omniweave.out-constructs/1"
carrier = "svg"
il = "owsvg/1"
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
selector = "svg|g[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
since = "0.1.0"
"""


def _bundle(tmp_path: Path, u02: str) -> ILBundle:
    il = tmp_path / "il"
    il.mkdir(parents=True)
    (il / "il.toml").write_text(
        'schema = "omniweave.out-il/1"\nil = "owsvg/1"\nconstructs_digest = "sha256:'
        + "0" * 64
        + '"\n\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.svg"\n'
        + '\n[[unit]]\nid = "u02"\nord = 2\nfile = "u02.svg"\n',
        encoding="utf-8",
    )
    (il / "u01.svg").write_text(f"<svg {NS}><rect/></svg>", encoding="utf-8")
    (il / "u02.svg").write_text(u02, encoding="utf-8")
    table = ConstructTable.parse(tomllib.loads(TABLE), {}, source="constructs.toml")
    return ILBundle.load(il, carrier=lambda p, t: svg_carrier(p, t, strict=False), constructs=table)


def test_assert_clean_names_every_unit_and_marker_and_counts_corrupt_ones(tmp_path: Path) -> None:
    marked = _marked().source()
    (marker,) = scan_text(marked)
    with pytest.raises(TargetError) as caught:
        assert_clean(_bundle(tmp_path / "a", marked))
    assert caught.value.code() == "OW_TARGET_MARKER_UNRESOLVED"
    assert f"u02: {marker.id}" in str(caught.value)
    corrupt = (
        f"<svg {NS}><!-- OWC1:v1 el=u02/e1 nsig=00000000 id=k-00000000 ts={TS} p=e30 --></svg>"
    )
    with pytest.raises(TargetError, match="k-00000000"):
        assert_clean(_bundle(tmp_path / "b", corrupt))
    assert_clean(_bundle(tmp_path / "c", f"<svg {NS}><rect/></svg>"))


def test_the_257th_marker_is_over_budget() -> None:
    lines = "".join(
        f"  <!-- OWC1:v1 el=u01/e2 nsig=00000000 id=k-{n:08x} ts={TS} "
        f"p={encode_payload(NOTE)} -->\n"
        for n in range(MAX_MARKERS_PER_UNIT - 1)
    )
    assert not over_budget(_svg(lines + TEXT))
    assert over_budget(
        _svg(
            lines + "  <!-- OWC1:v1 el=u01/e2 nsig=00000000 id=k-ffffffff "
            f"ts={TS} p={encode_payload(NOTE)} -->\n" + TEXT
        )
    )


def test_the_rule_runners_index_carries_each_units_markers() -> None:
    """`DocIndex.markers` is 09 section 4.4's marker inventory, filled by the scan (D745)."""
    marked = _marked().source()

    class _Bundle:
        units = (OutUnit(id="u01", ord=1, il_path="il/u01.svg"),)

        def text(self, il_path: str) -> str:  # noqa: ARG002 -- one unit, one text.
            return marked

    run = run_pack(
        {},
        _Bundle(),
        lambda *_: None,  # type: ignore[arg-type,return-value]  # an empty pack reads no ctx
        carrier=lambda p, t: svg_carrier(p, t, strict=False),
        stage="final",
        met=frozenset(),
        fixes={},
    )
    assert [m.id for m in run.index.markers] == [m.id for m in scan_text(marked)]
