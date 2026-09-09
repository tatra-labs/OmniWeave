"""`StreamHint` and `FormatGuess` — the two types in `ParseV1.sniff`'s signature.

THIS IS THE DECLARATION OF BOTH, and nothing else in the framework re-declares them:
05-ingest-and-routing.md section 2.1 references this module and adds the host-side wrapper.
Both live in `omniweave_ports` because both are in the signature of `sniff()`, the first
method a third-party `parse/1` driver implements, and a type in a driver's signature that a
driver cannot import is not a contract.

Two fields are deliberately absent. `FormatGuess` carries no `basis` and no `detail`: `basis`
is the HOST's classification of *how* a guess was obtained — magic bytes, container identity,
a content probe, an extension, a declaration, a driver's `sniff()` — and a driver has no
standing to assert it, so the host wraps each returned guess in
`RankedGuess(guess, basis, detail)` in `omniweave/route/detect.py`. `StreamHint` carries no
`trust_class` for the same reason plus a structural one: `TrustClass` is routing's type and
`tools/layers.toml` gives `omniweave_ports = []`, so the field would pull routing across the
layer boundary G4 closes.

Specified in 04-driver-system.md section 1.3.
"""

from __future__ import annotations

from dataclasses import dataclass

_CONFIDENCE_MIN = 0.0
_CONFIDENCE_MAX = 1.0


@dataclass(frozen=True, slots=True)
class StreamHint:
    """What the HOST knows before any driver looks. A hint, never an authority.

    `filename` is a basename only, never a path — a path leaks roots into a card test.
    `extension` is lower-cased and carries the dot: `'.docx'`. `byte_len` is `None` for a
    stream of unknown length. There is NO `trust_class`.

    Specified in 04-driver-system.md section 1.3.
    """

    filename: str | None
    extension: str | None
    declared_media_type: str | None
    byte_len: int | None


@dataclass(frozen=True, slots=True)
class FormatGuess:
    """One detection candidate as a DRIVER may state it. Four fields, and no more.

    `format_token` is the framework's own token — `'pdf'`, `'docx'`, `'eml'` — and naming it
    is what makes a new format reachable at all, because a token is what a routing rule
    matches (05-ingest-and-routing.md section 2.2). `consumed_bytes` is a REPORT of how far
    the guess looked, not a request for more: there is no "inconclusive, need more bytes"
    channel, so a driver for a format identified only by a trailer returns no guess rather
    than a low-confidence one. A third party's `confidence` is clamped to 0.95 host-side.

    Specified in 04-driver-system.md section 1.3.
    """

    media_type: str
    format_token: str
    confidence: float
    consumed_bytes: int

    def __post_init__(self) -> None:
        """`confidence` is in [0.0, 1.0] inclusive; outside it raises (18 section 5.1 rule 2)."""
        if not _CONFIDENCE_MIN <= self.confidence <= _CONFIDENCE_MAX:
            raise ValueError(
                f"confidence={self.confidence!r} is outside [{_CONFIDENCE_MIN}, {_CONFIDENCE_MAX}]"
            )
        if self.consumed_bytes < 0:
            raise ValueError("consumed_bytes is a non-negative byte count")
