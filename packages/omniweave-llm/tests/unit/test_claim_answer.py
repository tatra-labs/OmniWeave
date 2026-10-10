"""`derive.claim.llm`'s answer as frames (D721): checked against the lane's schema, translated."""

from __future__ import annotations

import json
from typing import Any

import pytest
from omniweave_llm.claim import LANE, answer_frames, parse_answer, precision, unparsed_frames
from omniweave_llm.entity import TRUST_CLAIM
from omniweave_llm.prompt import schema
from omniweave_llm.view import read_views

HEADER = {
    "t": "segment",
    "seg": "seg:1b2c3d4e5f607182",
    "heading_path": ["2. Payment"],
    "n_blocks": 3,
    "n_tokens": 40,
    "layer": "body",
    "atom": None,
    "defaults": {"layer": "body", "page": 1, "covered": False},
    "etypes": ["defined_term", "org", "unknown"],
    "document_scoped": ["defined_term"],
    "relations": [],
    "doc": {"format": "md", "media_type": "text/markdown"},
}
BLOCKS = [
    {"t": "block", "cite": "d1#4", "kind": "heading", "ord": 0, "text": "2. Payment"},
    {"t": "block", "cite": "d1#5", "kind": "paragraph", "ord": 1,
     "text": "Acme pays Beta 4,000 EUR by June 2026."},
    {"t": "block", "cite": "d1#6", "kind": "paragraph", "ord": 2, "text": "The Company may not.",
     "covered": True},
]  # fmt: skip
SCHEMA = schema(LANE, etypes=["defined_term", "org"])


def _view() -> Any:
    body = b"".join(json.dumps(frame).encode() + b"\n" for frame in [HEADER, *BLOCKS])
    [view] = read_views(body)
    return view


def _claim(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "subject": "Acme", "subject_etype": "org", "claim_type": "obligation",
        "predicate": "pays", "object": "4,000 EUR", "object_is_entity": False,
        "status": "asserted", "t_start": None, "t_end": None, "description": None,
        "cite": "d1#5", "quote": "Acme pays Beta",
    }  # fmt: skip
    base.update(fields)
    return base


def _frames(*claims: dict[str, Any]) -> list[dict[str, Any]]:
    answer = {"claims": list(claims), "more_available": False}
    value, problems = parse_answer(json.dumps(answer), SCHEMA)
    assert value is not None, problems
    return answer_frames(_view(), value)


def test_a_literal_object_is_a_string_literal_and_its_subject_an_entity_frame() -> None:
    frames = _frames(_claim())
    assert frames[0] == {"t": "seg", "seg": "seg:1b2c3d4e5f607182"}
    assert frames[1] == {
        "t": "entity", "tmp": "t1", "key": "Acme", "etype": "org", "title": "Acme",
        "scope": "corpus", "trust": TRUST_CLAIM,
    }  # fmt: skip
    assert frames[2] == {
        "t": "claim", "subject": "t1", "claim_type": "obligation", "predicate": "pays",
        "description": "", "status": "asserted",
        "observed": {"cite": "d1#5", "quote": "Acme pays Beta"}, "trust": TRUST_CLAIM,
        "object_literal": "4,000 EUR", "object_datatype": "string",
    }  # fmt: skip
    assert frames[3] == {"t": "cover", "lane": LANE, "cites": ["d1#5"]}
    assert len(frames) == 4, "no mention: the claim's own observed is its grounding"


def test_an_entity_object_is_an_entity_frame_and_subjects_group_by_name_and_type() -> None:
    frames = _frames(
        _claim(object="Beta", object_is_entity=True, description="Payment terms."),
        _claim(subject="ACME", predicate="delivers", object=None),
        _claim(subject="The Company", subject_etype="defined_term", object=None,
               status="denied"),
    )  # fmt: skip
    entities = [(f["tmp"], f["key"], f["etype"], f["scope"]) for f in frames if f["t"] == "entity"]
    assert entities == [
        ("t1", "Acme", "org", "corpus"),
        ("t2", "Beta", "unknown", "corpus"),
        ("t3", "The Company", "defined_term", "document"),
    ]
    claims = [f for f in frames if f["t"] == "claim"]
    assert [(c["subject"], c.get("object_entity"), c.get("object_literal")) for c in claims] == [
        ("t1", "t2", None),
        ("t1", None, None),
        ("t3", None, None),
    ], "ACME is Acme; a null object is neither an entity nor a literal"
    assert claims[0]["description"] == "Payment terms."
    assert claims[2]["status"] == "denied"


def test_an_entity_object_that_is_null_is_no_object() -> None:
    [claim] = [f for f in _frames(_claim(object=None, object_is_entity=True)) if f["t"] == "claim"]
    assert "object_entity" not in claim and "object_literal" not in claim


def test_a_null_subject_type_is_unknown() -> None:
    frames = _frames(_claim(subject_etype=None))
    assert frames[1]["etype"] == "unknown"


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (None, None, None),
        ("2026", None, "year"),
        ("2026-06", None, "month"),
        ("2026", "2026-06-30", "day"),
        ("2026-06-01", "2027", "day"),
    ],
)
def test_the_times_precision_is_the_finer_dates_shape(
    start: str | None, end: str | None, expected: str | None
) -> None:
    assert precision(start, end) == expected
    [claim] = [f for f in _frames(_claim(t_start=start, t_end=end)) if f["t"] == "claim"]
    if expected is None:
        assert "t_precision" not in claim and "t_start" not in claim
    else:
        assert (claim["t_start"], claim["t_end"], claim["t_precision"]) == (start, end, expected)


def test_a_covered_block_is_not_claimed_and_no_claim_is_cover_empty() -> None:
    frames = _frames(_claim(cite="d1#6", quote="The Company may not"))
    assert frames[-1] == {"t": "cover_empty", "lane": LANE, "reason": frames[-1]["reason"]}
    assert "no claim" in frames[-1]["reason"]
    assert _frames()[-1]["t"] == "cover_empty"


def test_an_answer_outside_the_schema_is_unparsed_and_kept() -> None:
    value, problems = parse_answer(
        json.dumps({"claims": [_claim(status="rumoured")], "more_available": False}), SCHEMA
    )
    assert value is None and any("rumoured" in p or "status" in p for p in problems), problems
    frames = unparsed_frames(_view(), "{ raw", problems)
    assert frames[1] == {"t": "claim", "unparsed": "{ raw", "problems": problems[:20]}
    assert frames[2]["t"] == "cover_empty" and frames[2]["lane"] == LANE
