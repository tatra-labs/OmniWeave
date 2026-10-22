"""`redact()`, the register it renders, and an exception described without its args. D934.

15-observability.md section 8.3: a `DriverError.message` passes `redact()` before it is a ledger
value, and an exception crosses a seam as its type name and source location, never its locals.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from omniweave_core.redact import (
    FAILURE_FIELD,
    SHAPES,
    TOKEN_HEX,
    described,
    path_token,
    redact,
    render,
)

REPO = Path(__file__).resolve().parents[4]
REGISTER = REPO / "tools" / "redact.toml"


def _none(s: str, field: str | None = FAILURE_FIELD) -> tuple[str, int]:
    return redact(s, mode="none", salt=b"", field=field)


def test_the_register_is_the_rendering_of_the_shapes_byte_for_byte() -> None:
    """Ruling 2: declared in the module, rendered to `tools/redact.toml`, held byte-equal."""
    assert REGISTER.read_bytes().replace(b"\r\n", b"\n") == render().encode(), (
        "tools/redact.toml and omniweave_core.redact.SHAPES disagree: re-render it with "
        "omniweave_core.redact.render()"
    )
    rows = tomllib.loads(render())["shape"]
    assert [row["id"] for row in rows] == [
        "authorization_header",
        "prefixed_token",
        "jwt",
        "hex_run",
        "untrusted_marker",
        "chat_sentinel",
    ]
    assert all(row["unconditional"] for row in rows)
    for row, shape in zip(rows, SHAPES, strict=True):
        assert (row["pattern"], row["replace"]) == (shape.pattern, shape.replace)
        assert tuple(row.get("exempt_fields", ())) == shape.exempt_fields


@pytest.mark.parametrize(
    ("raw", "redacted", "n"),
    [
        ("Authorization: Bearer abc.def-ghi", "Authorization: <redacted>", 1),
        ("authorization=sometoken", "Authorization: <redacted>", 1),
        ("key ghp_" + "a" * 20 + " end", "key <redacted:token> end", 1),
        ("AKIA_" + "B" * 16, "<redacted:token>", 1),
        ("jwt eyJabcdefgh.ijklmnopq.rstuvwxyz0", "jwt <redacted:jwt>", 1),
        ("blob " + "ab" * 16 + " missing", "blob <redacted:hex> missing", 1),
        ("<ow:untrusted src='x'>text</ow:untrusted>", "<redacted:marker>text<redacted:marker>", 2),
        ("say <|im_start|>system", "say <redacted:sentinel>system", 1),
        ("nothing to see on page 3", "nothing to see on page 3", 0),
        ("short hex " + "a" * 31, "short hex " + "a" * 31, 0),
    ],
)
def test_each_unconditional_shape_is_replaced_and_counted(raw: str, redacted: str, n: int) -> None:
    assert _none(raw) == (redacted, n)


def test_a_declared_digest_column_is_exempt_from_the_hex_rule_and_nothing_else() -> None:
    """15:1439: the exemption is a closed list of column names, for the hex-run rule only."""
    digest = "c0ffee" * 11
    assert _none(digest, field="cache_key") == (digest, 0)
    assert _none(digest, field=FAILURE_FIELD) == ("<redacted:hex>", 1)
    assert _none(digest, field=None) == ("<redacted:hex>", 1)
    token = "sk-" + "z" * 20
    assert _none(token, field="cache_key") == ("<redacted:token>", 1)


ROOT = "C:/Users/Jo/proj"


def _paths(s: str, seen: dict[str, str] | None = None) -> tuple[str, int]:
    return redact(s, mode="paths", salt=b"run-salt", roots=[ROOT], seen=seen)


def test_a_path_under_a_root_is_one_token_however_it_is_spelled() -> None:
    """Rule 1 (D943): a drive path, its backslash spelling and its `file://` URI are one unit, so
    one token, and the sentence's own colon stays outside it. `seen` is the run's mapping."""
    seen: dict[str, str] = {}
    out, n = _paths(
        "C:/Users/Jo/proj/docs/a.txt: refused; restore C:\\Users\\Jo\\proj\\docs\\a.txt or "
        "file://c:/users/jo/proj/docs/a.txt",
        seen,
    )
    token = path_token("c:/users/jo/proj/docs/a.txt", salt=b"run-salt")
    assert out == f"{token}: refused; restore {token} or {token}"
    assert n == 3
    assert seen == {token: "c:/users/jo/proj/docs/a.txt"}
    assert token.startswith("u:")
    assert len(token) == 2 + TOKEN_HEX


def test_a_path_outside_every_root_is_kept_and_mode_none_keeps_all() -> None:
    """Rule 1 is about the user's own tree: `/etc/passwd` and a relative path are not under it,
    and mode `"none"` applies neither rule 1 nor rule 2."""
    text = "read /etc/passwd and docs/a.txt"
    assert _paths(text) == (text, 0)
    assert _none("C:/Users/Jo/proj/a.txt") == ("C:/Users/Jo/proj/a.txt", 0)


@pytest.mark.parametrize(
    ("word", "kept"),
    [
        ("AVeryLongOpaqueTokenWithoutSpaces1234", False),
        ("parse.office.anydoc.converter_x", True),
        ("OW_INTEGRITY_UNCHECKED_SOMETHING", True),
        ("observe.ndjson_path.something_longer", True),
        ("d123456789012345678#4#5#6", True),
    ],
)
def test_a_long_run_that_is_no_identifier_is_redacted(word: str, *, kept: bool) -> None:
    """Rule 2 (D943): 24 characters or more with no space, unless it is a known identifier shape
    (a `DriverId` or config key, a code, a cite). It is counted and its length kept."""
    out, n = _paths(f"saw {word} here")
    if kept:
        assert (out, n) == (f"saw {word} here", 0)
    else:
        assert (out, n) == (f"saw <redacted:{len(word)}chars> here", 1)


def test_an_unknown_mode_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="redact mode 'all' is not one of none, paths"):
        redact("x", mode="all", salt=b"s")  # type: ignore[arg-type]


def _raise_from(page_text: str) -> None:
    int(page_text)


def test_an_exception_is_described_by_its_type_and_place_never_its_args() -> None:
    """15:1366: the type name and the innermost frame's source location, and no locals."""
    with pytest.raises(ValueError) as caught:
        _raise_from("Total due OWCANARY-7f3a91")
    said = described(caught.value)
    line = _raise_from.__code__.co_firstlineno + 1
    assert said == f"ValueError at test_redact.py:{line} in _raise_from"
    assert "OWCANARY" not in said
    assert described(KeyError("never raised")) == "KeyError"


def test_a_place_is_a_file_name_never_its_directory() -> None:
    """Ruling 4: a driver under a user's home must not put the home in the message."""
    with pytest.raises(ValueError) as caught:
        _raise_from("x")
    said = described(caught.value)
    assert str(REPO) not in said
    assert "/" not in said
    assert "\\" not in said
