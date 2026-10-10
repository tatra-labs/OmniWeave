"""`derive.merge.llm`: the resolution funnel's `[75, 92)` band, decided by a model. D726.

06 section 5.1's stage [8], over `omniweave_llm.merge`'s view and answer. 06:842 places it at
rank 2, phase 30, `corpus` granularity: a batch's pairs come from entities across the corpus.

## Rulings (the ledger's D726)

7. **One call per batch, and no glean.** The merge schema carries no `more_available`, and a pair
   left out is simply not merged (merge ruling 5), so there is nothing a second attempt could ask
   for.
8. **The call is the extraction lanes' call** (`lane_pass.chat`, D711 ruling 2) under the schema
   name `owgraph_merge`, and its Spend is reported the same way.
9. **Two artefacts.** `graph_items` holds the decision frames, and `witness_set` the host's witness
   echoed one JSON line per tuple, as the card declares both (04:2519).
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

from omniweave_llm.entity import parse_answer
from omniweave_llm.lane_pass import Tally, chat
from omniweave_llm.merge import LANE, answer_frames, read_pairs, unparsed_frames
from omniweave_llm.prompt import render

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from omniweave_ports.types import DeriveScope, DriverIO, ProbeEnv, Scalar

__all__ = ["DRIVER_ID", "MergeLLM"]

DRIVER_ID: Final = "derive.merge.llm"
_HEAD_WINDOW: Final = 4096


class MergeLLM:
    """The billed `merge` lane: entity pairs in the ambiguous band, decided by position."""

    PORT: ClassVar[str] = "derive/1"
    SCHEMA_VERSION: ClassVar[int] = 1
    DRIVER_ID: ClassVar[str] = DRIVER_ID

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
        """Rulings 7-9: each batch one call, its answer decision frames.

        Raises:
            DriverError: `CORRUPT_INPUT` for a body that is not a batch, `TIMEOUT` when cancelled,
                `EMPTY_RESULT` for a reply envelope with no message.
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
                view = read_pairs(raw)
            except (ValueError, KeyError, TypeError) as error:
                raise DriverError(cls=FailureClass.CORRUPT_INPUT, message=str(error)) from error
            prompt = render(LANE, body=view.body, source=view.batch)
            text = chat(
                handle, io, [{"role": "user", "content": prompt.text}], prompt.schema, spend,
                name=f"owgraph_{LANE}",
            )  # fmt: skip
            answer, problems = parse_answer(text, prompt.schema)
            frames += (
                unparsed_frames(view, text, problems)
                if answer is None
                else answer_frames(view, answer)
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
        """At least one batch answered, even if only with a malformed decision."""
        return b'"t":"batch"' in ref.head(_HEAD_WINDOW)


def _lines(rows: Iterable[Mapping[str, Any]]) -> bytes:
    return "".join(
        json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in rows
    ).encode("utf-8")
