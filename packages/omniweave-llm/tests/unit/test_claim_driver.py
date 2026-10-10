"""`derive.claim.llm` (D722): the claim lane's Pass, the shared `LanePass` over D721's frames."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_llm.claim import answer_frames
from omniweave_llm.claim_llm.driver import DRIVER_ID, ClaimLLM
from omniweave_llm.lane_pass import CHAT_PATH, GLEAN, LanePass
from omniweave_llm.prompt import decodable, render
from omniweave_llm.view import read_views
from omniweave_ports import ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef
from test_entity_driver import _IO, _Handle, _reply, _view

if TYPE_CHECKING:
    from pathlib import Path


def _claim(subject: str, cite: str, quote: str, **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "subject": subject, "subject_etype": "org", "claim_type": "obligation",
        "predicate": "pays", "object": None, "object_is_entity": False, "status": "asserted",
        "t_start": None, "t_end": None, "description": None, "cite": cite, "quote": quote,
    }  # fmt: skip
    base.update(fields)
    return base


def _answer(*claims: dict[str, Any], more: bool = False) -> dict[str, Any]:
    return {"claims": list(claims), "more_available": more}


def _run(tmp_path: Path, handle: _Handle, *bodies: bytes) -> tuple[list[dict[str, Any]], Any]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"seg:{i}", part="", content_sha256=blobs.add(b), byte_len=len(b))
        for i, b in enumerate(bodies)
    )
    io = _IO(make_io(blobs, tmp_path / "tmp"), handle)
    result = ClaimLLM().derive(
        DeriveScope(lane="claim", units=units, allowed_cites=frozenset()),
        io,  # type: ignore[arg-type]
    )
    assert result.outcome == "ok"
    [ref] = result.produced
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    return [json.loads(line) for line in body.decode().splitlines()], result.metrics


def test_one_segment_is_one_call_constrained_by_the_claim_schema(tmp_path: Path) -> None:
    answer = _answer(_claim("Acme", "d1#4", "Acme pays", object="Beta", object_is_entity=True))
    handle = _Handle([_reply(answer, tokens=(210, 30))])
    frames, metrics = _run(tmp_path, handle, _view())
    [view] = read_views(_view())
    assert frames == answer_frames(view, answer)
    [(path, request, _size)] = handle.requests
    prompt = render("claim", body=view.body, source=view.seg, etypes=view.etypes,
                    relations=view.relations)  # fmt: skip
    assert path == CHAT_PATH
    assert request["messages"] == [{"role": "user", "content": prompt.text}]
    assert request["response_format"]["json_schema"] == {
        "name": "owgraph_claim", "schema": decodable(prompt.schema), "strict": True,
    }  # fmt: skip
    assert (metrics.calls, metrics.tokens_in, metrics.tokens_out) == (1, 210, 30)


def test_the_glean_appends_its_claims_to_the_first_answers(tmp_path: Path) -> None:
    first = _answer(_claim("Acme", "d1#4", "Acme pays"), more=True)
    second = _answer(_claim("Gamma", "d1#5", "Gamma guarantees", predicate="guarantees"))
    handle = _Handle([_reply(first), _reply(second)])
    frames, metrics = _run(tmp_path, handle, _view())
    [view] = read_views(_view())
    both = {"claims": [*first["claims"], *second["claims"]], "more_available": False}
    assert frames == answer_frames(view, both)
    assert handle.requests[1][1]["messages"][-1] == {"role": "user", "content": GLEAN}
    assert metrics.calls == 2


def test_the_driver_declares_itself_as_the_claim_lanes_pass() -> None:
    assert issubclass(ClaimLLM, LanePass)
    assert (ClaimLLM.PORT, ClaimLLM.SCHEMA_VERSION, ClaimLLM.DRIVER_ID, ClaimLLM.LANE) == (
        "derive/1", 1, DRIVER_ID, "claim",
    )  # fmt: skip
    assert DRIVER_ID == "derive.claim.llm"
    assert ClaimLLM.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert ClaimLLM.LISTS == ("claims",)
