"""What crosses into a ledger column is redacted, and an exception crosses as its type. D934.

15-observability.md section 8.3 names five channels a document's content can leak through, and
two of them cross the Driver host seam on every failure:

- *"`Diag.message` and its `detail` bag; `DriverError.message`"*: *"`redact()` runs at the
  construction boundary."*
- *"**an exception traceback** -- **every local variable in every frame**"*: *"What is recorded
  instead is the exception's **type name** ... plus the frame's *source location* from
  `tb.tb_frame.f_code.co_filename` and `tb_lineno`, which are our own file paths and carry no
  data."*

Both hosts rendered a driver's unexpected exception as `f"{type(exc).__name__}: {exc}"`, and
`str(exc)` is the exception's `args`: `int(page_text)` raises a `ValueError` whose message *is* the
page text. That string became `work.failure_message`. `described()` is the replacement, and
`redact()` the boundary every `DriverError.message` now passes before it is stored.

## Rulings

1. **`redact()` lives here, not in `events.py`** (15:1376 prints it there). Both hosts call it,
   and the subprocess worker imports nothing of `events`, whose sinks bring a writer thread,
   `gzip` and `queue` into every worker start. This module is the standard library's `re` alone.
2. **The shapes are declared here and `tools/redact.toml` is rendered from them**, the way
   `tools/events.toml` is from `EVENTS`: 15:1376 makes `redact()` *"PURE, no clock, no IO, no
   env"*, and a wheel carries no `tools/`. `test_redact.py` holds the file byte-equal to
   `render()`, so an edit to either side alone fails.
3. **Only mode `"none"` is built**: rules 3 and 4, the credential and marker shapes, which
   15:1395 makes *"unconditional"*. Rules 1 and 2, the path digest and the long-run rule, are
   mode `"paths"`'s, and need the `[roots]` entries and the identifier shapes a call does not yet
   carry; `redact()` refuses that mode by name rather than returning text it did not redact.
4. **A source location is the innermost frame's file name, line and function**, never its
   directory: a driver installed under a user's home would put the user's name in the path.
5. **`authorization_header` also takes the scheme word.** 15:1411 prints
   `authorization\\s*[:=]\\s*\\S+`, which replaces `Authorization: Bearer` and leaves the token
   after it, and `Bearer <token>` is the header's ordinary form. The pattern takes an optional
   `Bearer`, `Basic`, `Digest` or `Token` before the value, so the value is what goes.

Specified in 15-observability.md section 8.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath
from typing import Final, Literal

__all__ = ["FAILURE_FIELD", "SHAPES", "Shape", "described", "redact", "render"]


@dataclass(frozen=True, slots=True)
class Shape:
    """One `[[shape]]` row of 15:1406-1437: an id, a pattern, and what replaces a match."""

    id: str
    pattern: str
    replace: str
    unconditional: bool = True
    exempt_fields: tuple[str, ...] = ()


SHAPES: Final[tuple[Shape, ...]] = (
    Shape(
        "authorization_header",
        r"(?i)\bauthorization\s*[:=]\s*(?:(?:bearer|basic|digest|token)\s+)?\S+",
        "Authorization: <redacted>",
    ),
    Shape(
        "prefixed_token",
        r"\b(sk|rk|ghp|gho|ghu|ghs|glpat|xoxb|xoxp|AKIA)[-_][A-Za-z0-9_-]{16,}",
        "<redacted:token>",
    ),
    Shape(
        "jwt",
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}",
        "<redacted:jwt>",
    ),
    Shape(
        "hex_run",
        r"\b[0-9a-fA-F]{32,}\b",
        "<redacted:hex>",
        exempt_fields=(
            "cache_key",
            "content_sha256",
            "config_digest",
            "semantic_digest",
            "policy_digest",
            "pricebook_digest",
            "lock_digest",
            "evidence_digest",
            "read_set_digest",
            "hints_digest",
            "card_sha256",
            "code_fp",
            "options_digest",
            "plan_digest",
            "argv_digest",
            "catalog_digest",
            "trace_id",
            "span_id",
            "parent_span_id",
            "member_sha256",
        ),
    ),
    Shape("untrusted_marker", r"</?ow:untrusted[^>]*>", "<redacted:marker>"),
    Shape(
        "chat_sentinel",
        r"<\|(im_start|im_end|endoftext|eot_id|start_header_id|end_header_id)\|>",
        "<redacted:sentinel>",
    ),
)
"""15:1406-1437's six shapes, in its order: four credential shapes (rule 3), then the two marker
shapes (rule 4). Every one is unconditional. APPEND-ONLY, as the register it renders."""

_COMPILED: Final = tuple((shape, re.compile(shape.pattern)) for shape in SHAPES)

FAILURE_FIELD: Final = "failure_message"
"""The ledger column a `DriverError.message` is written to (`work.failure_message`), which is the
`field` both hosts redact it for. It is no digest, so every shape applies."""

Mode = Literal["none", "paths"]


def redact(s: str, *, mode: Mode, salt: bytes, field: str | None = None) -> tuple[str, int]:
    """`(redacted, n_removed)`: `s` with every unconditional shape replaced, in `SHAPES` order.

    `field` names the column being written, so a declared digest column is exempt from the
    hex-run rule and nothing else is (15:1439). `salt` is mode `"paths"`'s, which ruling 3 refuses.
    """
    if mode != "none":
        msg = (
            f"redact(mode={mode!r}) is not built: rules 1 and 2 of 15-observability.md section "
            "8.3, the path digest and the long-run rule, need the [roots] entries and the "
            "identifier shapes no call carries yet"
        )
        raise ValueError(msg)
    del salt
    removed = 0
    for shape, pattern in _COMPILED:
        if field is not None and field in shape.exempt_fields:
            continue
        s, n = pattern.subn(shape.replace, s)
        removed += n
    return s, removed


def described(exc: BaseException) -> str:
    """An exception as 15:1366 records it: its type name and where it was raised, never its args.

    `ValueError at parse.py:41 in parse`, from the innermost traceback frame (ruling 4), or the
    type name alone for an exception that was never raised.
    """
    tb = exc.__traceback__
    if tb is None:
        return type(exc).__name__
    while tb.tb_next is not None:
        tb = tb.tb_next
    code = tb.tb_frame.f_code
    return (
        f"{type(exc).__name__} at {PurePath(code.co_filename).name}:{tb.tb_lineno} "
        f"in {code.co_name}"
    )


HEADER: Final = """\
# tools/redact.toml -- APPEND-ONLY, like codes.toml. The one register redact() reads.
#
# GENERATED from omniweave_core.redact.SHAPES (D934); do not edit. A wheel carries no tools/, so
# the shapes are declared in the module and this file is their rendering, held byte-equal by
# packages/omniweave-core/tests/unit/test_redact.py. Specified in 15-observability.md section 8.3.
# Patterns are TOML LITERAL strings: a backslash is a backslash and needs no escaping.
"""


def render() -> str:
    """`tools/redact.toml`, as 15:1405-1437 prints it, from `SHAPES` (ruling 2)."""
    rows = [HEADER]
    for shape in SHAPES:
        rows.append("[[shape]]\n")
        rows.append(f'id = "{shape.id}"\n')
        rows.append(f"unconditional = {'true' if shape.unconditional else 'false'}\n")
        rows.append(f"pattern = '{shape.pattern}'\n")
        rows.append(f'replace = "{shape.replace}"\n')
        if shape.exempt_fields:
            fields = ", ".join(f'"{name}"' for name in shape.exempt_fields)
            rows.append(f"exempt_fields = [{fields}]\n")
    return "".join(rows)
