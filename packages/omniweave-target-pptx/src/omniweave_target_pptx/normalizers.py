"""owsvg/1's normalizers: pure, deterministic, idempotent (09 section 3.4 assertion 2). D789.

Each is named by a `normalize` row of `constructs.toml` and rewrites one attribute value. A value
a normalizer cannot read is returned unchanged, so the native row's own rule reports it and the
normalizer never guesses. The three owsvg/1 adds are ppt-master's advisory spellings
(`svg_quality/svg_contracts.py:282-382`, `:720-764`, `drawingml/utils.py:486-498`) that have one
safe rewrite each: short or lower-case hex, a `px` suffix on a user-unit length, and an opacity
written as a percentage.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Final

_HEX: Final = re.compile(r"#([0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})")
_PX: Final = re.compile(r"(-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+))px")
_PERCENT: Final = re.compile(r"([0-9]+(?:\.[0-9]+)?|\.[0-9]+)%")
_HUNDRED: Final = Decimal(100)


def collapse_space(value: str) -> str:
    """`ow.cite.spacing`: runs of whitespace between cite tokens to one space, none at the ends."""
    return " ".join(value.split())


def upper_hex(value: str) -> str:
    """`paint.*.hex`: `#abc` and `#aabbcc` to `#AABBCC`. Any other paint is left as written."""
    m = _HEX.fullmatch(value.strip())
    if m is None:
        return value
    digits = m[1]
    if len(digits) == len("abc"):
        digits = "".join(d * 2 for d in digits)
    return "#" + digits.upper()


def px_length(value: str) -> str:
    """`*.px`: `"12px"` to `"12"`, because an owsvg/1 user unit is a CSS px. Other units stay."""
    m = _PX.fullmatch(value.strip())
    return value if m is None else m[1]


def opacity_fraction(value: str) -> str:
    """`paint.*-opacity.percent`: `"50%"` to `"0.5"`, in exact decimal, never a float's repr."""
    m = _PERCENT.fullmatch(value.strip())
    if m is None:
        return value
    fraction = (Decimal(m[1]) / _HUNDRED).normalize()
    return format(fraction, "f")
