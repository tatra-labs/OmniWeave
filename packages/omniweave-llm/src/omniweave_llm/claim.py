"""`derive.claim.llm`'s answer, as the `owgraph-items/1` frames the host writes. D721.

The model answers 06:1430-1460's schema: claims, each a subject, a type, a predicate, an object, a
status, an optional time and a cite with its quote. A claim's subject is an entity, and so is its
object when the model says so. The sink binds an entity frame to the entity its key already names
(06:628-634), so a claim lands on the subject `derive.entity.*` extracted. The host grounds every
quote, and refuses dangling cites and covered ground by itself (06 section 1.7). As in D710, this
module translates and does not judge.

## Rulings (the ledger's D721)

1. **An answer that does not parse, or does not match the schema, is one malformed `claim` frame**
   with the raw text, and a `cover_empty` saying why (D710 ruling 1, on this lane).
2. **A claim's subject is an entity frame, one per distinct `(subject, subject_etype)`.** A null
   type is `unknown`. Scope is the type's (D710 ruling 4). The frame carries no mention: the
   claim's own `observed` is its grounding, and a subject named in passing is not a mention of it.
3. **A claim has exactly one object** (D722, correcting D721). The sink's `claim` is bipartite:
   `object_entity` XOR `object_literal` (06:212). D721 sent a null object as neither, and the sink
   refused it, which only a real ingest showed:
   - an object is an entity only when `object_is_entity` says so and the object is named; it is
     then an entity frame of type `unknown`;
   - every other named object is a literal, typed by 06:1457's *"same closed rules as §3.6"*
     (`datatype`), with the predicate in the header's place;
   - a null object says the predicate holds of the subject, so it is the literal `true`, typed
     `xsd:boolean`, 06:1172's checkbox datatype.
4. **The time's precision is the sink's to derive** (06:1455, *"rather than asked for"*). D722
   sends `t_start` and `t_end` as given and no `t_precision`.
5. **A null description is the empty string.** `ClaimDraft.description` is not optional.
6. **Trust is claimed `extracted`**, for the runner's clamp to lower (D710 ruling 5).
7. **Cover is the uncovered members the claims cite**, or `cover_empty` with a reason (GR3).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Any, Final

from omniweave_llm.entity import TRUST_CLAIM, parse_answer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_llm.view import SegmentView

__all__ = ["HOLDS", "LANE", "answer_frames", "datatype", "parse_answer", "unparsed_frames"]

LANE: Final = "claim"
HOLDS: Final = ("true", "xsd:boolean")
"""Ruling 3: a claim with no object says its predicate holds of its subject."""
_NO_ITEMS: Final = "the model returned no claim on uncovered ground"
_UNPARSED: Final = "the model's answer did not parse against the lane's schema"

# --- 06 section 3.6's closed rules, restated (ruling 3). `omniweave_graph.table.rules.datatype`
# --- is the other copy: a Pass imports `omniweave_ports` alone, so neither can import the other,
# --- and `test_claim_datatype.py` holds the two to one answer over every rule.
_NUMERIC_WORDS: Final = frozenset(
    {
        "amount", "total", "quantity", "qty", "count", "number", "price", "rate", "value",
        "percent", "percentage", "balance", "units", "sum", "fee", "fees", "cost",
    }
)  # fmt: skip
_CURRENCY_CODES: Final = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "CNY", "HKD", "SGD", "INR",
        "SEK", "NOK", "DKK", "ZAR", "BRL", "MXN", "KRW",
    }
)  # fmt: skip
_CURRENCY_SIGNS: Final = {"\u20ac": "EUR", "\u00a3": "GBP"}
_MONTHS: Final = (
    "january|february|march|april|may|june|july|august|september|october|november|december"
)
_ISO_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_DAY_MONTH_YEAR: Final = re.compile(rf"\d{{1,2}} (?:{_MONTHS}) \d{{4}}\Z", re.IGNORECASE)
_MONTH_DAY_YEAR: Final = re.compile(rf"(?:{_MONTHS}) \d{{1,2}}, \d{{4}}\Z", re.IGNORECASE)
_NUMBER: Final = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\Z")
_CODE_TOKEN: Final = re.compile(r"\b[A-Z]{3}\b")
_WORD: Final = re.compile(r"[^\W\d_]+")


def datatype(literal: str, header: str) -> str:
    """06 section 3.6: `xsd:date`, `money:<ISO4217>`, `xsd:decimal`, else `string`.

    Closed and conservative: a guess is `string` (06:1165). `header` is what names the value. For a
    table it is the column's header; for a claim it is the predicate.
    """
    if _is_date(literal):
        return "xsd:date"
    if any(ch.isdigit() for ch in literal):
        code = _currency(literal) or _currency(header)
        if code is not None:
            return f"money:{code}"
    if _NUMBER.match(literal) and _NUMERIC_WORDS & set(_WORD.findall(header.casefold())):
        return "xsd:decimal"
    return "string"


def _is_date(text: str) -> bool:
    if _ISO_DATE.match(text):
        try:
            dt.date.fromisoformat(text)
        except ValueError:
            return False
        return True
    return bool(_DAY_MONTH_YEAR.match(text) or _MONTH_DAY_YEAR.match(text))


def _currency(text: str) -> str | None:
    for code in _CODE_TOKEN.findall(text):
        if code in _CURRENCY_CODES:
            return code
    return next((code for sign, code in _CURRENCY_SIGNS.items() if sign in text), None)


def unparsed_frames(view: SegmentView, raw: str, problems: list[str]) -> list[dict[str, Any]]:
    """Ruling 1: the raw answer kept in one malformed frame, and a cover_empty saying why."""
    return [
        {"t": "seg", "seg": view.seg},
        {"t": "claim", "unparsed": raw, "problems": problems[:20]},
        {"t": "cover_empty", "lane": LANE, "reason": _UNPARSED},
    ]


def answer_frames(view: SegmentView, answer: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rulings 2-7: one Segment's answer as `owgraph-items/1` frames, `seg` first."""
    frames: list[dict[str, Any]] = [{"t": "seg", "seg": view.seg}]
    tmps: dict[tuple[str, str], str] = {}
    cited: set[str] = set()

    def entity(name: str, etype: str) -> str:
        group = (name.casefold(), etype)
        if group not in tmps:
            tmps[group] = f"t{len(tmps) + 1}"
            frames.append(
                {
                    "t": "entity",
                    "tmp": tmps[group],
                    "key": name,
                    "etype": etype,
                    "title": name,
                    "scope": "document" if etype in view.document_scoped else "corpus",
                    "trust": TRUST_CLAIM,
                }
            )
        return tmps[group]

    for item in answer.get("claims", ()):
        subject = entity(item["subject"], item.get("subject_etype") or "unknown")
        claim: dict[str, Any] = {
            "t": "claim",
            "subject": subject,
            "claim_type": item["claim_type"],
            "predicate": item["predicate"],
            "description": item.get("description") or "",
            "status": item["status"],
            "observed": {"cite": item["cite"], "quote": item["quote"]},
            "trust": TRUST_CLAIM,
        }
        obj = item.get("object")
        if obj is not None and item.get("object_is_entity"):
            claim["object_entity"] = entity(obj, "unknown")
        elif obj is not None:
            claim |= {"object_literal": obj, "object_datatype": datatype(obj, item["predicate"])}
        else:
            claim |= {"object_literal": HOLDS[0], "object_datatype": HOLDS[1]}
        for key in ("t_start", "t_end"):
            if item.get(key) is not None:
                claim[key] = item[key]
        frames.append(claim)
        cited.add(item["cite"])
    claimed = sorted(b.cite for b in view.blocks if b.cite in cited and not b.covered)
    frames.append(
        {"t": "cover", "lane": LANE, "cites": claimed}
        if claimed
        else {"t": "cover_empty", "lane": LANE, "reason": _NO_ITEMS}
    )
    return frames
