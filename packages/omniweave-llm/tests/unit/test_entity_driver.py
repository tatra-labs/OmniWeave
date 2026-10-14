"""`derive.entity.llm` (D711): one prompt per Segment through `io.service()`, and one glean."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_llm.entity import answer_frames
from omniweave_llm.entity_llm.driver import CHAT_PATH, DRIVER_ID, GLEAN, EntityLLM
from omniweave_llm.prompt import decodable, render
from omniweave_llm.view import read_views
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

HEADER: dict[str, Any] = {
    "t": "segment",
    "seg": "seg:9f2c1d4a77b03e51",
    "heading_path": ["2. Payment"],
    "n_blocks": 2,
    "n_tokens": 20,
    "layer": "body",
    "atom": None,
    "defaults": {"layer": "body", "page": 1, "covered": False},
    "etypes": ["org", "unknown"],
    "document_scoped": [],
    "relations": [{"relation": "party_to", "actor_rule": "source is the PARTY."}],
    "doc": {"format": "md", "media_type": "text/markdown"},
}
BLOCKS = [
    {"t": "block", "cite": "d1#4", "kind": "paragraph", "ord": 0, "text": "Acme pays Beta."},
    {"t": "block", "cite": "d1#5", "kind": "paragraph", "ord": 1, "text": "Gamma guarantees."},
]


def _view(seg: str = HEADER["seg"]) -> bytes:
    frames = [{**HEADER, "seg": seg}, *BLOCKS]
    return b"".join(json.dumps(f).encode() + b"\n" for f in frames)


def _entity(name: str, cite: str, quote: str) -> dict[str, Any]:
    return {"name": name, "etype": "org", "cite": cite, "quote": quote, "description": None}


def _answer(*entities: dict[str, Any], more: bool = False) -> dict[str, Any]:
    return {"entities": list(entities), "relations": [], "more_available": more}


def _reply(answer: Any, *, tokens: tuple[int, int] = (100, 10)) -> bytes:
    content = answer if isinstance(answer, str) else json.dumps(answer)
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]},
        }
    ).encode()


class _Handle:
    """A ServiceHandle that answers from a script and records every request."""

    def __init__(self, replies: list[bytes], *, cancelled: bool = False) -> None:
        self.replies = list(replies)
        self.requests: list[tuple[str, dict[str, Any], int]] = []
        self._cancelled = cancelled
        self.name, self.base_url, self.token = "llm", "http://127.0.0.1:11434", ""
        self.model_id, self.model_rev = "qwen3:4b", "0123456789abcdef"
        self.capacity, self.traceparent, self.deadline_ms = 1, "", 60_000

    def post(self, path: str, body: bytes, *, headers: Mapping[str, str] | None = None) -> bytes:
        del headers
        self.requests.append((path, json.loads(body), len(body)))
        return self.replies.pop(0)

    def cancelled(self) -> bool:
        return self._cancelled


class _IO:
    """`make_io`'s KitIO, with `service()` answering from a `_Handle`."""

    def __init__(self, inner: Any, handle: _Handle) -> None:
        self._inner, self._handle, self.asked = inner, handle, []

    def service(self, name: str) -> _Handle:
        self.asked.append(name)
        return self._handle

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _run(
    tmp_path: Path, handle: _Handle, *bodies: bytes, **config: Any
) -> tuple[list[dict[str, Any]], Any, _IO]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"seg:{i}", part="", content_sha256=blobs.add(b), byte_len=len(b))
        for i, b in enumerate(bodies)
    )
    io = _IO(make_io(blobs, tmp_path / "tmp"), handle)
    result = EntityLLM(**config).derive(
        DeriveScope(lane="entity", units=units, allowed_cites=frozenset()),
        io,  # type: ignore[arg-type]
    )
    assert result.outcome == "ok"
    [ref] = result.produced
    body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
    assert EntityLLM().is_valid_nonempty(ref)
    return [json.loads(line) for line in body.decode().splitlines()], result.metrics, io


def test_one_segment_is_one_constrained_call(tmp_path: Path) -> None:
    """Rulings 1, 2 and 4."""
    answer = _answer(_entity("Acme", "d1#4", "Acme pays"))
    handle = _Handle([_reply(answer, tokens=(321, 45))])
    frames, metrics, io = _run(tmp_path, handle, _view())
    [view] = read_views(_view())
    assert frames == answer_frames(view, answer)
    [(path, request, size)] = handle.requests
    prompt = render("entity", body=view.body, source=view.seg, etypes=view.etypes,
                    relations=view.relations)  # fmt: skip
    assert path == CHAT_PATH
    assert request["model"] == "qwen3:4b" and request["temperature"] == 0
    assert request["messages"] == [{"role": "user", "content": prompt.text}]
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "owgraph_entity",
            "schema": decodable(prompt.schema),
            "strict": True,
        },
    }
    assert (metrics.calls, metrics.tokens_in, metrics.tokens_out) == (1, 321, 45)
    assert metrics.bytes_egress == size and metrics.bytes_read == len(_view())
    assert io.asked == ["llm"]


def test_more_available_gleans_once_and_the_answers_are_one(tmp_path: Path) -> None:
    """Ruling 3: attempt 2 re-sends the prompt and the first answer, and asks what was missed."""
    first = _answer(_entity("Acme", "d1#4", "Acme pays"), more=True)
    second = _answer(_entity("Gamma", "d1#5", "Gamma guarantees"), more=True)
    handle = _Handle([_reply(first, tokens=(100, 10)), _reply(second, tokens=(150, 20))])
    frames, metrics, _io = _run(tmp_path, handle, _view())
    assert len(handle.requests) == 2, "two attempts and no third, whatever the second says"
    [(_, opening, _), (_, glean, _)] = handle.requests
    assert glean["messages"] == [
        *opening["messages"],
        {"role": "assistant", "content": json.dumps(first)},
        {"role": "user", "content": GLEAN},
    ]
    [view] = read_views(_view())
    both = _answer(*first["entities"], *second["entities"])
    assert frames == answer_frames(view, both)
    assert (metrics.calls, metrics.tokens_in, metrics.tokens_out) == (2, 250, 30)


def test_an_unparsed_first_answer_is_kept_and_not_gleaned(tmp_path: Path) -> None:
    handle = _Handle([_reply("{not json")])
    frames, metrics, _io = _run(tmp_path, handle, _view())
    assert metrics.calls == 1
    assert frames[1]["unparsed"] == "{not json"
    assert frames[2]["t"] == "cover_empty"


def test_an_unparsed_glean_leaves_the_first_answer_standing(tmp_path: Path) -> None:
    first = _answer(_entity("Acme", "d1#4", "Acme pays"), more=True)
    handle = _Handle([_reply(first), _reply("nonsense")])
    frames, _metrics, _io = _run(tmp_path, handle, _view())
    [view] = read_views(_view())
    expected = answer_frames(view, first)
    assert frames[0] == expected[0]
    assert frames[1]["unparsed"] == "nonsense"
    assert frames[2:] == expected[1:]


def test_each_segment_is_its_own_prompt_and_its_own_frames(tmp_path: Path) -> None:
    """Ruling 1: two Segments in one unit, two calls, two `seg` blocks in order."""
    body = _view() + _view("seg:00000000000000ff")
    handle = _Handle([_reply(_answer()), _reply(_answer(_entity("Beta", "d1#4", "Beta")))])
    frames, metrics, _io = _run(tmp_path, handle, body)
    assert [f["seg"] for f in frames if f["t"] == "seg"] == [HEADER["seg"], "seg:00000000000000ff"]
    assert metrics.calls == 2
    assert [f["title"] for f in frames if f["t"] == "entity"] == ["Beta"]


@pytest.mark.parametrize(
    ("body", "handle", "cls"),
    [
        (b'{"t":"segment","seg":"seg:1"}\n', _Handle([]), FailureClass.CORRUPT_INPUT),
        (_view(), _Handle([], cancelled=True), FailureClass.TIMEOUT),
        (_view(), _Handle([b'{"choices":[]}']), FailureClass.EMPTY_RESULT),
    ],
    ids=["free_view", "cancelled", "no_message"],
)
def test_the_failures(tmp_path: Path, body: bytes, handle: _Handle, cls: FailureClass) -> None:
    """Ruling 5, and a body that is not the billed view."""
    with pytest.raises(DriverError) as raised:
        _run(tmp_path, handle, body)
    assert raised.value.cls is cls


def test_the_service_is_configured_by_name(tmp_path: Path) -> None:
    _frames, _metrics, io = _run(tmp_path, _Handle([_reply(_answer())]), _view(), service="gpu1")
    assert io.asked == ["gpu1"]
    with pytest.raises(ValueError, match="takes no temperature"):
        EntityLLM(temperature=1)


def test_the_driver_declares_itself() -> None:
    assert EntityLLM.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert (EntityLLM.PORT, EntityLLM.SCHEMA_VERSION, DRIVER_ID) == (
        "derive/1",
        1,
        "derive.entity.llm",
    )
