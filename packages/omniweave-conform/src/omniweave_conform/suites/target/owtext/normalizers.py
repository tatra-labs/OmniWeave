"""`owtext/1`'s normalizers: the pure `str -> str` functions a `normalize` row names. **D758.**

09-generation.md section 3.4 rule 2: a normalizer is idempotent, `f(f(x)) == f(x)`, or
`ow out normalize` would not terminate. The one row that names one is `attr.class.upper`.
"""

from __future__ import annotations

__all__ = ["lower_ascii"]


def lower_ascii(value: str) -> str:
    """Lower-case the ASCII letters only, so a non-ASCII class name is never rewritten."""
    return "".join(c.lower() if c.isascii() else c for c in value)
