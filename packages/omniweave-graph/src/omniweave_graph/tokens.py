"""`ow.bytes4/1` -- the framework's own token count: UTF-8 bytes over four, rounded up. **D662.**

`segment.tokenizer_id` is NOT NULL (0002_graph.sql) and 06 section 3.2's every bound is in tokens,
but no document names the tokenizer the segmenter counts with. The ruling is the one the plan's own
arithmetic already uses -- *"`SEGMENT_TARGET_TOKENS = 1200` x ~4 chars/token"* (12-performance.md
B14) and *"1200 ~ 4,800"* characters (07-store-and-retrieval.md:1066) -- spelled over bytes rather
than characters so a script whose characters are three bytes counts heavier, which is the direction
a real BPE vocabulary errs in too.

It is a COUNT, not a tokenizer: no vocabulary, no download, no model, nothing a `needs_network =
false` card could fail on, and the same number on every platform forever. A segmenter that counts
with a model's tokenizer is a different `tokenizer_id`, and therefore a different segmenter row,
which is what the column exists to say.
"""

from __future__ import annotations

from typing import Final

__all__ = ["TOKENIZER_ID", "count_tokens"]

TOKENIZER_ID: Final = "ow.bytes4/1"
"""`segment.tokenizer_id` for every Segment this package emits. The `/1` is the recipe: changing
the divisor or the rounding is `/2`, never an edit to this one."""


def count_tokens(text: str) -> int:
    """`ceil(len(text.encode("utf-8")) / 4)`. The empty string is zero tokens."""
    size = len(text) if text.isascii() else len(text.encode("utf-8"))
    return (size + 3) // 4
