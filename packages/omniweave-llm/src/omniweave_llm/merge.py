"""`derive.merge.llm`'s view and answer: a batch of entity pairs, decided by position. D726.

06:1460-1478 is the specification. The resolution funnel leaves a pair scoring in `[75, 92)`
undecided (06 section 5.1, stage [8]), and this lane asks a model whether its two sides name one
thing. The host renders up to `LLM_BATCH = 30` pairs as one unit, and the model answers each by its
position in the list it was handed. The host turns a `same` decision into an `llm_band` merge.

## Rulings (the ledger's D726)

1. **The view is a numbered pair list, and it names no identifier** (GR11, 06:1461). A `pairs`
   header names the batch and its size; then one `pair` frame per position, each side a surface,
   an entity type and the other names it is known by. No key, no cite and no id reaches the model,
   so a decision can only be taken on what the documents wrote.
2. **The witness set is the host's, echoed.** A corpus-granularity billed driver must emit one
   (04:731-737). The sides are rendered from the entities' live mentions, whose documents only the
   host can name, so the header carries `witness` and the driver writes it out unchanged.
3. **A decision is kept by its position.** Each frame is the pair's number, `same` and the reason.
4. **A position the host did not send, or one answered twice, is a malformed decision**: its item
   kept verbatim in a `decision` frame with no `same`, which the host quarantines as
   `OW_GRAPH_UNPARSED_ITEM` (06:1476). Both answers to a twice-answered position are malformed, so
   neither stands: a model that said `same` and `not same` of one pair has not decided it.
5. **A pair the model left out has no frame**, and is not merged: 06:1477's safe default.
6. **An answer that does not parse is one malformed frame for the batch**, and no pair is decided.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["LANE", "LLM_BATCH", "PairsView", "answer_frames", "read_pairs", "unparsed_frames"]

LANE: Final = "merge"
LLM_BATCH: Final = 30
"""06:1460: at most thirty pairs to one call, as the schema's `maxItems` and `maximum` bound."""


@dataclass(frozen=True, slots=True)
class PairsView:
    """One batch: its name, its size, what the host says it read, and the pair lines."""

    batch: str
    n: int
    witness: tuple[Mapping[str, str], ...]
    body: str
    """The `pair` frames as received: the prompt's part 5, which the model reads."""

    @property
    def source(self) -> str:
        """The name the prompt's untrusted block is labelled with (D731, `DecisionPass`)."""
        return self.batch


def read_pairs(body: bytes) -> PairsView:
    """Ruling 1: one unit's batch.

    Raises:
        ValueError: a line that is not a JSON object, no `pairs` header first, a size outside
            `[1, LLM_BATCH]`, or `pair` frames that are not numbered 0 to n-1 in order.
    """
    lines = [line for line in body.decode("utf-8").splitlines() if line.strip()]
    frames = [json.loads(line) for line in lines]
    if not frames or not all(isinstance(f, dict) for f in frames):
        msg = "a batch is JSON object lines"
        raise ValueError(msg)
    header, pairs = frames[0], frames[1:]
    if header.get("t") != "pairs":
        msg = "a batch opens with its pairs header"
        raise ValueError(msg)
    n = int(header.get("n", -1))
    if not 1 <= n <= LLM_BATCH or [p.get("pair") for p in pairs] != list(range(n)):
        msg = f"a batch holds 1 to {LLM_BATCH} pairs, numbered 0 to n-1 in order"
        raise ValueError(msg)
    return PairsView(
        batch=str(header["batch"]),
        n=n,
        witness=tuple(dict(w) for w in header.get("witness", ())),
        body="\n".join(lines[1:]),
    )


def unparsed_frames(view: PairsView, raw: str, problems: list[str]) -> list[dict[str, Any]]:
    """Ruling 6: the raw answer kept in one malformed decision, and no pair decided."""
    return [
        {"t": "batch", "batch": view.batch},
        {"t": "decision", "unparsed": raw, "problems": problems[:20]},
    ]


def answer_frames(view: PairsView, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rulings 3-5: one batch's decisions as frames, `batch` first, in the order answered."""
    decisions = list(answer.get("decisions", ()))
    seen: dict[int, int] = {}
    for item in decisions:
        seen[int(item["pair"])] = seen.get(int(item["pair"]), 0) + 1
    frames: list[dict[str, Any]] = [{"t": "batch", "batch": view.batch}]
    for item in decisions:
        pair = int(item["pair"])
        if pair >= view.n:
            problem = f"pair {pair} was not sent: the batch holds {view.n}"
        elif seen[pair] > 1:
            problem = f"pair {pair} was answered {seen[pair]} times"
        else:
            frames.append(
                {"t": "decision", "pair": pair, "same": bool(item["same"]),
                 "reason": str(item["reason"])}
            )  # fmt: skip
            continue
        frames.append(
            {"t": "decision", "pair": pair, "unparsed": json.dumps(item, ensure_ascii=False),
             "problems": [problem]}
        )  # fmt: skip
    return frames
