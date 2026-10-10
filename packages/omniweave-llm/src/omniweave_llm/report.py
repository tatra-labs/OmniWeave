"""`derive.report.llm`'s view and answer: one community's context, and its report. D731.

06 sections 6.2-6.3 are the specification. A community report is written on first descent, from a
context the host assembles in a fixed order within `REPORT_CONTEXT_TOKENS`. The model answers the
report schema (06:1479): a title, a summary, findings, a rating and its explanation. The host
renders `full_content` from them and stores `findings` as canonical JSON (06:2013).

## Rulings (the ledger's D731)

1. **The view is one community's context as the host renders it**, and it names no identifier
   (INV-8). A `community` header names the community, its level, the members' coverage and the
   witness. Then come the records in 06:2003's three passes: `member` (title, etype,
   description), `edge` (source, relation, target, quote) and `claim` (subject, predicate, object,
   status, start). A level-1 parent is written from its children's summaries (06:2017), as `child`
   records. The model reads the records alone.
2. **The witness is the host's, echoed**, as the merge lane's is (D726 ruling 2).
3. **The report is kept whole, as the model wrote it.** One `report` frame carries the title, the
   summary, the findings, the rating and its explanation, and the host writes `community_report`
   from it. The community's coverage is the host's measurement, not the model's, so it is not in
   the frame.
4. **An answer that does not parse is one malformed `report` frame** with no `title`, the raw text
   kept, which the host refuses into a quarantine row. The community stays unreported, which is
   its state before the call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["LANE", "RECORDS", "CommunityView", "answer_frames", "read_community", "unparsed_frames"]

LANE: Final = "report"
RECORDS: Final = frozenset({"member", "edge", "claim", "child"})
"""Ruling 1: the record kinds a community's context holds."""


@dataclass(frozen=True, slots=True)
class CommunityView:
    """One community: its name, level and coverage, what the host says it read, and the records."""

    community: str
    level: int
    coverage: float
    witness: tuple[Mapping[str, str], ...]
    body: str
    """The record frames as received: the prompt's part 5, which the model reads."""

    @property
    def source(self) -> str:
        """The name the prompt's untrusted block is labelled with."""
        return self.community


def read_community(body: bytes) -> CommunityView:
    """Ruling 1: one unit's community.

    Raises:
        ValueError: a line that is not a JSON object, no `community` header first, no record, or a
            frame that is not one of `RECORDS`.
    """
    lines = [line for line in body.decode("utf-8").splitlines() if line.strip()]
    frames = [json.loads(line) for line in lines]
    if not frames or not all(isinstance(f, dict) for f in frames):
        msg = "a community is JSON object lines"
        raise ValueError(msg)
    header, records = frames[0], frames[1:]
    if header.get("t") != "community":
        msg = "a community opens with its community header"
        raise ValueError(msg)
    if not records or any(r.get("t") not in RECORDS for r in records):
        msg = f"a community holds one or more records, each one of {sorted(RECORDS)}"
        raise ValueError(msg)
    return CommunityView(
        community=str(header["community"]),
        level=int(header.get("level", 0)),
        coverage=float(header.get("coverage", 1.0)),
        witness=tuple(dict(w) for w in header.get("witness", ())),
        body="\n".join(lines[1:]),
    )


def unparsed_frames(view: CommunityView, raw: str, problems: list[str]) -> list[dict[str, Any]]:
    """Ruling 4: the raw answer kept in one malformed report, and no report written."""
    return [
        {"t": "community", "community": view.community},
        {"t": "report", "unparsed": raw, "problems": problems[:20]},
    ]


def answer_frames(view: CommunityView, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Ruling 3: the community's report, whole."""
    return [
        {"t": "community", "community": view.community},
        {
            "t": "report",
            "title": str(answer["title"]),
            "summary": str(answer["summary"]),
            "findings": [
                {"summary": str(f["summary"]), "explanation": str(f["explanation"])}
                for f in answer["findings"]
            ],
            "rating": float(answer["rating"]),
            "rating_explanation": str(answer["rating_explanation"]),
        },
    ]
