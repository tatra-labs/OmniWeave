"""The untrusted-source wrapper a billed prompt carries its Segment in. D708.

06:2157 is layer 5 of the seven: *"graphify's `<untrusted_source path="<file>" sha256="<hex>">`
vendored at a pinned SHA, with three fixes"*. The source is graphify's `llm.py`, `_wrap_untrusted`
and `_INJECTION_SENTINELS` (`graphify/llm.py:557-594` at `33362d969292b57eda82f3fbd9eb5f3f5bc9bbc2`,
Apache-2.0), transcribed here because a `derive/1` driver may import `omniweave_ports` alone
(`tools/layers.toml`). Its home as source is `vendor/graphify-security/` (`tools/vendor.toml`
names it owed), as `normalize_key`'s is `vendor/graphify-ids/`.

## The three fixes (06:2161-2172), each a defect in the original

1. **(a) The `path` attribute is XML-escaped.** graphify interpolates it raw (`llm.py:592`), so a
   name holding `"` closes the attribute and one holding `>` the tag.
2. **(b) A copy is defanged.** The sink grounds every quote against the stored block text
   (`ground()`, 06 section 1.7), never against what the model was shown, so defanging here changes
   no offset. This module never sees the stored text and returns a new string.
3. **(c) The heading sentinel is dropped.** `^\\s*###?\\s*(?:system|instruction)s?\\s*:?\\s*$`
   matches "## Instructions" in every manual, RFP and SOP.

**Kept:** the generalised `<|...|>` chat-template form, the `<<SYS>>` and `[INST]` forms, the forged
closing delimiter, and the `sha256=` stamp, which is forensics rather than prevention: it lets a
reviewer trace a suspicious extracted item back to exact bytes. The stamp is over the text BEFORE
defanging, so it names the bytes the document holds.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

__all__ = ["CLOSING", "OPENING", "SENTINELS", "ZWSP", "defang", "wrap_untrusted"]

OPENING: Final = "untrusted_source"
CLOSING: Final = f"</{OPENING}>"
ZWSP: Final = chr(0x200B)
"""Inserted after a sentinel's first character: the token is no longer one, and still readable."""

SENTINELS: Final = re.compile(
    r"</?untrusted_source\b[^>]*>"
    r"|<\|[A-Za-z0-9_.\-]{1,64}\|>"
    r"|<<SYS>>|<</SYS>>"
    r"|\[/?(?:INST|SYSTEM)\]",
    re.IGNORECASE,
)
"""`graphify/llm.py:557-567`, less the heading sentinel (fix (c))."""

_ESCAPES: Final = str.maketrans(
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;"}
)


def defang(text: str) -> str:
    """Every sentinel in `text`, with a zero-width space after its first character (fix (b))."""
    return SENTINELS.sub(lambda m: m.group(0)[0] + ZWSP + m.group(0)[1:], text)


def wrap_untrusted(path: str, content: str) -> str:
    """`content` defanged inside one labelled, hash-stamped frame (fixes (a) and (b))."""
    sha = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
    return (
        f'<{OPENING} path="{path.translate(_ESCAPES)}" sha256="{sha}">\n'
        f"{defang(content)}\n"
        f"{CLOSING}"
    )
