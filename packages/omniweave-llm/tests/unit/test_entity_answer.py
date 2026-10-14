"""`derive.entity.llm`'s answer as frames (D710): the view read, the answer checked, translated."""

from __future__ import annotations

import json
from typing import Any

import pytest
from omniweave_llm.entity import (
    LANE,
    TRUST_CLAIM,
    answer_frames,
    parse_answer,
    unparsed_frames,
)
from omniweave_llm.prompt import schema
from omniweave_llm.validate import violations
from omniweave_llm.view import read_views

HEADER = {
    "t": "segment",
    "seg": "seg:9f2c1d4a77b03e51",
    "heading_path": ["2. Payment"],
    "n_blocks": 3,
    "n_tokens": 40,
    "layer": "body",
    "atom": None,
    "defaults": {"layer": "body", "page": 1, "covered": False},
    "etypes": ["defined_term", "org", "unknown"],
    "document_scoped": ["defined_term"],
    "relations": [{"relation": "party_to", "actor_rule": "source is the PARTY."}],
    "doc": {"format": "md", "media_type": "text/markdown"},
}
BLOCKS = [
    {"t": "block", "cite": "d1#4", "kind": "heading", "ord": 0, "text": "2. Payment"},
    {"t": "block", "cite": "d1#5", "kind": "paragraph", "ord": 1, "text": "Acme pays Beta."},
    {"t": "block", "cite": "d1#6", "kind": "paragraph", "ord": 2, "text": "The Company.",
     "covered": True},
]  # fmt: skip


def _body(*segments: list[dict[str, Any]]) -> bytes:
    return b"".join(json.dumps(frame).encode() + b"\n" for frames in segments for frame in frames)


def _view() -> Any:
    [view] = read_views(_body([HEADER, *BLOCKS]))
    return view


def test_the_billed_view_is_read_and_a_free_one_refused() -> None:
    view = _view()
    assert (view.seg, view.etypes, view.document_scoped) == (
        "seg:9f2c1d4a77b03e51",
        ("defined_term", "org", "unknown"),
        frozenset({"defined_term"}),
    )
    assert view.relations == (("party_to", "source is the PARTY."),)
    assert [(b.cite, b.covered) for b in view.blocks] == [
        ("d1#4", False),
        ("d1#5", False),
        ("d1#6", True),
    ]
    assert view.body.splitlines()[0] == json.dumps(HEADER), "part 5 is the frames as received"
    second = {**HEADER, "seg": "seg:00000000000000ff"}
    assert [v.seg for v in read_views(_body([HEADER, *BLOCKS], [second]))] == [
        HEADER["seg"],
        "seg:00000000000000ff",
    ]
    mostly = {**HEADER, "defaults": {**HEADER["defaults"], "covered": True}}
    flipped = [{**BLOCKS[0], "covered": False}, BLOCKS[1]]
    [view_b] = read_views(_body([mostly, *flipped]))
    assert [b.covered for b in view_b.blocks] == [False, True], "an absent key takes the default"
    free = {k: v for k, v in HEADER.items() if k not in ("etypes", "relations")}
    with pytest.raises(ValueError, match="a free view"):
        read_views(_body([free, *BLOCKS]))
    with pytest.raises(ValueError, match="before any segment"):
        read_views(_body(BLOCKS))
    with pytest.raises(ValueError, match="not a JSON object"):
        read_views(b"[1, 2]\n")


@pytest.mark.parametrize(
    ("node", "value", "ok"),
    [
        ({"type": "integer"}, True, False),
        ({"type": "number"}, False, False),
        ({"type": "number"}, 2.5, True),
        ({"type": ["string", "null"]}, None, True),
        ({"enum": ["a", None]}, None, True),
        ({"enum": ["a"]}, "b", False),
        ({"type": "string", "minLength": 3}, "ab", False),
        ({"type": "string", "maxLength": 3}, "abcd", False),
        ({"type": "string", "pattern": "^d[0-9]+$"}, "d7", True),
        ({"type": "string", "pattern": "^d[0-9]+$"}, "x7", False),
        ({"type": "integer", "minimum": 0, "maximum": 29}, 30, False),
        ({"type": "array", "maxItems": 1, "items": {"type": "string"}}, ["a", "b"], False),
        ({"type": "array", "minItems": 1}, [], False),
        ({"type": "array", "items": {"type": "string"}}, ["a", 1], False),
        ({"type": "object", "required": ["a"], "properties": {"a": {}}}, {}, False),
        ({"type": "object", "additionalProperties": False, "properties": {}}, {"x": 1}, False),
        ({"type": "object", "properties": {"a": {"type": "string"}}}, {"a": 1}, False),
    ],
)
def test_the_validator_reads_the_ten_keywords(node: dict[str, Any], value: Any, ok: bool) -> None:
    assert (violations(node, value) == []) == ok


ENTITY_SCHEMA = schema("entity", etypes=["defined_term", "org"], relations=["party_to"])


def _answer(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "entities": [
            {"name": "Acme", "etype": "org", "cite": "d1#5", "quote": "Acme pays",
             "description": "the payer"},
            {"name": "acme", "etype": "org", "cite": "d1#5", "quote": "Acme pays Beta",
             "description": None},
            {"name": None, "etype": None, "cite": "d1#5", "quote": "Beta",
             "description": None},
            {"name": "Company", "etype": "defined_term", "cite": "d1#6", "quote": "The Company",
             "description": None},
        ],
        "relations": [
            {"source": "ACME", "target": "Beta", "relation": "party_to", "cite": "d1#5",
             "quote": "Acme pays Beta"},
            {"source": "Acme", "target": "Zeta", "relation": "party_to", "cite": "d1#5",
             "quote": "Acme pays"},
        ],
        "more_available": False,
    }  # fmt: skip
    return base | overrides


def test_parse_answer_accepts_a_conforming_answer_and_says_why_not() -> None:
    answer, problems = parse_answer(json.dumps(_answer()), ENTITY_SCHEMA)
    assert (answer, problems) == (_answer(), [])
    assert parse_answer("not json", ENTITY_SCHEMA)[0] is None
    bad = _answer(more_available="yes")
    answer, problems = parse_answer(json.dumps(bad), ENTITY_SCHEMA)
    assert answer is None and problems == ["$.more_available: expected boolean"]
    unknown = _answer(relations=[{**_answer()["relations"][0], "relation": "owns"}])
    assert parse_answer(json.dumps(unknown), ENTITY_SCHEMA)[0] is None


def test_an_answer_becomes_drafts_the_sink_can_judge() -> None:
    """Rulings 2-7."""
    frames = answer_frames(_view(), _answer())
    assert frames[0] == {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"}
    entities = [f for f in frames if f["t"] == "entity"]
    assert [(e["tmp"], e["title"], e["etype"], e["scope"]) for e in entities] == [
        ("t1", "Acme", "org", "corpus"),
        ("t2", "Beta", "unknown", "corpus"),
        ("t3", "Company", "defined_term", "document"),
    ], "acme folds into Acme; a null name takes its quote; a null type is unknown"
    assert entities[0]["description"] == "the payer" and "description" not in entities[1]
    mentions = [f for f in frames if f["t"] == "mention"]
    assert [(m["entity"], m["cite"], m["quote"]) for m in mentions] == [
        ("t1", "d1#5", "Acme pays"),
        ("t1", "d1#5", "Acme pays Beta"),
        ("t2", "d1#5", "Beta"),
        ("t3", "d1#6", "The Company"),
    ]
    assert {f.get("trust") for f in frames if f["t"] in ("entity", "mention")} == {TRUST_CLAIM}
    resolved, unresolved = [f for f in frames if f["t"] == "edge"]
    assert (resolved["src"], resolved["dst"], resolved["trust"]) == ("t1", "t2", "extracted")
    assert resolved["observed"] == {"cite": "d1#5", "quote": "Acme pays Beta"}
    assert "src" not in unresolved and unresolved["target"] == "Zeta"
    assert frames[-1] == {"t": "cover", "lane": LANE, "cites": ["d1#5"]}, "not the covered d1#6"


def test_an_answer_with_nothing_on_uncovered_ground_is_cover_empty() -> None:
    frames = answer_frames(_view(), _answer(entities=[], relations=[]))
    assert frames == [
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {"t": "cover_empty", "lane": "entity",
         "reason": "the model returned no item on uncovered ground"},
    ]  # fmt: skip


def test_an_unparsed_answer_is_one_malformed_frame_and_a_reason() -> None:
    """Ruling 1: never an empty answer."""
    frames = unparsed_frames(_view(), "{oops", ["$: not JSON"])
    assert frames[1] == {"t": "entity", "unparsed": "{oops", "problems": ["$: not JSON"]}
    assert frames[2]["t"] == "cover_empty" and "did not parse" in frames[2]["reason"]
