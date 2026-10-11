"""owflow/1's normalizers: pure, deterministic, idempotent (09 section 3.4 assertion 2). D781.

Each is named by a `normalize` row of `constructs.toml` and rewrites one attribute value. A value
a normalizer cannot read is returned unchanged, so the native row's own rule reports it and the
normalizer never guesses.
"""

from __future__ import annotations

import re
from typing import Final

_DIGITS: Final = re.compile(r"[+]?[0-9]+")
_SUBTAG: Final = re.compile(r"[A-Za-z0-9]{1,8}")
_SCRIPT_LEN: Final = 4
_REGION_LEN: Final = 2
_NUMERIC_REGION_LEN: Final = 3


def collapse_space(value: str) -> str:
    """`ow.cite.spacing`: runs of whitespace between cite tokens to one space, none at the ends."""
    return " ".join(value.split())


def int_text(value: str) -> str:
    """`table.colspan.form` and `table.rowspan.form`: `" 02"` and `"+2"` to `"2"`."""
    stripped = value.strip()
    if _DIGITS.fullmatch(stripped) is None:
        return value
    return str(int(stripped.removeprefix("+")))


def bcp47_case(value: str) -> str:
    """`lang.tag.case`: BCP-47's conventional case. `EN-latn-us` to `en-Latn-US`.

    The first subtag is lower case, a four-letter subtag after it is a script and title case,
    and a two-letter one, or three digits, is a region and upper case. Everything after a
    singleton (`x-`, `u-`) is an extension and lower case. A value that is not dash-separated
    alphanumeric subtags is returned as it is.
    """
    parts = value.split("-")
    if not all(_SUBTAG.fullmatch(p) for p in parts):
        return value
    out = [parts[0].lower()]
    extension = len(parts[0]) == 1
    for part in parts[1:]:
        if extension or len(part) == 1:
            extension = True
            out.append(part.lower())
        elif len(part) == _SCRIPT_LEN and part.isalpha():
            out.append(part.title())
        elif (len(part) == _REGION_LEN and part.isalpha()) or (
            len(part) == _NUMERIC_REGION_LEN and part.isdigit()
        ):
            out.append(part.upper())
        else:
            out.append(part.lower())
    return "-".join(out)
