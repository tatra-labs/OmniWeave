"""The `OWC1` marker: element-addressed feedback that lives in the IL source. **D745.**

09-generation.md section 8 (the grammar, the two-factor anchor, apply-and-clear) and section 14.3
(a corrupt payload); charter OUT16 to OUT19. A marker is an XML or HTML comment carrying `el`,
`nsig`, an id, a timestamp and a base64url JSON payload. **Presence is the state**: present is
pending, absent is resolved, and present after a claimed application is a failure signal. There is
no side table, so the tracker and the artefact cannot disagree.

## Rulings (the ledger's D745)

1. **The payload is canonical JSON**, sorted keys and no whitespace, base64url without padding,
   with one U+0020 between every two adjacent `-` (09 section 8.1). The reader strips every space,
   re-pads and decodes; `decode(encode(x)) == x` and `"--" not in encode(x)` for every payload.
   Past `MAX_MARKER_PAYLOAD_BYTES` the payload is refused as a `ResourceLimit`, before encoding.
2. **A payload holds `note`, `sev` and `by`, and may hold `hint` and `prev`.** `sev` is `must`,
   `should` or `ask`, and `by` is `human` or `agent` (09's example). Anything else is a corrupt
   payload, not a different marker.
3. **`scan()` never throws.** It reads lines, so a work-in-progress file mid-keystroke still scans.
   A marker is a `MARKER_RE` match between the carrier's comment delimiters on one line; a payload
   that does not decode is `state = "corrupt"`, reported, never fatal (09 section 8.1).
4. **The id is minted from the marker's own content**: `k-` and the first 8 hex of
   `blake2b(el, nsig, ts, payload)`. No randomness, so a placement replayed mints the same id.
5. **Resolution is 09's table, in order**: no element is `OW_TARGET_MARKER_ORPHAN`, two elements
   are `OW_TARGET_EL_DUPLICATE`, a moved `nsig` is `OW_TARGET_MARKER_STALE`, and one element with
   its `nsig` is resolved. `MARKER_AMBIGUOUS` is the text-node half, which placement owns.
6. **`apply_reverse()` is one splice batch**: each resolved marker's edits and the deletion of its
   whole line, through the carrier's transactional `splice()` (OUT17). An unresolved marker is
   refused before anything is applied; a marker left out of the batch stays, because skip is legal.
7. **`assert_clean(bundle)` scans every unit's text, unparsed**, as 09 prints it, and raises
   `OW_TARGET_MARKER_UNRESOLVED` naming each unit and marker id, corrupt ones included: a marker
   nobody can read may be a `must`. Scanning is line-based, so no carrier is needed; both release-1
   carriers' delimiters are `<!--` and `-->`, the defaults.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from omniweave_core.errors import ResourceLimit, TargetError
from omniweave_core.limits import MAX_MARKER_PAYLOAD_BYTES, MAX_MARKERS_PER_UNIT
from omniweave_core.out.carrier import CarrierDoc, CarrierNode, ParseError, Splice
from omniweave_core.out.job import ILBundle

__all__ = [
    "MARKER_RE",
    "Marker",
    "MarkerEdit",
    "Payload",
    "Resolution",
    "apply_reverse",
    "assert_clean",
    "decode_payload",
    "encode_payload",
    "format_marker",
    "marker_id",
    "over_budget",
    "resolve",
    "scan",
    "scan_text",
]

MARKER_RE: Final = re.compile(
    r"OWC1:v1"
    r"\s+el=(?P<el>u\d{2,}/e\d{1,6})"
    r"\s+nsig=(?P<nsig>[0-9a-f]{8})"
    r"\s+id=(?P<id>k-[0-9a-f]{8})"
    r"\s+ts=(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)"
    r"\s+p=(?P<p>[A-Za-z0-9_ -]{0,11000})"
)
"""09 section 8.1, verbatim."""

_SEVERITIES: Final = frozenset({"must", "should", "ask"})
_AUTHORS: Final = frozenset({"human", "agent"})
_KEYS: Final = frozenset({"note", "sev", "by", "hint", "prev"})


@dataclass(frozen=True, slots=True)
class Payload:
    """Ruling 2: what a human or an agent wrote, and the placer's hints."""

    note: str
    sev: Literal["must", "should", "ask"]
    by: Literal["human", "agent"]
    hint: str | None = None
    prev: str | None = None

    def __post_init__(self) -> None:
        if self.sev not in _SEVERITIES:
            raise ValueError(f"sev {self.sev!r} is must, should or ask")
        if self.by not in _AUTHORS:
            raise ValueError(f"by {self.by!r} is human or agent")

    def as_json(self) -> dict[str, str]:
        doc = {"note": self.note, "sev": self.sev, "by": self.by}
        if self.hint is not None:
            doc["hint"] = self.hint
        if self.prev is not None:
            doc["prev"] = self.prev
        return doc


def encode_payload(payload: Payload) -> str:
    """Ruling 1: canonical JSON, base64url unpadded, a space between adjacent `-`."""
    raw = json.dumps(
        payload.as_json(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if len(raw) > MAX_MARKER_PAYLOAD_BYTES:
        raise ResourceLimit(
            f"a marker payload of {len(raw)} bytes is above MAX_MARKER_PAYLOAD_BYTES "
            f"({MAX_MARKER_PAYLOAD_BYTES})",
            limit="MAX_MARKER_PAYLOAD_BYTES",
            fix="shorten the note: one note, not a document",
        )
    text = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    while "--" in text:
        text = text.replace("--", "- -")
    return text


def decode_payload(text: str) -> Payload:
    """Ruling 1's inverse. Raises `ValueError` on anything that is not a payload."""
    compact = text.replace(" ", "")
    try:
        raw = base64.urlsafe_b64decode(compact + "=" * (-len(compact) % 4))
        doc = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not a payload: {exc}") from None
    if not isinstance(doc, dict) or not {"note", "sev", "by"} <= set(doc) or set(doc) - _KEYS:
        raise ValueError(
            f"payload keys {sorted(doc) if isinstance(doc, dict) else doc!r} are not 09's"
        )
    if not all(isinstance(v, str) for v in doc.values()):
        raise ValueError("payload values are strings")
    return Payload(**doc)


def marker_id(el: str, nsig: str, ts: str, payload: Payload) -> str:
    """Ruling 4: `k-` and 8 hex of the marker's own content."""
    body = json.dumps([el, nsig, ts, payload.as_json()], sort_keys=True, separators=(",", ":"))
    return "k-" + hashlib.blake2b(body.encode("utf-8"), digest_size=4).hexdigest()


def format_marker(doc: CarrierDoc, el: str, nsig: str, ts: str, payload: Payload) -> str:
    """One marker, between the carrier's own comment delimiters (09 section 8.1)."""
    text = (
        f"{doc.comment_open} OWC1:v1 el={el} nsig={nsig} id={marker_id(el, nsig, ts, payload)} "
        f"ts={ts} p={encode_payload(payload)} {doc.comment_close}"
    )
    if MARKER_RE.search(text) is None:
        raise ValueError(f"el {el!r}, nsig {nsig!r} or ts {ts!r} is outside the OWC1 grammar")
    return text


@dataclass(frozen=True, slots=True)
class Marker:
    """One scanned marker. Its location is its position: there is nothing to go stale."""

    el: str
    nsig: str
    id: str
    ts: str
    payload: Payload | None
    state: Literal["pending", "corrupt"]
    line: int
    start: int
    """The byte offset of the marker's line in `source().encode("utf-8")`."""
    end: int
    """One past the line's `\\n`, or the end of the source: the whole line, for removal."""

    def as_json(self) -> dict[str, str]:
        """`OutReport.markers`' row (09 section 4.2)."""
        return {"el": self.el, "id": self.id, "state": self.state}


def scan(doc: CarrierDoc) -> tuple[Marker, ...]:
    """Ruling 3: line-based, tolerant, never throws."""
    return scan_text(doc.source(), doc.comment_open, doc.comment_close)


def scan_text(
    source: str, comment_open: str = "<!--", comment_close: str = "-->"
) -> tuple[Marker, ...]:
    """`scan()` over a text, for a unit no carrier has parsed."""
    out: list[Marker] = []
    offset = 0
    data = source.encode("utf-8")
    for number, line in enumerate(data.split(b"\n"), start=1):
        start, offset = offset, offset + len(line) + 1
        text = line.decode("utf-8", "replace")
        opened = text.find(comment_open)
        if opened < 0:
            continue
        closed = text.find(comment_close, opened + len(comment_open))
        if closed < 0:
            continue
        m = MARKER_RE.search(text, opened + len(comment_open), closed)
        if m is None:
            continue
        try:
            payload: Payload | None = decode_payload(m["p"].rstrip())
            state: Literal["pending", "corrupt"] = "pending"
        except ValueError:
            payload, state = None, "corrupt"
        end = min(offset, len(data))
        out.append(Marker(m["el"], m["nsig"], m["id"], m["ts"], payload, state, number, start, end))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Resolution:
    """Ruling 5: the element a marker resolves to, or the code that refuses it."""

    marker: Marker
    node: CarrierNode | None
    code: str | None
    """`None` iff resolved."""


def resolve(doc: CarrierDoc, marker: Marker) -> Resolution:
    """`el` proposes, `nsig` disposes, uniqueness arbitrates (OUT18)."""
    nodes = [n for n in doc.select("@data-ow-el") if n.el == marker.el]
    if not nodes:
        return Resolution(marker, None, "OW_TARGET_MARKER_ORPHAN")
    if len(nodes) > 1:
        return Resolution(marker, None, "OW_TARGET_EL_DUPLICATE")
    if nodes[0].nsig != marker.nsig:
        return Resolution(marker, nodes[0], "OW_TARGET_MARKER_STALE")
    return Resolution(marker, nodes[0], None)


@dataclass(frozen=True, slots=True)
class MarkerEdit:
    """One marker an applier resolved, and the splices that resolve it."""

    marker: Marker
    splices: tuple[Splice, ...] = field(default_factory=tuple)


def apply_reverse(doc: CarrierDoc, edits: Sequence[MarkerEdit]) -> str | ParseError:
    """Ruling 6: every edit and every resolved marker's line, in ONE transactional batch."""
    present = {m.id: m for m in scan(doc)}
    batch: list[Splice] = []
    for edit in edits:
        if present.get(edit.marker.id) != edit.marker:
            raise ValueError(f"marker {edit.marker.id} is not in this document as scanned")
        resolution = resolve(doc, edit.marker)
        if resolution.code is not None:
            raise TargetError(
                f"marker {edit.marker.id} on {edit.marker.el} does not resolve: {resolution.code}",
                symbol=resolution.code,
                fix=f"ow out check --markers   # leave {edit.marker.id} in place, or re-place it",
            )
        batch.extend(edit.splices)
        batch.append(Splice(edit.marker.start, edit.marker.end, ""))
    return doc.splice(batch)


def assert_clean(bundle: ILBundle) -> None:
    """Ruling 7 (OUT16): no marker, pending or corrupt, reaches `lower()`."""
    left = {u.id: [m.id for m in scan_text(bundle.text(u.il_path))] for u in bundle.units}
    left = {unit: ids for unit, ids in left.items() if ids}
    if left:
        named = "; ".join(f"{unit}: {', '.join(ids)}" for unit, ids in sorted(left.items()))
        raise TargetError(
            f"unresolved feedback markers remain: {named}",
            symbol="OW_TARGET_MARKER_UNRESOLVED",
            fix="ow out check --markers --require-clean",
        )


def over_budget(doc: CarrierDoc) -> bool:
    """`MAX_MARKERS_PER_UNIT`: a 257th note is refused (09 section 8.2)."""
    return len(scan(doc)) >= MAX_MARKERS_PER_UNIT
