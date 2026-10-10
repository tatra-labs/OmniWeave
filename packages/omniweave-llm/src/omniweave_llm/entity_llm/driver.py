"""`derive.entity.llm`: one billed prompt per Segment, and one glean when the model says so. D711.

06 section 4 is the specification; `omniweave_llm.prompt` builds what is sent (D708),
`omniweave_llm.view` reads what the host renders (D709), and `omniweave_llm.entity` turns the answer
into the frames the host's sink judges (D710). This module is the call between them.

## Rulings (the ledger's D711)

1. **One prompt per Segment** (06:1513-1518). A unit's body may hold several Segments' views; each
   is its own call, its own answer and its own `seg` block of frames.
2. **The call is an OpenAI-shaped chat completion through `io.service(service)`**, as
   `parse.page.olmocr` makes its own (`omniweave_vision.driver`): `model` is the handle's
   `model_id`, `temperature` 0, and `response_format` the lane's JSON Schema, `strict`, so a server
   with constrained decoding enforces 06:1491-1500's rules before the validator re-checks them. No
   repetition penalty is sent, and 06:1497's `1.0` is every server's default.
3. **The glean is `attempt = 2`, serial, and fires only on `more_available`** (06:1529-1536). It
   re-sends the first prompt and the first answer, then asks only for what was missed, so its
   prompt is bounded. Its items are appended to the first answer's, and one set of frames is
   written over both. A glean that does not parse leaves the first answer standing and its own
   text kept in one malformed frame.
4. **Spend is reported as the provider reported it**: `calls`, and `tokens_in`/`tokens_out` from
   `usage.prompt_tokens`/`completion_tokens`, summed over both attempts. `bytes_egress` is the
   request bodies' bytes, because a hosted model is egress (05's `Spend`).
5. **A cancellation between calls is `TIMEOUT`**, as every Pass reports it, and a reply whose
   envelope carries no message is `EMPTY_RESULT`: the provider answered and said nothing.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, Final

from omniweave_ports import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    ProbeStatus,
    ProbeVerdict,
)

from omniweave_llm.entity import LANE, answer_frames, parse_answer, unparsed_frames
from omniweave_llm.prompt import render
from omniweave_llm.view import read_views

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar, ServiceHandle

    from omniweave_llm.view import SegmentView

__all__ = ["CHAT_PATH", "DRIVER_ID", "GLEAN", "MAX_ATTEMPTS", "EntityLLM"]

DRIVER_ID: Final = "derive.entity.llm"
CHAT_PATH: Final = "/v1/chat/completions"
MAX_ATTEMPTS: Final = 2
"""06:1530: `max_attempts = 2`, the first call and one glean."""
GLEAN: Final = (
    "Return only the items your answer above missed, in the same JSON shape. Do not repeat an "
    "item you already returned. Set more_available to false."
)
"""The second attempt's request, after the first prompt and the first answer (ruling 3)."""
_HEAD_WINDOW: Final = 4096


class EntityLLM:
    """The billed `entity` lane: entities and relations, grounded by quote, through a model."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """The model is the service's to reach; the driver itself is the standard library."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="reaches its model through io.service()")

    def __init__(self, *, service: Scalar = "llm", **config: Scalar) -> None:
        """`service` names the `[services.<name>]` table the model is behind."""
        if config:
            raise ValueError(f"{DRIVER_ID} takes no {', '.join(sorted(config))}")
        self.service = str(service)

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """Rulings 1-5: each Segment of each unit prompted, its answer translated into frames.

        Raises:
            DriverError: `CORRUPT_INPUT` for a body that is not the billed view, `TIMEOUT` when
                cancelled, `EMPTY_RESULT` for a reply envelope with no message.
        """
        handle = io.service(self.service)
        frames: list[dict[str, Any]] = []
        spend = _Spend()
        read = 0
        for done, unit in enumerate(scope.units):
            with io.blobs.open(unit.content_sha256) as blob:
                raw = blob.read()
            read += len(raw)
            try:
                views = read_views(raw)
            except ValueError as error:
                raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=str(error)) from error
            for view in views:
                frames += _segment(view, handle, io, spend)
            io.progress(done + 1, len(scope.units))
        payload = "".join(
            json.dumps(f, separators=(",", ":"), ensure_ascii=False) + "\n" for f in frames
        ).encode("utf-8")
        return DriverResult(
            outcome="ok",
            produced=(ArtifactRef.of("graph_items", payload, io),),
            metrics=DriverMetrics(
                tokens_in=spend.tokens_in,
                tokens_out=spend.tokens_out,
                calls=spend.calls,
                bytes_egress=spend.egress,
                bytes_read=read,
            ),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """At least one Segment answered, even if only with a `cover_empty`."""
        return b'"t":"seg"' in ref.head(_HEAD_WINDOW)


class _Spend:
    def __init__(self) -> None:
        self.calls = self.tokens_in = self.tokens_out = self.egress = 0


def _segment(
    view: SegmentView, handle: ServiceHandle, io: DriverIO, spend: _Spend
) -> list[dict[str, Any]]:
    """Ruling 3: the first answer, and the glean it asks for, as one Segment's frames."""
    prompt = render(
        LANE, body=view.body, source=view.seg, etypes=view.etypes, relations=view.relations
    )
    messages: list[dict[str, str]] = [{"role": "user", "content": prompt.text}]
    first_text = _call(handle, io, messages, prompt.schema, spend)
    first, problems = parse_answer(first_text, prompt.schema)
    if first is None:
        return unparsed_frames(view, first_text, problems)
    if not first.get("more_available"):
        return answer_frames(view, first)
    messages += [
        {"role": "assistant", "content": first_text},
        {"role": "user", "content": GLEAN},
    ]
    second_text = _call(handle, io, messages, prompt.schema, spend)
    second, problems = parse_answer(second_text, prompt.schema)
    if second is None:
        frames = answer_frames(view, first)
        return [frames[0], *unparsed_frames(view, second_text, problems)[1:2], *frames[1:]]
    both = {
        "entities": [*first.get("entities", ()), *second.get("entities", ())],
        "relations": [*first.get("relations", ()), *second.get("relations", ())],
        "more_available": False,
    }
    return answer_frames(view, both)


def _call(
    handle: ServiceHandle,
    io: DriverIO,
    messages: list[dict[str, str]],
    schema: Mapping[str, Any],
    spend: _Spend,
) -> str:
    """Ruling 2: one chat completion; ruling 4: its Spend; ruling 5: its failures."""
    if io.cancelled() or handle.cancelled():
        raise DriverError(
            cls=FailureClass.TIMEOUT, message="cancelled before the call", retry_after_ms=0
        )
    body = json.dumps(
        {
            "model": handle.model_id,
            "messages": messages,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "owgraph_entity", "schema": schema, "strict": True},
            },
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    spend.calls += 1
    spend.egress += len(body)
    reply = json.loads(handle.post(CHAT_PATH, body))
    usage = reply.get("usage") or {}
    spend.tokens_in += int(usage.get("prompt_tokens") or 0)
    spend.tokens_out += int(usage.get("completion_tokens") or 0)
    try:
        return str(reply["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as error:
        raise DriverError(
            cls=FailureClass.EMPTY_RESULT, message="the chat completion carried no message"
        ) from error
