"""`derive.merge.llm` (D726): a batch of entity pairs, one call, decided by position."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_llm.lane_pass import CHAT_PATH
from omniweave_llm.merge import LLM_BATCH, answer_frames, read_pairs, unparsed_frames
from omniweave_llm.merge_llm.driver import DRIVER_ID, MergeLLM
from omniweave_llm.prompt import decodable, render
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef
from test_entity_driver import _IO, _Handle, _reply

if TYPE_CHECKING:
    from pathlib import Path

WITNESS = [
    {"unit_uri": "file:///docs/a.md", "unit_part": "", "token": "acme_holdings"},
    {"unit_uri": "file:///docs/b.md", "unit_part": "", "token": "acme_holdings_ltd"},
]
SIDES = [
    (
        {"surface": "Acme Holdings", "etype": "org", "aliases": ["Acme"]},
        {"surface": "Acme Holdings Ltd", "etype": "org", "aliases": []},
    ),
    (
        {"surface": "Beta Corp", "etype": "org", "aliases": []},
        {"surface": "Beta Corporation", "etype": "org", "aliases": ["BetaCo"]},
    ),
]


def _batch(n: int = 2, *, batch: str = "band:0123456789abcdef", witness: Any = WITNESS) -> bytes:
    frames: list[dict[str, Any]] = [{"t": "pairs", "batch": batch, "n": n, "witness": witness}]
    frames += [
        {"t": "pair", "pair": i, "a": SIDES[i % 2][0], "b": SIDES[i % 2][1]} for i in range(n)
    ]
    return b"".join(json.dumps(f).encode() + b"\n" for f in frames)


def _decision(pair: int, *, same: bool = True, reason: str = "one company") -> dict[str, Any]:
    return {"pair": pair, "same": same, "reason": reason}


def _run(
    tmp_path: Path, handle: _Handle, *bodies: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"band:{i}", part="", content_sha256=blobs.add(b), byte_len=len(b))
        for i, b in enumerate(bodies)
    )
    io = _IO(make_io(blobs, tmp_path / "tmp"), handle)
    result = MergeLLM().derive(
        DeriveScope(lane="merge", units=units, allowed_cites=frozenset()),
        io,  # type: ignore[arg-type]
    )
    assert result.outcome == "ok"
    items, witness = result.produced
    assert (items.kind, witness.kind) == ("graph_items", "witness_set")
    assert MergeLLM().is_valid_nonempty(items)

    def lines(ref: Any) -> list[dict[str, Any]]:
        body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
        return [json.loads(line) for line in body.decode().splitlines()]

    return lines(items), lines(witness), result.metrics


# ---------------------------------------------------------------------------------------------
# the view
# ---------------------------------------------------------------------------------------------


def test_a_batch_is_its_header_and_its_numbered_pairs() -> None:
    """Merge ruling 1: the body the model reads is the pair lines alone."""
    view = read_pairs(_batch())
    assert (view.batch, view.n, view.witness) == ("band:0123456789abcdef", 2, tuple(WITNESS))
    assert [json.loads(line)["pair"] for line in view.body.splitlines()] == [0, 1]
    assert '"pairs"' not in view.body


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (b"", "JSON object lines"),
        (b"[1]\n", "JSON object lines"),
        (b'{"t": "pair", "pair": 0, "n": 1}\n', "opens with its pairs header"),
        (_batch(0), "holds 1 to 30 pairs"),
        (_batch(LLM_BATCH + 1), "holds 1 to 30 pairs"),
        (_batch(2).replace(b'"pair": 1', b'"pair": 2'), "numbered 0 to n-1"),
        (b'{"t": "pairs", "batch": "band:x", "n": 2}\n{"t": "pair", "pair": 0}\n', "numbered"),
    ],
    ids=["empty", "array", "headless", "none", "too-many", "gap", "short"],
)
def test_a_body_that_is_not_a_batch_is_refused(body: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        read_pairs(body)


def test_no_identifier_reaches_the_prompt() -> None:
    """GR11 (06:1461): the witness's units and tokens stay in the header, out of the prompt."""
    view = read_pairs(_batch())
    text = render("merge", body=view.body, source=view.batch).text
    assert "file:///" not in text
    assert "acme_holdings" not in text
    assert "Acme Holdings Ltd" in text


# ---------------------------------------------------------------------------------------------
# the answer
# ---------------------------------------------------------------------------------------------


def test_each_decision_is_kept_by_its_position() -> None:
    """Merge rulings 3 and 5: a pair left out has no frame."""
    view = read_pairs(_batch())
    frames = answer_frames(view, {"decisions": [_decision(1, same=False, reason="two firms")]})
    assert frames == [
        {"t": "batch", "batch": view.batch},
        {"t": "decision", "pair": 1, "same": False, "reason": "two firms"},
    ]


def test_a_position_not_sent_is_a_malformed_decision() -> None:
    """Merge ruling 4 (06:1476): kept verbatim, with no `same` for the host to merge on."""
    view = read_pairs(_batch())
    frames = answer_frames(view, {"decisions": [_decision(0), _decision(2)]})
    assert frames[1] == {"t": "decision", "pair": 0, "same": True, "reason": "one company"}
    assert frames[2]["pair"] == 2
    assert "same" not in frames[2]
    assert json.loads(frames[2]["unparsed"]) == _decision(2)
    assert frames[2]["problems"] == ["pair 2 was not sent: the batch holds 2"]


def test_a_position_answered_twice_decides_nothing() -> None:
    """Merge ruling 4: both answers are malformed, so neither stands."""
    view = read_pairs(_batch())
    answer = {"decisions": [_decision(0, same=True), _decision(0, same=False), _decision(1)]}
    frames = answer_frames(view, answer)
    twice = [f for f in frames if f.get("pair") == 0]
    assert len(twice) == 2
    assert all("same" not in f and f["problems"] == ["pair 0 was answered 2 times"] for f in twice)
    assert frames[-1] == {"t": "decision", "pair": 1, "same": True, "reason": "one company"}


def test_an_answer_that_does_not_parse_decides_nothing() -> None:
    """Merge ruling 6."""
    view = read_pairs(_batch())
    frames = unparsed_frames(view, "{oops", ["$: not JSON"])
    assert frames == [
        {"t": "batch", "batch": view.batch},
        {"t": "decision", "unparsed": "{oops", "problems": ["$: not JSON"]},
    ]


# ---------------------------------------------------------------------------------------------
# the Pass
# ---------------------------------------------------------------------------------------------


def test_one_batch_is_one_call_constrained_by_the_merge_schema(tmp_path: Path) -> None:
    """Rulings 7-8: one call, no glean, the extraction lanes' call under `owgraph_merge`."""
    answer = {"decisions": [_decision(0), _decision(1, same=False, reason="two firms")]}
    handle = _Handle([_reply(answer, tokens=(400, 40))])
    frames, witness, metrics = _run(tmp_path, handle, _batch())
    view = read_pairs(_batch())
    assert frames == answer_frames(view, answer)
    [(path, request, size)] = handle.requests
    prompt = render("merge", body=view.body, source=view.batch)
    assert path == CHAT_PATH
    assert request["messages"] == [{"role": "user", "content": prompt.text}]
    assert request["temperature"] == 0
    assert request["model"] == "qwen3:4b"
    assert request["response_format"]["json_schema"] == {
        "name": "owgraph_merge", "schema": decodable(prompt.schema), "strict": True,
    }  # fmt: skip
    assert (metrics.calls, metrics.tokens_in, metrics.tokens_out) == (1, 400, 40)
    assert metrics.bytes_egress == size
    assert witness == WITNESS, "ruling 9: the host's witness, echoed"


def test_each_batch_is_its_own_call_and_its_own_frames(tmp_path: Path) -> None:
    first, second = _batch(batch="band:aaaaaaaaaaaaaaaa"), _batch(1, batch="band:bbbbbbbbbbbbbbbb")
    handle = _Handle([_reply({"decisions": [_decision(1)]}), _reply({"decisions": [_decision(0)]})])
    frames, witness, metrics = _run(tmp_path, handle, first, second)
    assert [f["batch"] for f in frames if f["t"] == "batch"] == [
        "band:aaaaaaaaaaaaaaaa",
        "band:bbbbbbbbbbbbbbbb",
    ]
    assert [f["pair"] for f in frames if f["t"] == "decision"] == [1, 0]
    assert metrics.calls == 2
    assert witness == [*WITNESS, *WITNESS]


def test_an_answer_off_the_schema_is_one_malformed_frame(tmp_path: Path) -> None:
    handle = _Handle([_reply({"decisions": [{"pair": 0, "same": "yes", "reason": "x"}]})])
    frames, _witness, _metrics = _run(tmp_path, handle, _batch())
    assert frames[0]["t"] == "batch"
    [malformed] = frames[1:]
    assert "same" not in malformed
    assert malformed["problems"] == ["$.decisions[0].same: expected boolean"]


def test_a_body_that_is_not_a_batch_is_corrupt_input(tmp_path: Path) -> None:
    with pytest.raises(DriverError) as raised:
        _run(tmp_path, _Handle([]), b'{"t": "segment"}\n')
    assert raised.value.cls is FailureClass.CORRUPT_INPUT


def test_a_cancelled_run_makes_no_call(tmp_path: Path) -> None:
    handle = _Handle([], cancelled=True)
    with pytest.raises(DriverError) as raised:
        _run(tmp_path, handle, _batch())
    assert raised.value.cls is FailureClass.TIMEOUT
    assert handle.requests == []


def test_the_driver_reaches_its_model_through_the_service_and_takes_no_other_config() -> None:
    assert MergeLLM.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert MergeLLM().service == "llm"
    with pytest.raises(ValueError, match=DRIVER_ID):
        MergeLLM(model="x")
