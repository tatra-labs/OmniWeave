"""Canonical JSON and the two digest primitives every recipe in the framework is built from.

`canonical()` is the one canonicaliser; `sha256_canonical()` is the 64-char hex digest the TEXT
`*_digest` columns hold; `ow128()` is the 16-byte BLOB digest the BLOB `*_digest` columns hold.
Nothing here decides WHAT enters a digest -- every caller owns its own recipe.

Specified in 02-architecture.md section 2 row 3 (the owner interface and the boundary this
module does not cross), 03-document-model.md section 6.4 and charter.md section "Digests" (the
`ow128` definition and the `canonical()` grammar), 04-driver-system.md section 2.8 (the
`json.dumps` keyword arguments, verbatim) and 08-runtime.md section 4.2 ("the canonicaliser is
part of the specification").

Three failures this module exists to make unreachable, each observed in the mined collection:

* `"".join(values)` as a digest input -- graphrag's `gen_sha512_hash` concatenates without a
  separator, so `["a","bc"]` and `["ab","c"]` collide. Canonical JSON is self-delimiting.
* a `str()` fallback for an unserialisable value -- graphrag's `make_yaml_serializable` reaches
  one, and an address-bearing `repr` is a permanent silent 100% cache miss. There is no
  fallback here, ever (I12).
* collapsing absent / `null` / `""` -- three distinct encodings, because "this key was not in
  the config" and "this key was the empty string" are different facts.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import TypeAlias

__all__ = ["JsonValue", "canonical", "ow128", "sha256_canonical"]

# The value grammar `canonical()` accepts. It is exactly JSON's: no bytes, no sets, no dates,
# no arbitrary objects. `omniweave_core.config`'s four-shape `ConfigValue` is a subset of it,
# which is what "flat and JSON-canonicalisable by contract" (I12) means operationally.
JsonValue: TypeAlias = (
    "bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue] | None"
)

# `person=` is a DOMAIN SEPARATOR, not a prefix, and every domain the framework uses is a
# `b'ow.<what>.<recipe>'` literal (03-document-model.md section 6.4). Enforcing the shape here
# is what stops a caller passing a bare `b'content'` that a sibling recipe could also pick.
_DOMAIN = re.compile(rb"\Aow(?:\.[a-z0-9_]+)+\.[0-9]+\Z")
_PERSON_SIZE = hashlib.blake2b.PERSON_SIZE  # 16 bytes; a longer `person=` is a ValueError
_OW128_SIZE = 16


def canonical(obj: JsonValue) -> bytes:
    """The canonical UTF-8 JSON encoding of `obj`: sorted keys, no whitespace, no NaN/Inf.

    `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    allow_nan=False).encode("utf-8")` -- 04-driver-system.md section 2.8 prints exactly that --
    over a value first checked against the JSON grammar, because `json.dumps` alone silently
    coerces a non-string mapping key (`{1: "a"}` and `{"1": "a"}` become the same bytes) and
    accepts no `Mapping` it cannot round-trip.

    Raises `TypeError` for a value outside the grammar and `ValueError` for NaN, an infinity, a
    lone surrogate or a reference cycle. An un-canonicalisable value is an error, never a
    `str()` fallback (I12, 08-runtime.md section 4.2).
    """
    return json.dumps(
        _plain(obj, "$", []),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def sha256_canonical(obj: JsonValue) -> str:
    """`sha256(canonical(obj)).hexdigest()` -- 64 lowercase hex characters.

    The form every TEXT `_digest` column holds: `config_digest`, `semantic_digest`,
    `policy_digest`, `work.cache_key` and `decision_id`'s body. Specified in charter.md section
    "Digests" and 02-architecture.md section 8.3.
    """
    return hashlib.sha256(canonical(obj)).hexdigest()


def ow128(domain: bytes, obj: JsonValue) -> bytes:
    """`blake2b(canonical(obj), digest_size=16, person=domain).digest()` -- 16 raw bytes.

    `domain` is a `b'ow.<what>.<recipe>'` literal and is a DOMAIN SEPARATOR, not a prefix: two
    recipes over the same object are two digests, which is what P-6 (cache-key layer
    separation) rests on. `blake3` is not in the standard library; `hashlib.blake2b` is, is
    C-accelerated, and takes `person=` -- so every "blake3_128" in the source rulings is this
    function (charter.md section 5 C3 and X6).

    Specified in 03-document-model.md section 6.4 and glossary.md ("`ow128()`").
    """
    if not isinstance(domain, bytes):
        raise TypeError(f"ow128 domain must be bytes, not {type(domain).__name__}")
    if len(domain) > _PERSON_SIZE:
        raise ValueError(f"ow128 domain is {len(domain)} bytes; blake2b person= holds 16")
    if _DOMAIN.fullmatch(domain) is None:
        raise ValueError(f"ow128 domain {domain!r} is not a b'ow.<what>.<recipe>' literal")
    return hashlib.blake2b(canonical(obj), digest_size=_OW128_SIZE, person=domain).digest()


# --------------------------------------------------------------------------------------------
# The grammar check. `canonical()`'s contract is that two values encode to the same bytes iff
# they are the same value, so every coercion `json.dumps` would otherwise perform silently is
# an error here instead.
# --------------------------------------------------------------------------------------------


def _plain(value: object, where: str, stack: list[int]) -> object:
    """`value` reduced to plain `None`/`bool`/`int`/`float`/`str`/`list`/`dict`, or an error.

    `stack` holds the `id()` of every container on the path from the root, so a reference cycle
    is a `ValueError` naming where it closed rather than a `RecursionError`.
    """
    if value is None or value is True or value is False:
        return value
    if isinstance(value, str):
        # A `str` subclass -- `StrEnum` is the one that matters -- is flattened to its content,
        # so an overridden `__str__` cannot move a digest.
        text = "".join([value])
        _reject_surrogates(text, where)
        return text
    if isinstance(value, int):  # `bool` is an `int` subclass and was handled above
        return int(value)
    if isinstance(value, float):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            raise ValueError(f"{where}: {number!r} has no JSON encoding (allow_nan=False)")
        return number
    if isinstance(value, Mapping):
        return _plain_mapping(value, where, stack)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return _plain_sequence(value, where, stack)
    raise TypeError(
        f"{where}: {type(value).__name__} is not JSON-canonicalisable and there is no str() "
        f"fallback (I12, 08-runtime.md section 4.2)"
    )


def _plain_mapping(
    value: Mapping[object, object], where: str, stack: list[int]
) -> dict[str, object]:
    _enter(value, where, stack)
    try:
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"{where}: mapping key {key!r} is a {type(key).__name__}; json.dumps would "
                    f"coerce it to a string and collide with the string of that spelling"
                )
            name = "".join([key])
            _reject_surrogates(name, f"{where}.<key>")
            out[name] = _plain(item, f"{where}.{name}", stack)
        return out
    finally:
        stack.pop()


def _plain_sequence(value: Sequence[object], where: str, stack: list[int]) -> list[object]:
    _enter(value, where, stack)
    try:
        return [_plain(item, f"{where}[{i}]", stack) for i, item in enumerate(value)]
    finally:
        stack.pop()


def _enter(container: object, where: str, stack: list[int]) -> None:
    if id(container) in stack:
        raise ValueError(f"{where}: reference cycle; a cyclic value has no canonical encoding")
    stack.append(id(container))


def _reject_surrogates(text: str, where: str) -> None:
    """A lone surrogate has no UTF-8 encoding, and letting `.encode()` fail at the end of a
    digest recipe names the whole object rather than the one field that is unrepresentable."""
    if text.isascii():
        return
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{where}: {text!r} holds a lone surrogate and has no UTF-8 form") from exc
