"""Layer 5's two findings, judged by the sink over the text a billed prompt wrapped. **D736.**

06:2157-2172 is layer 5 of the seven: a billed driver wraps its Segment in an `untrusted_source`
frame and defangs a copy (`omniweave_llm.wrap`, D708). 06 section 9.5 says what the store keeps:
*"`SENTINEL = 1<<1` -- a chat-template sentinel was defanged in the wrapped copy"*, and for the
worked document *"`OW_GRAPH_INJECTION_SUSPECT` for the forged closing delimiter ... every
legitimately extracted `d41` row tainted `UNTRUSTED_SOURCE | SENTINEL`"*.

The sink is *"the ONLY place `restriction_bits` / `origin_driver` / `taint`"* are stamped
(charter.md:5444), so it judges the Segment's own stored text rather than take a driver's word for
what it defanged. This module is the judgement; `store.graph` applies it.

## Rulings (the ledger's D736)

1. **The sentinels are the driver's, restated.** `omniweave_core` may not import `omniweave_llm`,
   so `SENTINELS` is `omniweave_llm.wrap.SENTINELS` transcribed, and a test holds the two to one
   pattern and one set of flags. Fix (c) holds here too: the heading sentinel is not one, so an
   SOP's "## Instructions" taints nothing.
2. **A forged closing delimiter is the sentinel that closes the frame early**: a
   `</untrusted_source ...>` in the document's own text. It is both a sentinel and held.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

__all__ = ["FORGED", "SENTINELS", "Scan", "scan"]

SENTINELS: Final = re.compile(
    r"</?untrusted_source\b[^>]*>"
    r"|<\|[A-Za-z0-9_.\-]{1,64}\|>"
    r"|<<SYS>>|<</SYS>>"
    r"|\[/?(?:INST|SYSTEM)\]",
    re.IGNORECASE,
)
"""Ruling 1: `omniweave_llm.wrap.SENTINELS`, transcribed (`graphify/llm.py:557-567`, less the
heading sentinel)."""

FORGED: Final = re.compile(r"</untrusted_source\b[^>]*>", re.IGNORECASE)
"""Ruling 2: the closing delimiter a document must never hold."""

_KEPT: Final = 64
"""How much of a forged delimiter a quarantine row keeps: the tag, not the document."""


@dataclass(frozen=True, slots=True)
class Scan:
    """What one block's text holds of layer 5's two findings."""

    sentinel: bool
    forged: tuple[str, ...]
    """Each forged closing delimiter, as written, at most `_KEPT` characters."""


def scan(text: str) -> Scan:
    """Rulings 1-2 over one block's stored text."""
    return Scan(
        sentinel=SENTINELS.search(text) is not None,
        forged=tuple(m.group(0)[:_KEPT] for m in FORGED.finditer(text)),
    )
