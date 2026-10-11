"""`SqliteCiteResolver` -- a compile's `CiteResolver` over the store, batched. **D754.**

09-generation.md section 10: "A 2000-unit roster with 20 cites per unit is 40 000 resolutions;
`CiteResolver` therefore exposes `by_cites(...)` as well as `by_cite`... The resolver holds no store
handle beyond the read." `omniweave_core.out.cites` holds the interface and the `CitedBlock` it
returns. This file holds the read, which INV-17 puts in `omniweave_core.store`, run on a
`StoreThread` the way every other store reader here is.

## Rulings

1. **One `by_cites()` call is one `Unit` and one statement per 500 cites.** The cites travel as a
   JSON array of `[doc_ord, cite]` pairs, so `block_cite`'s `(doc_ord, cite)` index answers each
   one (D240's reason for carrying `doc_ord` in the cite string). Reading in one transaction
   means a batch never sees two states of the corpus.
2. **A compile cites what is live.** A cite resolves only to a block of its document's head
   generation (`ow_block_head`). A retired cite does not resolve. `ow open` follows supersession
   to show a reader the successor, but an artefact that silently quoted the successor would pin a
   `doc_gen` whose text the author never saw. The rule reports it unresolved, and the fix is
   `ow open <cite>`, which names the successor.
3. **The resolver serves one corpus.** A token qualified with that corpus's name resolves as its
   unqualified form. A token qualified with any other corpus, and a string that is not a cite,
   resolve to `None`, which is the rule's to report and never this reader's to raise. The mapping
   is keyed by each token exactly as asked.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import StoreError
from omniweave_core.model.enums import Quote
from omniweave_core.out.cites import CitedBlock
from omniweave_core.store.sqlite import INTERACTIVE_WAIT_MS, StoreThread, Unit

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["BATCH", "RESOLVE_SQL", "SqliteCiteResolver"]

BATCH: Final = 500
_TOKEN: Final = re.compile(r"(?:(?P<corpus>[A-Za-z0-9_.-]+):)?(?P<cite>d(?P<doc>\d+)#\d+)")

RESOLVE_SQL: Final = """\
SELECT b.cite, b.block_id, b.doc_ord, d.gen, b.text, b.quote, b.restriction_bits
  FROM json_each(:pairs) AS j
  JOIN block b ON b.doc_ord = json_extract(j.value, '$[0]')
              AND b.cite = json_extract(j.value, '$[1]')
  JOIN doc d ON d.doc_ord = b.doc_ord
 WHERE b.gen = d.gen AND b.state = 0"""
"""Ruling 2: `ow_block_head`'s predicate, written out so the `block_cite` index drives the join."""


class SqliteCiteResolver:
    """`CiteResolver` over one `StoreThread` and one corpus. Structural."""

    __slots__ = ("_corpus", "_thread", "_wait_ms")

    def __init__(
        self, thread: StoreThread, *, corpus: str, wait_ms: int = INTERACTIVE_WAIT_MS
    ) -> None:
        self._thread = thread
        self._corpus = corpus
        self._wait_ms = wait_ms

    def by_cite(self, cite: str) -> CitedBlock | None:
        return self.by_cites((cite,))[cite]

    def by_cites(self, cites: tuple[str, ...]) -> Mapping[str, CitedBlock | None]:
        """Rulings 1-3: every token, keyed as asked, `None` where nothing live answers."""
        canonical = {token: self._canonical(token) for token in dict.fromkeys(cites)}
        wanted = sorted({c for c in canonical.values() if c is not None})

        def run(connection: sqlite3.Connection) -> object:
            found: dict[str, CitedBlock] = {}
            for start in range(0, len(wanted), BATCH):
                pairs = [[_doc_ord(c), c] for c in wanted[start : start + BATCH]]
                for cite, block_id, doc_ord, gen, text, quote, bits in connection.execute(
                    RESOLVE_SQL, {"pairs": json.dumps(pairs)}
                ):
                    found[cite] = CitedBlock(
                        cite=cite,
                        block_id=block_id,
                        doc_ord=doc_ord,
                        doc_gen=gen,
                        text=text,
                        quote=Quote(quote),
                        restriction_bits=bits,
                    )
            return found

        found = (
            self._thread.run(Unit(name="out.cites", run=run, wait_ms=self._wait_ms))
            if wanted
            else {}
        )
        if not isinstance(found, dict):  # pragma: no cover -- the closure returns or raises.
            raise StoreError("the out.cites unit returned no mapping", fix="report this as a bug")
        return {token: None if c is None else found.get(c) for token, c in canonical.items()}

    def _canonical(self, token: str) -> str | None:
        match = _TOKEN.fullmatch(token)
        if match is None or match["corpus"] not in (None, self._corpus):
            return None
        return match["cite"]


def _doc_ord(cite: str) -> int:
    return int(cite[1 : cite.index("#")])
