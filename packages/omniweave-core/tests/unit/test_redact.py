"""`redact()`, the register it renders, and an exception described without its args. D934.

15-observability.md section 8.3: a `DriverError.message` passes `redact()` before it is a ledger
value, and an exception crosses a seam as its type name and source location, never its locals.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from omniweave_core.redact import FAILURE_FIELD, SHAPES, described, redact, render

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


def test_the_paths_mode_is_refused_by_name() -> None:
    """Ruling 3: rules 1 and 2 are not built, so a caller asking for them is told, not served."""
    with pytest.raises(ValueError, match=r"redact\(mode='paths'\) is not built"):
        redact("x", mode="paths", salt=b"s")


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
