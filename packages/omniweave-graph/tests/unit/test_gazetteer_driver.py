"""`Gazetteer` on the wire: a lexicon frame and Segment views in, `owgraph-items/1` out. D683."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_graph.gazetteer.driver import (
    AMBIGUOUS,
    DRIVER_ID,
    EMPTY_LEXICON,
    LANES,
    NO_HIT_REASON,
    Gazetteer,
)
from omniweave_graph.gazetteer.rules import LEXICON_FORMAT
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef

ACME = {"etype": "org", "key": "acme_holdings_ltd", "title": "Acme Holdings Ltd."}
ATLAS_ORG = {"etype": "org", "key": "atlas", "title": "Atlas"}
ATLAS_PRODUCT = {"etype": "product", "key": "atlas", "title": "Atlas"}


def lines(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f) + "\n" for f in frames).encode()


def lexicon(**names: list[dict[str, str]]) -> bytes:
    head = {"t": "lexicon", "format": LEXICON_FORMAT, "names": len(names), "truncated": False}
    return lines(head, *({"t": "name", "name": n, "entities": e} for n, e in sorted(names.items())))


def seg(name: str = "seg:9f2c1d4a77b03e51") -> dict[str, Any]:
    return {"t": "segment", "seg": name, "heading_path": []}


def para(cite: str, text: str | None) -> dict[str, Any]:
    return {"t": "block", "cite": cite, "kind": "paragraph", "text": text}


def run(
    tmp_path: Path,
    *views: bytes,
    lexicon_body: bytes | None = None,
    driver: Gazetteer | None = None,
) -> list[dict[str, Any]]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    head = b""
    if lexicon_body is not None:
        head = lines({"t": "lexicon", "blob": blobs.add(lexicon_body)})
    units = tuple(
        UnitRef(uri=f"doc:{i}", part="", content_sha256=blobs.add(head + v), byte_len=len(v))
        for i, v in enumerate(views)
    )
    io = make_io(blobs, tmp_path / "tmp")
    gazetteer = driver or Gazetteer()
    result = gazetteer.derive(
        DeriveScope(lane="entity", units=units, allowed_cites=frozenset()), io
    )
    assert result.outcome == "ok"
    [ref] = result.produced
    assert ref.kind == "graph_items"
    assert gazetteer.is_valid_nonempty(ref)
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    return [json.loads(line) for line in body.decode().splitlines()]


def test_probe_needs_nothing_and_the_port_is_derive() -> None:
    assert Gazetteer.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert Gazetteer.PORT == "derive/1"
    assert DRIVER_ID == "derive.entity.gazetteer"
    assert LANES == ("entity",)


def test_config_takes_nothing() -> None:
    with pytest.raises(ValueError, match="takes no names"):
        Gazetteer(names=3)


def test_a_hit_re_proposes_the_entity_once_and_mentions_each_occurrence(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        lines(
            seg(),
            para("d7#1", "Acme Holdings Ltd. shall pay. Acme Holdings Ltd agrees."),
            para("d7#2", None),
            para("d7#3", "Nobody here."),
        ),
        lexicon_body=lexicon(acme_holdings_ltd=[ACME]),
    )
    assert frames == [
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {"t": "entity", "tmp": "e1", "key": "acme_holdings_ltd", "etype": "org",
         "title": "Acme Holdings Ltd.", "scope": "corpus", "trust": "extracted"},
        {"t": "mention", "entity": "e1", "cite": "d7#1", "span": [0, 17],
         "surface": "Acme Holdings Ltd", "trust": "extracted"},
        {"t": "mention", "entity": "e1", "cite": "d7#1", "span": [30, 47],
         "surface": "Acme Holdings Ltd", "trust": "extracted"},
        {"t": "cover", "lane": "entity", "cites": ["d7#1"]},
    ]  # fmt: skip
    assert not any(f["t"] == "alias" for f in frames), (
        "no alias: nothing it writes moves the lexicon"
    )


def test_one_name_two_entities_is_two_mentions_and_a_diagnostic(tmp_path: Path) -> None:
    """Ruling 4."""
    frames = run(
        tmp_path,
        lines(seg(), para("d7#1", "Atlas shipped.")),
        lexicon_body=lexicon(atlas=[ATLAS_ORG, ATLAS_PRODUCT]),
    )
    kinds = [(f["t"], f.get("etype") or f.get("entity") or f.get("code")) for f in frames]
    assert kinds == [
        ("seg", None),
        ("entity", "org"),
        ("mention", "e1"),
        ("entity", "product"),
        ("mention", "e2"),
        ("diag", AMBIGUOUS),
        ("cover", None),
    ]
    [diag] = [f for f in frames if f["t"] == "diag"]
    assert (diag["cite"], diag["detail"], diag["severity"]) == (
        "d7#1",
        {"name": "atlas", "entities": 2},
        "warning",
    )


def test_tokens_are_per_segment_and_numbered_across_the_invocation(tmp_path: Path) -> None:
    """A token is bound for one run (one Segment); the next Segment re-proposes the entity."""
    frames = run(
        tmp_path,
        lines(
            seg("seg:a"),
            para("d7#1", "Acme Holdings Ltd"),
            seg("seg:b"),
            para("d7#2", "Acme Holdings Ltd"),
        ),
        lines(seg("seg:c"), para("d8#1", "Acme Holdings Ltd")),
        lexicon_body=lexicon(acme_holdings_ltd=[ACME]),
    )
    assert [f["tmp"] for f in frames if f["t"] == "entity"] == ["e1", "e2", "e3"]
    assert [f["entity"] for f in frames if f["t"] == "mention"] == ["e1", "e2", "e3"]


def test_no_hit_is_a_cover_empty_with_its_reason(tmp_path: Path) -> None:
    frames = run(
        tmp_path,
        lines(seg(), para("d7#1", "Nothing.")),
        lexicon_body=lexicon(acme_holdings_ltd=[ACME]),
    )
    assert frames[1:] == [{"t": "cover_empty", "lane": "entity", "reason": NO_HIT_REASON}]


@pytest.mark.parametrize("body", [None, lexicon()])
def test_no_lexicon_or_an_empty_one_is_06_913s_empty_lexicon(
    tmp_path: Path, body: bytes | None
) -> None:
    frames = run(tmp_path, lines(seg(), para("d7#1", "Acme Holdings Ltd")), lexicon_body=body)
    assert frames[1:] == [{"t": "cover_empty", "lane": "entity", "reason": EMPTY_LEXICON}]


def test_the_automaton_is_built_once_per_lexicon_per_worker(tmp_path: Path) -> None:
    driver = Gazetteer()
    body = lexicon(acme_holdings_ltd=[ACME])
    run(tmp_path / "a", lines(seg(), para("d7#1", "x")), lexicon_body=body, driver=driver)
    first = driver._built
    run(tmp_path / "b", lines(seg(), para("d7#1", "x")), lexicon_body=body, driver=driver)
    assert driver._built is first
    run(tmp_path / "c", lines(seg(), para("d7#1", "x")), lexicon_body=lexicon(), driver=driver)
    assert driver._built is not first


@pytest.mark.parametrize(
    ("head", "message"),
    [
        (b'{"t":"lexicon"}\n', "names no blob"),
        (b'{"t":"lexicon","blob":"LEX"}\n', "lexicon"),
    ],
)
def test_a_bad_lexicon_frame_or_artefact_is_corrupt_input(
    tmp_path: Path, head: bytes, message: str
) -> None:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    bad = blobs.add(b'{"t":"lexicon","format":"nope","names":0}\n')
    view = head.replace(b"LEX", bad.encode()) + lines(seg(), para("d7#1", "x"))
    unit = UnitRef(uri="doc:0", part="", content_sha256=blobs.add(view), byte_len=len(view))
    with pytest.raises(DriverError, match=message) as raised:
        Gazetteer().derive(
            DeriveScope(lane="entity", units=(unit,), allowed_cites=frozenset()),
            make_io(blobs, tmp_path / "tmp"),
        )
    assert raised.value.cls is FailureClass.CORRUPT_INPUT
