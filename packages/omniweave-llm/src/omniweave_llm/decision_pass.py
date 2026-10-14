"""A billed decision lane's Pass: one prompt a unit, no glean, its witness echoed. D731.

D726 wrote this as `derive.merge.llm`'s driver. D731 lifts it here, so `derive.report.llm` is the
same Pass over another view and translation, as D722 lifted `LanePass` for the extraction lanes. The
two decision lanes (`merge`, `report`) render no vocabulary (D708 ruling 2), and their schemas carry
no `more_available`, so a unit is one call.

A lane's driver names its id, its lane and the frame that opens a unit's answer, and supplies
`_read`, `_frames` and `_unparsed`.

## Rulings (the ledger's D726, carried)

1. **One call a unit, and no glean.** There is nothing a second attempt could ask for.
2. **The call is the extraction lanes' call** (`lane_pass.chat`, D711 ruling 2) under the schema
   name `owgraph_<lane>`, and its Spend is reported the same way.
3. **Two artefacts.** `graph_items` holds the frames, and `witness_set` the host's witness echoed
   one JSON line per tuple, since a billed corpus-granularity card declares both (04:2519).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar, Final, Protocol

from omniweave_ports import (
    ArtifactRef,
    DriverError,
    DriverMetrics,
    DriverResult,
    FailureClass,
    ProbeStatus,
    ProbeVerdict,
)

from omniweave_llm.entity import parse_answer
from omniweave_llm.lane_pass import Tally, chat
from omniweave_llm.prompt import render

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DecisionPass", "DecisionView"]

_HEAD_WINDOW: Final = 4096


class DecisionView(Protocol):
    """What a decision lane's reader returns: the unit's name, the host's witness, the body."""

    @property
    def source(self) -> str: ...

    @property
    def witness(self) -> tuple[Mapping[str, str], ...]: ...

    @property
    def body(self) -> str: ...


class DecisionPass:
    """A billed decision lane through a model. Rulings 1-3."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1
    DRIVER_ID: ClassVar[str]
    LANE: ClassVar[str]
    HEAD: ClassVar[bytes]
    """The frame an answer opens with, as `is_valid_nonempty` looks for it."""

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """The model is the service's to reach; the driver itself is the standard library."""
        del env
        return ProbeVerdict(status=ProbeStatus.OK, detail="reaches its model through io.service()")

    def __init__(self, *, service: Scalar = "llm", **config: Scalar) -> None:
        """`service` names the `[services.<name>]` table the model is behind."""
        if config:
            raise ValueError(f"{self.DRIVER_ID} takes no {', '.join(sorted(config))}")
        self.service = str(service)

    def _read(self, raw: bytes) -> DecisionView:
        """The lane's reader. Raises `ValueError`, `KeyError` or `TypeError` on a body that is not
        its view."""
        raise NotImplementedError

    def _frames(self, view: Any, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
        """The lane's translation of a parsed answer."""
        raise NotImplementedError

    def _unparsed(self, view: Any, raw: str, problems: list[str]) -> list[dict[str, Any]]:
        """The lane's malformed frame for an answer that did not parse."""
        raise NotImplementedError

    def derive(self, scope: DeriveScope, io: DriverIO) -> DriverResult:
        """Rulings 1-3: each unit one call, its answer the lane's frames.

        Raises:
            DriverError: `CORRUPT_INPUT` for a body that is not the lane's view, `TIMEOUT` when
                cancelled, `EMPTY_RESULT` for a reply envelope with no message.
        """
        handle = io.service(self.service)
        frames: list[dict[str, Any]] = []
        witness: list[Mapping[str, str]] = []
        spend = Tally()
        read = 0
        for done, unit in enumerate(scope.units):
            with io.blobs.open(unit.content_sha256) as blob:
                raw = blob.read()
            read += len(raw)
            try:
                view = self._read(raw)
            except (ValueError, KeyError, TypeError) as error:
                raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=str(error)) from error
            prompt = render(self.LANE, body=view.body, source=view.source)
            text = chat(
                handle, io, [{"role": "user", "content": prompt.text}], prompt.schema, spend,
                name=f"owgraph_{self.LANE}",
            )  # fmt: skip
            answer, problems = parse_answer(text, prompt.schema)
            frames += (
                self._unparsed(view, text, problems)
                if answer is None
                else self._frames(view, answer)
            )
            witness += view.witness
            io.progress(done + 1, len(scope.units))
        return DriverResult(
            outcome="ok",
            produced=(
                ArtifactRef.of("graph_items", _lines(frames), io),
                ArtifactRef.of("witness_set", _lines(witness), io),
            ),
            metrics=DriverMetrics(
                tokens_in=spend.tokens_in,
                tokens_out=spend.tokens_out,
                calls=spend.calls,
                bytes_egress=spend.egress,
                bytes_read=read,
            ),
        )

    def is_valid_nonempty(self, ref: ArtifactRef) -> bool:
        """At least one unit answered, even if only with a malformed frame."""
        return self.HEAD in ref.head(_HEAD_WINDOW)


def _lines(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return "".join(
        json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in rows
    ).encode("utf-8")
