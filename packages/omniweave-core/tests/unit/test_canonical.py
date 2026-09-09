"""`canonical()`, `sha256_canonical()` and `ow128()` -- the three digest primitives.

The properties here are 13-quality.md section 2.2's row for `core/canonical`: the `canonical()`
round-trip, the three distinct encodings for absent / null / `""`, and `ow128` domain
separation. Determinism is asserted from a SECOND INTERPRETER, because `PYTHONHASHSEED` is
exactly the kind of thing that makes a digest stable within one process and unstable across a
corpus.

Specified in 02-architecture.md section 2 row 3, 03-document-model.md section 6.4,
04-driver-system.md section 2.8 and 08-runtime.md section 4.2.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import subprocess  # noqa: TID251 - a second interpreter is the only witness for PYTHONHASHSEED.
import sys
from enum import IntEnum, StrEnum

import pytest
from omniweave_core.canonical import canonical, ow128, sha256_canonical

# --------------------------------------------------------------------------------------------
# canonical() -- the encoding itself
# --------------------------------------------------------------------------------------------


def test_the_printed_json_kwargs_are_the_encoding() -> None:
    """04-driver-system.md section 2.8 prints sort_keys=True, separators=(",", ":"),
    ensure_ascii=False, allow_nan=False. A digest that differs by a space is a corpus that
    will not re-open, so the exact bytes are asserted rather than the shape."""
    assert canonical({"b": 1, "a": [1, 2]}) == b'{"a":[1,2],"b":1}'
    assert canonical([]) == b"[]"
    assert canonical({}) == b"{}"
    assert canonical(None) == b"null"
    assert canonical("") == b'""'


def test_ensure_ascii_is_false_so_text_is_utf8_not_escaped() -> None:
    assert canonical("naïve") == '"naïve"'.encode()
    assert canonical({"ключ": "значение"}) == '{"ключ":"значение"}'.encode()


def test_there_is_no_whitespace_anywhere() -> None:
    blob = canonical({"a": {"b": [1, {"c": "d"}]}, "e": None})
    assert b" " not in blob
    assert b"\n" not in blob


@pytest.mark.parametrize("keys", list(itertools.permutations("abcd")))
def test_insertion_order_never_reaches_the_bytes(keys: tuple[str, ...]) -> None:
    """sort_keys=True. Twenty-four permutations, one encoding."""
    obj = dict.fromkeys(keys, 0) | dict.fromkeys(keys[:2], 1)
    assert canonical(obj) == canonical(dict(sorted(obj.items())))
    assert canonical(dict.fromkeys(keys, 0)) == b'{"a":0,"b":0,"c":0,"d":0}'


def test_nested_mappings_are_sorted_at_every_depth() -> None:
    assert canonical({"z": {"y": 1, "x": 2}}) == b'{"z":{"x":2,"y":1}}'


def test_the_round_trip_holds() -> None:
    """13-quality.md section 2.2: `canonical()` round-trip."""
    obj = {"a": [1, 2.5, None, True, ""], "b": {"c": "ü"}, "d": False}
    assert json.loads(canonical(obj).decode("utf-8")) == obj


# --------------------------------------------------------------------------------------------
# the three distinct encodings
# --------------------------------------------------------------------------------------------


def test_absent_null_and_empty_string_are_three_distinct_encodings() -> None:
    """08-runtime.md section 4.2: the difference between "this key was not in the config" and
    "this key was the empty string" is a real difference."""
    absent = canonical({})
    null = canonical({"k": None})
    empty = canonical({"k": ""})
    assert len({absent, null, empty}) == 3
    hexes = {sha256_canonical(x) for x in ({}, {"k": None}, {"k": ""})}
    assert len(hexes) == 3


def test_the_same_three_are_distinct_inside_a_list() -> None:
    """`content_digest`'s recipe is a LIST, so the distinction has to survive there too."""
    assert len({canonical([]), canonical([None]), canonical([""])}) == 3


def test_a_missing_key_is_not_a_null_key_at_depth() -> None:
    assert canonical({"a": {}}) != canonical({"a": {"b": None}})


# --------------------------------------------------------------------------------------------
# what is refused, and never coerced
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_allow_nan_false_actually_raises(bad: float) -> None:
    """A NaN config value would serialise as the non-JSON token `NaN` and silently differ
    across serialisers."""
    with pytest.raises(ValueError, match="allow_nan=False"):
        canonical(bad)
    with pytest.raises(ValueError, match="allow_nan=False"):
        canonical({"k": [1, bad]})


@pytest.mark.parametrize(
    "bad",
    [
        b"bytes",
        bytearray(b"bytes"),
        {1, 2},
        frozenset({1}),
        object(),
        complex(1, 2),
        Exception("x"),
    ],
)
def test_there_is_no_str_fallback(bad: object) -> None:
    """I12. graphrag's `make_yaml_serializable` falls back to `str()`, and an address-bearing
    repr is a permanent silent 100% cache miss."""
    with pytest.raises(TypeError, match="no str\\(\\) fallback"):
        canonical(bad)  # type: ignore[arg-type]


def test_a_set_is_refused_rather_than_ordered() -> None:
    """A set has no order, so there is no canonical encoding to pick."""
    with pytest.raises(TypeError):
        canonical({"k": {1, 2, 3}})  # type: ignore[arg-type]


@pytest.mark.parametrize("key", [1, 1.5, True, None, ("a",)])
def test_a_non_string_mapping_key_is_refused(key: object) -> None:
    """json.dumps coerces `{1: "a"}` to `{"1":"a"}`, which collides with the string key of the
    same spelling -- a silent two-values-one-digest."""
    with pytest.raises(TypeError, match="mapping key"):
        canonical({key: "a"})  # type: ignore[dict-item]


def test_the_int_key_collision_is_the_reason() -> None:
    assert canonical({"1": "a"}) == b'{"1":"a"}'
    with pytest.raises(TypeError):
        canonical({1: "a"})  # type: ignore[dict-item]


def test_a_reference_cycle_is_a_value_error_not_a_recursion_error() -> None:
    loop: list[object] = [1]
    loop.append(loop)
    with pytest.raises(ValueError, match="reference cycle"):
        canonical(loop)


def test_a_shared_but_acyclic_value_is_fine() -> None:
    """Cycle detection is over the PATH, not over every node ever seen."""
    shared = {"a": 1}
    assert canonical([shared, shared]) == b'[{"a":1},{"a":1}]'


def test_a_lone_surrogate_is_refused() -> None:
    with pytest.raises(ValueError, match="lone surrogate"):
        canonical("a\ud800b")
    with pytest.raises(ValueError, match="lone surrogate"):
        canonical({"a\ud800b": 1})


# --------------------------------------------------------------------------------------------
# type distinctions that a digest must not lose
# --------------------------------------------------------------------------------------------


def test_int_float_and_bool_are_three_values() -> None:
    assert len({canonical(1), canonical(1.0), canonical(True)}) == 3
    assert canonical(1) == b"1"
    assert canonical(1.0) == b"1.0"
    assert canonical(True) == b"true"


def test_a_list_and_a_tuple_are_one_json_array() -> None:
    """JSON has one array type, so this is a real collapse and it is the right one."""
    assert canonical(["a", "b"]) == canonical(("a", "b"))


def test_enum_members_flatten_to_their_values() -> None:
    class Kind(IntEnum):
        PARAGRAPH = 3

    class Layer(StrEnum):
        BODY = "body"

    assert canonical([Kind.PARAGRAPH, Layer.BODY]) == b'[3,"body"]'


def test_a_str_subclass_cannot_move_a_digest_through_dunder_str() -> None:
    class Sneaky(str):
        def __str__(self) -> str:
            return "elsewhere"

    assert canonical(Sneaky("here")) == b'"here"'
    assert canonical({Sneaky("k"): 1}) == b'{"k":1}'


def test_the_join_collision_class_is_closed() -> None:
    """graphrag's `gen_sha512_hash` concatenates without a separator, so `["a","bc"]` and
    `["ab","c"]` hash identically. Canonical JSON is self-delimiting."""
    assert sha256_canonical(["a", "bc"]) != sha256_canonical(["ab", "c"])


# --------------------------------------------------------------------------------------------
# sha256_canonical
# --------------------------------------------------------------------------------------------


def test_sha256_canonical_is_sha256_over_canonical() -> None:
    obj = {"b": [1, None, ""], "a": "ü"}
    assert sha256_canonical(obj) == hashlib.sha256(canonical(obj)).hexdigest()


def test_sha256_canonical_is_64_lowercase_hex() -> None:
    digest = sha256_canonical({"a": 1})
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


# --------------------------------------------------------------------------------------------
# ow128
# --------------------------------------------------------------------------------------------


def test_ow128_is_sixteen_bytes_of_blake2b_with_person() -> None:
    obj = {"a": 1}
    assert (
        ow128(b"ow.content.1", obj)
        == hashlib.blake2b(canonical(obj), digest_size=16, person=b"ow.content.1").digest()
    )
    assert len(ow128(b"ow.content.1", obj)) == 16


def test_the_person_domain_separates() -> None:
    """P-6: keys from two different `CacheLayer`s never collide, asserted by domain separation
    in `ow128`'s `person=` parameter."""
    obj = {"same": "input"}
    domains = [b"ow.content.1", b"ow.layout.1", b"ow.segment.1", b"ow.mention.1", b"ow.content.2"]
    digests = {ow128(domain, obj) for domain in domains}
    assert len(digests) == len(domains)


@pytest.mark.parametrize("i", range(64))
def test_domain_separation_holds_over_generated_inputs(i: int) -> None:
    obj = {"n": i, "s": f"value-{i}"}
    assert ow128(b"ow.content.1", obj) != ow128(b"ow.segment.1", obj)


def test_a_domain_is_a_separator_not_a_prefix() -> None:
    """Prefixing would make `ow128(d, x)` reachable as `ow128(d2, y)` for a crafted `y`;
    `person=` is a keyed parameter and cannot be."""
    assert ow128(b"ow.a.1", "b") != ow128(b"ow.a.2", "b")


@pytest.mark.parametrize(
    "domain",
    [b"content", b"OW.content.1", b"ow.content", b"ow..1", b"ow.content.x", b""],
)
def test_a_domain_that_is_not_an_ow_literal_is_refused(domain: bytes) -> None:
    with pytest.raises(ValueError, match=re.escape("ow.<what>.<recipe>")):
        ow128(domain, {})


def test_a_domain_over_sixteen_bytes_is_refused() -> None:
    with pytest.raises(ValueError, match="person="):
        ow128(b"ow.averylongname.1", {})


@pytest.mark.parametrize("domain", ["ow.content.1", 1, None])
def test_a_domain_that_is_not_bytes_is_refused(domain: object) -> None:
    with pytest.raises(TypeError, match="must be bytes"):
        ow128(domain, {})  # type: ignore[arg-type]


def test_ow128_propagates_the_canonical_grammar() -> None:
    with pytest.raises(ValueError, match="allow_nan=False"):
        ow128(b"ow.content.1", [float("nan")])


# --------------------------------------------------------------------------------------------
# determinism across processes
# --------------------------------------------------------------------------------------------

_PROBE = """
import json
from omniweave_core.canonical import canonical, ow128, sha256_canonical
obj = {"z": 1, "a": [None, "", "ü", 2.5, True], "m": {"q": None, "p": ""}}
print(json.dumps({
    "canonical": canonical(obj).decode("utf-8"),
    "sha256": sha256_canonical(obj),
    "ow128": ow128(b"ow.content.1", obj).hex(),
}))
"""


def _probe(seed: str) -> dict[str, str]:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_every_digest_is_identical_across_processes_and_hash_seeds() -> None:
    """PYTHONHASHSEED reorders `dict` iteration for str keys in a fresh interpreter, which is
    exactly what `sort_keys=True` exists to make invisible."""
    first = _probe("0")
    second = _probe("12345")
    third = _probe("98765")
    assert first == second == third
    assert first["sha256"] == sha256_canonical(
        {"z": 1, "a": [None, "", "ü", 2.5, True], "m": {"q": None, "p": ""}}
    )


def test_the_canonicaliser_is_total_on_deep_structures() -> None:
    obj: object = "leaf"
    for _ in range(30):
        obj = {"n": [obj]}
    assert len(sha256_canonical(obj)) == 64  # type: ignore[arg-type]


def test_float_repr_is_round_trip_exact() -> None:
    """04-driver-system.md section 2.8: floats are serialised by `float.__repr__`, which is
    round-trip-exact for IEEE-754 doubles, and `allow_nan=False` removes the rest."""
    for value in (0.1, 1e300, 5e-324, -0.0, math.pi):
        assert json.loads(canonical(value).decode("utf-8")) == value
