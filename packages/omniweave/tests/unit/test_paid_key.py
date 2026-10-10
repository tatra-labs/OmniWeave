"""`paid_key` and the call cache's payload: what a billed Segment's answer is kept and replayed by.

D725, rulings 8-10 of `omniweave.run.operators.billed`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from omniweave.run.operators.billed import DECODE, paid_key, remembered, replayed
from omniweave_core.store.graph import SegmentRef
from omniweave_core.store.items import ItemView

DIGEST = bytes.fromhex("9f2c1d4a77b03e51" + "00" * 24)
HEADER: dict[str, Any] = {
    "t": "segment",
    "seg": "seg:9f2c1d4a77b03e51",
    "etypes": ["person", "org"],
    "document_scoped": ["defined_term"],
    "relations": [{"relation": "party_to", "actor_rule": "source is the PARTY."}],
    "doc": {"format": "md", "media_type": "text/markdown"},
}


def _view(cites: list[str], *, header: dict[str, Any] | None = None, digest: bytes = DIGEST) -> Any:
    frames = [
        header or HEADER,
        *({"t": "block", "cite": c, "kind": "para", "ord": i} for i, c in enumerate(cites)),
    ]
    body = "".join(json.dumps(f, separators=(",", ":")) + "\n" for f in frames).encode()
    return ItemView(
        ref=SegmentRef(segment_id=7, doc_ord=1, gen=1, content_digest=digest, uncovered=None),
        seg=f"seg:{digest.hex()[:16]}",
        body=body,
        cites={c: i for i, c in enumerate(cites)},
    )


def _card(driver: str = "derive.entity.llm", schema_version: int = 1, prompt: str = "1") -> Any:
    return SimpleNamespace(
        identity=SimpleNamespace(id=driver, schema_version=schema_version),
        derive_sibling=SimpleNamespace(prompt_version=prompt),
    )


def _answer(*frames: dict[str, Any]) -> bytes:
    return "".join(json.dumps(f, separators=(",", ":")) + "\n" for f in frames).encode()


ANSWER = _answer(
    {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
    {"t": "entity", "local": "e1", "key": "acme", "name": "Acme", "scope": "corpus"},
    {"t": "mention", "entity": "e1", "cite": "d1#2", "quote": "Acme"},
    {"t": "cover", "lane": "entity", "cites": ["d1#1", "d1#2"]},
)


def test_the_key_is_stable_and_names_no_file() -> None:
    """Ruling 8: the same Segment text under other cites, in another file, is the same question."""
    key = paid_key(_card(), _view(["d1#1", "d1#2"]), "qwen3:4b", "a" * 40)
    assert key == paid_key(_card(), _view(["d9#1", "d9#2"]), "qwen3:4b", "a" * 40)
    assert len(key) == 64
    assert int(key, 16) >= 0


@pytest.mark.parametrize(
    "moved",
    [
        {"card": _card(driver="derive.claim.llm")},
        {"card": _card(schema_version=2)},
        {"card": _card(prompt="2")},
        {"view": _view(["d1#1", "d1#2"], digest=bytes.fromhex("11" * 32))},
        {"model_id": "qwen3:8b"},
        {"model_rev": "b" * 40},
        {"view": _view(["d1#1", "d1#2"], header={**HEADER, "etypes": ["person"]})},
        {"view": _view(["d1#1", "d1#2"], header={**HEADER, "document_scoped": []})},
        {"view": _view(["d1#1", "d1#2"], header={**HEADER, "relations": []})},
    ],
    ids=["pass", "schema", "prompt", "segment", "model", "revision", "etypes", "scoped", "rels"],
)
def test_each_input_06_names_moves_the_key(moved: dict[str, Any]) -> None:
    """06:1636's eight inputs: each one changes the answer, so each one changes the key."""
    base: dict[str, Any] = {
        "card": _card(),
        "view": _view(["d1#1", "d1#2"]),
        "model_id": "qwen3:4b",
        "model_rev": "a" * 40,
    }
    assert paid_key(**base) != paid_key(**{**base, **moved})


def test_the_view_s_doc_frame_is_not_a_key_input() -> None:
    """The file's format names no vocabulary, so it does not move the key; only the three do."""
    other = _view(["d1#1", "d1#2"], header={**HEADER, "doc": {"format": "txt"}})
    assert paid_key(_card(), other, "m", "r") == paid_key(
        _card(), _view(["d1#1", "d1#2"]), "m", "r"
    )


def test_the_decode_configuration_is_what_the_lane_sends() -> None:
    """Ruling 8: `DECODE` is a key input, so it must say what `LanePass` asks the server for."""
    assert DECODE == {
        "temperature": 0,
        "response_format": "json_schema",
        "strict": True,
        "decodable": 1,
    }


def test_an_answer_is_replayed_onto_another_file_s_cites_by_position() -> None:
    """Ruling 9: the stored cites map onto the new view's, and nothing else is touched."""
    kept = remembered(_view(["d1#1", "d1#2"]), ANSWER)
    assert kept is not None
    assert json.loads(kept)["cites"] == ["d1#1", "d1#2"]
    replay = replayed(kept, _view(["d4#7", "d4#9"]))
    assert replay is not None
    frames = [json.loads(line) for line in replay.splitlines()]
    assert frames[2]["cite"] == "d4#9"
    assert frames[3]["cites"] == ["d4#7", "d4#9"]
    assert frames[1] == json.loads(ANSWER.splitlines()[1]), "an entity frame names no cite"
    assert frames[0] == {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"}


def test_a_replay_onto_the_same_cites_is_the_answer_itself() -> None:
    kept = remembered(_view(["d1#1", "d1#2"]), ANSWER)
    assert kept is not None
    replay = replayed(kept, _view(["d1#1", "d1#2"]))
    assert replay is not None
    assert [json.loads(x) for x in replay.splitlines()] == [
        json.loads(x) for x in ANSWER.splitlines()
    ]


def test_a_view_with_another_block_count_is_a_miss() -> None:
    """Ruling 9: position is the only map, so a count that differs maps nothing."""
    kept = remembered(_view(["d1#1", "d1#2"]), ANSWER)
    assert kept is not None
    assert replayed(kept, _view(["d4#7"])) is None
    assert replayed(kept, _view(["d4#7", "d4#8", "d4#9"])) is None


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not json",
        b"{}",
        b"[]",
        b'{"cites": 3, "frames": []}',
        b'{"cites": ["d1#1", "d1#2"], "frames": [1]}',
    ],
)
def test_a_payload_that_does_not_parse_is_a_miss(payload: bytes) -> None:
    """08:1439 clause 2: a corrupt entry is a miss, never a failure."""
    assert replayed(payload, _view(["d1#1", "d1#2"])) is None


def test_an_answer_that_did_not_parse_is_not_kept() -> None:
    """Ruling 10: the model may not repeat a malformed answer, so the cache must not."""
    unparsed = _answer(
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {"t": "entity", "unparsed": "{oops", "problems": ["not JSON"]},
        {"t": "cover_empty", "lane": "entity", "reason": "unparsed"},
    )
    assert remembered(_view(["d1#1"]), unparsed) is None


def test_an_answer_that_found_nothing_is_kept() -> None:
    """A `cover_empty` with a reason other than a parse failure is an answer, and it cost a call."""
    empty = _answer(
        {"t": "seg", "seg": "seg:9f2c1d4a77b03e51"},
        {"t": "cover_empty", "lane": "entity", "reason": "no_items"},
    )
    assert remembered(_view(["d1#1"]), empty) is not None
